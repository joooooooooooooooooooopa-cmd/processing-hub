"""
DailyStatsBot — ежедневная статистика ProcessingHub.

Отправляет сравнение вчера vs позавчера каждый день в 00:00 МСК.
Формулы: точная копия Dashboard #6 (PostgreSQL DB 2).
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz
import psycopg2
import requests
import urllib3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# ─── config ────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
MASTER_KEY = os.environ.get("MASTER_KEY", "")
METABASE_URL = os.environ.get("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.environ.get("METABASE_EMAIL", "")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD", "")
PG_DB_ID = int(os.environ.get("PG_DB_ID", "2"))
REPORT_HOUR = int(os.environ.get("REPORT_HOUR", "0"))
REPORT_MINUTE = int(os.environ.get("REPORT_MINUTE", "0"))
MSK = pytz.timezone("Europe/Moscow")

# ─── metabase ──────────────────────────────────────────────────────────────
_mb_token: Optional[str] = None
_mb_token_at: Optional[datetime] = None


def mb_auth() -> dict:
    global _mb_token, _mb_token_at
    now = datetime.utcnow()
    if _mb_token and _mb_token_at and (now - _mb_token_at).seconds < 21000:
        return {
            "Content-Type": "application/json",
            "X-Metabase-Session": _mb_token,
        }
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
        verify=False, timeout=15,
    )
    r.raise_for_status()
    _mb_token = r.json()["id"]
    _mb_token_at = now
    return {
        "Content-Type": "application/json",
        "X-Metabase-Session": _mb_token,
    }


def mb_query(sql: str, db_id: int = PG_DB_ID) -> list[dict]:
    r = requests.post(
        f"{METABASE_URL}/api/dataset",
        headers=mb_auth(),
        json={
            "database": db_id,
            "type": "native",
            "native": {"query": sql},
        },
        verify=False, timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"]]


# ─── local db (авторизация) ───────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL)


def db_ensure():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stats_users (
                    chat_id  BIGINT PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
    log.info("DB tables OK")


def db_add_user(chat_id: int, username: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stats_users (chat_id, username) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (chat_id, username),
            )
        conn.commit()


def db_is_auth(chat_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM stats_users WHERE chat_id = %s", (chat_id,)
            )
            return cur.fetchone() is not None


def db_all_users() -> list[int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM stats_users")
            return [r[0] for r in cur.fetchall()]


# ─── SQL (точная копия Dashboard #6, PostgreSQL DB 2) ─────────────────────

GENERAL_SQL = """
SELECT
    (orders.created_at AT TIME ZONE 'Europe/Moscow')::date AS day,
    COUNT(*) FILTER (WHERE orders.status != 'deleted')
        AS total_orders,
    COUNT(*) FILTER (WHERE orders.requisites IS NOT NULL
                     AND orders.status != 'deleted')
        AS issued_reqs,
    COUNT(*) FILTER (WHERE orders.status = 'closed')
        AS closed,
    ROUND(SUM(CASE WHEN orders.status != 'deleted'
              THEN orders.amount ELSE 0 END)::numeric, 2)
        AS turnover_all,
    ROUND(SUM(CASE WHEN orders.status = 'closed'
              THEN orders.amount ELSE 0 END)::numeric, 2)
        AS turnover_closed,
    ROUND(SUM(CASE WHEN orders.status = 'closed' THEN
        ABS(orders.amount - (orders.merchant_coins * orders.merchant_currency_rate))
        - CASE
            WHEN orders.exchange_platform_amount IS NOT NULL
                THEN ABS(orders.amount - orders.exchange_platform_amount)
            ELSE ABS(COALESCE(orders.trader_amount, 0))
          END
    ELSE 0 END)::numeric, 2)
        AS profit,
    ROUND(
        COUNT(*) FILTER (WHERE orders.status = 'closed') * 100.0 /
        NULLIF(COUNT(*) FILTER (WHERE orders.requisites IS NOT NULL
                                AND orders.status != 'deleted'), 0)
    , 2) AS conv_success,
    ROUND(
        COUNT(*) FILTER (WHERE orders.requisites IS NOT NULL
                         AND orders.status != 'deleted') * 100.0 /
        NULLIF(COUNT(*) FILTER (WHERE orders.status != 'deleted'), 0)
    , 2) AS conv_issuance,
    ROUND(AVG(CASE WHEN orders.status = 'closed' THEN
        ABS(orders.amount - (orders.merchant_coins * orders.merchant_currency_rate))
        - CASE
            WHEN orders.exchange_platform_amount IS NOT NULL
                THEN ABS(orders.amount - orders.exchange_platform_amount)
            ELSE ABS(COALESCE(orders.trader_amount, 0))
          END
    END)::numeric, 2)
        AS avg_profit_per_tx
