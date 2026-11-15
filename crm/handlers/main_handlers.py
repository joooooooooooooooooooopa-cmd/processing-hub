import asyncio
import io
import json
import html
import logging
import zipfile
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

from handlers.utils import (
    escape, is_authenticated, is_admin, MSK,
    BTN_TODAY, BTN_CANCELED, BTN_ALERTS, BTN_CONVERSION, BTN_LOW_CONVERSION,
    BTN_BAD_CLIENTS, BTN_SEARCH, BTN_EXPORT, BTN_RATES, BTN_ADD_MERCHANT,
    BTN_EDIT_MERCHANT, BTN_INCIDENTS, BTN_NEW_INCIDENT, BTN_UPLOAD_EXPORT,
    BTN_ACTIVE_SUMMARY, BTN_PAYOUT, BTN_METHOD_OVERVIEW, BTN_ADMIN, calculate_merchant_score, format_money,
)
from handlers.keyboards import (
    kb_main, kb_cancel, kb_export, kb_admin, kb_refresh, kb_merchant_card,
)
from handlers.formatters import (
    format_today, format_canceled, format_alerts, format_bad_clients,
    format_conversion_detailed, format_rates, format_payout,
    export_merchants_csv, export_methods_csv, export_hourly_csv,
    export_conv_history_csv, export_incidents_csv,
)
from handlers.jobs import (
    CONVERSION_THRESHOLD, MIN_ORDERS_WITH_REQ_FOR_ALERT, MIN_METHOD_REQ_FOR_ALERT,
    EXCLUDED_MERCHANTS,
    get_greeting_by_time, get_merchants_status_map, get_template_variant,
)
from handlers.crm import (
    handle_crm_text_state, add_merchant_start, edit_merchant_start,
    inc_create_start, show_incidents_list, format_unified_card,
    handle_alert_callback, handle_inc_callback, handle_medit_callback,
)

import metabase as mb
import database
import keys
import storage
import visualization
from config import BOT_TOKEN, ADMIN_IDS, WEBAPP_URL

logger = logging.getLogger(__name__)


