"""
CRM-related handlers: merchant cards, add/edit merchant, incidents,
inline queries, and alert callbacks.
"""

import logging
from datetime import datetime, timedelta

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import ContextTypes, ConversationHandler

import database
import storage

from handlers.utils import (
    escape,
    is_authenticated,
    is_admin,
    time_ago,
    calculate_merchant_score,
    score_emoji,
    MSK,
    MERCH_NAME,
    MERCH_STATUS,
    MERCH_RATE,
    MERCH_CONTACT,
    MERCH_NOTES,
    EDIT_FIND,
    EDIT_FIELD,
    EDIT_VALUE,
    INC_MERCHANT,
    INC_TYPE,
    INC_PRIORITY,
    INC_DESC,
    INC_DUE,
    INC_COMMENT_TEXT,
    INC_CLOSE_NOTES,
    MERCH_TAG_INPUT,
)
from handlers.keyboards import (
    kb_main,
    kb_merchant_card,
    kb_alert,
    kb_incidents_list,
    INC_PAGE_SIZE,
    PRIORITY_EMOJI,
)

logger = logging.getLogger(__name__)

# ============ TREND ICONS ============

TREND_ICON = {'declining': '📉', 'improving': '📈', 'stable': ''}

# ============ CRM: КАРТОЧКА МЕРЧАНТА ============

STATUS_EMOJI = {
    'active': '🟢', 'testing': '🔵', 'integration': '🔧',
    'negotiation': '🤝', 'new': '🆕', 'paused': '⏸️',
    'problem': '🟡', 'disconnected': '🔴',
}


def format_unified_card(mb_data: dict, crm_m: dict, tags: list, score: int, trend: str) -> str:
    """Объединённая карточка: live-данные Metabase + CRM-профиль"""
    name = escape(mb_data.get("name") or (crm_m.get("name") if crm_m else "?"))
    sc_e = score_emoji(score) if score is not None else ""
    sc_txt = f"{sc_e} <b>{score}/100</b>" if score is not None else ""
    tr_icon = TREND_ICON.get(trend, "")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏪  <b>{name}</b>   {sc_txt} {tr_icon}".strip(),
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Блок live-данных из Metabase
    today = mb_data.get("today") or {}
    if today:
        total = today.get("Всего", 0) or 0
        success = today.get("Успешных", 0) or 0
        conv = today.get("Конверсия %", 0) or 0
        lines.append("")
        lines.append("📊 <b>СЕГОДНЯ (live)</b>")
        lines.append(f"   Конверсия: <b>{conv:.1f}%</b>  |  Заявок: {total}")
        lines.append(f"   Успешных: {success}")
    else:
        lines.append("\n📊 <b>СЕГОДНЯ:</b> нет данных Metabase")

    # Блок CRM
    if crm_m:
        status_e = STATUS_EMOJI.get(crm_m.get('status', ''), '⚪')
        upd = time_ago(crm_m.get('updated_at', '')) if crm_m.get('updated_at') else '—'
        lines.append("")
        lines.append("🗂 <b>CRM</b>")
        lines.append(f"   Статус: {status_e} {crm_m.get('status', '—')}  |  Настроение: {crm_m.get('mood') or '—'}")
        if crm_m.get('current_rate'):
            lines.append(f"   Ставка: {crm_m['current_rate']}%  |  Мин: {crm_m.get('min_rate') or '—'}%")
        if crm_m.get('contact_person'):
            lines.append(f"   Контакт: {escape(crm_m['contact_person'])}")
        if tags:
            lines.append(f"   Теги: {', '.join(escape(t) for t in tags)}")
        if crm_m.get('notes'):
            lines.append(f"   Заметки: {escape(str(crm_m['notes'])[:150])}")
        lines.append(f"   Обновлён: {upd}")
    else:
        lines.append("\n🗂 <b>CRM:</b> не найден — добавьте через «Добавить мерчанта»")

    return "\n".join(lines)