FROM orders
WHERE orders.created_at AT TIME ZONE 'Europe/Moscow' >= '{day1}'::date
  AND orders.created_at AT TIME ZONE 'Europe/Moscow' < ('{day2}'::date + INTERVAL '1 day')
GROUP BY (orders.created_at AT TIME ZONE 'Europe/Moscow')::date
ORDER BY day
"""

DEPOSIT_BY_METHOD_SQL = """
SELECT
    (orders.created_at AT TIME ZONE 'Europe/Moscow')::date AS day,
    orders.payment_type,
    COUNT(*) AS closed,
    ROUND(SUM(orders.amount)::numeric, 2) AS closed_amount
FROM orders
WHERE orders.created_at AT TIME ZONE 'Europe/Moscow' >= '{day1}'::date
  AND orders.created_at AT TIME ZONE 'Europe/Moscow' < ('{day2}'::date + INTERVAL '1 day')
  AND orders.type = 'deposit'
  AND orders.status = 'closed'
  AND orders.payment_type IS NOT NULL
GROUP BY (orders.created_at AT TIME ZONE 'Europe/Moscow')::date, orders.payment_type
ORDER BY day, closed_amount DESC
"""

PAYOUT_SQL = """
SELECT
    (orders.created_at AT TIME ZONE 'Europe/Moscow')::date AS day,
    COUNT(*) FILTER (WHERE orders.status = 'closed') AS closed,
    ROUND(SUM(CASE WHEN orders.status = 'closed'
              THEN orders.amount ELSE 0 END)::numeric, 2) AS closed_amount
FROM orders
WHERE orders.created_at AT TIME ZONE 'Europe/Moscow' >= '{day1}'::date
  AND orders.created_at AT TIME ZONE 'Europe/Moscow' < ('{day2}'::date + INTERVAL '1 day')
  AND orders.type = 'credit'
