import os

# Для Railway берём из переменных окружения, иначе локальные значения
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
EXCEL_PATH = os.getenv("EXCEL_PATH", "rates.csv")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Metabase
METABASE_URL = os.getenv("METABASE_URL", "https://metabase.example.com")
METABASE_EMAIL = os.getenv("METABASE_EMAIL", "")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "")
METABASE_CARD_ID = int(os.getenv("METABASE_CARD_ID", "72"))
METABASE_UPDATE_HOURS = int(os.getenv("METABASE_UPDATE_HOURS", "6"))

ALLOWED_USER_IDS = [int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()]

ADMIN_USER_IDS = ALLOWED_USER_IDS

# Мастер ключ (берётся ТОЛЬКО из environment variable на Railway)
MASTER_KEY = os.getenv("MASTER_KEY", "")

# Путь к базе ключей
KEYS_DB = os.getenv("KEYS_DB", "keys.json")

# Google Sheet с курсами мерчей
EXCHANGE_SHEET_URL = os.getenv(
    "EXCHANGE_SHEET_URL",
    ""
)