def format_merchant_card(m: dict, tags: list = None) -> str:
    status_e = STATUS_EMOJI.get(m.get('status', ''), '⚪')
    score = calculate_merchant_score(m)
    sc_e = score_emoji(score)
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏪  <b>{escape(m['name'])}</b>   {sc_e} <b>{score}/100</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Статус: {status_e} {m.get('status', '—')}  |  Интеграция: {m.get('integration_status') or '—'}",
        f"Настроение: {m.get('mood') or '—'}  |  Ставка: {m.get('current_rate') or '—'}%",
        f"Конверсия: {m.get('conversion') or '—'}%  |  Методы: {m.get('payment_methods') or '—'}",
    ]
    if m.get('contact_person'):
        lines.append(f"Контакт: {escape(m['contact_person'])}")
    if tags:
        lines.append(f"Теги: {', '.join(escape(t) for t in tags)}")
    if m.get('notes'):
        lines.append(f"Заметки: {escape(m['notes'][:200])}")
    upd = time_ago(m.get('updated_at', '')) if m.get('updated_at') else '—'
    lines.append(f"Обновлён: {upd}")
    return "\n".join(lines)


async def show_merchant_card(update: Update, context, merchant_id: int):
    m = database.get_merchant_by_id(merchant_id)
    if not m:
        await update.effective_message.reply_text("Мерчант не найден.")
        return
    tags = database.get_merchant_tags(merchant_id)
    text = format_merchant_card(m, tags)
    kb = kb_merchant_card(merchant_id)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# ============ CRM: ДОБАВИТЬ МЕРЧАНТА (ConversationHandler) ============

async def add_merchant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update):
        return ConversationHandler.END
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "➕  <b>ДОБАВИТЬ МЕРЧАНТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Введите название мерчанта:\n\n"
        "<i>Отправьте /cancel для отмены</i>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("◀️ Вернуться в меню")]], resize_keyboard=True)
    )
    return MERCH_NAME


async def add_merchant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if name == "◀️ Вернуться в меню":
        await update.message.reply_text("Отменено.", reply_markup=kb_main(is_admin(update)))
        return ConversationHandler.END
    context.user_data['new_merchant'] = {'name': name}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 new", callback_data="mnew_status:new"),
         InlineKeyboardButton("🤝 negotiation", callback_data="mnew_status:negotiation")],
        [InlineKeyboardButton("🔧 integration", callback_data="mnew_status:integration"),
         InlineKeyboardButton("🔵 testing", callback_data="mnew_status:testing")],
        [InlineKeyboardButton("🟢 active", callback_data="mnew_status:active"),
         InlineKeyboardButton("⏸️ paused", callback_data="mnew_status:paused")],
        [InlineKeyboardButton("⏩ Пропустить", callback_data="mnew_status:new")],
    ])
    await update.message.reply_text(
        f"Мерчант: <b>{escape(name)}</b>\n\nВыберите статус:",
        parse_mode="HTML", reply_markup=kb
    )
    return MERCH_STATUS


async def add_merchant_status_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":")[1]
    context.user_data['new_merchant']['status'] = status
    await query.edit_message_text(
        f"Статус: <b>{status}</b>\n\nВведите текущую ставку (%) или отправьте /skip:",
        parse_mode="HTML"
    )
    return MERCH_RATE


async def add_merchant_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt not in ('/skip', '◀️ Вернуться в меню'):
        try:
            context.user_data['new_merchant']['current_rate'] = float(txt.replace(',', '.'))
        except ValueError:
            await update.message.reply_text("Введите число (например: 3.5) или /skip:")
            return MERCH_RATE
    await update.message.reply_text("Введите контактное лицо (@username или имя) или /skip:")
    return MERCH_CONTACT


async def add_merchant_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != '/skip':
        context.user_data['new_merchant']['contact_person'] = txt
    await update.message.reply_text("Добавьте заметку о мерчанте или /skip:")
    return MERCH_NOTES


async def add_merchant_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt != '/skip':
        context.user_data['new_merchant']['notes'] = txt
    data = context.user_data.get('new_merchant', {})
    mid = database.create_or_update_merchant(
        name=data['name'],
        status=data.get('status', 'new'),
        current_rate=data.get('current_rate'),
        contact_person=data.get('contact_person'),
        notes=data.get('notes'),
        name_source='manual',
        reason='Добавлен вручную через бот',
        decided_by=f"user:{update.effective_user.id}"
    )
    await update.message.reply_text(
        f"✅ <b>Мерчант добавлен!</b>\n\n{escape(data['name'])} (ID: {mid})",
        parse_mode="HTML",
        reply_markup=kb_main(is_admin(update))
    )
    context.user_data.pop('new_merchant', None)
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=kb_main(is_admin(update)))
    context.user_data.clear()
    return ConversationHandler.END


