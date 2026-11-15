import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "processinghub.db")

FREE_DAILY_LIMIT = 5
PRO_PRICE_STARS = 250
PRO_DURATION_DAYS = 30

BIN_API_URL = "https://lookup.binlist.net/"
BIN_API_TIMEOUT = 10

NEWS_CACHE_TTL = 3600
DATA_CACHE_TTL = 86400

import pathlib
DATA_DIR = pathlib.Path(__file__).parent / "data"
