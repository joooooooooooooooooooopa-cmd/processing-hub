import asyncio
import os
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
import requests
import urllib3
urllib3.disable_warnings()

from fpdf import FPDF
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Update,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN         = os.environ["BOT_TOKEN"]
DATABASE_URL      = os.environ["DATABASE_URL"]
MASTER_KEY        = os.environ.get("MASTER_KEY", "")
METABASE_URL      = os.environ.get("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL    = os.environ.get("METABASE_EMAIL", "")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD", "")
METABASE_DB_ID    = int(os.environ.get("METABASE_DB_ID", "2"))

SPAM_THRESHOLD       = 20   # immediate alert threshold
CHECK_INTERVAL_MIN   = 20   # scheduler interval (minutes)

FONT_PATH = Path(__file__).parent / "DejaVuSans.ttf"

_FONT_URL = "https://github.com/py-pdf/fpdf2/raw/master/test/fonts/DejaVuSans.ttf"


def ensure_font():
    """Download DejaVuSans.ttf if missing or corrupted."""
    try:
        if FONT_PATH.exists() and FONT_PATH.stat().st_size > 100_000:
            # Quick sanity check: real TTF starts with 0x00010000 or 'true' or 'OTTO'
            with open(FONT_PATH, "rb") as f:
                header = f.read(4)
            if header[:2] == b'\x00\x01' or header == b'true' or header == b'OTTO':
                return  # font is valid
        logger.info("Downloading DejaVuSans.ttf...")
        r = requests.get(_FONT_URL, timeout=30, verify=False)
        r.raise_for_status()
        FONT_PATH.write_bytes(r.content)
        logger.info("Font downloaded: %d bytes", len(r.content))
    except Exception as e:
        logger.error("Font download failed: %s", e)


# ── Metabase ──────────────────────────────────────────────────────────────────

_mb_token = None
_mb_token_at = None


def mb_auth() -> dict:
    global _mb_token, _mb_token_at
    now = datetime.utcnow()
    if _mb_token and _mb_token_at and (now - _mb_token_at) < timedelta(hours=6):
        return {"Content-Type": "application/json", "X-Metabase-Session": _mb_token}
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
        verify=False, timeout=15,
    )
    r.raise_for_status()
    _mb_token = r.json()["id"]
    _mb_token_at = now
    logger.info("Metabase auth OK")
    return {"Content-Type": "application/json", "X-Metabase-Session": _mb_token}


