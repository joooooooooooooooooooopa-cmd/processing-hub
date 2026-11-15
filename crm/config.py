"""
Configuration for Merchant CRM
"""
import os
import hmac
import hashlib
import base64
import tempfile
from dotenv import load_dotenv

load_dotenv()


def get_session_path() -> str:
    """Return path to Telethon session file.
    On Railway: reassemble from SESSION_B64_1..N env vars into a temp file.
    Locally: use the file on disk.
    """
    parts = []
    i = 1
    while True:
        val = os.getenv(f"SESSION_B64_{i}")
        if not val:
            break
        parts.append(val)
        i += 1

    if parts:
        data = base64.b64decode("".join(parts))
        tmp = tempfile.NamedTemporaryFile(suffix=".session", delete=False)
        tmp.write(data)
        tmp.flush()
        tmp.close()
        return tmp.name.replace(".session", "")

    return "merchant_crm_session"

# ============ TELEGRAM BOT ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Admin users who can access the bot
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

# Alert group chat ID — bot should ignore all messages in this group
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "0"))

# Secret access key (user must send this to unlock the bot)
ACCESS_KEY = os.getenv("ACCESS_KEY", "")

# Secret for hashing keys/passwords (HMAC-SHA256)
# Без секрета хэши ключей предсказуемы, поэтому не стартуем с дефолтом
PASSWORD_SECRET = os.getenv("PASSWORD_SECRET", "")
if not PASSWORD_SECRET:
    raise RuntimeError("PASSWORD_SECRET is not set")

def hash_key(value: str) -> str:
    """HMAC-SHA256 hash for keys/passwords. Without PASSWORD_SECRET, hashes are useless."""
    return hmac.new(PASSWORD_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

# File to store access keys
KEYS_FILE = os.getenv("KEYS_FILE", "access_keys.json")

# ============ TELEGRAM USERBOT (for reading chats) ============
# Get these from https://my.telegram.org
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")  # +79991234567

# ============ OPENAI ============
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

# ============ DATABASE ============
# Для локальной разработки - SQLite
DB_PATH = os.getenv("DB_PATH", "merchants.db")

# Для Railway - PostgreSQL (автоматически предоставляется Railway)
# Формат: postgresql://user:password@host:port/database
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Определяем тип БД
USE_POSTGRES = bool(DATABASE_URL)

# ============ MONITORING SETTINGS ============
# How often to scan chats (seconds)
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# Maximum messages to process per scan
MAX_MESSAGES_PER_SCAN = int(os.getenv("MAX_MESSAGES_PER_SCAN", "100"))

# ============ GROUP TYPES ============
# Define group types for categorization
GROUP_TYPES = {
    "merchant": "Чаты с мерчантами",
    "provider": "Чаты с провайдерами",
    "traffic": "Запросы трафика",
    "internal": "Внутренние чаты",
    "other": "Прочие"
}

# ============ MERCHANT STATUSES ============
STATUSES = [
    "unknown",      # Неизвестно
    "new",          # Новый
    "negotiation",  # Переговоры
    "integration",  # Интеграция
    "testing",      # Тестирование
    "active",       # В работе
    "paused",       # На паузе
    "problem",      # Проблемы
    "disconnected", # Отключен
]

INTEGRATION_STATUSES = [
    "unknown",
    "request",      # Заявка
    "docs",         # Документы
    "tech",         # Техническая интеграция
    "testing",      # Тестирование
    "completed",    # Завершена
]

MOODS = [
    "unknown",
    "loyal",        # Лояльный
    "neutral",      # Нейтральный
    "difficult",    # Сложный
    "aggressive",   # Агрессивный
]

RATE_FLEXIBILITY = [
    "unknown",
    "flexible",     # Готов снизить
    "negotiable",   # Можно договориться
    "firm",         # Твёрдо стоит
]

# ============ METABASE ============
METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL", "")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "")

# Metabase Question IDs
METABASE_QUESTIONS = {
    "merchants_report": 69,      # Отчет по мерчантам
    "rates_by_method": 72,       # Ставки по методам
    "conversion_requisites": 55, # Конверсия в реквизиты
    "conversion_payment": 56,    # Конверсия в оплату
    "volumes_by_method": 43,     # Объемы по методам
    "conversion_today": 76,      # Конверсия за сегодня (по мерчантам + итого)
    "conversion_by_method": 77,  # Конверсия по методам оплаты
    "hourly_stats": 78,          # Почасовая статистика
    "stats_by_bank": 79,         # Статистика по банкам
    "compare_yesterday": 80,     # Сравнение с вчера
    "canceled_analysis": 81,     # Анализ отмен
    "main_dashboard": 82,        # Главный дашборд
    "weekly_stats": 83,          # Статистика за неделю
    "weekly_by_day": 84,         # По дням за неделю
    "monthly_stats": 85,         # Статистика за месяц
    "unpaid_orders": 95,         # Неоплаченные заявки по мерчантам
    "bad_clients": 97,           # Плохие пользователи по client_id (ВРЕМЕННЫЙ ID - ОБНОВИТЬ ПОСЛЕ СОЗДАНИЯ ВОПРОСА)
    "hourly_by_merchant": 255,   # Почасовая конверсия по мерчантам (сегодня)
    "conv_by_merchant_method": 256,  # Конверсия по мерчант+метод (PG, сегодня)
}

# ============ MINI APP ============
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

# ============ ALERTS ============
ALERT_THRESHOLDS = {
    "conversion_drop_percent": 20,  # Алерт если конверсия упала на X%
    "cancellation_rate_percent": 30,  # Алерт если отмен больше X%
    "min_orders_for_alert": 10,  # Минимум заявок для алерта
}
