"""
MerchantReportBot — выгрузка потранзакционки по мерчантам в Excel.

Фичи:
- Выбор мерчанта (с подсказками из БД)
- Фильтр статусов: успешные, +просроченные, +отмененные, все
- Выбор периода (дата от — дата до)
- Выгрузка в Excel (.xlsx)
- Управление доступом (админ выдаёт/отзывает)
"""

import os
import io
import logging
from datetime import datetime, timedelta

import pytz
import psycopg2
import requests
import urllib3
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# ─── config ──────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
METABASE_URL = os.environ.get("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.environ.get("METABASE_EMAIL", "")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD", "")
PG_DB_ID = int(os.environ.get("PG_DB_ID", "2"))
MSK = pytz.timezone("Europe/Moscow")

# ─── conversation states ─────────────────────────────────────────────────
CHOOSE_LETTER, CHOOSE_MERCHANT, CHOOSE_STATUS, CHOOSE_DATE_FROM, CHOOSE_DATE_TO = range(5)

# ─── status filter presets ───────────────────────────────────────────────
STATUS_FILTERS = {
    "Успешные (closed)": ["closed"],
    "Успешные + Неуспешные": ["closed", "failed"],
    "Успешные + Отмененные": ["closed", "canceled"],
    "Все операции": ["closed", "canceled", "failed", "process"],
}

STATUS_ICONS = {
    "Успешные (closed)": "✅",
    "Успешные + Неуспешные": "✅❌",
    "Успешные + Отмененные": "✅🚫",
    "Все операции": "📋",
}

# ─── main menu keyboard ─────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup(
    [["📊 Выгрузка транзакций"], ["❓ Помощь"]],
    resize_keyboard=True,
)

ADMIN_KB = ReplyKeyboardMarkup(
    [["📊 Выгрузка транзакций"], ["👥 Управление доступом", "❓ Помощь"]],
    resize_keyboard=True,
)

# ─── metabase ────────────────────────────────────────────────────────────
_mb_token = None
_mb_token_at = None


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
        verify=False,
        timeout=15,
    )
    r.raise_for_status()
    _mb_token = r.json()["id"]
    _mb_token_at = now
    return {
        "Content-Type": "application/json",
        "X-Metabase-Session": _mb_token,
    }


