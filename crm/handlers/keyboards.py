"""Keyboard builder functions for the Merchant CRM bot."""

from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from handlers.utils import (
    BTN_TODAY,
    BTN_CANCELED,
    BTN_ALERTS,
    BTN_CONVERSION,
    BTN_LOW_CONVERSION,
    BTN_BAD_CLIENTS,
    BTN_SEARCH,
    BTN_EXPORT,
    BTN_RATES,
    BTN_ADD_MERCHANT,
    BTN_EDIT_MERCHANT,
    BTN_INCIDENTS,
    BTN_NEW_INCIDENT,
    BTN_UPLOAD_EXPORT,
    BTN_ACTIVE_SUMMARY,
    BTN_PAYOUT,
    BTN_METHOD_OVERVIEW,
    BTN_ADMIN,
)

import database

# ── Incident-list helpers ──────────────────────────────────
INC_PAGE_SIZE = 5
PRIORITY_EMOJI = {'P0': '🔴', 'P1': '🟠', 'P2': '🟡', 'P3': '⚪'}


# ── Keyboards ──────────────────────────────────────────────

def kb_main(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню — понятные категории"""
    buttons = [
        [KeyboardButton(BTN_CONVERSION)],
        [KeyboardButton(BTN_LOW_CONVERSION)],
        [KeyboardButton(BTN_PAYOUT)],
        [KeyboardButton(BTN_METHOD_OVERVIEW)],
        [KeyboardButton(BTN_UPLOAD_EXPORT), KeyboardButton(BTN_ACTIVE_SUMMARY)],
    ]
    if is_admin:
        buttons.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def kb_refresh(callback_data: str) -> InlineKeyboardMarkup:
    """Кнопка обновления"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить данные", callback_data=callback_data)]
    ])


def kb_export() -> InlineKeyboardMarkup:
    """Меню экспорта"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Мерчанты (CSV)", callback_data="export_merchants")],
        [InlineKeyboardButton("💳 Методы оплаты (CSV)", callback_data="export_methods")],
        [InlineKeyboardButton("🕐 По часам (CSV)", callback_data="export_hourly")],
        [InlineKeyboardButton("📈 Конверсия за неделю (CSV)", callback_data="export_conv_history")],
        [InlineKeyboardButton("🚨 Инциденты за месяц (CSV)", callback_data="export_incidents")],
        [InlineKeyboardButton("📋 Скачать всё (ZIP)", callback_data="export_all")],
    ])


def kb_cancel() -> ReplyKeyboardMarkup:
    """Кнопка отмены"""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("◀️ Вернуться в меню")]],
        resize_keyboard=True
    )


def kb_admin() -> InlineKeyboardMarkup:
    """Админ-панель"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Создать ключ", callback_data="admin_newkey")],
        [InlineKeyboardButton("📋 Список ключей", callback_data="admin_keys")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton("📊 Статистика ключей", callback_data="admin_stats")],
    ])


def kb_merchant_card(merchant_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Статус", callback_data=f"medit_status:{merchant_id}"),
         InlineKeyboardButton("📝 Заметки", callback_data=f"medit_notes:{merchant_id}")],
        [InlineKeyboardButton("🏷️ Добавить тег", callback_data=f"medit_tag:{merchant_id}"),
         InlineKeyboardButton("📞 Контакт", callback_data=f"medit_contact:{merchant_id}")],
        [InlineKeyboardButton("💰 Ставка", callback_data=f"medit_rate:{merchant_id}"),
         InlineKeyboardButton("📊 История конв.", callback_data=f"mhist:{merchant_id}")],
        [InlineKeyboardButton("🚨 Создать инцидент", callback_data=f"inc_new_from_card:{merchant_id}")],
    ])


def kb_alert(merchant_name: str) -> InlineKeyboardMarkup:
    n = merchant_name[:30]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚨 Создать инцидент", callback_data=f"alert_inc:{n}"),
         InlineKeyboardButton("✏️ Статус", callback_data=f"alert_status:{n}")],
        [InlineKeyboardButton("📊 Карточка CRM", callback_data=f"alert_card:{n}")],
    ])


def kb_incidents_list(incidents: list, page: int = 0) -> InlineKeyboardMarkup:
    total = len(incidents)
    total_pages = (total + INC_PAGE_SIZE - 1) // INC_PAGE_SIZE if total else 1
    page_items = incidents[page * INC_PAGE_SIZE:(page + 1) * INC_PAGE_SIZE]
    rows = []
    for inc in page_items:
        pe = PRIORITY_EMOJI.get(inc.get('priority', 'P2'), '⚪')
        name = inc.get('merchant_name', '')[:15]
        comment_count = database.get_incident_comment_count(inc['id'])
        rows.append([
            InlineKeyboardButton(f"{pe} {name}", callback_data=f"inc_view:{inc['id']}"),
            InlineKeyboardButton("✋", callback_data=f"inc_take:{inc['id']}"),
            InlineKeyboardButton("✅", callback_data=f"inc_close:{inc['id']}"),
            InlineKeyboardButton(f"💬{comment_count}", callback_data=f"inc_comments:{inc['id']}"),
        ])
    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"inc_page:{page - 1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="inc_page_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"inc_page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("➕ Создать инцидент", callback_data="inc_create_start")])
    return InlineKeyboardMarkup(rows)
