"""
Конфигурация бота мониторинга реквизитов
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Master Key
MASTER_KEY = os.getenv("MASTER_KEY", "")

# Metabase
METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL", "")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Monitoring Settings
MIN_CONVERSION_PCT = float(os.getenv("MIN_CONVERSION_PCT", "20.0"))  # Минимальная конверсия 20%
MIN_ATTEMPTS = int(os.getenv("MIN_ATTEMPTS", "10"))  # Минимум 10 транзакций для алерта
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "20"))  # Интервал проверки в минутах

# Smart Alerts Settings
SUMMARY_THRESHOLD = int(os.getenv("SUMMARY_THRESHOLD", "5"))  # Сводка при 5+ реквизитах
RECURRING_ALERT_THRESHOLD = int(os.getenv("RECURRING_ALERT_THRESHOLD", "3"))  # "Постоянная проблема" при 3+ алертах в день
CRITICAL_DROP_PERCENT = float(os.getenv("CRITICAL_DROP_PERCENT", "50.0"))  # "Резкое падение" при падении на 50%+
ALERT_HISTORY_RETENTION_DAYS = int(os.getenv("ALERT_HISTORY_RETENTION_DAYS", "30"))  # Хранить историю 30 дней
MAX_COMMENT_LENGTH = int(os.getenv("MAX_COMMENT_LENGTH", "500"))  # Максимальная длина комментария