# ============ CRM: РЕДАКТИРОВАТЬ МЕРЧАНТА ============

async def edit_merchant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update):
        return ConversationHandler.END
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✏️  <b>РЕДАКТИРОВАТЬ МЕРЧАНТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Введите название мерчанта для поиска:\n\n"
        "<i>Отправьте /cancel для отмены</i>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("◀️ Вернуться в меню")]], resize_keyboard=True)
    )
    return EDIT_FIND


async def edit_merchant_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "◀️ Вернуться в меню":
        await update.message.reply_text("Отменено.", reply_markup=kb_main(is_admin(update)))
        return ConversationHandler.END
    results = database.search_merchants(txt)
    if not results:
        await update.message.reply_text("Мерчант не найден. Попробуйте другое название:")
        return EDIT_FIND
    m = results[0]
    context.user_data['edit_merchant_id'] = m['id']
    tags = database.get_merchant_tags(m['id'])
    text = format_merchant_card(m, tags)
    kb = kb_merchant_card(m['id'])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    await update.message.reply_text("Нажмите кнопку для редактирования поля.", reply_markup=kb_main(is_admin(update)))
    return ConversationHandler.END


# ============ CRM: ИНЦИДЕНТЫ ============

def format_incidents_list(incidents: list, page: int = 0) -> str:
    total = len(incidents)
    if not total:
        return "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📋  <b>ИНЦИДЕНТЫ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n✅ Нет открытых инцидентов"
    total_pages = (total + INC_PAGE_SIZE - 1) // INC_PAGE_SIZE
    page_items = incidents[page * INC_PAGE_SIZE:(page + 1) * INC_PAGE_SIZE]
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📋  <b>ОТКРЫТЫЕ ИНЦИДЕНТЫ ({total})</b>  стр. {page + 1}/{total_pages}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for inc in page_items:
        pe = PRIORITY_EMOJI.get(inc.get('priority', 'P2'), '⚪')
        assigned = inc.get('assigned_user_name') or 'Не назначен'
        due = ''
        if inc.get('due_at'):
            try:
                due_dt = datetime.fromisoformat(inc['due_at'])
                due = f" | Дедлайн: {due_dt.strftime('%d.%m %H:%M')}"
            except Exception:
                pass
        lines.append(f"\n{pe} <b>{inc.get('priority')}</b> · {escape(inc.get('merchant_name', ''))}")
        lines.append(f"   {escape(inc.get('incident_type', ''))}{due}")
        lines.append(f"   Назначен: {escape(assigned)}")
    return "\n".join(lines)


async def show_incidents_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, edit: bool = False):
    incidents = database.get_open_incidents()
    text = format_incidents_list(incidents, page)
    kb = kb_incidents_list(incidents, page)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# ============ CRM: СОЗДАТЬ ИНЦИДЕНТ (ConversationHandler) ============

async def inc_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update):
        return ConversationHandler.END
    await update.effective_message.reply_text(
        "🚨 <b>Создать инцидент</b>\n\nВведите название мерчанта:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("◀️ Вернуться в меню")]], resize_keyboard=True)
    )
    return INC_MERCHANT


async def inc_merchant_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "◀️ Вернуться в меню":
        await update.message.reply_text("Отменено.", reply_markup=kb_main(is_admin(update)))
        return ConversationHandler.END
    context.user_data['new_incident'] = {'merchant_name': txt}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📉 Конверсия", callback_data="inc_type:conversion_drop"),
         InlineKeyboardButton("💰 Ставки", callback_data="inc_type:rate_issue")],
        [InlineKeyboardButton("🔧 Интеграция", callback_data="inc_type:integration_stuck"),
         InlineKeyboardButton("💬 Связь", callback_data="inc_type:communication")],
        [InlineKeyboardButton("⚙️ Техническое", callback_data="inc_type:technical"),
         InlineKeyboardButton("📊 Статус", callback_data="inc_type:status_degraded")],
    ])
    await update.message.reply_text(
        f"Мерчант: <b>{escape(txt)}</b>\n\nВыберите тип инцидента:",
        parse_mode="HTML", reply_markup=kb
    )
    return INC_TYPE


