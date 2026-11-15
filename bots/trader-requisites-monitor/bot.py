"""
Telegram бот для мониторинга проблемных реквизитов
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
import asyncio

from config import (
    BOT_TOKEN,
    ADMIN_IDS,
    CHECK_INTERVAL_MINUTES,
    MIN_CONVERSION_PCT,
    MIN_ATTEMPTS,
    MAX_COMMENT_LENGTH,
    SUMMARY_THRESHOLD,
    ALERT_HISTORY_RETENTION_DAYS
)
from keys import (
    validate_key,
    is_user_authorized,
    get_authorized_users,
    is_admin,
    generate_key,
    get_all_keys,
    delete_key,
    revoke_user
)
from metabase import check_problem_requisites, test_connection
from ignored_requisites import is_ignored, add_to_ignored
import database

# Московский часовой пояс (UTC+3)
MSK = timezone(timedelta(hours=3))

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def group_requisites_by_severity(requisites: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Группирует реквизиты по критичности

    Returns:
        Словарь с ключами: 'critical', 'urgent', 'warning'
    """
    grouped = {
        'critical': [],  # 0% конверсия
        'urgent': [],    # <10% конверсия
        'warning': []    # 10-20% конверсия
    }

    for req in requisites:
        conversion = req.get('conversion_pct', 0) or 0
        if conversion == 0:
            grouped['critical'].append(req)
        elif conversion < 10:
            grouped['urgent'].append(req)
        else:
            grouped['warning'].append(req)

    return grouped


def format_summary_message(grouped: Dict[str, List[Dict]], total_count: int) -> str:
    """
    Форматирует сводное сообщение о проблемных реквизитах

    Args:
        grouped: Сгруппированные реквизиты
        total_count: Общее количество проблемных реквизитов

    Returns:
        Отформатированное сводное сообщение
    """
    message = f"⚠️ <b>СВОДКА: Найдено {total_count} проблемных реквизитов</b>\n\n"

    # Критичные (0%)
    if grouped['critical']:
        message += f"🔴 <b>КРИТИЧНО</b> (0% конверсия): {len(grouped['critical'])} шт.\n"
        for req in grouped['critical']:
            gate_name = req.get('gate_username', 'Н/Д')
            total = req.get('total_orders', 0)
            success = req.get('success_orders', 0)
            bank = req.get('bank', 'Н/Д')
            message += f"   • {gate_name} | 🏦 {bank} | {success}/{total} заказов\n"
        message += "\n"

    # Срочные (<10%)
    if grouped['urgent']:
        message += f"🟠 <b>СРОЧНО</b> (&lt;10% конверсия): {len(grouped['urgent'])} шт.\n"
        for req in grouped['urgent']:
            gate_name = req.get('gate_username', 'Н/Д')
            conversion = req.get('conversion_pct', 0) or 0
            total = req.get('total_orders', 0)
            success = req.get('success_orders', 0)
            bank = req.get('bank', 'Н/Д')
            message += f"   • {gate_name} | 🏦 {bank} | {conversion:.1f}% ({success}/{total})\n"
        message += "\n"

    # Внимание (10-20%)
    if grouped['warning']:
        message += f"🟡 <b>ВНИМАНИЕ</b> (10-20% конверсия): {len(grouped['warning'])} шт.\n"
        for req in grouped['warning']:
            gate_name = req.get('gate_username', 'Н/Д')
            conversion = req.get('conversion_pct', 0) or 0
            total = req.get('total_orders', 0)
            success = req.get('success_orders', 0)
            bank = req.get('bank', 'Н/Д')
            message += f"   • {gate_name} | 🏦 {bank} | {conversion:.1f}% ({success}/{total})\n"
        message += "\n"

    message += f"⏰ Проверка: {datetime.now(MSK).strftime('%d.%m.%Y %H:%M')}\n"
    message += "\n📋 Нажмите кнопку ниже для просмотра деталей"

    return message


def format_detailed_list(requisites: List[Dict]) -> str:
    """
    Форматирует детальный список реквизитов для кнопки "Показать детали"

    Returns:
        Список реквизитов в кратком формате
    """
    message = f"📋 <b>Детальный список ({len(requisites)} реквизитов):</b>\n\n"

    for i, req in enumerate(requisites, 1):
        gate_name = req.get('gate_username', 'Н/Д')
        conversion = req.get('conversion_pct', 0) or 0
        total = req.get('total_orders', 0)
        success = req.get('success_orders', 0)
        bank = req.get('bank', 'Н/Д')

        # Определяем эмодзи критичности
        if conversion == 0:
            emoji = "🔴"
        elif conversion < 10:
            emoji = "🟠"
        else:
            emoji = "🟡"

        message += f"{emoji} <b>{i}. {gate_name}</b>\n"
        message += f"   🏦 {bank} | 📊 {conversion:.1f}% ({success}/{total})\n\n"

    message += "💡 Используйте /start для ручной проверки и отметки реквизитов"

    return message