def _split_message(text: str, max_len: int = 4096):
    """Split message into chunks for Telegram's 4096 char limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_pos = text.rfind('\n', 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip('\n')
    return chunks


async def _generate_active_merchants_summary() -> str:
    """Generate summary of active merchants using AI."""
    merchants = mb.get_conversion_today()
    active = [m for m in merchants if (m.get("С реквизитами") or 0) > 0 and "ИТОГО" not in (m.get("Мерчант") or "")]
    if not active:
        return "Нет активных мерчантов с реквизитами."
    lines = ["📝 <b>СВОДКА ПО АКТИВНЫМ МЕРЧАНТАМ</b>", ""]
    for m in sorted(active, key=lambda x: x.get("Конверсия в оплату %") or 0):
        name = escape((m.get("Мерчант") or "?")[:25])
        conv = m.get("Конверсия в оплату %") or 0
        with_req = m.get("С реквизитами") or 0
        success = m.get("Успешных") or 0
        emoji = "🟢" if conv >= 40 else "🟡" if conv >= 25 else "🟠" if conv >= 15 else "🔴"
        lines.append(f"{emoji} <b>{name}</b>: {conv:.1f}% ({success}/{with_req})")
    return "\n".join(lines)


def _extract_text_messages(messages: list) -> list:
    """Extract text messages from Telegram Desktop JSON export format."""
    text_messages = []
    for msg in messages:
        if msg.get("type") != "message":
            continue
        raw_text = msg.get("text", "")
        if isinstance(raw_text, list):
            text = "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in raw_text
            )
        else:
            text = str(raw_text)

        if len(text) < 15:
            continue

        text_messages.append({
            "text": text,
            "sender_name": msg.get("from", "Unknown"),
            "sender_id": msg.get("from_id", ""),
            "telegram_msg_id": msg.get("id", 0),
            "date": msg.get("date", ""),
        })
    return text_messages


def _parse_sender_id(sid) -> int:
    """Parse sender_id from Telegram export (handles 'user123' strings and ints)."""
    if isinstance(sid, int):
        return sid
    if isinstance(sid, str):
        cleaned = sid.replace("user", "").replace("channel", "")
        try:
            return int(cleaned)
        except ValueError:
            return 0
    return 0


async def _process_single_chat(data: dict, status_msg, chat_name_fallback: str = "") -> str:
    """Process a single chat JSON export. Returns report text."""
    from scheduler import process_message
    import analyzer

    chat_name = data.get("name", chat_name_fallback)
    chat_id = data.get("id", 0)
    messages = data.get("messages", [])

    if not messages:
        return "⚠️ В файле нет сообщений."

    text_messages = _extract_text_messages(messages)
    if not text_messages:
        return "⚠️ В файле нет текстовых сообщений для анализа."

    await status_msg.edit_text(
        f"🔍 <b>Анализирую {len(text_messages)} сообщений из «{escape(chat_name)}»...</b>\n"
        f"Это может занять пару минут.",
        parse_mode="HTML"
    )

    updated = 0
    processed = 0
    merchants_found = set()

    for msg in text_messages:
        try:
            sender_id = _parse_sender_id(msg.get("sender_id", ""))
            result = await process_message(
                text=msg["text"],
                chat_name=chat_name,
                group_id=int(chat_id) if chat_id else 0,
                telegram_msg_id=msg["telegram_msg_id"],
                sender_id=sender_id,
                sender_name=msg["sender_name"],
            )
            processed += 1
            if result:
                updated += 1
                quick = analyzer.quick_analyze(msg["text"])
                if quick.get("merchant_name"):
                    merchants_found.add(quick["merchant_name"])
        except Exception as e:
            logger.error(f"Error processing message from export: {e}")
            continue

    merchants_list = ", ".join(merchants_found) if merchants_found else "—"
    report = (
        f"✅ <b>Экспорт обработан!</b>\n\n"
        f"📁 Чат: <b>{escape(chat_name)}</b>\n"
        f"💬 Сообщений: {len(text_messages)}\n"
        f"🔍 Обработано: {processed}\n"
        f"📝 Обновлено мерчантов: {updated}\n"
    )
    if merchants_found:
        report += f"\n🏢 Найдены мерчанты: {escape(merchants_list)}"
    report += "\n\n<i>Данные обновлены в CRM. Проверьте карточки мерчантов в Mini App.</i>"
    return report


async def _process_full_export(data: dict, status_msg) -> str:
    """Process full Telegram Desktop export with chats.list. Returns report text."""
    from scheduler import process_message, is_business_chat

    chats_data = data.get("chats", {})
    all_chats = chats_data.get("list", [])

    if not all_chats:
        return "⚠️ В выгрузке нет чатов."

    # Filter business chats
    business_chats = []
    for chat in all_chats:
        chat_name = chat.get("name", "")
        if is_business_chat(chat_name):
            msgs = chat.get("messages", [])
            if msgs:
                business_chats.append(chat)

    if not business_chats:
        return (
            f"⚠️ <b>Бизнес-чаты не найдены</b>\n\n"
            f"Всего чатов в выгрузке: {len(all_chats)}\n"
            f"Ни один не содержит признаков бизнес-чата (processinghub + business/integration).\n\n"
            f"<i>Проверьте, что экспортировали нужные чаты.</i>"
        )

    await status_msg.edit_text(
        f"📂 <b>Найдено {len(business_chats)} бизнес-чатов из {len(all_chats)}</b>\n"
        f"Начинаю обработку...",
        parse_mode="HTML"
    )

    total_updated = 0
    total_processed = 0
    total_messages = 0
    chat_results = []

    for i, chat in enumerate(business_chats, 1):
        chat_name = chat.get("name", f"Chat #{i}")
        chat_id = chat.get("id", 0)
        messages = chat.get("messages", [])
        text_messages = _extract_text_messages(messages)
        total_messages += len(text_messages)

        # Progress update (once per chat)
        try:
            await status_msg.edit_text(
                f"🔄 <b>Обработка [{i}/{len(business_chats)}]:</b>\n"
                f"«{escape(chat_name[:50])}» — {len(text_messages)} сообщ.",
                parse_mode="HTML"
            )
        except Exception:
            pass  # Rate limit — skip progress update

        chat_updated = 0
        chat_processed = 0

        for msg in text_messages:
            try:
                sender_id = _parse_sender_id(msg.get("sender_id", ""))
                result = await process_message(
                    text=msg["text"],
                    chat_name=chat_name,
                    group_id=int(chat_id) if chat_id else 0,
                    telegram_msg_id=msg["telegram_msg_id"],
                    sender_id=sender_id,
                    sender_name=msg["sender_name"],
                )
                chat_processed += 1
                if result:
                    chat_updated += 1
            except Exception as e:
                logger.error(f"Error processing msg in {chat_name}: {e}")
                continue

        total_updated += chat_updated
        total_processed += chat_processed

        if chat_updated > 0:
            chat_results.append(f"  • {escape(chat_name[:40])} — +{chat_updated} обновл.")

    # Final report
    report = (
        f"✅ <b>Полная выгрузка обработана!</b>\n\n"
        f"📂 Бизнес-чатов: <b>{len(business_chats)}</b> из {len(all_chats)}\n"
        f"💬 Сообщений: {total_messages}\n"
        f"🔍 Обработано: {total_processed}\n"
        f"📝 Обновлений мерчантов: {total_updated}\n"
    )

    if chat_results:
        report += f"\n<b>Чаты с обновлениями:</b>\n"
        report += "\n".join(chat_results[:30])  # Limit to 30 entries
        if len(chat_results) > 30:
            report += f"\n  ... и ещё {len(chat_results) - 30}"

    report += "\n\n<i>Данные обновлены в CRM. Проверьте карточки мерчантов в Mini App.</i>"
    return report


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    uid = update.effective_user.id if update.effective_user else None

    if not is_authenticated(update):
        context.user_data["mode"] = "auth"
        await update.message.reply_text(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔐  <b>PROCESSING HUB ANALYTICS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Для доступа введите ключ:",
            parse_mode="HTML"
        )
        return

    context.user_data["mode"] = None

    try:
        data = mb.get_main_dashboard()
        text = format_today(data)
    except Exception as e:
        text = f"<b>ProcessingHub Analytics</b>\n\nОшибка загрузки: {str(e)[:50]}"

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_main(is_admin(update)))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений"""
    txt = update.message.text.strip()
    mode = context.user_data.get("mode")
    uid = update.effective_user.id if update.effective_user else None

    # === АУТЕНТИФИКАЦИЯ ===
    if mode == "auth" or not is_authenticated(update):
        if keys.validate_key(txt, uid):
            storage.log_audit(uid, "login_ok", "bot")
            context.user_data["mode"] = None
            # Delete message with key for security
            try: await update.message.delete()
            except: pass
            try:
                data = mb.get_main_dashboard()
                text = "✅ <b>Доступ разрешён!</b>\n\n" + format_today(data)
            except:
                text = "✅ <b>Доступ разрешён!</b>\n\nВыберите раздел в меню."
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        else:
            storage.log_audit(uid, "login_fail", "bot: wrong key")
            await update.message.reply_text(
                "❌ <b>Ключ недействителен</b>\n\n"
                "Ключ неверный или уже использован.\n"
                "Получите новый ключ у администратора.",
                parse_mode="HTML"
            )
        return

    # === ОТМЕНА / ВОЗВРАТ ===
    if txt == "◀️ Вернуться в меню":
        context.user_data["mode"] = None
        context.user_data.pop('conv_state', None)
        await update.message.reply_text("Главное меню:", reply_markup=kb_main(is_admin(update)))
        return

    # === CRM ТЕКСТОВЫЕ СОСТОЯНИЯ ===
    if await handle_crm_text_state(update, context):
        return

    # === РЕЖИМ ПОИСКА ===
    if mode == "search":
        results = mb.search_merchant(txt)

        if not results:
            await update.message.reply_text(
                f"❌ Мерчант «<b>{txt}</b>» не найден\n\n"
                "Попробуйте другое название или вернитесь в меню.",
                parse_mode="HTML",
                reply_markup=kb_cancel()
            )
            return

        if len(results) == 1:
            merchant_name = results[0].get("Мерчант") or ""
            mb_data = mb.get_merchant_detailed(merchant_name)
            crm_list = database.search_merchants(merchant_name)
            crm_m = crm_list[0] if crm_list else None
            tags = database.get_merchant_tags(crm_m['id']) if crm_m else []
            score = calculate_merchant_score(crm_m) if crm_m else None
            trend = database.get_conversion_trend(merchant_name) if crm_m else 'stable'
            text = format_unified_card(mb_data, crm_m, tags, score, trend)
            context.user_data["mode"] = None
            kb_extra = kb_merchant_card(crm_m['id']) if crm_m else None
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
            if kb_extra:
                await update.message.reply_text("Действия:", reply_markup=kb_extra)
        else:
            lines = [f"🔍 Найдено: <b>{len(results)}</b>", ""]
            for m in results[:10]:
                name = escape(m.get("Мерчант") or "?")
                conv = m.get("Конверсия %") or 0
                status = "🟢" if conv >= 1.5 else "🟡" if conv >= 0.8 else "🔴"
                lines.append(f"{status} {name} ({conv:.1f}%)")
            lines.append("")
            lines.append("Уточните название для точного поиска.")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=kb_cancel())
        return

    # === КНОПКИ МЕНЮ ===
    try:
        if txt == BTN_TODAY:
            data = mb.get_main_dashboard()
            text = format_today(data)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_refresh("refresh_today"))

        elif txt == BTN_CONVERSION:
            merchants = mb.get_conversion_today()
            text = format_conversion_detailed(merchants)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_refresh("refresh_conversion"))

        elif txt == BTN_PAYOUT:
            await update.message.reply_text("⏳ Загружаю данные PaycrowOUT...")
            data = mb.get_payout_stats()
            text = format_payout(data)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_refresh("refresh_payout"))

        elif txt == BTN_LOW_CONVERSION:
            merchants = mb.get_conversion_today()
            unpaid_orders = mb.get_unpaid_orders()
            try:
                hourly_by_merchant = mb.get_hourly_by_merchant()
            except Exception:
                hourly_by_merchant = {}
            try:
                conv_by_method = mb.get_conv_by_merchant_method()
            except Exception:
                conv_by_method = {}
            merchant_statuses = get_merchants_status_map()

            # Находим мерчантов с низкой конверсией (по общей)
            low_conv_merchants = []
            for m in merchants:
                name = m.get("Мерчант") or ""
                if "ИТОГО" in name:
                    continue
                if merchant_statuses.get(name) == 'disconnected':
                    continue
                if name in EXCLUDED_MERCHANTS:
                    continue

                total = m.get("Всего") or 0
                with_req = m.get("С реквизитами") or 0
                conv = m.get("Конверсия в оплату %") or 0

                if with_req >= MIN_ORDERS_WITH_REQ_FOR_ALERT and conv < CONVERSION_THRESHOLD:
                    low_conv_merchants.append({
                        "name": name,
                        "total": total,
                        "with_req": with_req,
                        "conv": conv,
                        "successful": m.get("Успешных") or 0,
                    })

            if not low_conv_merchants:
                await update.message.reply_text(
                    "✅ <b>Все мерчанты имеют нормальную конверсию</b>\n\n"
                    f"Порог: {CONVERSION_THRESHOLD}%\n"
                    f"Минимум заявок с реквизитами: {MIN_ORDERS_WITH_REQ_FOR_ALERT}",
                    parse_mode="HTML"
                )
            else:
                # Отправляем уведомление
                await update.message.reply_text(
                    f"🚨 <b>Найдено {len(low_conv_merchants)} мерчантов с низкой конверсией</b>\n\n"
                    f"Отправляю отдельное сообщение для каждого...",
                    parse_mode="HTML"
                )

                # Получаем приветствие
                greeting = get_greeting_by_time()

                # Для каждого мерчанта отправляем отдельное сообщение с картинкой
                for m in low_conv_merchants:
                    conv = m['conv']
                    name = m['name']
                    total = m['total']
                    with_req = m['with_req']
                    successful = m['successful']

                    # Выбираем шаблон
                    if conv < 10:
                        emoji = "🔴"
                        template_text = get_template_variant('critical')
                    elif conv < 20:
                        emoji = "⚠️"
                        template_text = get_template_variant('low')
                    else:
                        emoji = "💛"
                        template_text = get_template_variant('warning')

                    template = f"Коллеги, {greeting}!\n\n{template_text}"

                    lines = [
                        f"{emoji} <b>{escape(name)}</b>",
                        "",
                        f"📊 Конверсия в оплату: <b>{conv:.1f}%</b> (порог {CONVERSION_THRESHOLD}%)",
                        f"📋 С реквизитами: {with_req} → Оплатили: {successful}",
                    ]

                    # Разбивка по методам со статусом
                    merchant_methods = conv_by_method.get(name, [])
                    methods_with_req = [ms for ms in merchant_methods if (ms.get('with_req', 0) or 0) > 0]
                    if methods_with_req:
                        lines.append("")
                        lines.append("💳 <b>По методам:</b>")
                        for ms in sorted(methods_with_req, key=lambda x: x.get('with_req', 0), reverse=True):
                            m_name = ms.get('method', '?')
                            m_conv = ms.get('conv_pct', 0) or 0
                            m_req = ms.get('with_req', 0)
                            m_succ = ms.get('successful', 0)
                            if m_conv >= 40:
                                m_icon = "🟢"
                            elif m_conv >= CONVERSION_THRESHOLD:
                                m_icon = "🟡"
                            elif m_conv >= 10:
                                m_icon = "🟠"
                            else:
                                m_icon = "🔴"
                            lines.append(f"   {m_icon} {m_name}: <b>{m_conv:.1f}%</b> ({m_succ}/{m_req})")

                    lines.extend([
                        "",
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                        "",
                        template,
                    ])

                    # Добавляем примеры неоплаченных заявок
                    merchant_unpaid = unpaid_orders.get(name, [])
                    if merchant_unpaid and isinstance(merchant_unpaid, list):
                        lines.append("")
                        lines.append("📋 <b>Примеры неоплаченных заявок:</b>")
                        for item in merchant_unpaid[:10]:
                            if isinstance(item, dict):
                                ext = item.get('external_id', '?')
                                method = item.get('method', '')
                                method_str = f" · {method}" if method else ""
                                lines.append(f"• <code>{ext}</code>{method_str}")
                            else:
                                lines.append(f"• <code>{item}</code>")

                    lines.append("")
                    lines.append(f"⏰ {datetime.now(MSK).strftime('%d.%m.%Y %H:%M:%S')}")

                    text = "\n".join(lines)

                    # Генерируем картинку
                    try:
                        chart_image = visualization.generate_conversion_chart(
                            merchant_name=name,
                            total=total,
                            with_req=with_req,
                            successful=successful,
                            conv=conv,
                            hourly_data=hourly_by_merchant.get(name),
                            method_stats_pg=merchant_methods,
                        )
                        await update.message.reply_photo(
                            photo=chart_image,
                            caption=text,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка генерации визуализации для {name}: {e}")
                        await update.message.reply_text(text, parse_mode="HTML")

        elif txt == BTN_METHOD_OVERVIEW:
            await update.message.reply_text("⏳ Загружаю данные по методам...", parse_mode="HTML")
            try:
                conv_by_method = mb.get_conv_by_merchant_method()
            except Exception:
                conv_by_method = {}

            if not conv_by_method:
                await update.message.reply_text("❌ Нет данных по методам", parse_mode="HTML")
            else:
                # Только мерчанты с ≥10 выданных реквизитов суммарно
                for merchant_name in sorted(conv_by_method.keys()):
                    methods = conv_by_method[merchant_name]
                    methods_with_req = [ms for ms in methods if (ms.get('with_req', 0) or 0) > 0]
                    total_req_all = sum(ms.get('with_req', 0) or 0 for ms in methods_with_req)
                    if total_req_all < 10:
                        continue

                    total_req = sum(ms.get('with_req', 0) or 0 for ms in methods_with_req)
                    total_succ = sum(ms.get('successful', 0) or 0 for ms in methods_with_req)
                    overall_conv = round(total_succ * 100.0 / total_req, 1) if total_req > 0 else 0

                    if overall_conv >= 40:
                        m_emoji = "🟢"
                    elif overall_conv >= CONVERSION_THRESHOLD:
                        m_emoji = "🟡"
                    elif overall_conv >= 10:
                        m_emoji = "🟠"
                    else:
                        m_emoji = "🔴"

                    lines = [
                        f"{m_emoji} <b>{escape(merchant_name)}</b>",
                        f"📊 Общая: <b>{overall_conv:.1f}%</b> ({total_succ}/{total_req})",
                        "",
                    ]

                    for ms in sorted(methods_with_req, key=lambda x: x.get('with_req', 0), reverse=True):
                        m_name = ms.get('method', '?')
                        m_conv = ms.get('conv_pct', 0) or 0
                        m_req = ms.get('with_req', 0)
                        m_succ = ms.get('successful', 0)
                        if m_conv >= 40:
                            icon = "🟢"
                        elif m_conv >= CONVERSION_THRESHOLD:
                            icon = "🟡"
                        elif m_conv >= 10:
                            icon = "🟠"
                        else:
                            icon = "🔴"
                        lines.append(f"   {icon} {m_name}: <b>{m_conv:.1f}%</b> ({m_succ}/{m_req})")

                    text = "\n".join(lines)
                    await update.message.reply_text(text, parse_mode="HTML")

        elif txt == BTN_CANCELED:
            canceled = mb.get_canceled_analysis()
            text = format_canceled(canceled)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_refresh("refresh_canceled"))

        elif txt == BTN_ALERTS:
            alerts = mb.check_alerts()
            text = format_alerts(alerts)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_refresh("refresh_alerts"))

        elif txt == BTN_BAD_CLIENTS:
            bad_clients = mb.get_bad_clients()
            text = format_bad_clients(bad_clients)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_refresh("refresh_bad_clients"))

        elif txt == BTN_SEARCH:
            context.user_data["mode"] = "search"
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔍  <b>ПОИСК МЕРЧАНТА</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Введите название мерчанта:",
                parse_mode="HTML",
                reply_markup=kb_cancel()
            )

        elif txt == BTN_EXPORT:
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📤  <b>ВЫГРУЗКА ОТЧЁТОВ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Выберите данные для экспорта:",
                parse_mode="HTML",
                reply_markup=kb_export()
            )

        elif txt == BTN_RATES:
            rates = mb.get_rates_by_method()
            text = format_rates(rates)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_main(is_admin(update)))

        elif txt == BTN_ADD_MERCHANT:
            await add_merchant_start(update, context)

        elif txt == BTN_EDIT_MERCHANT:
            await edit_merchant_start(update, context)

        elif txt == BTN_NEW_INCIDENT:
            await inc_create_start(update, context)

        elif txt == BTN_INCIDENTS:
            await show_incidents_list(update, context)

        elif txt == BTN_ADMIN:
            if not is_admin(update):
                await update.message.reply_text("⛔ Нет доступа")
                return
            stats = keys.get_stats()
            text = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔐  <b>АДМИН-ПАНЕЛЬ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>Статистика:</b>\n"
                f"   Всего ключей: {stats['total_keys']}\n"
                f"   Активных: {stats['active_keys']}\n"
                f"   Использовано: {stats['used_keys']}\n"
                f"   Пользователей: {stats['authorized_users']}\n\n"
                "Выберите действие:"
            )
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb_admin())

        elif txt == BTN_UPLOAD_EXPORT:
            await update.message.reply_text(
                "📂 <b>Загрузка выгрузки чатов</b>\n\n"
                "Отправьте файл экспорта из Telegram Desktop:\n"
                "• <b>JSON</b> — экспорт одного чата\n"
                "• <b>ZIP</b> — полный экспорт всех чатов\n\n"
                "<i>Telegram Desktop → ⋮ → Export chat history → Format: JSON</i>\n"
                "<i>Или: Настройки → Продвинутые → Экспорт данных</i>",
                parse_mode="HTML"
            )

        elif txt == BTN_ACTIVE_SUMMARY:
            await update.message.reply_text("⏳ <b>Генерирую сводку по активным мерчантам...</b>", parse_mode="HTML")
            try:
                summary = await _generate_active_merchants_summary()
                for chunk in _split_message(summary):
                    await update.message.reply_text(chunk, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Active summary error: {e}")
                await update.message.reply_text(f"❌ Ошибка генерации сводки: {str(e)[:200]}", parse_mode="HTML")

        else:
            await update.message.reply_text(
                "Выберите раздел из меню ниже 👇",
                reply_markup=kb_main(is_admin(update))
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка: {str(e)[:100]}",
            reply_markup=kb_main(is_admin(update))
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загруженных файлов — JSON/ZIP экспорт из Telegram Desktop"""
    if not is_authenticated(update):
        await update.message.reply_text("🔐 Требуется авторизация")
        return

    doc = update.message.document
    if not doc:
        return

    fname = (doc.file_name or "").lower()

    # Supported formats: .json and .zip
    if not fname.endswith(".json") and not fname.endswith(".zip"):
        await update.message.reply_text(
            "⚠️ <b>Неподдерживаемый формат</b>\n\n"
            "Отправьте <b>JSON</b> или <b>ZIP</b> файл из экспорта Telegram Desktop.\n"
            "<i>Telegram Desktop → Настройки → Продвинутые → Экспорт данных → JSON</i>",
            parse_mode="HTML"
        )
        return

    # Size limit (20 MB)
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("⚠️ Файл слишком большой (максимум 20 МБ)")
        return

    status_msg = await update.message.reply_text("⏳ <b>Загружаю и обрабатываю файл...</b>", parse_mode="HTML")

    try:
        # Download file
        file = await doc.get_file()
        file_bytes = await file.download_as_bytearray()

        # Parse JSON from file or ZIP
        if fname.endswith(".zip"):
            zip_buf = io.BytesIO(file_bytes)
            with zipfile.ZipFile(zip_buf, 'r') as zf:
                # Look for result.json inside ZIP
                json_name = None
                for name in zf.namelist():
                    if name.endswith("result.json") or name.endswith(".json"):
                        json_name = name
                        break
                if not json_name:
                    await status_msg.edit_text(
                        "⚠️ <b>В ZIP-архиве не найден JSON файл</b>\n\n"
                        "Ожидается <code>result.json</code> внутри архива.",
                        parse_mode="HTML"
                    )
                    return
                content = zf.read(json_name).decode("utf-8")
                data = json.loads(content)
        else:
            content = file_bytes.decode("utf-8")
            data = json.loads(content)

        # Detect format: single chat vs full export
        if "chats" in data and "list" in data.get("chats", {}):
            # Full export format
            report = await _process_full_export(data, status_msg)
        elif "messages" in data:
            # Single chat format
            report = await _process_single_chat(
                data, status_msg,
                chat_name_fallback=(doc.file_name or "").replace(".json", "")
            )
        else:
            report = (
                "⚠️ <b>Неверный формат файла</b>\n\n"
                "Файл не похож на экспорт из Telegram Desktop.\n"
                "Нужен файл <code>result.json</code> с полем <code>messages</code> или <code>chats</code>."
            )

        await status_msg.edit_text(report, parse_mode="HTML")

    except json.JSONDecodeError:
        await status_msg.edit_text(
            "⚠️ <b>Ошибка парсинга JSON</b>\n\n"
            "Файл повреждён или имеет неверный формат.\n"
            "Убедитесь что экспортируете в формате JSON (Machine-readable).",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error processing chat export: {e}")
        await status_msg.edit_text(
            f"❌ <b>Ошибка обработки</b>\n\n"
            f"<code>{html.escape(str(e)[:200])}</code>",
            parse_mode="HTML"
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка inline-кнопок"""
    if not is_authenticated(update):
        await update.callback_query.answer("🔐 Требуется авторизация")
        return

    query = update.callback_query
    data = query.data

    await query.answer("Обновляю...")

    try:
        # === ЭКСПОРТ ===
        if data.startswith("export_"):
            export_type = data.replace("export_", "")
            date_str = datetime.now(MSK).strftime('%Y-%m-%d')

            if export_type == "merchants":
                merchants = mb.get_conversion_today()
                file = export_merchants_csv(merchants)
                await query.message.reply_document(
                    document=file,
                    filename=f"merchants_{date_str}.csv",
                    caption="📊 Статистика мерчантов"
                )

            elif export_type == "methods":
                methods = mb.get_conversion_by_method()
                file = export_methods_csv(methods)
                await query.message.reply_document(
                    document=file,
                    filename=f"methods_{date_str}.csv",
                    caption="💳 Статистика методов оплаты"
                )

            elif export_type == "hourly":
                hours = mb.get_hourly_stats()
                file = export_hourly_csv(hours)
                await query.message.reply_document(
                    document=file,
                    filename=f"hourly_{date_str}.csv",
                    caption="🕐 Почасовая статистика"
                )

            elif export_type == "conv_history":
                file = export_conv_history_csv(days=7)
                await query.message.reply_document(
                    document=file,
                    filename=f"conv_history_{date_str}.csv",
                    caption="📈 История конверсии за 7 дней"
                )

            elif export_type == "incidents":
                file = export_incidents_csv(days=30)
                await query.message.reply_document(
                    document=file,
                    filename=f"incidents_{date_str}.csv",
                    caption="🚨 Инциденты за 30 дней"
                )

            elif export_type == "all":
                merchants = mb.get_conversion_today()
                methods = mb.get_conversion_by_method()
                hours = mb.get_hourly_stats()

                # ZIP архив со всеми отчётами
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"merchants_{date_str}.csv", export_merchants_csv(merchants).getvalue())
                    zf.writestr(f"methods_{date_str}.csv", export_methods_csv(methods).getvalue())
                    zf.writestr(f"hourly_{date_str}.csv", export_hourly_csv(hours).getvalue())
                    zf.writestr(f"conv_history_{date_str}.csv", export_conv_history_csv(7).getvalue())
                    zf.writestr(f"incidents_{date_str}.csv", export_incidents_csv(30).getvalue())
                zip_buffer.seek(0)
                await query.message.reply_document(
                    document=zip_buffer,
                    filename=f"crm_export_{date_str}.zip",
                    caption="📋 Все отчёты (ZIP)"
                )
            return

        # === АДМИН ПАНЕЛЬ ===
        if data == "admin_newkey":
            if not is_admin(update):
                await query.answer("⛔ Нет доступа")
                return
            key = keys.generate_key(name="", created_by=update.effective_user.id)
            storage.log_audit(update.effective_user.id, "key_created", f"bot: new key by admin")
            await query.answer("Ключ создан!")
            await query.message.reply_text(
                f"🔑 <b>Новый ключ доступа:</b>\n\n"
                f"<code>{key}</code>\n\n"
                f"<i>Отправьте этот ключ пользователю для доступа к боту.</i>",
                parse_mode="HTML"
            )
            return

        if data == "admin_keys":
            if not is_admin(update):
                await query.answer("⛔ Нет доступа")
                return
            all_keys = keys.get_all_keys()
            if not all_keys:
                await query.edit_message_text(
                    "📋 <b>Ключи доступа</b>\n\nНет созданных ключей",
                    parse_mode="HTML",
                    reply_markup=kb_admin()
                )
                return

            lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "📋  <b>КЛЮЧИ ДОСТУПА</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
            for k in all_keys[-15:]:
                status = "🟢" if k["active"] and not k["used_by"] else "🔵" if k["used_by"] else "🔴"
                used = f"→ {k['used_by']}" if k["used_by"] else "свободен"
                lines.append(f"{status} <code>{k['key']}</code>")
                lines.append(f"   {used}")

            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb_admin())
            return

        if data == "admin_users":
            if not is_admin(update):
                await query.answer("⛔ Нет доступа")
                return
            users = keys.get_authorized_users()
            if not users:
                await query.edit_message_text(
                    "👥 <b>Пользователи</b>\n\nНет авторизованных пользователей",
                    parse_mode="HTML",
                    reply_markup=kb_admin()
                )
                return

            lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "👥  <b>АВТОРИЗОВАННЫЕ</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
            for u in users:
                lines.append(f"👤 <code>{u['user_id']}</code>")
                lines.append(f"   🔑 {u['key'][:12]}...")
                if u.get('used_at'):
                    lines.append(f"   📅 {u['used_at'][:10]}")
                lines.append("")

            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb_admin())
            return

        if data == "admin_stats":
            if not is_admin(update):
                await query.answer("⛔ Нет доступа")
                return
            stats = keys.get_stats()
            text = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📊  <b>СТАТИСТИКА КЛЮЧЕЙ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔑 Всего ключей: <b>{stats['total_keys']}</b>\n"
                f"🟢 Активных: <b>{stats['active_keys']}</b>\n"
                f"🔵 Использовано: <b>{stats['used_keys']}</b>\n"
                f"👥 Пользователей: <b>{stats['authorized_users']}</b>\n"
            )
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb_admin())
            return

        # === ОБНОВЛЕНИЕ ===

        # Специальная обработка для refresh_low_conversion (отправляет отдельные сообщения с картинками)
        if data == "refresh_low_conversion":
            await query.answer("Обновляю данные по конверсии...")

            merchants = mb.get_conversion_today()
            unpaid_orders = mb.get_unpaid_orders()
            try:
                hourly_by_merchant = mb.get_hourly_by_merchant()
            except Exception:
                hourly_by_merchant = {}
            try:
                conv_by_method = mb.get_conv_by_merchant_method()
            except Exception:
                conv_by_method = {}
            merchant_statuses = get_merchants_status_map()

            # Находим мерчантов с низкой конверсией (по общей)
            low_conv_merchants = []
            for m in merchants:
                name = m.get("Мерчант") or ""
                if "ИТОГО" in name:
                    continue
                if merchant_statuses.get(name) == 'disconnected':
                    continue
                if name in EXCLUDED_MERCHANTS:
                    continue

                total = m.get("Всего") or 0
                with_req = m.get("С реквизитами") or 0
                conv = m.get("Конверсия в оплату %") or 0

                if with_req >= MIN_ORDERS_WITH_REQ_FOR_ALERT and conv < CONVERSION_THRESHOLD:
                    low_conv_merchants.append({
                        "name": name, "total": total, "with_req": with_req,
                        "conv": conv, "successful": m.get("Успешных") or 0,
                    })

            if not low_conv_merchants:
                await query.message.reply_text(
                    "✅ <b>Все мерчанты имеют нормальную конверсию</b>\n\n"
                    f"Порог: {CONVERSION_THRESHOLD}%",
                    parse_mode="HTML"
                )
                return

            greeting = get_greeting_by_time()

            # Отправляем сообщения для каждого мерчанта
            for m in low_conv_merchants:
                conv = m['conv']
                name = m['name']
                total = m['total']
                with_req = m['with_req']
                successful = m['successful']

                if conv < 10:
                    emoji = "🔴"
                    template_text = get_template_variant('critical')
                elif conv < 20:
                    emoji = "⚠️"
                    template_text = get_template_variant('low')
                else:
                    emoji = "💛"
                    template_text = get_template_variant('warning')

                template = f"Коллеги, {greeting}!\n\n{template_text}"

                lines = [
                    f"{emoji} <b>{escape(name)}</b>",
                    "",
                    f"📊 Конверсия в оплату: <b>{conv:.1f}%</b>",
                    f"📋 С реквизитами: {with_req} → Оплатили: {successful}",
                ]

                merchant_methods = conv_by_method.get(name, [])
                methods_with_req = [ms for ms in merchant_methods if ms.get('with_req', 0) > 0]
                if methods_with_req:
                    lines.append("")
                    lines.append("💳 <b>По методам:</b>")
                    for ms in sorted(methods_with_req, key=lambda x: x.get('with_req', 0), reverse=True):
                        m_name = ms.get('method', '?')
                        m_conv = ms.get('conv_pct', 0) or 0
                        m_req = ms.get('with_req', 0)
                        m_succ = ms.get('successful', 0)
                        lines.append(f"   {m_name}: <b>{m_conv:.1f}%</b> ({m_succ}/{m_req})")

                lines.extend([
                    "",
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    "",
                    template,
                ])

                merchant_unpaid = unpaid_orders.get(name, [])
                if merchant_unpaid and isinstance(merchant_unpaid, list):
                    lines.append("")
                    lines.append("📋 <b>Примеры неоплаченных заявок:</b>")
                    for item in merchant_unpaid[:10]:
                        if isinstance(item, dict):
                            ext = item.get('external_id', '?')
                            method = item.get('method', '')
                            method_str = f" · {method}" if method else ""
                            lines.append(f"• <code>{ext}</code>{method_str}")
                        else:
                            lines.append(f"• <code>{item}</code>")

                lines.append("")
                lines.append(f"⏰ {datetime.now(MSK).strftime('%d.%m.%Y %H:%M:%S')}")

                text = "\n".join(lines)

                try:
                    chart_image = visualization.generate_conversion_chart(
                        merchant_name=name,
                        total=total,
                        with_req=with_req,
                        successful=successful,
                        conv=conv,
                        hourly_data=hourly_by_merchant.get(name),
                        method_stats_pg=merchant_methods,
                    )
                    await query.message.reply_photo(
                        photo=chart_image,
                        caption=text,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка генерации визуализации: {e}")
                    await query.message.reply_text(text, parse_mode="HTML")
            return

        # === CRM: АЛЕРТ КНОПКИ ===
        if data.startswith("alert_"):
            await handle_alert_callback(update, context, data)
            return

        # === CRM: ИНЦИДЕНТЫ ===
        if (data.startswith("inc_") or data.startswith("inc_type:") or
                data.startswith("inc_prio:") or data.startswith("inc_due:")):
            await handle_inc_callback(update, context, data)
            return

        # === CRM: МЕРЧАНТЫ (редактирование, история) ===
        if (data.startswith("medit_") or data.startswith("mset_") or data.startswith("mhist:")):
            await handle_medit_callback(update, context, data)
            return

        # Остальные обработчики обновления
        refresh_handlers = {
            "refresh_today": lambda: format_today(mb.get_main_dashboard()),
            "refresh_conversion": lambda: format_conversion_detailed(mb.get_conversion_today()),
            "refresh_canceled": lambda: format_canceled(mb.get_canceled_analysis()),
            "refresh_alerts": lambda: format_alerts(mb.check_alerts()),
            "refresh_bad_clients": lambda: format_bad_clients(mb.get_bad_clients()),
            "refresh_payout": lambda: format_payout(mb.get_payout_stats()),
        }

        if data in refresh_handlers:
            text = refresh_handlers[data]()
            await query.edit_message_text(
                text, parse_mode="HTML",
                reply_markup=kb_refresh(data)
            )

    except Exception as e:
        if "not modified" not in str(e).lower():
            try:
                await query.edit_message_text(f"❌ Ошибка: {str(e)[:100]}")
            except:
                pass


def check_config():
    """Проверка конфигурации перед запуском"""
    errors = []

    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
        errors.append("BOT_TOKEN не задан")

    if not ADMIN_IDS:
        errors.append("ADMIN_IDS не задан")

    from config import METABASE_EMAIL, METABASE_PASSWORD
    if not METABASE_EMAIL or not METABASE_PASSWORD:
        errors.append("METABASE_EMAIL или METABASE_PASSWORD не заданы")

    return errors


async def webapp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открыть CRM Mini App"""
    if not WEBAPP_URL:
        await update.message.reply_text("⚠️ Mini App не настроен (нет WEBAPP_URL)")
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Открыть CRM", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await update.message.reply_text("CRM панель:", reply_markup=keyboard)