def mb_query(sql: str, db_id: int = None) -> list[dict]:
    if db_id is None:
        db_id = PG_DB_ID
    r = requests.post(
        f"{METABASE_URL}/api/dataset",
        headers=mb_auth(),
        json={
            "database": db_id,
            "type": "native",
            "native": {"query": sql},
        },
        verify=False,
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"]]


# ─── local db (авторизация) ──────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL)


def db_ensure():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS report_users (
                    chat_id  BIGINT PRIMARY KEY,
                    username TEXT,
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
    log.info("DB tables OK")


def db_add_user(chat_id: int, username: str, added_by: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO report_users (chat_id, username, added_by) "
                "VALUES (%s, %s, %s) ON CONFLICT (chat_id) DO UPDATE SET username = %s",
                (chat_id, username, added_by, username),
            )
        conn.commit()


def db_remove_user(chat_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM report_users WHERE chat_id = %s", (chat_id,))
        conn.commit()


def db_is_auth(chat_id: int) -> bool:
    if chat_id == ADMIN_ID:
        return True
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM report_users WHERE chat_id = %s", (chat_id,))
            return cur.fetchone() is not None


def db_all_users() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, username, added_at FROM report_users ORDER BY added_at")
            return [
                {"chat_id": r[0], "username": r[1], "added_at": r[2]}
                for r in cur.fetchall()
            ]


# ─── data queries ────────────────────────────────────────────────────────
def fetch_merchants() -> list[str]:
    """Получить список мерчантов из PostgreSQL."""
    rows = mb_query(
        "SELECT name FROM merchants "
        "WHERE name IS NOT NULL AND name != '' AND deleted_at IS NULL "
        "ORDER BY name"
    )
    return [r["name"] for r in rows]


def escape_sql(value: str) -> str:
    """Escape single quotes for PostgreSQL SQL."""
    return value.replace("'", "''")


def fetch_transactions(merchant: str, statuses: list[str],
                       date_from: str, date_to: str) -> list[dict]:
    """Выгрузка транзакций — формат карточки Metabase #253."""
    status_list = ", ".join(f"'{s}'" for s in statuses)
    safe_merchant = escape_sql(merchant)
    sql = f"""
    SELECT
        orders.created_at,
        orders.updated_at,
        orders.client_id,
        orders.type,
        orders.id,
        orders.external_id,
        orders.number,
        orders.payment_type,
        orders.status,
        merchants.name AS merchant_name,
        orders.currency,
        orders.amount,
        orders.amount - (orders.merchant_coins * orders.merchant_currency_rate) AS merchant_fee,
        orders.merchant_currency_rate,
        orders.merchant_coins,
        orders.merchant_currency
    FROM orders
    LEFT JOIN merchants ON orders.merchant_id = merchants.id
    WHERE 1=1
      AND orders.requisites IS NOT NULL
      AND merchants.name = '{safe_merchant}'
      AND orders.status IN ({status_list})
      AND (orders.created_at AT TIME ZONE 'Europe/Moscow')::date >= '{date_from}'::date
      AND (orders.created_at AT TIME ZONE 'Europe/Moscow')::date <= '{date_to}'::date
    ORDER BY orders.updated_at ASC
    """
    return mb_query(sql)


# ─── excel generation ────────────────────────────────────────────────────
def generate_excel(rows: list[dict], merchant: str,
                   statuses: list[str], date_from: str, date_to: str) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Транзакции"

    # Header style
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Info rows
    ws.append(["Мерчант:", merchant])
    ws.append(["Период:", f"{date_from} — {date_to}"])
    ws.append(["Статусы:", ", ".join(statuses)])
    ws.append(["Всего строк:", len(rows)])
    ws.append([])

    # Column headers
    headers = [
        "Создан", "Обновлён", "Client ID", "Тип", "ID",
        "External ID", "Номер", "Метод оплаты", "Статус",
        "Мерчант", "Валюта", "Сумма", "Комиссия мерчанта",
        "Курс мерчанта", "Merchant Coins", "Валюта мерчанта",
    ]
    ws.append(headers)
    header_row = 6
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # Data rows
    keys = [
        "created_at", "updated_at", "client_id", "type", "id",
        "external_id", "number", "payment_type", "status",
        "merchant_name", "currency", "amount", "merchant_fee",
        "merchant_currency_rate", "merchant_coins", "merchant_currency",
    ]

    status_colors = {
        "closed": "C6EFCE",
        "canceled": "FFC7CE",
        "failed": "FFD9D9",
        "process": "FFEB9C",
    }

    for row_idx, row in enumerate(rows, header_row + 1):
        values = [row.get(k, "") for k in keys]
        ws.append(values)

        status_val = row.get("status", "")
        if status_val in status_colors:
            fill = PatternFill(
                start_color=status_colors[status_val],
                end_color=status_colors[status_val],
                fill_type="solid",
            )
            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill

        for col_idx in range(1, len(headers) + 1):
            ws.cell(row=row_idx, column=col_idx).border = thin_border

    # Auto-width
    for col_idx, h in enumerate(headers, 1):
        max_len = len(h)
        for row_idx in range(header_row + 1, min(header_row + 101, ws.max_row + 1)):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 40)

    # Summary sheet
    ws2 = wb.create_sheet("Сводка")
    ws2.append(["Статус", "Кол-во", "Сумма"])
    for col_idx in range(1, 4):
        cell = ws2.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill

    status_summary = {}
    for row in rows:
        s = row.get("status", "unknown")
        if s not in status_summary:
            status_summary[s] = {"count": 0, "amount": 0}
        status_summary[s]["count"] += 1
        status_summary[s]["amount"] += float(row.get("amount", 0) or 0)

    for s, data in sorted(status_summary.items()):
        ws2.append([s, data["count"], round(data["amount"], 2)])

    ws2.append([])
    ws2.append(["ИТОГО", len(rows), round(sum(d["amount"] for d in status_summary.values()), 2)])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─── telegram handlers ──────────────────────────────────────────────────
def get_kb(chat_id: int):
    return ADMIN_KB if chat_id == ADMIN_ID else MAIN_KB


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not db_is_auth(cid):
        await update.message.reply_text(
            "🔒 <b>Доступ ограничен</b>\n\n"
            "Обратитесь к администратору для получения доступа.",
            parse_mode="HTML",
        )
        return

    name = update.effective_user.first_name or "User"
    await update.message.reply_text(
        f"👋 Привет, <b>{name}</b>!\n\n"
        "📊 <b>Бот выгрузки транзакций по мерчантам</b>\n\n"
        "Нажмите кнопку ниже для начала работы.",
        parse_mode="HTML",
        reply_markup=get_kb(cid),
    )


# ─── report conversation ────────────────────────────────────────────────
def build_letter_buttons(merchants: list[str]) -> InlineKeyboardMarkup:
    """Build alphabet navigation buttons from merchant first letters."""
    letters = sorted(set(m[0].upper() for m in merchants if m))
    buttons = []
    row = []
    for letter in letters:
        count = sum(1 for m in merchants if m[0].upper() == letter)
        row.append(InlineKeyboardButton(
            f"{letter} ({count})", callback_data=f"l:{letter}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def build_merchant_buttons(merchants: list[str], all_merchants: list[str]) -> InlineKeyboardMarkup:
    """Build merchant selection buttons (1 per row for readability)."""
    buttons = []
    for m in merchants[:40]:
        idx = all_merchants.index(m)
        buttons.append([InlineKeyboardButton(f"🏢 {m}", callback_data=f"m:{idx}")])
    if len(merchants) > 40:
        buttons.append([InlineKeyboardButton(
            f"... ещё {len(merchants) - 40} — напишите название", callback_data="noop"
        )])
    buttons.append([InlineKeyboardButton("⬅️ Назад к буквам", callback_data="l:back")])
    return InlineKeyboardMarkup(buttons)


async def report_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not db_is_auth(cid):
        await update.message.reply_text("🔒 У вас нет доступа.")
        return ConversationHandler.END

    msg = await update.message.reply_text("⏳ Загружаю список мерчантов...")
    try:
        merchants = fetch_merchants()
        ctx.user_data["merchants"] = merchants
    except Exception as e:
        log.exception("Failed to fetch merchants")
        await msg.edit_text(f"❌ Ошибка загрузки: {e}")
        return ConversationHandler.END

    if len(merchants) <= 40:
        kb = build_merchant_buttons(merchants, merchants)
        await msg.edit_text(
            f"🏢 <b>Выбор мерчанта</b>\n\n"
            f"Найдено: {len(merchants)}\n"
            f"Выберите из списка или напишите название:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return CHOOSE_MERCHANT
    else:
        kb = build_letter_buttons(merchants)
        await msg.edit_text(
            f"🏢 <b>Выбор мерчанта</b>\n\n"
            f"Найдено: {len(merchants)}\n"
            f"Выберите первую букву или напишите название:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return CHOOSE_LETTER


async def letter_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    letter = query.data[2:]
    if letter == "back":
        merchants = ctx.user_data.get("merchants", [])
        kb = build_letter_buttons(merchants)
        await query.edit_message_text(
            f"🏢 <b>Выбор мерчанта</b>\n\n"
            f"Найдено: {len(merchants)}\n"
            f"Выберите первую букву или напишите название:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return CHOOSE_LETTER

    merchants = ctx.user_data.get("merchants", [])
    filtered = [m for m in merchants if m[0].upper() == letter]

    kb = build_merchant_buttons(filtered, merchants)
    await query.edit_message_text(
        f"🏢 <b>Мерчанты на «{letter}»</b>  ({len(filtered)} шт.)\n\n"
        f"Выберите или напишите название:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return CHOOSE_MERCHANT


def build_status_buttons() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            f"{STATUS_ICONS[label]} {label}", callback_data=f"s:{label}"
        )]
        for label in STATUS_FILTERS
    ]
    return InlineKeyboardMarkup(buttons)


async def merchant_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "noop":
        await query.answer("Напишите название мерчанта текстом")
        return CHOOSE_MERCHANT
    await query.answer()

    idx = int(query.data[2:])
    merchants = ctx.user_data.get("merchants", [])
    merchant = merchants[idx]
    ctx.user_data["merchant"] = merchant

    await query.edit_message_text(
        f"🏢 Мерчант: <b>{merchant}</b>\n\n"
        f"📋 Выберите фильтр статусов:",
        parse_mode="HTML",
        reply_markup=build_status_buttons(),
    )
    return CHOOSE_STATUS


async def merchant_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    merchants = ctx.user_data.get("merchants", [])

    matches = [m for m in merchants if text.lower() in m.lower()]

    if not matches:
        await update.message.reply_text(
            f"❌ Мерчант «{text}» не найден.\nПопробуйте другое название."
        )
        return CHOOSE_MERCHANT

    if len(matches) == 1:
        ctx.user_data["merchant"] = matches[0]
        await update.message.reply_text(
            f"🏢 Мерчант: <b>{matches[0]}</b>\n\n"
            f"📋 Выберите фильтр статусов:",
            parse_mode="HTML",
            reply_markup=build_status_buttons(),
        )
        return CHOOSE_STATUS

    kb = build_merchant_buttons(matches, merchants)
    await update.message.reply_text(
        f"🔍 Найдено <b>{len(matches)}</b> совпадений по «{text}»\n\nВыберите:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return CHOOSE_MERCHANT


async def status_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    label = query.data[2:]
    ctx.user_data["status_label"] = label
    ctx.user_data["statuses"] = STATUS_FILTERS[label]

    now_msk = datetime.now(MSK)
    today = now_msk.strftime("%Y-%m-%d")
    yesterday = (now_msk - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (now_msk - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now_msk - timedelta(days=30)).strftime("%Y-%m-%d")

    buttons = [
        [
            InlineKeyboardButton("📅 Сегодня", callback_data=f"d:{today}:{today}"),
            InlineKeyboardButton("📅 Вчера", callback_data=f"d:{yesterday}:{yesterday}"),
        ],
        [
            InlineKeyboardButton("📆 7 дней", callback_data=f"d:{week_ago}:{today}"),
            InlineKeyboardButton("📆 30 дней", callback_data=f"d:{month_ago}:{today}"),
        ],
    ]

    await query.edit_message_text(
        f"🏢 Мерчант: <b>{ctx.user_data['merchant']}</b>\n"
        f"{STATUS_ICONS.get(label, '')} Статусы: <b>{label}</b>\n\n"
        f"📅 Выберите период или напишите дату (ГГГГ-ММ-ДД):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return CHOOSE_DATE_FROM


async def date_quick_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data[2:].split(":")
    date_from, date_to = parts[0], parts[1]
    ctx.user_data["date_from"] = date_from
    ctx.user_data["date_to"] = date_to

    await query.edit_message_text("⏳ Формирую выгрузку...")
    await do_export(query.message, ctx, query.from_user.id)
    return ConversationHandler.END


async def date_from_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите дату как ГГГГ-ММ-ДД:")
        return CHOOSE_DATE_FROM

    ctx.user_data["date_from"] = text
    await update.message.reply_text(
        f"📅 Дата начала: <b>{text}</b>\n\n"
        "Теперь введите дату окончания (ГГГГ-ММ-ДД):",
        parse_mode="HTML",
    )
    return CHOOSE_DATE_TO


async def date_to_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите дату как ГГГГ-ММ-ДД:")
        return CHOOSE_DATE_TO

    ctx.user_data["date_to"] = text
    msg = await update.message.reply_text("⏳ Формирую выгрузку...")
    await do_export(msg, ctx, update.effective_chat.id)
    return ConversationHandler.END


async def do_export(msg, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    merchant = ctx.user_data["merchant"]
    statuses = ctx.user_data["statuses"]
    status_label = ctx.user_data["status_label"]
    date_from = ctx.user_data["date_from"]
    date_to = ctx.user_data["date_to"]

    try:
        rows = fetch_transactions(merchant, statuses, date_from, date_to)
    except Exception as e:
        log.exception("fetch_transactions error")
        await msg.edit_text(f"❌ Ошибка при запросе данных: {e}")
        return

    if not rows:
        await msg.edit_text(
            f"📭 <b>Нет транзакций</b>\n\n"
            f"🏢 {merchant}\n"
            f"📋 {status_label}\n"
            f"📅 {date_from} — {date_to}",
            parse_mode="HTML",
        )
        return

    try:
        buf = generate_excel(rows, merchant, statuses, date_from, date_to)
    except Exception as e:
        log.exception("generate_excel error")
        await msg.edit_text(f"❌ Ошибка генерации Excel: {e}")
        return

    # Calculate summary
    total_amount = sum(float(r.get("amount", 0) or 0) for r in rows)
    closed_count = sum(1 for r in rows if r.get("status") == "closed")

    safe_name = merchant.replace(" ", "_").replace("/", "_")[:30]
    filename = f"{safe_name}_{date_from}_{date_to}.xlsx"

    await msg.edit_text(
        f"✅ <b>Выгрузка готова</b>\n\n"
        f"🏢 {merchant}\n"
        f"📋 {status_label}\n"
        f"📅 {date_from} — {date_to}\n\n"
        f"📊 Всего: <b>{len(rows)}</b> транзакций\n"
        f"✅ Успешных: <b>{closed_count}</b>\n"
        f"💰 Сумма: <b>{total_amount:,.2f}</b> ₽",
        parse_mode="HTML",
    )
    await msg.reply_document(
        document=buf,
        filename=filename,
        caption=f"📎 {merchant} | {status_label} | {date_from} — {date_to}",
        reply_markup=get_kb(chat_id),
    )


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text("Отменено.", reply_markup=get_kb(cid))
    return ConversationHandler.END


# ─── access management ──────────────────────────────────────────────────
async def access_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid != ADMIN_ID:
        await update.message.reply_text("🔒 Только администратор может управлять доступом.")
        return

    users = db_all_users()
    text = "👥 <b>Управление доступом</b>\n\n"
    if users:
        for i, u in enumerate(users, 1):
            date_str = u['added_at'].strftime('%d.%m.%Y') if u['added_at'] else '?'
            text += f"{i}. <code>{u['chat_id']}</code> — @{u['username']} ({date_str})\n"
    else:
        text += "<i>Нет пользователей</i>\n"

    text += (
        "\n<b>Команды:</b>\n"
        "/add &lt;chat_id&gt; — выдать доступ\n"
        "/remove &lt;chat_id&gt; — отозвать доступ"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid != ADMIN_ID:
        await update.message.reply_text("Только администратор.")
        return

    if not ctx.args:
        await update.message.reply_text("Использование: /add <chat_id>")
        return

    try:
        target_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("chat_id должен быть числом.")
        return

    username = ctx.args[1] if len(ctx.args) > 1 else str(target_id)
    db_add_user(target_id, username, cid)
    await update.message.reply_text(f"Доступ выдан: {target_id} ({username})")

    # Notify user
    try:
        await ctx.bot.send_message(
            target_id,
            "Вам выдан доступ к боту выгрузки транзакций.\nНажмите /start",
        )
    except Exception:
        pass


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid != ADMIN_ID:
        await update.message.reply_text("Только администратор.")
        return

    if not ctx.args:
        await update.message.reply_text("Использование: /remove <chat_id>")
        return

    try:
        target_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("chat_id должен быть числом.")
        return

    db_remove_user(target_id)
    await update.message.reply_text(f"Доступ отозван: {target_id}")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    text = (
        "📖 <b>Как пользоваться</b>\n\n"
        "1️⃣ Нажмите «📊 Выгрузка транзакций»\n"
        "2️⃣ Выберите мерчанта (по букве или поиском)\n"
        "3️⃣ Выберите фильтр статусов\n"
        "4️⃣ Выберите период\n"
        "5️⃣ Получите Excel-файл\n\n"
        "💡 /cancel — отменить текущую операцию"
    )
    if cid == ADMIN_ID:
        text += (
            "\n\n👤 <b>Админ-команды:</b>\n"
            "/add &lt;chat_id&gt; [username] — выдать доступ\n"
            "/remove &lt;chat_id&gt; — отозвать доступ"
        )
    await update.message.reply_text(text, parse_mode="HTML")


# ─── main ────────────────────────────────────────────────────────────────
async def post_init(app: Application):
    db_ensure()
    users = db_all_users()
    log.info("DB ready. Users: %d", len(users))

    try:
        mb_auth()
        log.info("Metabase auth OK")
    except Exception as e:
        log.error("Metabase auth FAILED: %s", e)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Conversation for report generation
    report_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📊 Выгрузка транзакций$"), report_start),
        ],
        states={
            CHOOSE_LETTER: [
                CallbackQueryHandler(letter_button, pattern=r"^l:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, merchant_text),
            ],
            CHOOSE_MERCHANT: [
                CallbackQueryHandler(merchant_button, pattern=r"^m:"),
                CallbackQueryHandler(letter_button, pattern=r"^l:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, merchant_text),
            ],
            CHOOSE_STATUS: [
                CallbackQueryHandler(status_button, pattern=r"^s:"),
            ],
            CHOOSE_DATE_FROM: [
                CallbackQueryHandler(date_quick_button, pattern=r"^d:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, date_from_text),
            ],
            CHOOSE_DATE_TO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, date_to_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^Отмена$"), cancel),
        ],
    )

    app.add_handler(report_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Regex("^❓ Помощь$"), cmd_help))
    app.add_handler(MessageHandler(filters.Regex("^👥 Управление доступом$"), access_menu))

    log.info("MerchantReportBot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