def split_long_message(message: str, max_length: int = 4000) -> List[str]:
    """
    Разбивает длинное сообщение на части по строкам

    Args:
        message: Исходное сообщение
        max_length: Максимальная длина одной части

    Returns:
        Список частей сообщения
    """
    if len(message) <= max_length:
        return [message]

    parts = []
    lines = message.split('\n')
    current_part = ""

    for line in lines:
        if len(current_part) + len(line) + 1 <= max_length:
            current_part += line + '\n'
        else:
            if current_part:
                parts.append(current_part.rstrip())
            current_part = line + '\n'

    if current_part:
        parts.append(current_part.rstrip())

    return parts


def analyze_alert_patterns(gate_name: str, req: Dict) -> list:
    """
    Анализирует паттерны алертов и возвращает список бейджей

    Args:
        gate_name: Название реквизита
        req: Данные реквизита

    Returns:
        Список бейджей ['🔥 Постоянная проблема', ...]
    """
    from config import RECURRING_ALERT_THRESHOLD, CRITICAL_DROP_PERCENT

    badges = []

    try:
        # 1. Проверка на постоянную проблему (>3 раза за день)
        alerts_today = database.get_alert_count_today(gate_name)
        if alerts_today >= RECURRING_ALERT_THRESHOLD:
            badges.append("🔥 Постоянная проблема")
            logger.info(f"🔥 {gate_name} - постоянная проблема (алертов сегодня: {alerts_today})")

        # 2. Проверка на резкое падение конверсии
        current_conversion = req.get('conversion_pct', 0) or 0
        avg_conversion = database.get_average_conversion_last_week(gate_name)

        if avg_conversion and avg_conversion > 0:
            drop_percent = ((avg_conversion - current_conversion) / avg_conversion) * 100
            if drop_percent >= CRITICAL_DROP_PERCENT:  # Падение на 50%+
                badges.append(f"⚠️ Резкое падение! (было {avg_conversion:.1f}%)")
                logger.info(f"⚠️ {gate_name} - резкое падение: {avg_conversion:.1f}% → {current_conversion:.1f}%")

        # 3. Проверка на новую проблему
        if database.is_new_problem_requisite(gate_name):
            badges.append("🆕 Новая проблема")
            logger.info(f"🆕 {gate_name} - новая проблема (первый раз в алертах)")

    except Exception as e:
        logger.error(f"Ошибка анализа паттернов для {gate_name}: {e}")

    return badges


def determine_alert_type(badges: list) -> str:
    """
    Определяет тип алерта на основе бейджей

    Args:
        badges: Список бейджей

    Returns:
        Тип алерта: 'recurring', 'critical_drop', 'new', 'normal'
    """
    for badge in badges:
        if "Постоянная проблема" in badge:
            return "recurring"
        elif "Резкое падение" in badge:
            return "critical_drop"
        elif "Новая проблема" in badge:
            return "new"
    return "normal"


def format_requisite_alert(req: Dict, alert_badges: list = None) -> str:
    """
    Форматирует данные о проблемном реквизите для отправки

    Args:
        req: Словарь с данными о реквизите
        alert_badges: Список бейджей для добавления

    Returns:
        Отформатированное сообщение
    """
    # Рассчитываем конверсию
    total = req.get('total_orders', 0)
    success = req.get('success_orders', 0)
    conversion = req.get('conversion_pct', 0) or 0

    # Получаем данные о реквизите
    bank = req.get('bank', 'Н/Д')
    holder = req.get('holder_name', 'Н/Д')

    # Преобразуем код типа оплаты в читаемый вид
    pay_type_code = req.get('pay_type', '')
    payment_type_map = {
        'sbp': 'СБП',
        'c2c': 'С2С',
        'alfa': 'Альфа',
        'tinkoff': 'Тинькофф',
        'sber': 'Сбер',
        'tbank': 'Т-Банк',
        'vtb': 'ВТБ',
        'psb': 'ПСБ',
        'ozon': 'Ozon',
        'sim': 'СИМ',
        'sng_sbp': 'СНГ СБП',
        'sng_c2c': 'СНГ С2С',
        'card': 'Карта'
    }
    payment_type = payment_type_map.get(pay_type_code, pay_type_code or 'Н/Д')

    account = req.get('pay_acc', 'Н/Д')

    # Провайдер
    provider_name = req.get('gate_username', 'Н/Д')

    # Подсчитываем отмененные заказы
    cancelled = total - success

    # Определяем серьезность проблемы
    if conversion == 0:
        alert_level = "🚨 КРИТИЧНО"
    elif conversion < 10:
        alert_level = "⚠️ СРОЧНО"
    else:
        alert_level = "⚠️ ВНИМАНИЕ"

    # Форматируем бейджи, если они есть
    badges_text = ""
    if alert_badges:
        badges_text = "\n" + "\n".join(f"• {badge}" for badge in alert_badges) + "\n"

    message = f"""
{alert_level} Плохие реки провайдеров
{badges_text}
🏦 Банк: {bank}
👤 Держатель: {holder}
💳 Тип оплаты: {payment_type}
💰 Счет: {account}

🏢 Провайдер: {provider_name}

📊 Статистика:
  • Всего заказов: {total}
  • Успешных: {success}
  • Отмененных: {cancelled}
  • Конверсия: {conversion:.1f}%

⏰ Проверка: {datetime.now(MSK).strftime('%d.%m.%Y %H:%M')}
"""
    return message


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id

    # Проверяем авторизацию
    if is_user_authorized(user_id):
        keyboard = [
            [KeyboardButton("🔍 Проверить сейчас")],
            [KeyboardButton("📊 Меню")]
        ]

        # Добавляем кнопку админа для админов
        if is_admin(user_id):
            keyboard.append([KeyboardButton("⚙️ Админ-панель")])

        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "✅ Добро пожаловать в RequisitesMonitor!\n\n"
            "Вы авторизованы и будете получать уведомления о проблемных реквизитах.\n\n"
            "🔍 Проверить сейчас - ручная проверка\n"
            "📊 Меню - просмотр статистики и экспорт отчётов",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👋 Добро пожаловать в RequisitesMonitor!\n\n"
            "Для доступа к боту введите мастер-ключ:"
        )