def mb_run(sql: str) -> list[dict]:
    r = requests.post(
        f"{METABASE_URL}/api/dataset",
        headers=mb_auth(),
        json={"database": METABASE_DB_ID, "type": "native", "native": {"query": sql}},
        verify=False, timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    err = data.get("error") or (data.get("data") or {}).get("error")
    if err:
        raise RuntimeError(f"Metabase: {err}")
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"]]


def query_spam_by_merchant_24h(merchant_name: str) -> list[dict]:
    """All spam clients for a specific merchant over last 24h."""
    return mb_run(f"""
        SELECT
            o.client_id::text                            AS client_id,
            COUNT(*)                                     AS total_orders,
            COUNT(*) FILTER (WHERE o.status = 'closed') AS paid_orders
        FROM orders o
        LEFT JOIN merchants m ON m.id = o.merchant_id
        WHERE o.created_at >= NOW() - INTERVAL '24 hours'
          AND o.client_id IS NOT NULL
          AND COALESCE(m.name, o.merchant_id::text) = '{merchant_name.replace("'", "''")}'
        GROUP BY o.client_id
        HAVING COUNT(*) >= 5
        ORDER BY COUNT(*) DESC
    """)


def query_merchants_with_spam_24h() -> list[str]:
    """Merchants that have spam clients (5+ orders) in last 24h."""
    rows = mb_run("""
        SELECT DISTINCT COALESCE(m.name, o.merchant_id::text) AS merchant_name
        FROM orders o
        LEFT JOIN merchants m ON m.id = o.merchant_id
        WHERE o.created_at >= NOW() - INTERVAL '24 hours'
          AND o.client_id IS NOT NULL
        GROUP BY o.client_id, o.merchant_id, m.name
        HAVING COUNT(*) >= 5
        ORDER BY merchant_name
    """)
    return [r["merchant_name"] for r in rows]


def query_last_hour() -> list[dict]:
    """Merchants and their spam clients in last 1 hour (5+ orders)."""
    return mb_run("""
        SELECT
            COALESCE(m.name, o.merchant_id::text)        AS merchant_name,
            o.client_id::text                            AS client_id,
            COUNT(*)                                     AS total_orders,
            COUNT(*) FILTER (WHERE o.status = 'closed') AS paid_orders
        FROM orders o
        LEFT JOIN merchants m ON m.id = o.merchant_id
        WHERE o.created_at >= NOW() - INTERVAL '1 hour'
          AND o.client_id IS NOT NULL
        GROUP BY o.client_id, o.merchant_id, m.name
        HAVING COUNT(*) >= 5
        ORDER BY merchant_name, COUNT(*) DESC
    """)


def query_alert_check() -> list[dict]:
    """Clients with 20+ orders in last 5 min for immediate alerts."""
    return mb_run(f"""
        SELECT
            o.client_id::text                            AS client_id,
            o.merchant_id,
            COALESCE(m.name, o.merchant_id::text)        AS merchant_name,
            COUNT(*)                                     AS total_orders,
            COUNT(*) FILTER (WHERE o.status = 'closed') AS paid_orders
        FROM orders o
        LEFT JOIN merchants m ON m.id = o.merchant_id
        WHERE o.created_at >= NOW() - INTERVAL '{CHECK_INTERVAL_MIN} minutes'
          AND o.client_id IS NOT NULL
        GROUP BY o.client_id, o.merchant_id, m.name
        HAVING COUNT(*) >= {SPAM_THRESHOLD}
        ORDER BY COUNT(*) DESC
    """)


# ── Railway Postgres ──────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def db_ensure_tables():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS spam_monitor_users (
                    chat_id  BIGINT PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS spam_alerts_sent (
                    id           SERIAL PRIMARY KEY,
                    client_id    TEXT,
                    merchant_id  TEXT,
                    window_start TIMESTAMP,
                    created_at   TIMESTAMP DEFAULT NOW(),
                    UNIQUE (client_id, merchant_id, window_start)
                );
            """)
        conn.commit()
    logger.info("Tables ready")


def db_is_authorized(chat_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM spam_monitor_users WHERE chat_id=%s", (chat_id,))
            return cur.fetchone() is not None


def db_authorize(chat_id: int, username):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO spam_monitor_users (chat_id,username) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (chat_id, username),
            )
        conn.commit()


def db_get_users() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM spam_monitor_users")
            return [r[0] for r in cur.fetchall()]


def current_window() -> datetime:
    now = datetime.utcnow().replace(second=0, microsecond=0)
    return now.replace(minute=(now.minute // CHECK_INTERVAL_MIN) * CHECK_INTERVAL_MIN)


def db_mark_alerted(rows: list[dict]) -> list[dict]:
    window = current_window()
    new_rows = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute("""
                    INSERT INTO spam_alerts_sent (client_id, merchant_id, window_start)
                    VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
                """, (str(row["client_id"]), str(row["merchant_id"]), window))
                if cur.fetchone():
                    new_rows.append(row)
        conn.commit()
    return new_rows


# ── PDF generation ────────────────────────────────────────────────────────────

def build_pdf(merchant_name: str, clients: list[dict]) -> bytes:
    pdf = FPDF(orientation="L")  # landscape — больше места для client_id
    pdf.add_page()
    pdf.add_font("DejaVu", fname=str(FONT_PATH))
    pdf.add_font("DejaVu", style="B", fname=str(FONT_PATH))

    # Usable width in landscape A4 = 277mm
    W_ID = 200   # client_id column
    W_NUM = 38   # orders column
    W_PAID = 39  # paid column

    # Header
    pdf.set_font("DejaVu", style="B", size=16)
    pdf.set_fill_color(41, 128, 185)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, f"Спам-отчёт: {merchant_name}", fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("DejaVu", size=10)
    pdf.set_text_color(100, 100, 100)
    now_msk = datetime.utcnow() + timedelta(hours=3)
    pdf.cell(0, 8, f"Сформирован: {now_msk.strftime('%d.%m.%Y %H:%M')} МСК  |  Период: последние 24 часа",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Table header
    pdf.set_font("DejaVu", style="B", size=11)
    pdf.set_fill_color(52, 73, 94)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(W_ID, 9, "Client ID", fill=True, border=1)
    pdf.cell(W_NUM, 9, "Заявок", fill=True, border=1, align="C")
    pdf.cell(W_PAID, 9, "Оплачено", fill=True, border=1, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("DejaVu", size=10)
    for i, c in enumerate(clients):
        pdf.set_fill_color(245, 245, 245) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(W_ID, 8, str(c["client_id"]), fill=True, border=1)
        pdf.cell(W_NUM, 8, str(c["total_orders"]), fill=True, border=1, align="C")
        pdf.cell(W_PAID, 8, str(c["paid_orders"]), fill=True, border=1, align="C")
        pdf.ln()

    # Summary
    pdf.ln(6)
    pdf.set_font("DejaVu", style="B", size=11)
    pdf.set_text_color(41, 128, 185)
    total_orders = sum(c["total_orders"] for c in clients)
    pdf.cell(0, 8, f"Итого спам-клиентов: {len(clients)}  |  Всего заявок: {total_orders}")

    return bytes(pdf.output())


# ── Keyboards ─────────────────────────────────────────────────────────────────

MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📥 Выгрузка по мерчанту")],
        [KeyboardButton("⏰ Последний час")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def merchants_kb(merchants: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for name in merchants:
        short = name[:32]  # Telegram callback_data limit
        buttons.append([InlineKeyboardButton(name, callback_data=f"merch|{short}")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="merch|__cancel__")])
    return InlineKeyboardMarkup(buttons)


# ── Formatting ────────────────────────────────────────────────────────────────

def format_last_hour(rows: list[dict]) -> str:
    if not rows:
        return "✅ За последний час спам-клиентов не обнаружено."

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["merchant_name"], []).append(r)

    now_msk = datetime.utcnow() + timedelta(hours=3)
    lines = [f"⏰ <b>Спам за последний час</b>  ({now_msk.strftime('%H:%M')} МСК)\n"]

    for merchant, clients in groups.items():
        lines.append(f"🏪 <b>{merchant}</b>")
        for c in clients:
            lines.append(
                f"  👤 <code>{c['client_id']}</code> — {c['total_orders']} заявок"
                f"  (оплачено: {c['paid_orders']})"
            )
        lines.append("")

    return "\n".join(lines).rstrip()


def format_alert(rows: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["merchant_name"], []).append(r)

    lines = [f"🚨 <b>Спам-алерт! ({SPAM_THRESHOLD}+ заявок за 5 мин)</b>\n"]
    for merchant, clients in groups.items():
        lines.append(f"🏪 <b>{merchant}</b>")
        for c in clients:
            lines.append(
                f"  👤 <code>{c['client_id']}</code> — {c['total_orders']} заявок"
                f"  (оплачено: {c['paid_orders']})"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if db_is_authorized(chat_id):
        await update.message.reply_text(
            "✅ Вы авторизованы.\n\n"
            "📥 <b>Выгрузка по мерчанту</b> — PDF со всеми спам-клиентами за 24ч\n"
            "⏰ <b>Последний час</b> — кто спамил в последний час\n\n"
            "Авто-алерт при 20+ заявках от одного клиента за 5 минут.",
            parse_mode="HTML",
            reply_markup=MAIN_KB,
        )
    else:
        await update.message.reply_text("🔐 Введите мастер-ключ для доступа:")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    if not db_is_authorized(chat_id):
        if text == MASTER_KEY:
            db_authorize(chat_id, update.effective_user.username)
            await update.message.reply_text(
                "✅ Доступ открыт!\n\n"
                "📥 <b>Выгрузка по мерчанту</b> — PDF со спам-клиентами за 24ч\n"
                "⏰ <b>Последний час</b> — кто спамил в последний час\n\n"
                "Авто-алерт при 20+ заявках за 5 минут.",
                parse_mode="HTML",
                reply_markup=MAIN_KB,
            )
            logger.info("Authorized chat_id=%s", chat_id)
        else:
            await update.message.reply_text("❌ Неверный ключ.")
        return

    if text == "📥 Выгрузка по мерчанту":
        await action_export(update, context)
    elif text == "⏰ Последний час":
        await action_last_hour(update, context)


async def action_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю список мерчантов...")
    try:
        merchants = await asyncio.get_event_loop().run_in_executor(None, query_merchants_with_spam_24h)
    except Exception as e:
        logger.error("action_export error: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=MAIN_KB)
        return

    if not merchants:
        await update.message.reply_text(
            "✅ За последние 24ч спам-клиентов не обнаружено.", reply_markup=MAIN_KB
        )
        return

    await update.message.reply_text(
        f"Найдено <b>{len(merchants)}</b> мерчантов со спам-клиентами за 24ч.\nВыберите мерчанта:",
        parse_mode="HTML",
        reply_markup=merchants_kb(merchants),
    )


async def action_last_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Проверяю...")
    try:
        rows = await asyncio.get_event_loop().run_in_executor(None, query_last_hour)
        text = format_last_hour(rows)
        # Split if exceeds Telegram 4096-char limit
        if len(text) <= 4096:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=MAIN_KB)
        else:
            parts = []
            current = ""
            for line in text.split("\n"):
                if len(current) + len(line) + 1 > 4000:
                    parts.append(current)
                    current = line
                else:
                    current += ("\n" if current else "") + line
            if current:
                parts.append(current)
            for i, part in enumerate(parts):
                kb = MAIN_KB if i == len(parts) - 1 else None
                await update.message.reply_text(part, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.error("action_last_hour error: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=MAIN_KB)


async def cb_merchant_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if not db_is_authorized(chat_id):
        return

    _, merchant_name = query.data.split("|", 1)

    if merchant_name == "__cancel__":
        await query.message.delete()
        return

    await query.message.delete()
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ Формирую PDF для <b>{merchant_name}</b>...",
        parse_mode="HTML",
    )

    try:
        clients = await asyncio.get_event_loop().run_in_executor(
            None, lambda: query_spam_by_merchant_24h(merchant_name)
        )
    except Exception as e:
        logger.error("cb_merchant_select error: %s", e)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {e}", reply_markup=MAIN_KB)
        return

    if not clients:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ У мерчанта <b>{merchant_name}</b> нет спам-клиентов за 24ч.",
            parse_mode="HTML",
            reply_markup=MAIN_KB,
        )
        return

    try:
        pdf_bytes = build_pdf(merchant_name, clients)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка PDF: {e}", reply_markup=MAIN_KB)
        return

    now_str = (datetime.utcnow() + timedelta(hours=3)).strftime("%d%m%Y_%H%M")
    filename = f"spam_{merchant_name.replace(' ', '_')}_{now_str}.pdf"

    await context.bot.send_document(
        chat_id=chat_id,
        document=io.BytesIO(pdf_bytes),
        filename=filename,
        caption=f"📄 Спам-клиенты мерчанта <b>{merchant_name}</b> за 24ч — {len(clients)} клиентов",
        parse_mode="HTML",
        reply_markup=MAIN_KB,
    )


# ── Scheduled auto-alert ──────────────────────────────────────────────────────

async def scheduled_check(app: Application):
    try:
        rows = query_alert_check()
    except Exception as e:
        logger.error("Scheduled check error: %s", e)
        return

    if not rows:
        return

    new_rows = db_mark_alerted(rows)
    if not new_rows:
        return

    text = format_alert(new_rows)
    users = db_get_users()
    logger.info("Alert: %d spammer(s), notifying %d user(s)", len(new_rows), len(users))

    for chat_id in users:
        try:
            await app.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=MAIN_KB
            )
        except Exception as e:
            logger.error("Notify %s: %s", chat_id, e)


# ── App lifecycle ─────────────────────────────────────────────────────────────

async def post_init(app: Application):
    ensure_font()
    db_ensure_tables()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_check,
        trigger="interval",
        minutes=CHECK_INTERVAL_MIN,
        args=[app],
        id="spam_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("SpamMonitorBot ready — alert threshold=%d, check every %dmin",
                SPAM_THRESHOLD, CHECK_INTERVAL_MIN)


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_merchant_select, pattern=r"^merch\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting SpamMonitorBot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