async def inc_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    inc_type = query.data.split(":")[1]
    context.user_data['new_incident']['incident_type'] = inc_type
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 P0 Критический", callback_data="inc_prio:P0"),
         InlineKeyboardButton("🟠 P1 Высокий", callback_data="inc_prio:P1")],
        [InlineKeyboardButton("🟡 P2 Средний", callback_data="inc_prio:P2"),
         InlineKeyboardButton("⚪ P3 Низкий", callback_data="inc_prio:P3")],
    ])
    await query.edit_message_text("Выберите приоритет:", reply_markup=kb)
    return INC_PRIORITY


async def inc_priority_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    priority = query.data.split(":")[1]
    context.user_data['new_incident']['priority'] = priority
    await query.edit_message_text(
        f"Приоритет: <b>{priority}</b>\n\nОпишите проблему:",
        parse_mode="HTML"
    )
    return INC_DESC


async def inc_desc_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_incident']['description'] = update.message.text.strip()
    now_msk = datetime.now(MSK)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Сегодня 18:00", callback_data="inc_due:today18"),
         InlineKeyboardButton("📅 Завтра 12:00", callback_data="inc_due:tomorrow12")],
        [InlineKeyboardButton("⏩ Без дедлайна", callback_data="inc_due:none")],
    ])
    await update.message.reply_text("Установите дедлайн:", reply_markup=kb)
    return INC_DUE


async def inc_due_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]
    due_at = None
    now_msk = datetime.now(MSK)
    if choice == "today18":
        due_at = now_msk.replace(hour=18, minute=0, second=0, microsecond=0)
    elif choice == "tomorrow12":
        due_at = (now_msk + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)

    data = context.user_data.get('new_incident', {})
    uid = query.from_user.id
    inc_id = database.create_incident_manual(
        merchant_name=data['merchant_name'],
        incident_type=data.get('incident_type', 'technical'),
        priority=data.get('priority', 'P2'),
        description=data.get('description', ''),
        user_id=uid,
        due_at=due_at
    )
    due_str = due_at.strftime('%d.%m %H:%M') if due_at else 'Без дедлайна'
    await query.edit_message_text(
        f"✅ <b>Инцидент #{inc_id} создан</b>\n\n"
        f"Мерчант: {escape(data['merchant_name'])}\n"
        f"Тип: {data.get('incident_type')}\n"
        f"Приоритет: {data.get('priority')}\n"
        f"Дедлайн: {due_str}",
        parse_mode="HTML"
    )
    context.user_data.pop('new_incident', None)
    return ConversationHandler.END


# ============ CRM: ОБРАБОТКА INLINE КНОПОК ИНЦИДЕНТОВ ============