GROUP BY (orders.created_at AT TIME ZONE 'Europe/Moscow')::date
ORDER BY day
"""


# ─── data fetch ────────────────────────────────────────────────────────────
def fetch_stats(day1: str, day2: str) -> dict:
    """
    Получает все данные за два дня.
    day1, day2 — строки 'YYYY-MM-DD'.
    Возвращает {'general': {day: row}, 'methods': {day: [rows]}, 'payouts': {day: row}}.
    """
    gen_rows = mb_query(GENERAL_SQL.format(day1=day1, day2=day2))
    dep_rows = mb_query(DEPOSIT_BY_METHOD_SQL.format(day1=day1, day2=day2))
    pay_rows = mb_query(PAYOUT_SQL.format(day1=day1, day2=day2))

    general = {}
    for r in gen_rows:
        d = str(r["day"])[:10]
        general[d] = r

    methods: dict[str, list] = {}
    for r in dep_rows:
        d = str(r["day"])[:10]
        methods.setdefault(d, []).append(r)

    payouts = {}
    for r in pay_rows:
        d = str(r["day"])[:10]
        payouts[d] = r

    return {"general": general, "methods": methods, "payouts": payouts}


# ─── formatting ───────────────────────────────────────────────────────────
def fmt_num(n, decimals=0) -> str:
    """123456789 → '123 456 789'"""
    if n is None:
        return "0"
    if decimals > 0:
        s = f"{n:,.{decimals}f}"
    else:
        s = f"{int(round(n)):,}"
    return s.replace(",", " ")


def fmt_pct_change(old, new) -> str:
    """Возвращает строку типа '+35%' или '-12%' и иконку."""
    if old is None or old == 0:
        return "+∞", "✅" if (new or 0) > 0 else "⬇️"
    change = (new - old) / abs(old) * 100
    icon = "✅" if change > 0 else ("⬇️" if change < 0 else "➡️")
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.0f}%", icon


def fmt_pp_change(old, new) -> str:
    """Для процентных пунктов."""
    if old is None:
        old = 0
    if new is None:
        new = 0
    diff = new - old
    sign = "+" if diff > 0 else ""
    icon = "✅" if diff > 0 else ("⬇️" if diff < 0 else "➡️")
    return f"{sign}{diff:.2f} пп", icon


def format_day(d: str) -> str:
    """'2026-03-07' → '7 марта'"""
    months = [
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ]
    parts = d.split("-")
    day = int(parts[2])
    month = int(parts[1])
    return f"{day} {months[month]}"


def build_report(day1: str, day2: str) -> str:
    """
    Строит текст отчёта. day1 — ранний день, day2 — поздний.
    Формат: day1 → day2.
    """
    data = fetch_stats(day1, day2)
    g1 = data["general"].get(day1, {})
    g2 = data["general"].get(day2, {})
    m1 = data["methods"].get(day1, [])
    m2 = data["methods"].get(day2, [])
    p1 = data["payouts"].get(day1, {})
    p2 = data["payouts"].get(day2, {})

    d1_label = format_day(day1)
    d2_label = format_day(day2)

    def g(row, key, default=0):
        return row.get(key, default) or default

    lines = [f"📊 Статистика ({d1_label} → {d2_label})", ""]

    # Прибыль
    pct, icon = fmt_pct_change(g(g1, "profit"), g(g2, "profit"))
    lines.append(
        f"💰 Прибыль: {fmt_num(g(g1, 'profit'))} ₽ → "
        f"{fmt_num(g(g2, 'profit'))} ₽ ({pct}) {icon}"
    )

    # Оборот (все статусы)
    pct, icon = fmt_pct_change(g(g1, "turnover_all"), g(g2, "turnover_all"))
    lines.append(
        f"📈 Оборот: {fmt_num(g(g1, 'turnover_all'))} ₽ → "
        f"{fmt_num(g(g2, 'turnover_all'))} ₽ ({pct}) {icon}"
    )

    # Успешных
    pct, icon = fmt_pct_change(g(g1, "closed"), g(g2, "closed"))
    lines.append(
        f"✅ Успешных: {fmt_num(g(g1, 'closed'))} → "
        f"{fmt_num(g(g2, 'closed'))} ({pct}) {icon}"
    )

    # Сумма успешных
    pct, icon = fmt_pct_change(
        g(g1, "turnover_closed"), g(g2, "turnover_closed")
    )
    lines.append(
        f"💵 Сумма успешных: {fmt_num(g(g1, 'turnover_closed'))} ₽ → "
        f"{fmt_num(g(g2, 'turnover_closed'))} ₽ ({pct}) {icon}"
    )

    # Выдано реков
    pct, icon = fmt_pct_change(g(g1, "issued_reqs"), g(g2, "issued_reqs"))
    lines.append(
        f"📋 Выдано реков: {fmt_num(g(g1, 'issued_reqs'))} → "
        f"{fmt_num(g(g2, 'issued_reqs'))} ({pct}) {icon}"
    )

    # Всего заявок
    pct, icon = fmt_pct_change(g(g1, "total_orders"), g(g2, "total_orders"))
    lines.append(
        f"📊 Всего заявок: {fmt_num(g(g1, 'total_orders'))} → "
        f"{fmt_num(g(g2, 'total_orders'))} ({pct}) {icon}"
    )

    # Конверсия в успех
    pp, icon = fmt_pp_change(g(g1, "conv_success"), g(g2, "conv_success"))
    lines.append(
        f"🎯 Конверсия в успех: {g(g1, 'conv_success'):.2f}% → "
        f"{g(g2, 'conv_success'):.2f}% ({pp}) {icon}"
    )

    # Конверсия в выдачу
    pp, icon = fmt_pp_change(g(g1, "conv_issuance"), g(g2, "conv_issuance"))
    lines.append(
        f"🔄 Конверсия в выдачу: {g(g1, 'conv_issuance'):.2f}% → "
        f"{g(g2, 'conv_issuance'):.2f}% ({pp}) {icon}"
    )

    # Средняя прибыль на транзакцию
    pct, icon = fmt_pct_change(
        g(g1, "avg_profit_per_tx"), g(g2, "avg_profit_per_tx")
    )
    lines.append(
        f"💵 Ср. прибыль/транзакцию: {fmt_num(g(g1, 'avg_profit_per_tx'), 2)} ₽ → "
        f"{fmt_num(g(g2, 'avg_profit_per_tx'), 2)} ₽ ({pct}) {icon}"
    )

    # По методам (депозиты)
    lines.append("")
    lines.append("📦 По методам (депозиты, closed):")

    m1_map = {r["payment_type"]: r for r in m1}
    m2_map = {r["payment_type"]: r for r in m2}
    all_types = []
    seen = set()
    for r in m2 + m1:
        pt = r["payment_type"]
        if pt not in seen:
            all_types.append(pt)
            seen.add(pt)

    for pt in all_types:
        r1 = m1_map.get(pt, {})
        r2 = m2_map.get(pt, {})
        a1 = r1.get("closed_amount", 0) or 0
        a2 = r2.get("closed_amount", 0) or 0
        c1 = r1.get("closed", 0) or 0
        c2 = r2.get("closed", 0) or 0
        if a1 == 0 and a2 == 0:
            continue
        pct, icon = fmt_pct_change(a1, a2)
        lines.append(
            f"• {pt.upper()} — {fmt_num(a1)} ₽ ({fmt_num(c1)}) → "
            f"{fmt_num(a2)} ₽ ({fmt_num(c2)}) {pct} {icon}"
        )

    # Выплаты
    lines.append("")
    lines.append("💳 Выплаты:")
    pct, icon = fmt_pct_change(
        p1.get("closed", 0) or 0, p2.get("closed", 0) or 0
    )
    lines.append(
        f"• Закрыто: {fmt_num(p1.get('closed', 0))} → "
        f"{fmt_num(p2.get('closed', 0))} ({pct}) {icon}"
    )
    pct, icon = fmt_pct_change(
        p1.get("closed_amount", 0) or 0, p2.get("closed_amount", 0) or 0
    )
    lines.append(
        f"• Сумма: {fmt_num(p1.get('closed_amount', 0))} ₽ → "
        f"{fmt_num(p2.get('closed_amount', 0))} ₽ ({pct}) {icon}"
    )

    return "\n".join(lines)


# ─── telegram handlers ────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if db_is_auth(cid):
        await update.message.reply_text(
            "✅ Вы авторизованы.\n\n"
            "/stats — статистика вчера vs позавчера\n"
            "Отчёт автоматически приходит каждый день в 00:00 МСК"
        )
        return
    await update.message.reply_text("🔑 Отправьте мастер-ключ для авторизации.")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    text = (update.message.text or "").strip()

    if not db_is_auth(cid):
        if text == MASTER_KEY:
            uname = (
                update.effective_user.username
                or str(update.effective_user.id)
            )
            db_add_user(cid, uname)
            log.info("Authorized: %s (%s)", cid, uname)
            await update.message.reply_text(
                "✅ Авторизация успешна!\n\n"
                "/stats — статистика вчера vs позавчера\n"
                "Отчёт автоматически приходит каждый день в 00:00 МСК"
            )
        else:
            await update.message.reply_text("❌ Неверный ключ.")
        return


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db_is_auth(update.effective_chat.id):
        await update.message.reply_text("🔑 Сначала авторизуйтесь: /start")
        return

    msg = await update.message.reply_text("⏳ Собираю данные...")
    try:
        now_msk = datetime.now(MSK)
        yesterday = (now_msk - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before = (now_msk - timedelta(days=2)).strftime("%Y-%m-%d")

        report = build_report(day_before, yesterday)
        await msg.edit_text(report)
    except Exception as e:
        log.exception("cmd_stats error")
        await msg.edit_text(f"❌ Ошибка: {e}")


# ─── scheduler ─────────────────────────────────────────────────────────────
async def send_daily_report(app):
    """Ежедневный отчёт в 00:00 МСК."""
    log.info("Daily report starting")
    try:
        now_msk = datetime.now(MSK)
        yesterday = (now_msk - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before = (now_msk - timedelta(days=2)).strftime("%Y-%m-%d")

        report = build_report(day_before, yesterday)

        for cid in db_all_users():
            try:
                await app.bot.send_message(cid, report)
            except Exception as e:
                log.warning("Notify %s failed: %s", cid, e)

        log.info("Daily report sent to %d users", len(db_all_users()))
    except Exception as e:
        log.exception("Daily report failed")


# ─── main ──────────────────────────────────────────────────────────────────
async def post_init(app: Application):
    db_ensure()
    users = db_all_users()
    log.info("DB ready. Authorized users: %d — %s", len(users), users)

    # Test Metabase connection
    try:
        mb_auth()
        log.info("Metabase auth OK")
    except Exception as e:
        log.error("Metabase auth FAILED: %s", e)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_daily_report,
        CronTrigger(
            hour=REPORT_HOUR,
            minute=REPORT_MINUTE,
            timezone="Europe/Moscow",
        ),
        args=[app],
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler: daily at %02d:%02d MSK", REPORT_HOUR, REPORT_MINUTE)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    log.info("DailyStatsBot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