async def show_ignored_with_comments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает список игнорируемых реквизитов с комментариями
    """
    try:
        ignored_with_comments = database.get_all_ignored_with_comments()

        if not ignored_with_comments:
            await update.message.reply_text("📝 Игнор-лист пуст")
            return

        message = "📝 <b>Игнорируемые реквизиты с комментариями:</b>\n\n"

        for item in ignored_with_comments:
            gate_name = item['gate_name']
            expires_at = item['expires_at']
            comments = item.get('comments', [])

            # Форматируем время
            time_str = expires_at.strftime('%d.%m.%Y %H:%M')

            message += f"🏦 <b>{gate_name}</b>\n"
            message += f"⏰ До: {time_str}\n"

            if comments:
                message += "💬 Комментарии:\n"
                for comment in comments:
                    user_id_comment = comment['user_id']
                    comment_text = comment['comment']
                    created_at = comment['created_at'].strftime('%d.%m %H:%M')
                    message += f"   • [{created_at}] ID{user_id_comment}: {comment_text}\n"
            else:
                message += "💬 Комментариев нет\n"

            message += "\n"

        # Разбиваем длинные сообщения
        if len(message) > 4000:
            # Отправляем по частям
            parts = []
            current_part = "📝 <b>Игнорируемые реквизиты с комментариями:</b>\n\n"

            for item in ignored_with_comments:
                gate_name = item['gate_name']
                expires_at = item['expires_at']
                comments = item.get('comments', [])
                time_str = expires_at.strftime('%d.%m.%Y %H:%M')

                item_text = f"🏦 <b>{gate_name}</b>\n⏰ До: {time_str}\n"

                if comments:
                    item_text += "💬 Комментарии:\n"
                    for comment in comments:
                        user_id_comment = comment['user_id']
                        comment_text = comment['comment']
                        created_at = comment['created_at'].strftime('%d.%m %H:%M')
                        item_text += f"   • [{created_at}] ID{user_id_comment}: {comment_text}\n"
                else:
                    item_text += "💬 Комментариев нет\n"

                item_text += "\n"

                if len(current_part) + len(item_text) > 4000:
                    parts.append(current_part)
                    current_part = item_text
                else:
                    current_part += item_text

            if current_part:
                parts.append(current_part)

            for part in parts:
                await update.message.reply_text(part, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Ошибка показа игнор-листа с комментариями: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def handle_export(update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int = 24):
    """
    Обрабатывает экспорт отчётов в CSV

    Args:
        hours: Количество часов для выборки (24 = сутки, 168 = неделя)
    """
    import export_utils

    try:
        await update.message.reply_text("⏳ Генерирую отчёт...")

        # Получаем статистику
        stats = export_utils.get_export_stats(hours)

        if stats['total_alerts'] == 0:
            period = "за сутки" if hours == 24 else "за неделю"
            await update.message.reply_text(f"📊 Нет данных для экспорта {period}")
            return

        # Генерируем CSV
        csv_file = export_utils.generate_csv_report(hours)

        # Форматируем имя файла
        period_name = "sutki" if hours == 24 else "nedelya"
        filename = f"alerts_{period_name}_{datetime.now(MSK).strftime('%Y%m%d_%H%M')}.csv"

        # Убедимся, что позиция в начале файла
        csv_file.seek(0)

        # Отправляем файл
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=csv_file,
            filename=filename,
            caption=export_utils.format_export_summary(stats),
            parse_mode=ParseMode.HTML
        )

        # Закрываем файл после отправки
        csv_file.close()

        logger.info(f"📥 Экспорт за {hours}ч отправлен пользователю {update.effective_user.id}")

    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка генерации отчёта: {str(e)}")


async def user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню для всех авторизованных пользователей"""
    user_id = update.effective_user.id

    if not is_user_authorized(user_id):
        await update.message.reply_text("❌ Доступ запрещен. Введите мастер-ключ.")
        return

    keyboard = [
        [KeyboardButton("📝 Игнор-лист с комментариями")],
        [KeyboardButton("📥 Экспорт за сутки"), KeyboardButton("📥 Экспорт за неделю")],
        [KeyboardButton("◀️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    # Получаем статистику
    try:
        import export_utils
        stats = export_utils.get_export_stats(hours=24)

        message = (
            f"📊 Меню статистики и отчётов\n\n"
            f"📈 За последние 24 часа:\n"
            f"  • Алертов: {stats['total_alerts']}\n"
            f"  • Уникальных реквизитов: {stats['unique_requisites']}\n"
            f"  • Критичных: {stats['critical_count']}\n"
            f"  • Срочных: {stats['urgent_count']}\n\n"
            f"Выберите действие:"
        )
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        message = "📊 Меню статистики и отчётов\n\nВыберите действие:"

    await update.message.reply_text(message, reply_markup=reply_markup)


async def broadcast_to_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет рассылку всем авторизованным пользователям
    """
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Доступ запрещен")
        return

    # Получаем всех пользователей (админы + авторизованные)
    all_users = set(ADMIN_IDS) | set(get_authorized_users())

    message = (
        "🔄 <b>Обновление бота!</b>\n\n"
        "Добавлены новые функции:\n"
        "• 📊 Меню со статистикой\n"
        "• 📝 Просмотр игнор-листа с комментариями\n"
        "• 📥 Экспорт отчётов в CSV\n"
        "• 🎯 Умные уведомления с бейджами\n"
        "• 📋 Сводка при большом количестве алертов\n\n"
        "Для активации новых функций нажмите /start"
    )

    await update.message.reply_text(
        f"📢 Начинаю рассылку для {len(all_users)} пользователей...",
    )

    success_count = 0
    fail_count = 0

    for target_user_id in all_users:
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=message,
                parse_mode=ParseMode.HTML
            )
            success_count += 1
            logger.info(f"✅ Рассылка отправлена пользователю {target_user_id}")
        except Exception as e:
            fail_count += 1
            logger.error(f"❌ Ошибка отправки пользователю {target_user_id}: {e}")

    await update.message.reply_text(
        f"✅ Рассылка завершена!\n\n"
        f"📊 Результаты:\n"
        f"  • Отправлено: {success_count}\n"
        f"  • Ошибок: {fail_count}\n"
        f"  • Всего: {len(all_users)}"
    )

    logger.info(f"📢 Рассылка завершена: {success_count}/{len(all_users)} успешно")


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ-панель"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Доступ запрещен")
        return

    keyboard = [
        [KeyboardButton("➕ Создать ключ"), KeyboardButton("📋 Список ключей")],
        [KeyboardButton("👥 Пользователи"), KeyboardButton("🗑️ Удалить ключ")],
        [KeyboardButton("📢 Рассылка")],
        [KeyboardButton("🧹 Очистить игнор-лист")],
        [KeyboardButton("◀️ Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    keys_count = len(get_all_keys())
    users_count = len(get_authorized_users())

    await update.message.reply_text(
        f"⚙️ Админ-панель (только для администраторов)\n\n"
        f"📊 Статистика:\n"
        f"  • Ключей доступа: {keys_count}\n"
        f"  • Авторизованных пользователей: {users_count}\n\n"
        f"Выберите действие:\n\n"
        f"💡 Игнор-лист и экспорт доступны в меню \"📊 Меню\"",
        reply_markup=reply_markup
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text

    # Проверяем, ожидается ли ввод комментария
    if context.user_data.get('waiting_for_comment'):
        gate_name = context.user_data['waiting_for_comment']

        # Проверяем длину комментария
        if len(text) > MAX_COMMENT_LENGTH:
            await update.message.reply_text(
                f"❌ Комментарий слишком длинный!\n"
                f"Максимум {MAX_COMMENT_LENGTH} символов, у вас {len(text)}.\n\n"
                f"Пожалуйста, сократите текст и отправьте заново."
            )
            return

        # Сохраняем комментарий
        try:
            database.add_ignore_comment(gate_name, user_id, text)
            await update.message.reply_text(
                f"✅ Комментарий сохранён!\n\n"
                f"🏦 Реквизит: {gate_name}\n"
                f"💬 Комментарий: {text}"
            )
            logger.info(f"💾 Комментарий от {user_id} для {gate_name} сохранён: {text[:50]}...")
        except Exception as e:
            logger.error(f"Ошибка сохранения комментария: {e}")
            await update.message.reply_text(f"❌ Ошибка сохранения комментария: {str(e)}")

        # Очищаем флаг ожидания
        del context.user_data['waiting_for_comment']
        return

    # Админ-панель
    if text == "⚙️ Админ-панель":
        await admin_panel(update, context)
        return

    # Админ: Рассылка
    if text == "📢 Рассылка":
        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        await broadcast_to_all_users(update, context)
        return

    # Админ: Создать ключ
    if text == "➕ Создать ключ":
        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        key = generate_key(f"Key-{len(get_all_keys())}")
        await update.message.reply_text(
            f"✅ Ключ создан!\n\n"
            f"🔑 <code>{key}</code>\n\n"
            f"Отправьте этот ключ пользователю для авторизации.",
            parse_mode=ParseMode.HTML
        )
        return

    # Админ: Список ключей
    if text == "📋 Список ключей":
        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        keys = get_all_keys()
        if not keys:
            await update.message.reply_text("📋 Нет активных ключей")
            return

        message = "📋 Список ключей доступа:\n\n"
        for key, name in keys.items():
            message += f"🔑 <code>{key}</code>\n   └ {name}\n\n"

        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        return

    # Админ: Пользователи
    if text == "👥 Пользователи":
        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        users = get_authorized_users()
        if not users:
            await update.message.reply_text("👥 Нет авторизованных пользователей")
            return

        message = "👥 Авторизованные пользователи:\n\n"
        for uid in users:
            admin_mark = " (Админ)" if uid in ADMIN_IDS else ""
            message += f"• ID: <code>{uid}</code>{admin_mark}\n"

        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        return

    # Админ: Удалить ключ
    if text == "🗑️ Удалить ключ":
        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        await update.message.reply_text(
            "🗑️ Отправьте ключ для удаления:\n\n"
            "Формат: <code>KEY-XXXXXXXXXXXX</code>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['waiting_for_key_delete'] = True
        return

    # Обработка удаления ключа
    if context.user_data.get('waiting_for_key_delete'):
        context.user_data['waiting_for_key_delete'] = False

        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        if delete_key(text):
            await update.message.reply_text(f"✅ Ключ удален: <code>{text}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Ключ не найден или это мастер-ключ (его нельзя удалить)")
        return

    # Очистить игнор-лист
    if text == "🧹 Очистить игнор-лист":
        if not is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return

        try:
            pool = database.get_connection_pool()
            conn = pool.getconn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ignored_requisites")
            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            pool.putconn(conn)

            await update.message.reply_text(
                f"✅ Игнор-лист очищен!\n"
                f"Удалено записей: {deleted}\n\n"
                f"Теперь все проблемные реквизиты будут отображаться в алертах."
            )
            logger.info(f"🧹 Админ {user_id} очистил игнор-лист ({deleted} записей)")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка очистки: {str(e)}")
            logger.error(f"Ошибка очистки игнор-листа: {e}")
        return

    # Меню для всех пользователей
    if text == "📊 Меню":
        if not is_user_authorized(user_id):
            await update.message.reply_text("❌ Доступ запрещен. Введите мастер-ключ.")
            return

        await user_menu(update, context)
        return

    # Игнор-лист с комментариями (доступно всем авторизованным)
    if text == "📝 Игнор-лист с комментариями":
        if not is_user_authorized(user_id):
            await update.message.reply_text("❌ Доступ запрещен. Введите мастер-ключ.")
            return

        await show_ignored_with_comments(update, context)
        return

    # Экспорт за сутки (доступно всем авторизованным)
    if text == "📥 Экспорт за сутки":
        if not is_user_authorized(user_id):
            await update.message.reply_text("❌ Доступ запрещен. Введите мастер-ключ.")
            return

        await handle_export(update, context, hours=24)
        return

    # Экспорт за неделю (доступно всем авторизованным)
    if text == "📥 Экспорт за неделю":
        if not is_user_authorized(user_id):
            await update.message.reply_text("❌ Доступ запрещен. Введите мастер-ключ.")
            return

        await handle_export(update, context, hours=168)
        return

    # Назад
    if text == "◀️ Назад":
        await start_command(update, context)
        return

    # Кнопка проверки
    if text == "🔍 Проверить сейчас":
        if not is_user_authorized(user_id):
            await update.message.reply_text("❌ Доступ запрещен. Введите мастер-ключ.")
            return

        await update.message.reply_text("⏳ Проверяю реквизиты...")
        await check_and_alert_user(update, context, user_id)
        return

    # Проверка мастер-ключа
    if not is_user_authorized(user_id):
        if validate_key(text, user_id):
            keyboard = [[KeyboardButton("🔍 Проверить сейчас")]]

            # Добавляем кнопку админа для админов
            if is_admin(user_id):
                keyboard.append([KeyboardButton("⚙️ Админ-панель")])

            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

            await update.message.reply_text(
                "✅ Авторизация успешна!\n\n"
                "Вы будете получать уведомления о проблемных реквизитах.",
                reply_markup=reply_markup
            )
            logger.info(f"Пользователь {user_id} авторизован")
        else:
            await update.message.reply_text(
                "❌ Неверный мастер-ключ. Попробуйте снова:"
            )


async def check_and_alert_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Проверяет реквизиты и отправляет алерты конкретному пользователю

    Args:
        update: Update объект
        context: Context объект
        user_id: ID пользователя для отправки
    """
    try:
        logger.info(f"🔍 Пользователь {user_id} запустил ручную проверку")

        results = check_problem_requisites()
        logger.info(f"📊 Получено результатов от Metabase: {len(results)}")

        # Логируем все найденные реквизиты
        for req in results:
            gate_username = req.get('gate_username', '')
            logger.info(f"  - Найден реквизит: {gate_username}")

        # Фильтруем игнорируемые реквизиты
        filtered_results = []
        ignored_list = []
        for req in results:
            gate_username = req.get('gate_username', '')
            if is_ignored(gate_username):
                ignored_list.append(gate_username)
            else:
                filtered_results.append(req)

        ignored_count = len(ignored_list)

        if ignored_count > 0:
            logger.info(f"🔇 Отфильтровано игнорируемых реквизитов: {ignored_count}")
            for ign in ignored_list:
                logger.info(f"  - Игнорируется: {ign}")

        if not filtered_results:
            logger.info(f"✅ Проблемных реквизитов не найдено (всего: {len(results)}, игнорируется: {ignored_count})")
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Проблемных реквизитов не найдено!"
            )
            return

        logger.info(f"📤 Отправляю {len(filtered_results)} алертов пользователю {user_id}")

        # Проверяем, нужна ли сводка (5+ реквизитов)
        if len(filtered_results) >= SUMMARY_THRESHOLD:
            logger.info(f"📊 Используем сводку для {len(filtered_results)} реквизитов (порог: {SUMMARY_THRESHOLD})")

            # Группируем по критичности
            grouped = group_requisites_by_severity(filtered_results)

            # Форматируем сводное сообщение
            summary = format_summary_message(grouped, len(filtered_results))

            # Кнопка для просмотра деталей
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Показать детали", callback_data="show_details")]
            ])

            # Сохраняем данные для кнопки "Показать детали"
            context.user_data['detailed_requisites'] = filtered_results

            # Отправляем сводку
            await context.bot.send_message(
                chat_id=user_id,
                text=summary,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

            # Сохраняем алерты в историю
            for req in filtered_results:
                gate_name = req.get('gate_username', '')
                try:
                    alert_badges = analyze_alert_patterns(gate_name, req)
                    alert_type = determine_alert_type(alert_badges)
                    conversion_pct = req.get('conversion_pct', 0) or 0
                    total_orders = req.get('total_orders', 0)
                    success_orders = req.get('success_orders', 0)
                    database.save_alert(gate_name, conversion_pct, total_orders, success_orders, alert_type)
                except Exception as e:
                    logger.error(f"Ошибка сохранения алерта для {gate_name}: {e}")

        else:
            # Отправляем каждый проблемный реквизит отдельно (< 5 реквизитов)
            for req in filtered_results:
                gate_name = req.get('gate_username', '')

                # Анализируем паттерны и получаем бейджи
                alert_badges = analyze_alert_patterns(gate_name, req)

                # Форматируем сообщение с бейджами
                message = format_requisite_alert(req, alert_badges)

                # Определяем тип алерта
                alert_type = determine_alert_type(alert_badges)

                # Кнопка для отметки "Выполнено"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Выполнено", callback_data=f"ignore:{gate_name}")]
                ])

                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard
                )

                # Сохраняем информацию об алерте в историю
                try:
                    conversion_pct = req.get('conversion_pct', 0) or 0
                    total_orders = req.get('total_orders', 0)
                    success_orders = req.get('success_orders', 0)
                    database.save_alert(gate_name, conversion_pct, total_orders, success_orders, alert_type)
                except Exception as e:
                    logger.error(f"Ошибка сохранения алерта для {gate_name}: {e}")

            # Итоговое сообщение
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📋 Всего найдено проблемных реквизитов: {len(filtered_results)}"
            )

        logger.info(f"✅ Проверка для пользователя {user_id} завершена успешно")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке для пользователя {user_id}: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Ошибка при проверке: {str(e)}"
        )