async def handle_inc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обрабатывает inc_* callback_data"""
    query = update.callback_query

    if data.startswith("inc_page:"):
        await query.answer()
        page = int(data.split(":")[1])
        await show_incidents_list(update, context, page=page, edit=True)
        return

    if data == "inc_page_noop":
        await query.answer()
        return

    if data == "inc_create_start":
        await query.answer()
        await query.message.reply_text(
            "🚨 <b>Создать инцидент</b>\n\nВведите название мерчанта:",
            parse_mode="HTML"
        )
        context.user_data['conv_state'] = 'inc_merchant'
        return

    if data.startswith("inc_take:"):
        inc_id = int(data.split(":")[1])
        user = update.effective_user
        ok = database.assign_incident(inc_id, user.id, user.first_name or str(user.id))
        await query.answer("Инцидент взят!" if ok else "Уже назначен")
        # Обновляем список
        incidents = database.get_open_incidents()
        text = format_incidents_list(incidents)
        kb = kb_incidents_list(incidents)
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
        return

    if data.startswith("inc_close:"):
        inc_id = int(data.split(":")[1])
        context.user_data['closing_incident_id'] = inc_id
        await query.answer()
        await query.message.reply_text(
            f"Закрываем инцидент #{inc_id}. Введите результат/заметку:"
        )
        context.user_data['conv_state'] = 'inc_close_notes'
        return

    if data.startswith("inc_comments:"):
        inc_id = int(data.split(":")[1])
        await query.answer()
        comments = database.get_incident_comments(inc_id)
        inc = database.get_incident_by_id(inc_id)
        lines = [f"💬 <b>Комментарии к инциденту #{inc_id}</b>",
                 f"Мерчант: {escape(inc.get('merchant_name', '') if inc else '')}",
                 ""]
        if comments:
            for c in comments:
                dt = c.get('created_at', '')[:16].replace('T', ' ')
                lines.append(f"<b>{escape(c.get('user_name') or str(c['user_id']))}</b> [{dt}]")
                lines.append(escape(c['text']))
                lines.append("")
        else:
            lines.append("Комментариев пока нет.")
        lines.append("\nВведите комментарий или нажмите /skip:")
        context.user_data['commenting_incident_id'] = inc_id
        context.user_data['conv_state'] = 'inc_comment'
        await query.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if data.startswith("inc_view:"):
        inc_id = int(data.split(":")[1])
        await query.answer()
        inc = database.get_incident_by_id(inc_id)
        if not inc:
            await query.message.reply_text("Инцидент не найден.")
            return
        pe = PRIORITY_EMOJI.get(inc.get('priority', 'P2'), '⚪')
        due = ''
        if inc.get('due_at'):
            try:
                due_dt = datetime.fromisoformat(inc['due_at'])
                due = f"\nДедлайн: {due_dt.strftime('%d.%m.%Y %H:%M')}"
            except Exception:
                pass
        comment_count = database.get_incident_comment_count(inc_id)
        text = (
            f"{pe} <b>Инцидент #{inc_id}</b>\n"
            f"Мерчант: {escape(inc.get('merchant_name', ''))}\n"
            f"Тип: {inc.get('incident_type', '')}\n"
            f"Приоритет: {inc.get('priority', '')}{due}\n"
            f"Назначен: {escape(inc.get('assigned_user_name') or 'Не назначен')}\n"
            f"Описание: {escape(inc.get('description') or '')}\n"
            f"Комментариев: {comment_count}\n"
            f"Создан: {str(inc.get('created_at', ''))[:16]}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✋ Взять", callback_data=f"inc_take:{inc_id}"),
             InlineKeyboardButton("✅ Закрыть", callback_data=f"inc_close:{inc_id}")],
            [InlineKeyboardButton(f"💬 Комментарии ({comment_count})", callback_data=f"inc_comments:{inc_id}")],
        ])
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return

    # Inline-flow: type/priority/due callbacks (used when starting from incident list inline button)
    if data.startswith("inc_type:") and context.user_data.get('conv_state') == 'inc_type':
        inc_type = data.split(":")[1]
        context.user_data['new_incident']['incident_type'] = inc_type
        context.user_data['conv_state'] = 'inc_priority'
        await query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 P0 Критический", callback_data="inc_prio:P0"),
             InlineKeyboardButton("🟠 P1 Высокий", callback_data="inc_prio:P1")],
            [InlineKeyboardButton("🟡 P2 Средний", callback_data="inc_prio:P2"),
             InlineKeyboardButton("⚪ P3 Низкий", callback_data="inc_prio:P3")],
        ])
        await query.edit_message_reply_markup(reply_markup=kb)
        return

    if data.startswith("inc_prio:") and context.user_data.get('conv_state') == 'inc_priority':
        priority = data.split(":")[1]
        context.user_data['new_incident']['priority'] = priority
        context.user_data['conv_state'] = 'inc_desc'
        await query.answer()
        await query.message.reply_text(
            f"Приоритет: <b>{priority}</b>\n\nОпишите проблему:",
            parse_mode="HTML"
        )
        return

    if data.startswith("inc_due:") and context.user_data.get('conv_state') == 'inc_due':
        choice = data.split(":")[1]
        due_at = None
        now_msk = datetime.now(MSK)
        if choice == "today18":
            due_at = now_msk.replace(hour=18, minute=0, second=0, microsecond=0)
        elif choice == "tomorrow12":
            due_at = (now_msk + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        data_inc = context.user_data.get('new_incident', {})
        uid = update.effective_user.id
        inc_id = database.create_incident_manual(
            merchant_name=data_inc.get('merchant_name', ''),
            incident_type=data_inc.get('incident_type', 'technical'),
            priority=data_inc.get('priority', 'P2'),
            description=data_inc.get('description', ''),
            user_id=uid,
            due_at=due_at
        )
        due_str = due_at.strftime('%d.%m %H:%M') if due_at else 'Без дедлайна'
        await query.answer("Инцидент создан!")
        await query.edit_message_text(
            f"✅ <b>Инцидент #{inc_id} создан</b>\n\n"
            f"Мерчант: {escape(data_inc.get('merchant_name', ''))}\n"
            f"Тип: {data_inc.get('incident_type')}\n"
            f"Приоритет: {data_inc.get('priority')}\n"
            f"Дедлайн: {due_str}",
            parse_mode="HTML"
        )
        context.user_data.pop('new_incident', None)
        context.user_data.pop('conv_state', None)
        return

    if data.startswith("inc_new_from_card:"):
        merchant_id = int(data.split(":")[1])
        m = database.get_merchant_by_id(merchant_id)
        await query.answer()
        if m:
            context.user_data['new_incident'] = {'merchant_name': m['name']}
            context.user_data['conv_state'] = 'inc_type'
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📉 Конверсия", callback_data="inc_type:conversion_drop"),
                 InlineKeyboardButton("💰 Ставки", callback_data="inc_type:rate_issue")],
                [InlineKeyboardButton("🔧 Интеграция", callback_data="inc_type:integration_stuck"),
                 InlineKeyboardButton("⚙️ Техническое", callback_data="inc_type:technical")],
            ])
            await query.message.reply_text(
                f"🚨 Создать инцидент для <b>{escape(m['name'])}</b>\n\nВыберите тип:",
                parse_mode="HTML", reply_markup=kb
            )
        return


# ============ CRM: ОБРАБОТКА INLINE КНОПОК МЕРЧАНТА ============

async def handle_medit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обрабатывает medit_* и mhist_* callback_data"""
    query = update.callback_query

    if data.startswith("medit_status:"):
        merchant_id = int(data.split(":")[1])
        await query.answer()
        context.user_data['edit_merchant_id'] = merchant_id
        context.user_data['edit_field'] = 'status'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 new", callback_data="mset_status:new"),
             InlineKeyboardButton("🤝 negotiation", callback_data="mset_status:negotiation")],
            [InlineKeyboardButton("🔧 integration", callback_data="mset_status:integration"),
             InlineKeyboardButton("🔵 testing", callback_data="mset_status:testing")],
            [InlineKeyboardButton("🟢 active", callback_data="mset_status:active"),
             InlineKeyboardButton("⏸️ paused", callback_data="mset_status:paused")],
            [InlineKeyboardButton("🟡 problem", callback_data="mset_status:problem"),
             InlineKeyboardButton("🔴 disconnected", callback_data="mset_status:disconnected")],
        ])
        await query.edit_message_reply_markup(reply_markup=kb)
        return

    if data.startswith("mset_status:"):
        merchant_id = context.user_data.get('edit_merchant_id')
        new_status = data.split(":")[1]
        if merchant_id:
            database.update_merchant_field(merchant_id, 'status', new_status, update.effective_user.id)
            await query.answer(f"Статус обновлён: {new_status}")
            await show_merchant_card(update, context, merchant_id)
        return

    if data.startswith("medit_notes:"):
        merchant_id = int(data.split(":")[1])
        await query.answer()
        context.user_data['edit_merchant_id'] = merchant_id
        context.user_data['edit_field'] = 'notes'
        context.user_data['conv_state'] = 'medit_value'
        await query.message.reply_text("Введите новую заметку:")
        return

    if data.startswith("medit_contact:"):
        merchant_id = int(data.split(":")[1])
        await query.answer()
        context.user_data['edit_merchant_id'] = merchant_id
        context.user_data['edit_field'] = 'contact_person'
        context.user_data['conv_state'] = 'medit_value'
        await query.message.reply_text("Введите контактное лицо (@username или имя):")
        return

    if data.startswith("medit_rate:"):
        merchant_id = int(data.split(":")[1])
        await query.answer()
        context.user_data['edit_merchant_id'] = merchant_id
        context.user_data['edit_field'] = 'current_rate'
        context.user_data['conv_state'] = 'medit_value'
        await query.message.reply_text("Введите новую ставку (%):")
        return

    if data.startswith("medit_tag:"):
        merchant_id = int(data.split(":")[1])
        await query.answer()
        context.user_data['edit_merchant_id'] = merchant_id
        context.user_data['conv_state'] = 'medit_tag'
        await query.message.reply_text("Введите тег (например: VIP, приоритет, быстрый):")
        return

    if data.startswith("mhist:"):
        merchant_id = int(data.split(":")[1])
        await query.answer()
        m = database.get_merchant_by_id(merchant_id)
        merchant_name = m['name'] if m else str(merchant_id)
        conv_hist = database.get_conversion_history(merchant_name, days=14)
        lines = [f"📊 <b>История конверсии: {escape(merchant_name)}</b>", ""]
        if conv_hist:
            for h in conv_hist[:14]:
                date = h.get('date', '')
                conv = h.get('conversion_pct', 0) or 0
                total = h.get('total_orders', 0) or 0
                bar = '▓' * min(int(conv / 5), 20) + '░' * max(0, 20 - int(conv / 5))
                lines.append(f"<code>{date}</code> {conv:.1f}% {bar[:10]} ({total} зак.)")
        else:
            lines.append("Данных о конверсии нет.")
            lines.append("<i>Данные накапливаются автоматически каждый день.</i>")
        # Also show status changes
        history = database.get_merchant_history(merchant_id, limit=5)
        if history:
            lines.append("")
            lines.append("<b>Последние изменения:</b>")
            for h in history:
                dt = str(h.get('created_at', ''))[:10]
                lines.append(f"[{dt}] {h.get('field_name')}: {escape(str(h.get('old_value') or '—'))} → {escape(str(h.get('new_value') or '—'))}")
        await query.message.reply_text("\n".join(lines), parse_mode="HTML")
        return


