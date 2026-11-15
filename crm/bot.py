"""
ProcessingHub Analytics Bot v5.0
Модульная архитектура — точка входа и регистрация обработчиков.

Вся логика вынесена в handlers/:
  - utils.py        — утилиты, константы, форматирование чисел
  - keyboards.py    — построители клавиатур
  - formatters.py   — форматирование экранов и CSV-экспорт
  - jobs.py         — фоновые задачи (мониторинг, дайджест, очистка)
  - admin.py        — админ-команды (/newkey, /keys, /users, /revoke, /kickuser)
  - crm.py          — CRM: мерчанты, инциденты, inline-запросы
  - main_handlers.py — основные хендлеры (start, message, callback, document)
"""
import logging
from datetime import datetime

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, InlineQueryHandler, filters,
)
from telegram import WebAppInfo, MenuButtonWebApp

from config import BOT_TOKEN, WEBAPP_URL, ALERT_CHAT_ID
import metabase as mb

# --- Импорт из модулей ---
from handlers.utils import (
    BTN_ADD_MERCHANT, BTN_EDIT_MERCHANT, BTN_NEW_INCIDENT,
    MERCH_NAME, MERCH_STATUS, MERCH_RATE, MERCH_CONTACT, MERCH_NOTES,
    EDIT_FIND, INC_MERCHANT, INC_TYPE, INC_PRIORITY, INC_DESC, INC_DUE,
)
from handlers.main_handlers import (
    start, handle_message, handle_document, handle_callback,
    check_config, webapp_command,
)
from handlers.admin import cmd_newkey, cmd_keys, cmd_users, cmd_revoke, cmd_kickuser
from handlers.crm import (
    add_merchant_start, add_merchant_name, add_merchant_status_cb,
    add_merchant_rate, add_merchant_contact, add_merchant_notes,
    cancel_conversation,
    edit_merchant_start, edit_merchant_find,
    inc_create_start, inc_merchant_step, inc_type_cb,
    inc_priority_cb, inc_desc_step, inc_due_cb,
    handle_inline_query,
)
from handlers.jobs import (
    check_low_conversion, send_daily_digest, save_daily_conversion_job,
    check_overdue_incidents_job, cleanup_old_data_job,
    CHECK_INTERVAL, CONVERSION_THRESHOLD,
)

logger = logging.getLogger(__name__)


def main():
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  ProcessingHub Analytics v5.0")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Проверка конфигурации
    config_errors = check_config()
    if config_errors:
        for err in config_errors:
            logger.error(f"Ошибка конфигурации: {err}")
        logger.error("Проверьте файл .env и переменные окружения")
        return

    if mb.test_connection():
        logger.info("Metabase подключен")
    else:
        logger.warning("Metabase недоступен — бот запустится без аналитики")

    logger.info("Запуск бота...")

    async def post_init(application):
        if WEBAPP_URL:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=WEBAPP_URL))
            )
            logger.info(f"Кнопка меню WebApp: {WEBAPP_URL}")
        else:
            logger.info("WEBAPP_URL не задан — кнопка меню не изменена")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Filter: ignore alert group — bot only sends alerts there, no responses
    NOT_ALERT = ~filters.Chat(ALERT_CHAT_ID)

    # --- Команды ---
    app.add_handler(CommandHandler("start", start, filters=NOT_ALERT))
    app.add_handler(CommandHandler("webapp", webapp_command, filters=NOT_ALERT))
    app.add_handler(CommandHandler("newkey", cmd_newkey, filters=NOT_ALERT))
    app.add_handler(CommandHandler("keys", cmd_keys, filters=NOT_ALERT))
    app.add_handler(CommandHandler("users", cmd_users, filters=NOT_ALERT))
    app.add_handler(CommandHandler("revoke", cmd_revoke, filters=NOT_ALERT))
    app.add_handler(CommandHandler("kickuser", cmd_kickuser, filters=NOT_ALERT))

    # --- ConversationHandler: добавление мерчанта ---
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Text([BTN_ADD_MERCHANT]), add_merchant_start)],
        states={
            MERCH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_merchant_name)],
            MERCH_STATUS: [CallbackQueryHandler(add_merchant_status_cb, pattern="^mnew_status:")],
            MERCH_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_merchant_rate)],
            MERCH_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_merchant_contact)],
            MERCH_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_merchant_notes)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            MessageHandler(filters.Text(["◀️ Вернуться в меню"]), cancel_conversation),
        ],
    ))

    # --- ConversationHandler: редактирование мерчанта ---
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Text([BTN_EDIT_MERCHANT]), edit_merchant_start)],
        states={
            EDIT_FIND: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_merchant_find)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            MessageHandler(filters.Text(["◀️ Вернуться в меню"]), cancel_conversation),
        ],
    ))

    # --- ConversationHandler: создание инцидента ---
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Text([BTN_NEW_INCIDENT]), inc_create_start)],
        states={
            INC_MERCHANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, inc_merchant_step)],
            INC_TYPE: [CallbackQueryHandler(inc_type_cb, pattern="^inc_type:")],
            INC_PRIORITY: [CallbackQueryHandler(inc_priority_cb, pattern="^inc_prio:")],
            INC_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, inc_desc_step)],
            INC_DUE: [CallbackQueryHandler(inc_due_cb, pattern="^inc_due:")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            MessageHandler(filters.Text(["◀️ Вернуться в меню"]), cancel_conversation),
        ],
    ))

    # --- Загрузка файлов (экспорт чатов из Telegram Desktop) ---
    app.add_handler(MessageHandler(filters.Document.ALL & NOT_ALERT, handle_document))

    # --- Сообщения и кнопки ---
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & NOT_ALERT, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # --- Inline-режим (@bot query) ---
    app.add_handler(InlineQueryHandler(handle_inline_query))

    # --- Фоновые задачи ---
    job_queue = app.job_queue

    # Мониторинг конверсии
    job_queue.run_repeating(check_low_conversion, interval=CHECK_INTERVAL, first=60)
    logger.info(f"Мониторинг конверсии: каждые {CHECK_INTERVAL // 3600} ч (порог {CONVERSION_THRESHOLD}%)")

    # Ежедневный дайджест в 09:00 МСК (06:00 UTC)
    job_queue.run_daily(send_daily_digest, time=datetime.strptime("06:00", "%H:%M").time())
    logger.info("Дайджест: ежедневно в 09:00 МСК")

    # Сохранение конверсии за день в 23:50 МСК (20:50 UTC)
    job_queue.run_daily(save_daily_conversion_job, time=datetime.strptime("20:50", "%H:%M").time())
    logger.info("Сохранение конверсии: ежедневно в 23:50 МСК")

    # Проверка просроченных инцидентов каждые 30 мин
    job_queue.run_repeating(check_overdue_incidents_job, interval=1800, first=120)
    logger.info("Проверка дедлайнов инцидентов: каждые 30 мин")

    # Очистка старых данных в 03:00 МСК (00:00 UTC)
    job_queue.run_daily(cleanup_old_data_job, time=datetime.strptime("00:00", "%H:%M").time())
    logger.info("Очистка старых данных: ежедневно в 03:00 МСК")

    logger.info("Бот запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