async def check_and_alert_all(context: ContextTypes.DEFAULT_TYPE):
    """
    Периодическая проверка реквизитов и отправка алертов всем авторизованным пользователям
    """
    logger.info("🔄 Запуск автоматической проверки реквизитов")

    try:
        results = check_problem_requisites()
        logger.info(f"📊 Получено от Metabase: {len(results)} реквизитов")

        # Логируем все найденные
        for req in results:
            gate_username = req.get('gate_username', '')
            logger.info(f"  - Найден: {gate_username}")

        # Фильтруем игнорируемые реквизиты
        filtered_results = []
        ignored_list = []
        for req in results:
            gate_username = req.get('gate_username', '')
            if is_ignored(gate_username):
                ignored_list.append(gate_username)
            else:
                filtered_results.append(req)

        if ignored_list:
            logger.info(f"🔇 Игнорируется: {len(ignored_list)} реквизитов")
            for ign in ignored_list:
                logger.info(f"  - Игнорируется: {ign}")

        if not filtered_results:
            logger.info("✅ Проблемных реквизитов не найдено (или все игнорируются)")
            return

        logger.info(f"⚠️ Найдено проблемных реквизитов: {len(filtered_results)}")

        # Получаем всех кому отправить
        all_users = set(ADMIN_IDS) | set(get_authorized_users())

        # Сохраняем алерты в историю (один раз для всех пользователей)
        for req in filtered_results:
            gate_name = req.get('gate_username', '')
            try:
                alert_badges = analyze_alert_patterns(gate_name, req)
                alert_type = determine_alert_type(alert_badges)
                conversion_pct = req.get('conversion_pct', 0) or 0
                total_orders = req.get('total_orders', 0)
                success_orders = req.get('success_orders', 0)
                database.save_alert(gate_name, conversion_pct, total_orders, success_orders, alert_type)
            except Exception as e:
                logger.error(f"Ошибка сохранения алерта для {gate_name}: {e}")

        for user_id in all_users:
            try:
                # Проверяем, нужна ли сводка (5+ реквизитов)
                if len(filtered_results) >= SUMMARY_THRESHOLD:
                    logger.info(f"📊 Используем сводку для пользователя {user_id}: {len(filtered_results)} реквизитов")

                    # Группируем по критичности
                    grouped = group_requisites_by_severity(filtered_results)

                    # Форматируем сводное сообщение
                    summary = format_summary_message(grouped, len(filtered_results))

                    # Кнопка для просмотра деталей
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Показать детали", callback_data="show_details")]
                    ])

                    # Сохраняем данные для кнопки "Показать детали"
                    # Примечание: context.user_data может не работать для автоматических проверок
                    # Это ограничение Telegram Bot API для callback_data без активного update

                    # Отправляем сводку
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=summary,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )

                else:
                    # Отправляем каждый проблемный реквизит отдельно (< 5 реквизитов)
                    for req in filtered_results:
                        gate_name = req.get('gate_username', '')

                        # Анализируем паттерны и получаем бейджи
                        alert_badges = analyze_alert_patterns(gate_name, req)

                        # Форматируем сообщение с бейджами
                        message = format_requisite_alert(req, alert_badges)

                        # Кнопка для отметки "Выполнено"
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Выполнено", callback_data=f"ignore:{gate_name}")]
                        ])

                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )

                    # Итоговое сообщение
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"📋 Всего найдено проблемных реквизитов: {len(filtered_results)}"
                    )

                logger.info(f"Алерты отправлены пользователю {user_id}")

            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {user_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при автоматической проверке: {e}")


async def handle_ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие кнопки "Выполнено" - добавляет реквизит в игнор-лист на 24 часа
    """
    query = update.callback_query
    await query.answer()

    # Проверяем авторизацию
    user_id = update.effective_user.id
    if not is_user_authorized(user_id) and user_id not in ADMIN_IDS:
        await query.edit_message_text(text="❌ У вас нет доступа к этой функции")
        return

    # Парсим callback_data
    callback_data = query.data
    if not callback_data.startswith("ignore:"):
        return

    gate_name = callback_data.replace("ignore:", "")

    logger.info(f"✅ Пользователь {user_id} отмечает реквизит '{gate_name}' как выполненный")

    # Добавляем в игнор-лист (в БД)
    try:
        add_to_ignored(gate_name)
        logger.info(f"💾 Реквизит '{gate_name}' добавлен в БД на 24 часа")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления реквизита '{gate_name}' в игнор-лист: {e}")
        await query.edit_message_text(
            text=f"{query.message.text}\n\n❌ <b>Ошибка сохранения</b>",
            parse_mode=ParseMode.HTML
        )
        return

    # Обновляем сообщение с кнопкой для добавления комментария
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Добавить комментарий", callback_data=f"comment:{gate_name}")]
    ])

    await query.edit_message_text(
        text=f"{query.message.text}\n\n✅ <b>Отмечено как выполнено</b>\nРеквизит будет игнорироваться 24 часа",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def handle_comment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие кнопки "Добавить комментарий" - запускает диалог для ввода комментария
    """
    query = update.callback_query
    await query.answer()

    # Проверяем авторизацию
    user_id = update.effective_user.id
    if not is_user_authorized(user_id) and user_id not in ADMIN_IDS:
        await query.edit_message_text(text="❌ У вас нет доступа к этой функции")
        return

    # Парсим callback_data
    callback_data = query.data
    if not callback_data.startswith("comment:"):
        return

    gate_name = callback_data.replace("comment:", "")

    logger.info(f"💬 Пользователь {user_id} добавляет комментарий к реквизиту '{gate_name}'")

    # Сохраняем gate_name в context для последующей обработки
    context.user_data['waiting_for_comment'] = gate_name

    # Просим пользователя ввести комментарий
    await query.edit_message_text(
        text=f"{query.message.text}\n\n📝 <b>Введите комментарий</b> (до {MAX_COMMENT_LENGTH} символов):\n\nНапример: \"Связались с провайдером, решают проблему до 22:00\"",
        parse_mode=ParseMode.HTML
    )


async def handle_show_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие кнопки "Показать детали" - отправляет детальный список реквизитов
    """
    query = update.callback_query
    await query.answer()

    # Проверяем авторизацию
    user_id = update.effective_user.id
    if not is_user_authorized(user_id) and user_id not in ADMIN_IDS:
        await query.edit_message_text(text="❌ У вас нет доступа к этой функции")
        return

    # Получаем сохранённые данные из context
    detailed_requisites = context.user_data.get('detailed_requisites', [])

    if not detailed_requisites:
        await query.answer("❌ Данные устарели, выполните проверку заново", show_alert=True)
        return

    # Форматируем детальный список
    message = format_detailed_list(detailed_requisites)

    # Разбиваем на части если слишком длинное
    parts = split_long_message(message, max_length=4000)

    # Отправляем первую часть как ответ на callback
    await query.edit_message_text(text=parts[0], parse_mode=ParseMode.HTML)

    # Остальные части отправляем отдельными сообщениями
    for part in parts[1:]:
        await context.bot.send_message(
            chat_id=user_id,
            text=part,
            parse_mode=ParseMode.HTML
        )

    # Отправляем кнопки для действий с каждым реквизитом
    for req in detailed_requisites:
        gate_name = req.get('gate_username', '')
        conversion = req.get('conversion_pct', 0) or 0
        total = req.get('total_orders', 0)

        short_message = f"🏦 {gate_name}\n📊 Конверсия: {conversion:.1f}% ({total} заказов)"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"ignore:{gate_name}")]
        ])

        await context.bot.send_message(
            chat_id=user_id,
            text=short_message,
            reply_markup=keyboard
        )

    logger.info(f"Детальный список отправлен пользователю {user_id} ({len(detailed_requisites)} реквизитов)")


async def post_init(application: Application):
    """Настраивает периодическую проверку после инициализации"""
    job_queue = application.job_queue

    # Первая проверка через 1 минуту после запуска
    job_queue.run_once(check_and_alert_all, when=60)

    # Периодическая проверка каждые N минут
    interval_seconds = CHECK_INTERVAL_MINUTES * 60
    job_queue.run_repeating(
        check_and_alert_all,
        interval=interval_seconds,
        first=interval_seconds
    )

    logger.info(f"Настроена автоматическая проверка каждые {CHECK_INTERVAL_MINUTES} мин.")

    # Автоматическая очистка старых алертов раз в неделю
    async def cleanup_old_alerts(context):
        """Периодическая очистка старых алертов"""
        try:
            deleted = database.clean_old_alerts(days=ALERT_HISTORY_RETENTION_DAYS)
            logger.info(f"🧹 Автоочистка: удалено {deleted} старых алертов (>{ALERT_HISTORY_RETENTION_DAYS} дней)")
        except Exception as e:
            logger.error(f"Ошибка автоочистки алертов: {e}")

    # Очистка раз в неделю (604800 секунд), первый запуск через час
    job_queue.run_repeating(
        cleanup_old_alerts,
        interval=604800,  # 7 дней
        first=3600  # Через час после запуска
    )

    logger.info(f"Настроена автоочистка алертов старше {ALERT_HISTORY_RETENTION_DAYS} дней (раз в неделю)")


def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return

    logger.info("Запуск RequisitesMonitor бота...")

    # Инициализируем базу данных для игнорируемых реквизитов
    try:
        logger.info("Инициализация базы данных...")
        database.init_database()
        logger.info("✅ База данных инициализирована успешно")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации базы данных: {e}")
        return

    # Проверяем подключение к Metabase
    if not test_connection():
        logger.error("Не удалось подключиться к Metabase!")
        return

    logger.info(f"Минимальная конверсия: {MIN_CONVERSION_PCT}%")
    logger.info(f"Минимум транзакций: {MIN_ATTEMPTS}")
    logger.info(f"Интервал проверки: {CHECK_INTERVAL_MINUTES} мин.")
    logger.info(f"Админы: {ADMIN_IDS}")

    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(handle_ignore_callback, pattern="^ignore:"))
    application.add_handler(CallbackQueryHandler(handle_comment_callback, pattern="^comment:"))
    application.add_handler(CallbackQueryHandler(handle_show_details_callback, pattern="^show_details$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Настраиваем периодическую проверку
    application.post_init = post_init

    # Запускаем бота
    logger.info("✅ Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