# ============ CRM: ОБРАБОТКА ТЕКСТОВОГО ВВОДА В conv_state ============

async def handle_crm_text_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Обрабатывает текстовые ответы для CRM-диалогов через context.user_data['conv_state'].
    Возвращает True если сообщение обработано.
    """
    state = context.user_data.get('conv_state')
    if not state:
        return False

    txt = update.message.text.strip()

    if state == 'medit_value':
        merchant_id = context.user_data.get('edit_merchant_id')
        field = context.user_data.get('edit_field')
        if merchant_id and field:
            val = txt
            if field == 'current_rate':
                try:
                    val = float(txt.replace(',', '.'))
                except ValueError:
                    await update.message.reply_text("Введите число:")
                    return True
            database.update_merchant_field(merchant_id, field, val, update.effective_user.id)
            await update.message.reply_text(f"✅ {field} обновлено.", reply_markup=kb_main(is_admin(update)))
        context.user_data.pop('conv_state', None)
        return True

    if state == 'medit_tag':
        merchant_id = context.user_data.get('edit_merchant_id')
        if merchant_id and txt:
            database.add_merchant_tag(merchant_id, txt)
            await update.message.reply_text(f"✅ Тег «{escape(txt)}» добавлен.", parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        context.user_data.pop('conv_state', None)
        return True

    if state == 'inc_merchant':
        # Inline-triggered incident creation: merchant name step
        merchant_name = txt
        context.user_data['new_incident'] = {'merchant_name': merchant_name}
        context.user_data['conv_state'] = 'inc_type'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📉 Конверсия", callback_data="inc_type:conversion_drop"),
             InlineKeyboardButton("💰 Ставки", callback_data="inc_type:rate_issue")],
            [InlineKeyboardButton("🔧 Интеграция", callback_data="inc_type:integration_stuck"),
             InlineKeyboardButton("💬 Связь", callback_data="inc_type:communication")],
            [InlineKeyboardButton("⚙️ Техническое", callback_data="inc_type:technical"),
             InlineKeyboardButton("📊 Статус", callback_data="inc_type:status_degraded")],
        ])
        await update.message.reply_text(
            f"Мерчант: <b>{escape(merchant_name)}</b>\n\nВыберите тип инцидента:",
            parse_mode="HTML", reply_markup=kb
        )
        return True

    if state == 'inc_desc':
        # Inline-triggered incident creation: description step
        context.user_data['new_incident']['description'] = txt
        context.user_data['conv_state'] = 'inc_due'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Сегодня 18:00", callback_data="inc_due:today18"),
             InlineKeyboardButton("📅 Завтра 12:00", callback_data="inc_due:tomorrow12")],
            [InlineKeyboardButton("⏩ Без дедлайна", callback_data="inc_due:none")],
        ])
        await update.message.reply_text("Установите дедлайн:", reply_markup=kb)
        return True

    if state == 'inc_close_notes':
        inc_id = context.user_data.get('closing_incident_id')
        if inc_id:
            notes = txt if txt != '/skip' else None
            database.resolve_incident(inc_id, update.effective_user.id, notes)
            await update.message.reply_text(f"✅ Инцидент #{inc_id} закрыт.", reply_markup=kb_main(is_admin(update)))
        context.user_data.pop('conv_state', None)
        context.user_data.pop('closing_incident_id', None)
        return True

    if state == 'inc_comment':
        inc_id = context.user_data.get('commenting_incident_id')
        if inc_id and txt != '/skip':
            user = update.effective_user
            database.add_incident_comment(inc_id, user.id, user.first_name or str(user.id), txt)
            await update.message.reply_text(f"✅ Комментарий к инциденту #{inc_id} добавлен.", reply_markup=kb_main(is_admin(update)))
        context.user_data.pop('conv_state', None)
        context.user_data.pop('commenting_incident_id', None)
        return True

    return False


# ============ INLINE-РЕЖИМ (@bot query) ============

async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка inline-запросов: @bot <название мерчанта>"""
    query_text = update.inline_query.query.strip()
    user_id = update.effective_user.id

    if not storage.is_user_authorized(user_id):
        await update.inline_query.answer([], cache_time=0)
        return

    try:
        if len(query_text) < 2:
            # Показываем проблемных и активных мерчантов
            all_m = database.get_all_merchants()
            merchants = [m for m in all_m if m.get('status') in ('problem', 'active')][:5]
        else:
            merchants = database.search_merchants(query_text)[:10]

        results = []
        for m in merchants:
            score = calculate_merchant_score(m)
            tags = database.get_merchant_tags(m['id'])
            text = format_merchant_card(m, tags)
            status_e = STATUS_EMOJI.get(m.get('status', ''), '⚪')
            results.append(InlineQueryResultArticle(
                id=str(m['id']),
                title=f"{m['name']}  ⭐{score}",
                description=f"{status_e} {m.get('status', '—')} | конв: {m.get('conversion') or '?'}%",
                input_message_content=InputTextMessageContent(text, parse_mode="HTML"),
            ))

        await update.inline_query.answer(results, cache_time=60)
    except Exception as e:
        logger.error(f"Ошибка inline-запроса: {e}")
        await update.inline_query.answer([], cache_time=0)


# ============ АЛЕРТ КНОПКИ ============

async def handle_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обработчик кнопок из алертов низкой конверсии"""
    query = update.callback_query

    if data.startswith("alert_inc:"):
        merchant_name = data[len("alert_inc:"):]
        await query.answer()
        try:
            inc_id = database.create_incident_manual(
                merchant_name=merchant_name,
                incident_type='conversion_drop',
                priority='P1',
                description='Автоматически создан из алерта низкой конверсии',
                user_id=update.effective_user.id,
            )
            await query.message.reply_text(
                f"✅ <b>Инцидент #{inc_id} создан</b>\n"
                f"Мерчант: {escape(merchant_name)}\n"
                f"Приоритет: P1 · conversion_drop",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка создания инцидента: {e}")
        return

    if data.startswith("alert_status:"):
        merchant_name = data[len("alert_status:"):]
        await query.answer()
        context.user_data['alert_merchant_name'] = merchant_name
        results = database.search_merchants(merchant_name)
        if not results:
            await query.message.reply_text(f"Мерчант «{escape(merchant_name)}» не найден в CRM.")
            return
        m = results[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 active", callback_data=f"mset_status:{m['id']}:active"),
             InlineKeyboardButton("🟡 problem", callback_data=f"mset_status:{m['id']}:problem")],
            [InlineKeyboardButton("⏸️ paused", callback_data=f"mset_status:{m['id']}:paused"),
             InlineKeyboardButton("🔴 disconnected", callback_data=f"mset_status:{m['id']}:disconnected")],
            [InlineKeyboardButton("🔧 integration", callback_data=f"mset_status:{m['id']}:integration"),
             InlineKeyboardButton("🔵 testing", callback_data=f"mset_status:{m['id']}:testing")],
        ])
        await query.message.reply_text(
            f"Выберите новый статус для <b>{escape(merchant_name)}</b>:",
            parse_mode="HTML", reply_markup=kb
        )
        return

    if data.startswith("alert_card:"):
        merchant_name = data[len("alert_card:"):]
        await query.answer()
        results = database.search_merchants(merchant_name)
        if not results:
            await query.message.reply_text(f"Мерчант «{escape(merchant_name)}» не найден в CRM.")
            return
        m = results[0]
        tags = database.get_merchant_tags(m['id'])
        text = format_merchant_card(m, tags)
        kb = kb_merchant_card(m['id'])
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return
