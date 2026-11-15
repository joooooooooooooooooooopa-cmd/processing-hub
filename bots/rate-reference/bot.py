import os
import re
import math
import json
import asyncio
import requests
import threading
import time
from datetime import datetime
import numpy as np
import pandas as pd
from typing import Optional, List, Tuple
from difflib import get_close_matches
from io import StringIO

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from openai import OpenAI

from config import BOT_TOKEN, EXCEL_PATH, ALLOWED_USER_IDS, OPENAI_API_KEY, MASTER_KEY, KEYS_DB, EXCHANGE_SHEET_URL
try:
    from config import METABASE_URL, METABASE_EMAIL, METABASE_PASSWORD, METABASE_CARD_ID, METABASE_UPDATE_HOURS
except ImportError:
    METABASE_URL = None
    METABASE_EMAIL = None
    METABASE_PASSWORD = None
    METABASE_CARD_ID = None
    METABASE_UPDATE_HOURS = 6
try:
    from config import ADMIN_USER_IDS
except Exception:
    ADMIN_USER_IDS = ALLOWED_USER_IDS


# ----------------- KEYS DATABASE -----------------
def load_keys():
    try:
        with open(KEYS_DB, 'r') as f:
            return json.load(f)
    except:
        return {"keys": [MASTER_KEY], "users": []}

def save_keys(data):
    with open(KEYS_DB, 'w') as f:
        json.dump(data, f, indent=2)

def init_keys():
    try:
        with open(KEYS_DB, 'r') as f:
            data = json.load(f)
            if MASTER_KEY not in data.get("keys", []):
                data["keys"].append(MASTER_KEY)
                save_keys(data)
    except:
        save_keys({"keys": [MASTER_KEY], "users": []})

init_keys()

# ----------------- ACCESS -----------------
def is_allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid in ALLOWED_USER_IDS:
        return True
    # Проверяем авторизацию по ключу
    data = load_keys()
    return uid in data.get("users", [])

def is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid in ADMIN_USER_IDS

def check_key(key: str) -> bool:
    data = load_keys()
    return key in data.get("keys", [])

def authorize_user(uid: int):
    data = load_keys()
    if uid not in data.get("users", []):
        data.setdefault("users", []).append(uid)
        save_keys(data)


# ----------------- IO (CSV/XLSX) -----------------
def parse_number_with_spaces(x):
    """Парсит числа с пробелами и запятой как разделителем (10,5 -> 10.5, 300 000 -> 300000)"""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    if not s or s.lower() in ['nan', 'none', '']:
        return None
    # Убираем пробелы внутри числа
    s = s.replace('\u00a0', '').replace(' ', '')
    # Заменяем запятую на точку
    s = s.replace(',', '.')
    try:
        return float(s)
    except:
        return None

def read_table(path: str) -> pd.DataFrame:
    p = path.lower()
    if p.endswith(".csv"):
        df = pd.read_csv(path, encoding="utf-8-sig", sep=",")
    else:
        df = pd.read_excel(path)

    # Маппинг колонок нового формата на старый
    column_mapping = {
        'margin_buy': 'basefee',
    }
    df = df.rename(columns=column_mapping)

    return df

def write_table(df: pd.DataFrame, path: str):
    p = path.lower()
    if p.endswith(".csv"):
        df.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(path, index=False)


# ----------------- METABASE -----------------
_metabase_session_token = None
_last_metabase_update = None

def metabase_login() -> Optional[str]:
    """Авторизация в Metabase, возвращает session token"""
    global _metabase_session_token
    if not METABASE_URL or not METABASE_EMAIL or not METABASE_PASSWORD:
        print("[Metabase] Не настроены учетные данные")
        return None
    try:
        resp = requests.post(
            f"{METABASE_URL}/api/session",
            json={"username": METABASE_EMAIL, "password": METABASE_PASSWORD},
            timeout=30
        )
        if resp.status_code == 200:
            _metabase_session_token = resp.json().get("id")
            print(f"[Metabase] Авторизация успешна")
            return _metabase_session_token
        else:
            print(f"[Metabase] Ошибка авторизации: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        print(f"[Metabase] Ошибка подключения: {e}")
        return None

def metabase_fetch_csv() -> Optional[str]:
    """Загружает CSV из Metabase карточки"""
    global _metabase_session_token
    if not METABASE_URL or not METABASE_CARD_ID:
        return None

    # Получаем токен если нет
    if not _metabase_session_token:
        if not metabase_login():
            return None

    try:
        headers = {"X-Metabase-Session": _metabase_session_token}
        resp = requests.post(
            f"{METABASE_URL}/api/card/{METABASE_CARD_ID}/query/csv",
            headers=headers,
            timeout=60
        )
        if resp.status_code == 401:
            # Токен истёк, перелогинимся
            print("[Metabase] Токен истёк, перелогиниваемся...")
            if metabase_login():
                headers = {"X-Metabase-Session": _metabase_session_token}
                resp = requests.post(
                    f"{METABASE_URL}/api/card/{METABASE_CARD_ID}/query/csv",
                    headers=headers,
                    timeout=60
                )
        if resp.status_code == 200:
            print(f"[Metabase] CSV загружен: {len(resp.text)} символов")
            return resp.text
        else:
            print(f"[Metabase] Ошибка загрузки CSV: {resp.status_code}")
            return None
    except Exception as e:
        print(f"[Metabase] Ошибка: {e}")
        return None

def update_from_metabase() -> bool:
    """Обновляет rates.csv из Metabase"""
    global _last_metabase_update
    csv_text = metabase_fetch_csv()
    if not csv_text:
        return False
    try:
        # Сохраняем CSV
        with open(EXCEL_PATH, "w", encoding="utf-8-sig") as f:
            f.write(csv_text)
        _last_metabase_update = datetime.now()
        print(f"[Metabase] Данные обновлены: {_last_metabase_update}")
        reload_data()
        return True
    except Exception as e:
        print(f"[Metabase] Ошибка сохранения: {e}")
        return False

def metabase_scheduler():
    """Фоновый поток для обновления данных каждые N часов"""
    interval = METABASE_UPDATE_HOURS * 3600  # часы в секунды
    print(f"[Metabase] Планировщик запущен: обновление каждые {METABASE_UPDATE_HOURS} часов")
    while True:
        time.sleep(interval)
        print(f"[Metabase] Запуск планового обновления...")
        update_from_metabase()

def start_metabase_scheduler():
    """Запускает планировщик в фоновом потоке"""
    if not METABASE_URL:
        print("[Metabase] Не настроен, планировщик не запущен")
        return
    # Первое обновление сразу при старте
    print("[Metabase] Первичная загрузка данных...")
    update_from_metabase()
    # Запуск фонового потока
    thread = threading.Thread(target=metabase_scheduler, daemon=True)
    thread.start()


# ----------------- EXCHANGE RATES (Google Sheets) -----------------
EXCHANGE_DF = None
EXCHANGE_MERCHANTS = []
_last_exchange_update = None

def load_exchange_rates():
    """Загружает курсы мерчей из Google Sheets"""
    global EXCHANGE_DF, EXCHANGE_MERCHANTS, _last_exchange_update
    try:
        resp = requests.get(EXCHANGE_SHEET_URL, timeout=30)
        resp.encoding = "utf-8"
        df = pd.read_csv(StringIO(resp.text))
        # Нормализуем названия колонок
        df.columns = [c.strip() for c in df.columns]
        # Маппим по позиции как fallback (Merchant Name, Echange, Наценка, Comment)
        if len(df.columns) >= 4:
            positional = {
                df.columns[0]: "merchant_name",
                df.columns[1]: "exchange",
                df.columns[2]: "markup",
                df.columns[3]: "comment",
            }
        else:
            positional = {}
        # Пробуем по имени, fallback по позиции
        col_map = {}
        for c in df.columns:
            cl = c.lower().strip()
            if cl in ("merchant name", "merchant_name", "name"):
                col_map[c] = "merchant_name"
            elif cl in ("echange", "exchange", "биржа"):
                col_map[c] = "exchange"
            elif cl in ("наценка", "markup") or "ценк" in cl:
                col_map[c] = "markup"
            elif cl in ("comment", "комментарий") or "comment" in cl:
                col_map[c] = "comment"
        # Fallback: если не нашли merchant_name по имени, используем позицию
        if "merchant_name" not in col_map.values() and positional:
            col_map = positional
        df = df.rename(columns=col_map)

        if "merchant_name" not in df.columns:
            print("[Exchange] Колонка merchant_name не найдена!")
            return False

        df["merchant_name"] = df["merchant_name"].astype(str).str.strip()
        df["merchant_key"] = df["merchant_name"].map(strip_prefixes)
        df = df[df["merchant_name"].str.len() > 0].copy()

        for col in ["exchange", "markup", "comment"]:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].astype(str).replace("nan", "").str.strip()

        EXCHANGE_DF = df
        EXCHANGE_MERCHANTS = sorted(df["merchant_key"].unique().tolist())
        _last_exchange_update = datetime.now()
        print(f"[Exchange] Загружено {len(df)} записей ({_last_exchange_update})")
        return True
    except Exception as e:
        print(f"[Exchange] Ошибка загрузки: {e}")
        return False


def find_exchange_merchants(text: str) -> list:
    """Ищет мерчантов в таблице курсов (fuzzy)"""
    if EXCHANGE_DF is None or EXCHANGE_DF.empty:
        return []
    t_key = strip_prefixes(text)
    if not t_key:
        return []

    # Exact match
    exact = EXCHANGE_DF[EXCHANGE_DF["merchant_key"] == t_key]
    if not exact.empty:
        return exact["merchant_name"].unique().tolist()

    # Contains
    contains = EXCHANGE_DF[EXCHANGE_DF["merchant_key"].str.contains(t_key, na=False)]
    if not contains.empty:
        return contains["merchant_name"].unique().tolist()[:10]

    # Fuzzy
    close = get_close_matches(t_key, EXCHANGE_MERCHANTS, n=5, cutoff=0.5)
    if close:
        out = []
        for k in close:
            out.extend(EXCHANGE_DF[EXCHANGE_DF["merchant_key"] == k]["merchant_name"].unique().tolist())
        return list(dict.fromkeys(out))[:10]
    return []


def format_exchange_info(merchants: list) -> str:
    """Формирует ответ с курсами мерчей"""
    if not merchants:
        return "❌ Мерч не найден в таблице курсов"

    lines = [
        "<b>💱 Курсы мерчей</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for name in merchants:
        rows = EXCHANGE_DF[EXCHANGE_DF["merchant_name"] == name]
        for _, r in rows.iterrows():
            exchange = r.get("exchange", "")
            markup = r.get("markup", "")
            comment = r.get("comment", "")

            lines.append(f"🏪 <b>{name}</b>")
            if exchange:
                lines.append(f"    📊 Биржа: <b>{exchange}</b>")
            if markup:
                lines.append(f"    📈 Наценка: <b>{markup}</b>")
            if comment:
                lines.append(f"    💬 {comment}")
            lines.append("")

    if _last_exchange_update:
        lines.append(f"<i>Обновлено: {_last_exchange_update.strftime('%d.%m.%Y %H:%M')}</i>")

    return "\n".join(lines).rstrip()


def list_all_exchanges() -> str:
    """Список всех мерчей и их курсов"""
    if EXCHANGE_DF is None or EXCHANGE_DF.empty:
        return "📭 Таблица курсов пуста"

    lines = [
        "<b>💱 Все курсы мерчей</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for _, r in EXCHANGE_DF.sort_values("merchant_key").iterrows():
        name = r["merchant_name"]
        exchange = r.get("exchange", "")
        markup = r.get("markup", "")
        comment = r.get("comment", "")

        info_parts = []
        if exchange:
            info_parts.append(exchange)
        if markup:
            info_parts.append(f"+{markup}" if not markup.startswith("+") else markup)
        info_str = " · ".join(info_parts) if info_parts else "—"

        line = f"<b>{name}</b>: {info_str}"
        if comment:
            line += f"  <i>({comment})</i>"
        lines.append(line)

    return "\n".join(lines)




# ----------------- UI -----------------
# Главное меню
BTN_RATE = "🔍 Поиск ставки"
BTN_MERCH_ALL = "🏪 Мерч"
BTN_METHOD_ALL = "💳 Метод"
BTN_LIMITS = "📊 Лимиты"
BTN_BELOW = "📉 Ниже %"
BTN_AIHELP = "🤖 AI"
BTN_UPDATE = "🔄 Обновить"
BTN_EDITOR = "⚙️ Редактор"
BTN_BROADCAST = "📢 Рассылка"
BTN_BACK = "⬅️ Назад"
BTN_CANCEL = "🏠 Меню"
BTN_EXCHANGE = "💱 Курсы"
BTN_WEBAPP = "📱 App"

# Подменю лимитов
BTN_L_HIGH = "🔼 Хай 10K+"
BTN_L_MIN = "🔽 Мин до 10K"
BTN_L_MICRO = "💎 Микрочек"
BTN_L_HIGH_M = "🔼 Хай (другой)"
BTN_L_MIN_M = "🔽 Мин (другой)"
BTN_L_MICRO_M = "💎 Микрочек (другой)"

# Подменю редактора
BTN_E_FEE = "💰 Fee"
BTN_E_BASE = "📋 Basefee"
BTN_E_RELOAD = "🔄 Обновить"
BTN_E_METABASE = "☁️ Metabase"
BTN_E_REINDEX = "🧠 AI индекс"

MODE_NONE = "none"
MODE_RATE = "rate"
MODE_MERCH_ALL = "merch_all"
MODE_METHOD_ALL = "method_all"
MODE_LIMITS_MENU = "limits_menu"
MODE_LIMITS_METHOD_PICK = "limits_method_pick"
MODE_BELOW = "below"
MODE_AI = "ai"
MODE_EDITOR_MENU = "editor_menu"
MODE_EDIT_FEE = "edit_fee"
MODE_EDIT_BASE = "edit_base"
MODE_EXCHANGE = "exchange"

# рассылка
MODE_BCAST_CHATS = "bcast_chats"
MODE_BCAST_TEXT = "bcast_text"


def kb_main(is_admin_user: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_RATE), KeyboardButton(BTN_EXCHANGE), KeyboardButton(BTN_WEBAPP)],
        [KeyboardButton(BTN_MERCH_ALL), KeyboardButton(BTN_METHOD_ALL), KeyboardButton(BTN_LIMITS)],
        [KeyboardButton(BTN_BELOW), KeyboardButton(BTN_AIHELP), KeyboardButton(BTN_UPDATE)],
    ]
    if is_admin_user:
        rows.append([KeyboardButton(BTN_EDITOR), KeyboardButton(BTN_BROADCAST)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_limits() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_L_HIGH), KeyboardButton(BTN_L_MIN), KeyboardButton(BTN_L_MICRO)],
            [KeyboardButton(BTN_L_HIGH_M), KeyboardButton(BTN_L_MIN_M), KeyboardButton(BTN_L_MICRO_M)],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True
    )

def kb_editor() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_E_FEE), KeyboardButton(BTN_E_BASE)],
            [KeyboardButton(BTN_E_RELOAD), KeyboardButton(BTN_E_METABASE), KeyboardButton(BTN_E_REINDEX)],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True
    )


# ----------------- UTILS -----------------
def norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s

def strip_prefixes(s: str) -> str:
    s = norm(s)
    s = re.sub(r"^(merchant|provider)\s+", "", s)
    return s

def to_num(x):
    try:
        if x is None:
            return None
        if isinstance(x, float) and math.isnan(x):
            return None
        return float(x)
    except Exception:
        return None

def fmt_amount(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{int(x):,}".replace(",", " ")

def fmt_rate(x) -> str:
    if x is None:
        return "—"
    try:
        f = float(x)
        if f.is_integer():
            return str(int(f))
        return str(f).rstrip("0").rstrip(".")
    except Exception:
        return str(x)

def parse_amount(text: str) -> Optional[float]:
    nums = re.findall(r"(\d[\d\s.,]*)", text)
    if not nums:
        return None
    raw = nums[-1].replace(" ", "").replace(",", "").replace(".", "")
    try:
        return float(raw)
    except Exception:
        return None

async def send_long(update: Update, text: str, chunk: int = 3500):
    parts = []
    while len(text) > chunk:
        cut = text.rfind("\n", 0, chunk)
        if cut == -1:
            cut = chunk
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    for p in parts:
        await update.message.reply_text(p, parse_mode="HTML")


# ----------------- DATA -----------------
DF = None
MERCHANT_KEYS = []
METHODS = []

def reload_data():
    global DF, MERCHANT_KEYS, METHODS
    df = read_table(EXCEL_PATH)
    for c in ["name", "payment_type", "amount_gt", "amount_lt", "fee", "basefee"]:
        if c not in df.columns:
            df[c] = np.nan

    df["name"] = df["name"].astype(str).fillna("").map(lambda x: x.strip())
    df["merchant"] = df["name"]
    df["merchant_norm_full"] = df["merchant"].map(norm)
    df["merchant_key"] = df["merchant"].map(strip_prefixes)

    # Используем parse_number_with_spaces для чисел с пробелами и запятыми
    df["basefee"] = df["basefee"].apply(parse_number_with_spaces)
    df["fee"] = df["fee"].apply(parse_number_with_spaces)

    df["payment_type"] = df["payment_type"].astype(str)
    df.loc[df["payment_type"].str.lower().isin(["nan", "none"]), "payment_type"] = ""
    df["payment_type_norm"] = df["payment_type"].map(norm)

    # Используем parse_number_with_spaces для лимитов
    df["amount_gt"] = df["amount_gt"].apply(parse_number_with_spaces)
    df["amount_lt"] = df["amount_lt"].apply(parse_number_with_spaces)

    df = df[~df["merchant_key"].str.fullmatch(r"\d+", na=False)].copy()

    DF = df
    MERCHANT_KEYS = sorted([m for m in DF["merchant_key"].unique().tolist() if m])
    METHODS = sorted([m for m in DF["payment_type_norm"].unique().tolist() if m])

reload_data()
load_exchange_rates()


# ----------------- SEARCH -----------------
def find_merchants(text: str) -> List[str]:
    t_full = norm(text)
    t_key = strip_prefixes(text)

    t_full = re.sub(r"\b(ставка|ставки|какая|какой|на|у|мерч|мерча|merchant|rate)\b", " ", t_full)
    t_key = re.sub(r"\b(ставка|ставки|какая|какой|на|у|мерч|мерча|merchant|rate)\b", " ", t_key)
    t_full = norm(t_full)
    t_key = strip_prefixes(t_key)

    if not t_key and not t_full:
        return []

    exact_key = DF[DF["merchant_key"] == t_key]["merchant"].unique().tolist()
    if exact_key:
        return exact_key

    exact_full = DF[DF["merchant_norm_full"] == t_full]["merchant"].unique().tolist()
    if exact_full:
        return exact_full

    close = get_close_matches(t_key, MERCHANT_KEYS, n=5, cutoff=0.6)
    if close:
        out = []
        for k in close:
            out.extend(DF[DF["merchant_key"] == k]["merchant"].unique().tolist())
        return list(dict.fromkeys(out))
    return []

def normalize_method_query(q: str) -> str:
    q = norm(q)
    if q == "альфа":
        return "alfa"
    if q == "сбп":
        return "sbp"
    return q

def match_methods(q: str) -> List[str]:
    q = normalize_method_query(q)
    if not q:
        return []
    if q in ["alfa", "alpha"]:
        return [m for m in METHODS if ("alfa" in m) or ("альфа" in m)]
    if q in ["sbp"]:
        return [m for m in METHODS if ("sbp" in m) or ("сбп" in m)]
    if q in ["c2c"]:
        return [m for m in METHODS if "c2c" in m]
    direct = [m for m in METHODS if q in m]
    if direct:
        return direct
    return get_close_matches(q, METHODS, n=8, cutoff=0.6)

def choose_payment_type(text: str, merchant: str) -> Optional[str]:
    t = norm(text)
    rows = DF[DF["merchant"] == merchant]
    methods = sorted([m for m in rows["payment_type_norm"].unique().tolist() if m])
    for m in methods:
        if m and m in t:
            return m
    return None


# ----------------- LOGIC -----------------
def pick_rate(merchant: str, payment_type_norm: Optional[str], amount: Optional[float]):
    rows = DF[DF["merchant"] == merchant].copy()
    base_candidates = rows["basefee"].dropna().tolist()
    basefee = base_candidates[0] if base_candidates else None

    if not payment_type_norm:
        return {"rate": basefee, "source": "basefee", "payment_type": None, "range": None}

    mrows = rows[rows["payment_type_norm"] == payment_type_norm].copy()
    if mrows.empty:
        return {"rate": basefee, "source": "basefee", "payment_type": payment_type_norm, "range": None}

    if amount is None:
        out = []
        for _, r in mrows.iterrows():
            if r["fee"] is None:
                continue
            out.append((r["amount_gt"], r["amount_lt"], r["fee"]))
        return {"rate": basefee, "source": "need_amount", "payment_type": payment_type_norm, "ranges": out[:20]}

    def in_range(r):
        gt = r["amount_gt"]
        lt = r["amount_lt"]
        ok1 = True if (gt is None or (isinstance(gt, float) and math.isnan(gt))) else (amount >= gt)
        ok2 = True if (lt is None or (isinstance(lt, float) and math.isnan(lt))) else (amount <= lt)
        return ok1 and ok2

    candidates = mrows[mrows.apply(in_range, axis=1)].copy()
    if candidates.empty:
        return {"rate": basefee, "source": "basefee", "payment_type": payment_type_norm, "range": None}

    best = candidates.iloc[0]
    fee = best["fee"]
    if fee is None:
        return {"rate": basefee, "source": "basefee", "payment_type": payment_type_norm, "range": None}

    return {"rate": fee, "source": "fee", "payment_type": payment_type_norm, "range": (best["amount_gt"], best["amount_lt"])}

def list_all_rates_for_merchant(merchant: str) -> str:
    rows = DF[DF["merchant"] == merchant].copy()
    base_candidates = rows["basefee"].dropna().tolist()
    basefee = base_candidates[0] if base_candidates else None

    lines = [
        f"<b>🏪 {merchant}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📌 Basefee: <b>{fmt_rate(basefee)}%</b>"
    ]

    # Сначала показываем ставки без метода (общие)
    no_method = rows[rows["payment_type_norm"].astype(str).str.len() == 0].copy()
    no_method_fee = no_method[no_method["fee"].notna()].copy()
    if not no_method_fee.empty:
        lines.append("")
        lines.append("📋 <b>Общие ставки:</b>")
        no_method_fee = no_method_fee.sort_values(by=["amount_gt", "amount_lt"], na_position="first")
        for _, r in no_method_fee.iterrows():
            gt = r["amount_gt"]
            lt = r["amount_lt"]
            fee = r["fee"]
            gt_txt = fmt_amount(gt)
            lt_txt = fmt_amount(lt)
            lines.append(f"    {gt_txt} – {lt_txt} → <b>{fmt_rate(fee)}%</b>")

    # Потом по методам
    mrows = rows[rows["payment_type_norm"].astype(str).str.len() > 0].copy()
    if mrows.empty and no_method_fee.empty:
        lines.append("")
        lines.append("<i>Методы не настроены</i>")
        return "\n".join(lines)

    if not mrows.empty:
        lines.append("")
        for method in sorted(mrows["payment_type_norm"].unique().tolist()):
            sub = mrows[mrows["payment_type_norm"] == method].copy()
            sub_fee = sub[sub["fee"].notna()].copy()
            if sub_fee.empty:
                lines.append(f"💳 <b>{method}</b>: basefee {fmt_rate(basefee)}%")
                continue
            lines.append(f"💳 <b>{method}</b>:")
            sub_fee = sub_fee.sort_values(by=["amount_gt", "amount_lt"], na_position="first")
            for _, r in sub_fee.iterrows():
                gt = r["amount_gt"]
                lt = r["amount_lt"]
                fee = r["fee"]
                gt_txt = fmt_amount(gt)
                lt_txt = fmt_amount(lt)
                lines.append(f"    {gt_txt} – {lt_txt} → <b>{fmt_rate(fee)}%</b>")
    return "\n".join(lines)

def list_all_rates_for_method(q: str) -> str:
    matched = match_methods(q)
    if not matched:
        return f"❌ Метод не найден: <b>{q}</b>"
    rows_all = DF[DF["payment_type_norm"].isin(matched)].copy()
    if rows_all.empty:
        return f"📭 По методу <b>{q}</b> ставок нет"

    lines = [
        f"<b>💳 Метод: {q.upper()}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    for merchant in sorted(rows_all["merchant"].unique().tolist(), key=lambda x: strip_prefixes(x)):
        mr = rows_all[rows_all["merchant"] == merchant].copy()
        sub_fee = mr[mr["fee"].notna()].copy()

        # Получаем basefee для мерча
        base_candidates = DF[DF["merchant"] == merchant]["basefee"].dropna().tolist()
        basefee = base_candidates[0] if base_candidates else None

        if sub_fee.empty:
            # Если нет fee, показываем basefee
            if basefee is not None:
                lines.append(f"🏪 <b>{merchant}</b>")
                lines.append(f"    basefee → <b>{fmt_rate(basefee)}%</b>")
                lines.append("")
            continue

        lines.append(f"🏪 <b>{merchant}</b>")
        sub_fee = sub_fee.sort_values(by=["fee", "amount_gt", "amount_lt"], na_position="first")
        for _, r in sub_fee.iterrows():
            gt = r["amount_gt"]
            lt = r["amount_lt"]
            fee = r["fee"]
            gt_txt = fmt_amount(gt)
            lt_txt = fmt_amount(lt)
            lines.append(f"    {gt_txt} – {lt_txt} → <b>{fmt_rate(fee)}%</b>")
        lines.append("")
    return "\n".join(lines).rstrip()

def band_row_mask(df: pd.DataFrame, band: str):
    lt = df["amount_lt"]
    gt = df["amount_gt"]
    if band == "high":
        # 10000+: диапазон включает суммы >= 10000
        return (lt.isna() | (lt >= 10000))
    if band == "micro":
        # 100-1000: ставки где диапазон пересекается с 100-1000
        # gt <= 1000 (начало диапазона не выше 1000)
        # lt >= 100 (конец диапазона не ниже 100)
        # lt <= 1000 (конец диапазона до 1000, чтобы не захватывать большие)
        gt_ok = gt.notna() & (gt <= 1000)
        lt_ok = lt.notna() & (lt >= 100) & (lt <= 1000)
        return (gt_ok & lt_ok)
    # min: до 10000
    return (lt.notna() & (lt <= 10000))

def list_rates_for_band(band: str, method_query: Optional[str]) -> str:
    if method_query:
        matched_methods = match_methods(method_query)
        title_methods = method_query.upper()
    else:
        matched_methods = match_methods("sbp") + match_methods("c2c")
        seen = set()
        matched_methods = [m for m in matched_methods if not (m in seen or seen.add(m))]
        title_methods = "SBP + C2C"

    if band == "high":
        band_icon = "🔼"
        band_title = "10 000+"
    elif band == "micro":
        band_icon = "💎"
        band_title = "Микрочек 100-1000"
    else:
        band_icon = "🔽"
        band_title = "до 10 000"

    # Фильтруем по методам
    if matched_methods:
        rows = DF[DF["payment_type_norm"].isin(matched_methods)].copy()
    else:
        rows = DF.copy()

    # Для микрочека НЕ добавляем пустые методы - только конкретные SBP/C2C
    if band != "micro":
        empty_method_rows = DF[DF["payment_type_norm"].astype(str).str.len() == 0].copy()
        if not empty_method_rows.empty:
            rows = pd.concat([rows, empty_method_rows]).drop_duplicates()

    rows = rows[band_row_mask(rows, band)].copy()

    if rows.empty:
        return f"{band_icon} {band_title}: ставок не найдено"

    lines = [
        f"<b>{band_icon} {band_title} · {title_methods}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    for merchant in sorted(rows["merchant"].unique().tolist(), key=lambda x: strip_prefixes(x)):
        mr = rows[rows["merchant"] == merchant].copy()
        sub_fee = mr[mr["fee"].notna()].copy()
        if sub_fee.empty:
            continue
        lines.append(f"🏪 <b>{merchant}</b>")
        sub_fee = sub_fee.sort_values(by=["payment_type_norm", "amount_gt", "amount_lt"], na_position="first")
        for _, r in sub_fee.iterrows():
            gt = r["amount_gt"]
            lt = r["amount_lt"]
            method_name = r['payment_type_norm'] if r['payment_type_norm'] else "общая"
            gt_txt = fmt_amount(gt)
            lt_txt = fmt_amount(lt)
            lines.append(f"    {method_name} · {gt_txt} – {lt_txt} → <b>{fmt_rate(r['fee'])}%</b>")
        lines.append("")
    return "\n".join(lines).rstrip()

def parse_threshold_and_method(s: str) -> Optional[Tuple[float, str]]:
    s = norm(s)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%?\s+([a-zа-я0-9_\-\/]+)", s)
    if not m:
        return None
    thr = float(m.group(1).replace(",", "."))
    method = m.group(2)
    return thr, method

def template_raise(thr: float, method_query: str) -> str:
    matched = match_methods(method_query)
    if not matched:
        return f"❌ Метод не найден: <b>{method_query}</b>"
    rows_all = DF[(DF["payment_type_norm"].isin(matched)) & (DF["fee"].notna())].copy()
    if rows_all.empty:
        return f"📭 По методу <b>{method_query}</b> нет fee-ставок"

    best = []
    for merchant in sorted(rows_all["merchant"].unique().tolist(), key=lambda x: strip_prefixes(x)):
        mr = rows_all[rows_all["merchant"] == merchant].copy().sort_values(
            by=["fee", "amount_gt", "amount_lt"], na_position="first"
        )
        r = mr.iloc[0]
        fee = float(r["fee"])
        if fee < thr:
            best.append((fee, merchant, r["payment_type_norm"], r["amount_gt"], r["amount_lt"]))

    if not best:
        return f"✅ Нет мерчей с fee ниже <b>{fmt_rate(thr)}%</b> по методу <b>{method_query}</b>"

    best.sort(key=lambda x: x[0])
    lines = [
        f"<b>📉 Мерчи ниже {fmt_rate(thr)}% · {method_query.upper()}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        "",
        f"<i>Рекомендация: поднять до {fmt_rate(thr)}%</i>",
        ""
    ]
    for fee, merchant, mth, gt, lt in best:
        gt_txt = fmt_amount(gt)
        lt_txt = fmt_amount(lt)
        lines.append(f"🏪 <b>{merchant}</b>")
        lines.append(f"    {mth} · {gt_txt} – {lt_txt}")
        lines.append(f"    Сейчас: <b>{fmt_rate(fee)}%</b> → <b>{fmt_rate(thr)}%</b>")
        lines.append("")
    return "\n".join(lines).rstrip()


# ----------------- danhelp -----------------
DAN_MODEL = "gpt-4.1-mini"
EMBED_MODEL = "text-embedding-3-small"
INDEX_VECS = "rates_index.npz"
INDEX_META = "rates_meta.json"

_dan_client = None
_index_vecs = None
_index_meta = None

def load_dan_index():
    global _index_vecs, _index_meta, _dan_client
    try:
        _dan_client = OpenAI(api_key=OPENAI_API_KEY)
        _index_vecs = np.load(INDEX_VECS)["vecs"].astype(np.float32)
        with open(INDEX_META, "r", encoding="utf-8") as f:
            _index_meta = json.load(f)
    except Exception:
        _index_vecs = None
        _index_meta = None

def dan_ready() -> bool:
    return _index_vecs is not None and _index_meta is not None and _dan_client is not None

def embed_text(text: str) -> np.ndarray:
    resp = _dan_client.embeddings.create(model=EMBED_MODEL, input=[text])
    v = np.array(resp.data[0].embedding, dtype=np.float32)
    n = np.linalg.norm(v)
    return v if n == 0 else (v / n)

def retrieve_context(question: str, top_k: int = 18) -> List[str]:
    qv = embed_text(question)
    sims = _index_vecs @ qv
    idx = np.argsort(-sims)[:top_k]
    return [_index_meta[int(i)]["text"] for i in idx]

def ai_answer(question: str) -> str:
    if not dan_ready():
        return "danhelp недоступен: нет индекса. Запусти ai_index.py или обнови индекс в редакторе."
    ctx = retrieve_context(question, top_k=18)
    context_block = "\n".join(f"- {c}" for c in ctx)
    system = (
        "Ты помощник по ставкам. Отвечай ТОЛЬКО на основе контекста (строки из таблицы).\n"
        "Если ответа нет — скажи: 'В таблице нет данных по этому запросу'.\n"
        "Коротко, по делу, на русском."
    )
    user = f"Контекст:\n{context_block}\n\nВопрос: {question}\nОтвет:"
    resp = _dan_client.chat.completions.create(
        model=DAN_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content.strip()

def build_index_files():
    df = read_table(EXCEL_PATH)
    for c in ["name", "payment_type", "amount_gt", "amount_lt", "fee", "basefee"]:
        if c not in df.columns:
            df[c] = np.nan

    def row_to_text(r) -> str:
        merchant = str(r.get("name", "")).strip()
        method = str(r.get("payment_type", "")).strip()
        gt = to_num(r.get("amount_gt"))
        lt = to_num(r.get("amount_lt"))
        fee = to_num(r.get("fee"))
        basefee = to_num(r.get("basefee"))
        parts = [f"merchant={merchant}"]
        if method and method.lower() not in ("nan", "none"):
            parts.append(f"method={method}")
        if gt is not None:
            parts.append(f"amount_gt={int(gt)}")
        if lt is not None:
            parts.append(f"amount_lt={int(lt)}")
        if fee is not None:
            parts.append(f"fee={fee}")
        if basefee is not None:
            parts.append(f"basefee={basefee}")
        return " | ".join(parts)

    texts, meta = [], []
    for _, r in df.iterrows():
        t = row_to_text(r)
        if "merchant=" in t and len(t) > 10:
            texts.append(t)
            meta.append({"text": t})

    client = OpenAI(api_key=OPENAI_API_KEY)
    vecs = []
    batch = 128
    for i in range(0, len(texts), batch):
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts[i:i+batch])
        vecs.extend([d.embedding for d in resp.data])

    arr = np.array(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1
    arr = arr / norms

    np.savez(INDEX_VECS, vecs=arr)
    with open(INDEX_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


# ----------------- EDITOR (pandas) -----------------
def _parse_nullable_int(token: str) -> Optional[int]:
    token = token.strip()
    if token in ["-", "—", "none", "null", ""]:
        return None
    return int(float(token.replace(",", ".")))

def _parse_float(token: str) -> float:
    return float(token.strip().replace(",", "."))

def set_fee_line(s: str) -> str:
    parts = s.split()
    if len(parts) < 5:
        return "❌ Формат: МЕРЧ МЕТОД ОТ ДО FEE\n\nПример:\nMerchantA sbp 1000 9999 9.5\nMerchantA c2c - - 10"
    fee_val = _parse_float(parts[-1])
    lt = _parse_nullable_int(parts[-2])
    gt = _parse_nullable_int(parts[-3])
    method_q = parts[-4]
    merchant_q = " ".join(parts[:-4])

    merch_list = find_merchants(merchant_q)
    if not merch_list:
        return "❌ Мерч не найден"
    merch = merch_list[0]

    mm = match_methods(method_q)
    if not mm:
        return "❌ Метод не найден"
    method_norm = mm[0]

    sub = DF[(DF["merchant"] == merch) & (DF["payment_type_norm"] == method_norm)]
    method_value = None
    if not sub.empty:
        vals = [v for v in sub["payment_type"].tolist() if str(v).strip() != ""]
        method_value = vals[0] if vals else None
    if not method_value:
        method_value = method_q

    df = read_table(EXCEL_PATH)
    for c in ["name", "basefee", "fee", "payment_type", "amount_gt", "amount_lt"]:
        if c not in df.columns:
            df[c] = np.nan

    base_candidates = DF[DF["merchant"] == merch]["basefee"].dropna().tolist()
    basefee = base_candidates[0] if base_candidates else np.nan

    def same(a, b):
        if b is None:
            return (a is None) or (isinstance(a, float) and np.isnan(a)) or (str(a).strip() == "")
        if a is None or (isinstance(a, float) and np.isnan(a)) or str(a).strip() == "":
            return False
        return int(float(a)) == int(b)

    mask = (
        df["name"].astype(str).str.strip().str.lower().eq(str(merch).strip().lower())
        & df["payment_type"].astype(str).str.strip().str.lower().eq(str(method_value).strip().lower())
        & df["amount_gt"].apply(lambda x: same(x, gt))
        & df["amount_lt"].apply(lambda x: same(x, lt))
    )

    if mask.any():
        idx = df.index[mask][0]
        df.loc[idx, "fee"] = fee_val
        action = "обновил"
    else:
        df = pd.concat([df, pd.DataFrame([{
            "name": merch,
            "basefee": basefee,
            "fee": fee_val,
            "payment_type": method_value,
            "amount_gt": gt,
            "amount_lt": lt,
        }])], ignore_index=True)
        action = "добавил"

    write_table(df, EXCEL_PATH)
    reload_data()
    gt_txt = fmt_amount(gt)
    lt_txt = fmt_amount(lt)
    action_icon = "✏️" if action == "обновил" else "➕"
    return f"{action_icon} {action.capitalize()}\n\n🏪 {merch}\n💳 {method_value}\n📏 {gt_txt} – {lt_txt}\n💰 Fee: {fee_val}%"

def set_base_line(s: str) -> str:
    parts = s.split()
    if len(parts) < 2:
        return "❌ Формат: МЕРЧ BASEFEE\n\nПример: MerchantA 9.2"
    basefee = _parse_float(parts[-1])
    merchant_q = " ".join(parts[:-1])

    merch_list = find_merchants(merchant_q)
    if not merch_list:
        return "❌ Мерч не найден"
    merch = merch_list[0]

    df = read_table(EXCEL_PATH)
    for c in ["name", "basefee", "fee", "payment_type", "amount_gt", "amount_lt"]:
        if c not in df.columns:
            df[c] = np.nan

    mask = df["name"].astype(str).str.strip().str.lower().eq(str(merch).strip().lower())
    if mask.any():
        df.loc[mask, "basefee"] = basefee
        action = "обновил"
    else:
        df = pd.concat([df, pd.DataFrame([{
            "name": merch,
            "basefee": basefee,
            "fee": np.nan,
            "payment_type": "",
            "amount_gt": np.nan,
            "amount_lt": np.nan,
        }])], ignore_index=True)
        action = "добавил"

    write_table(df, EXCEL_PATH)
    reload_data()
    action_icon = "✏️" if action == "обновил" else "➕"
    return f"{action_icon} {action.capitalize()}\n\n🏪 {merch}\n📌 Basefee: {basefee}%"


# ----------------- BROADCAST -----------------
def parse_chat_ids(s: str) -> List[int]:
    # принимаем: 123 456, -100123... по строкам/пробелам/запятым
    toks = re.split(r"[,\s]+", s.strip())
    out = []
    for t in toks:
        if not t:
            continue
        if t.startswith("@"):
            # username нельзя надежно отправить без chat_id
            continue
        if re.fullmatch(r"-?\d+", t):
            out.append(int(t))
    # unique preserve order
    uniq = []
    seen = set()
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq

async def do_broadcast(context: ContextTypes.DEFAULT_TYPE, chat_ids: List[int], text: str) -> Tuple[int, List[str]]:
    ok = 0
    errors = []
    # защита от случайной “бомбы”
    chat_ids = chat_ids[:50]

    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=text)
            ok += 1
        except Exception as e:
            errors.append(f"{cid}: {e}")
        await asyncio.sleep(0.2)  # анти-флуд
    return ok, errors


# ----------------- STATE HELPERS -----------------
def set_mode(context: ContextTypes.DEFAULT_TYPE, mode: str):
    context.user_data["mode"] = mode

def get_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("mode", MODE_NONE)

def reset_mode(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = MODE_NONE


# ----------------- MESSAGES -----------------
def msg_welcome():
    return """<b>📊 Бот по ставкам</b>
━━━━━━━━━━━━━━━━━━━━

🔍 <b>Поиск</b> — найти ставку
💱 <b>Курсы</b> — биржа и наценка мерча
🏪 <b>Мерч</b> — все ставки мерча
💳 <b>Метод</b> — мерчи по методу
📊 <b>Лимиты</b> — по диапазонам
📉 <b>Ниже %</b> — мерчи ниже порога
🤖 <b>AI</b> — умный поиск
🔄 <b>Обновить</b> — загрузить из Metabase

Выбери действие 👇"""

def msg_rate_prompt():
    return """<b>🔍 Поиск ставки</b>
━━━━━━━━━━━━━━━━━━━━

Примеры запросов:

<code>MerchantA</code>
<code>MerchantA sbp</code>
<code>MerchantA sbp 50000</code>"""

def msg_merch_prompt():
    return """<b>🏪 Все ставки мерча</b>
━━━━━━━━━━━━━━━━━━━━

Введи название:

<code>MerchantA</code>"""

def msg_method_prompt():
    return """<b>💳 Ставки по методу</b>
━━━━━━━━━━━━━━━━━━━━

Введи метод:

<code>sbp</code>  <code>c2c</code>  <code>alfa</code>  <code>sber</code>"""

def msg_below_prompt():
    return """<b>📉 Мерчи ниже порога</b>
━━━━━━━━━━━━━━━━━━━━

Формат: <code>% метод</code>

Пример: <code>10 sbp</code>"""

def msg_limits_menu():
    return """<b>📊 Лимиты по диапазонам</b>
━━━━━━━━━━━━━━━━━━━━

🔼 <b>Хай</b> — от 10 000 ₽
🔽 <b>Мин</b> — до 10 000 ₽
💎 <b>Микрочек</b> — 100-1000 ₽

<i>SBP + C2C или выбрать метод</i>

Выбери диапазон 👇"""

def msg_ai_prompt():
    return """<b>🤖 AI помощник</b>
━━━━━━━━━━━━━━━━━━━━

Задай вопрос:

<i>«ставка MerchantA sbp»</i>
<i>«у кого самый низкий c2c»</i>"""

def msg_webapp():
    return """<b>📱 Mini App</b>
━━━━━━━━━━━━━━━━━━━━

Открой веб-приложение 👇"""

# ----------------- COMMANDS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("🔐 Введите ключ доступа:")
        return
    reset_mode(context)
    await update.message.reply_text(msg_welcome(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    reset_mode(context)
    await update.message.reply_text(msg_welcome(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # чтобы удобно собирать chat_id: добавь бота в группу/канал и напиши там /chatid
    if not is_allowed(update):
        return
    cid = update.effective_chat.id if update.effective_chat else None
    await update.message.reply_text(f"🆔 Chat ID: <code>{cid}</code>", parse_mode="HTML", reply_markup=kb_main(is_admin(update)))


# ----------------- BUTTONS / TEXT ROUTER -----------------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id if update.effective_user else None

    # Проверка ключа для неавторизованных
    if not is_allowed(update):
        if txt.startswith("KEY-") and check_key(txt):
            authorize_user(uid)
            await update.message.reply_text("✅ Доступ разрешён!", reply_markup=kb_main(is_admin(update)))
            return
        elif txt.startswith("KEY-"):
            await update.message.reply_text("❌ Неверный ключ")
            return
        return

    if txt == BTN_CANCEL:
        await cancel(update, context)
        return

    if txt == BTN_BACK:
        reset_mode(context)
        await update.message.reply_text(msg_welcome(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_RATE:
        set_mode(context, MODE_RATE)
        await update.message.reply_text(msg_rate_prompt(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_EXCHANGE:
        set_mode(context, MODE_EXCHANGE)
        await update.message.reply_text(
            "<b>💱 Курсы мерчей</b>\n━━━━━━━━━━━━━━━━━━━━\n\nВведи название мерча:\n\n<code>MerchantA</code>\n<code>Empire</code>\n\nИли напиши <b>все</b> для полного списка",
            parse_mode="HTML", reply_markup=kb_main(is_admin(update))
        )
        return

    if txt == BTN_MERCH_ALL:
        set_mode(context, MODE_MERCH_ALL)
        await update.message.reply_text(msg_merch_prompt(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_METHOD_ALL:
        set_mode(context, MODE_METHOD_ALL)
        await update.message.reply_text(msg_method_prompt(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_LIMITS:
        set_mode(context, MODE_LIMITS_MENU)
        await update.message.reply_text(msg_limits_menu(), parse_mode="HTML", reply_markup=kb_limits())
        return

    if txt == BTN_BELOW:
        set_mode(context, MODE_BELOW)
        await update.message.reply_text(msg_below_prompt(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_AIHELP:
        set_mode(context, MODE_AI)
        await update.message.reply_text(msg_ai_prompt(), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_WEBAPP:
        webapp_url = os.environ.get("WEBAPP_URL", "https://rates.example.com")
        webapp_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Открыть Mini App", web_app=WebAppInfo(url=webapp_url))]
        ])
        await update.message.reply_text(
            msg_webapp(),
            parse_mode="HTML",
            reply_markup=webapp_button
        )
        return

    if txt == BTN_UPDATE:
        await update.message.reply_text("☁️ Загружаю данные...", reply_markup=kb_main(is_admin(update)))
        try:
            success_mb = await asyncio.to_thread(update_from_metabase)
            success_ex = await asyncio.to_thread(load_exchange_rates)
            parts = []
            if success_mb:
                parts.append(f"✅ Ставки из Metabase обновлены")
            else:
                parts.append(f"❌ Ошибка загрузки ставок из Metabase")
            if success_ex:
                parts.append(f"✅ Курсы мерчей обновлены")
            else:
                parts.append(f"❌ Ошибка загрузки курсов")
            await update.message.reply_text("\n".join(parts), reply_markup=kb_main(is_admin(update)))
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=kb_main(is_admin(update)))
        return

    if txt == BTN_EDITOR:
        if not is_admin(update):
            await update.message.reply_text("🚫 Нет доступа", reply_markup=kb_main(is_admin(update)))
            return
        set_mode(context, MODE_EDITOR_MENU)
        await update.message.reply_text(
            "<b>⚙️ Редактор ставок</b>\n━━━━━━━━━━━━━━━━━━━━\n\nВыбери действие 👇",
            parse_mode="HTML", reply_markup=kb_editor()
        )
        return

    if txt == BTN_BROADCAST:
        if not is_admin(update):
            await update.message.reply_text("🚫 Нет доступа", reply_markup=kb_main(is_admin(update)))
            return
        set_mode(context, MODE_BCAST_CHATS)
        await update.message.reply_text(
            "<b>📢 Рассылка</b>\n━━━━━━━━━━━━━━━━━━━━\n\nВведи chat_id через пробел\n<code>/chatid</code> — узнать ID чата",
            parse_mode="HTML", reply_markup=kb_main(True)
        )
        return

    # limits submenu
    if txt in [BTN_L_HIGH, BTN_L_MIN, BTN_L_MICRO, BTN_L_HIGH_M, BTN_L_MIN_M, BTN_L_MICRO_M]:
        if txt == BTN_L_HIGH:
            reset_mode(context)
            await send_long(update, list_rates_for_band("high", None))
            return
        if txt == BTN_L_MIN:
            reset_mode(context)
            await send_long(update, list_rates_for_band("min", None))
            return
        if txt == BTN_L_MICRO:
            reset_mode(context)
            await send_long(update, list_rates_for_band("micro", None))
            return
        if txt == BTN_L_HIGH_M:
            context.user_data["limits_band"] = "high"
            set_mode(context, MODE_LIMITS_METHOD_PICK)
            await update.message.reply_text("💳 Введи метод:\n<code>sbp</code> <code>c2c</code> <code>alfa</code>", parse_mode="HTML", reply_markup=kb_limits())
            return
        if txt == BTN_L_MIN_M:
            context.user_data["limits_band"] = "min"
            set_mode(context, MODE_LIMITS_METHOD_PICK)
            await update.message.reply_text("💳 Введи метод:\n<code>sbp</code> <code>c2c</code> <code>alfa</code>", parse_mode="HTML", reply_markup=kb_limits())
            return
        if txt == BTN_L_MICRO_M:
            context.user_data["limits_band"] = "micro"
            set_mode(context, MODE_LIMITS_METHOD_PICK)
            await update.message.reply_text("💳 Введи метод:\n<code>sbp</code> <code>c2c</code> <code>alfa</code>", parse_mode="HTML", reply_markup=kb_limits())
            return

    # editor submenu
    if txt in [BTN_E_FEE, BTN_E_BASE, BTN_E_RELOAD, BTN_E_METABASE, BTN_E_REINDEX]:
        if not is_admin(update):
            await update.message.reply_text("Нет доступа", reply_markup=kb_main(is_admin(update)))
            return

        if txt == BTN_E_RELOAD:
            reload_data()
            reset_mode(context)
            await update.message.reply_text("✅ Данные обновлены из файла", reply_markup=kb_main(True))
            return

        if txt == BTN_E_METABASE:
            await update.message.reply_text("☁️ Загружаю из Metabase...", reply_markup=kb_editor())
            try:
                success = await asyncio.to_thread(update_from_metabase)
                reset_mode(context)
                if success:
                    await update.message.reply_text(f"✅ Данные загружены из Metabase\n📅 {_last_metabase_update.strftime('%d.%m.%Y %H:%M')}", reply_markup=kb_main(True))
                else:
                    await update.message.reply_text("❌ Ошибка загрузки из Metabase", reply_markup=kb_main(True))
            except Exception as e:
                reset_mode(context)
                await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=kb_main(True))
            return

        if txt == BTN_E_REINDEX:
            await update.message.reply_text("🧠 Обновляю AI индекс...", reply_markup=kb_editor())
            try:
                await asyncio.to_thread(build_index_files)
                load_dan_index()
                reset_mode(context)
                await update.message.reply_text("✅ AI индекс обновлен", reply_markup=kb_main(True))
            except Exception as e:
                reset_mode(context)
                await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=kb_main(True))
            return

        if txt == BTN_E_FEE:
            set_mode(context, MODE_EDIT_FEE)
            await update.message.reply_text(
                "<b>💰 Изменить Fee</b>\n━━━━━━━━━━━━━━━━━━━━\n\nФормат: <code>мерч метод от до fee</code>\n\nПример:\n<code>MerchantA sbp 1000 9999 9.5</code>",
                parse_mode="HTML", reply_markup=kb_editor()
            )
            return

        if txt == BTN_E_BASE:
            set_mode(context, MODE_EDIT_BASE)
            await update.message.reply_text(
                "<b>📋 Изменить Basefee</b>\n━━━━━━━━━━━━━━━━━━━━\n\nФормат: <code>мерч basefee</code>\n\nПример:\n<code>MerchantA 9.2</code>",
                parse_mode="HTML", reply_markup=kb_editor()
            )
            return

    # если не кнопка — это обычный ввод по текущему режиму
    await handle_text(update, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    txt = (update.message.text or "").strip()
    if not txt:
        return

    mode = get_mode(context)

    if txt == BTN_CANCEL:
        await cancel(update, context)
        return

    # ----------------- BROADCAST FLOW -----------------
    if mode == MODE_BCAST_CHATS:
        if not is_admin(update):
            reset_mode(context)
            await update.message.reply_text("Нет доступа", reply_markup=kb_main(is_admin(update)))
            return

        chat_ids = parse_chat_ids(txt)
        if not chat_ids:
            await update.message.reply_text("❌ chat_id не найден", reply_markup=kb_main(True))
            return

        context.user_data["bcast_chat_ids"] = chat_ids
        set_mode(context, MODE_BCAST_TEXT)
        await update.message.reply_text(f"Чатов: {len(chat_ids)}\n\nВведи текст рассылки", reply_markup=kb_main(True))
        return

    if mode == MODE_BCAST_TEXT:
        if not is_admin(update):
            reset_mode(context)
            await update.message.reply_text("Нет доступа", reply_markup=kb_main(is_admin(update)))
            return

        chat_ids = context.user_data.get("bcast_chat_ids", [])
        if not chat_ids:
            reset_mode(context)
            await update.message.reply_text("❌ Список чатов пуст", reply_markup=kb_main(True))
            return

        text_to_send = update.message.text
        await update.message.reply_text("📤 Отправляю...", reply_markup=kb_main(True))

        ok, errors = await do_broadcast(context, chat_ids, text_to_send)

        msg = f"✅ Отправлено: {ok}"
        if errors:
            msg += f"\n❌ Ошибок: {len(errors)}"

        reset_mode(context)
        context.user_data.pop("bcast_chat_ids", None)
        await update.message.reply_text(msg, reply_markup=kb_main(True))
        return

    # ----------------- OTHER MODES -----------------
    if mode == MODE_RATE:
        merchants = find_merchants(txt)
        if not merchants:
            await update.message.reply_text("❌ Мерч не найден", reply_markup=kb_main(is_admin(update)))
            return

        merchant = merchants[0]
        amount = parse_amount(txt)
        method_norm = choose_payment_type(txt, merchant)
        res = pick_rate(merchant, method_norm, amount)

        if res["rate"] is None:
            await update.message.reply_text("❌ Ставка не найдена", reply_markup=kb_main(is_admin(update)))
        elif res["source"] == "need_amount":
            ranges = res.get("ranges", [])
            lines = [
                f"<b>🏪 {merchant}</b>",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"💳 {res['payment_type']}",
                ""
            ]
            for gt, lt, fee in ranges:
                gt_txt = fmt_amount(gt)
                lt_txt = fmt_amount(lt)
                lines.append(f"    {gt_txt} – {lt_txt} → <b>{fmt_rate(fee)}%</b>")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
        elif res["source"] == "fee":
            gt, lt = res["range"]
            gt_txt = fmt_amount(gt)
            lt_txt = fmt_amount(lt)
            await update.message.reply_text(
                f"<b>🏪 {merchant}</b>\n━━━━━━━━━━━━━━━━━━━━\n💳 {res['payment_type']} · {gt_txt} – {lt_txt}\n\n✅ <b>{fmt_rate(res['rate'])}%</b>",
                parse_mode="HTML", reply_markup=kb_main(is_admin(update))
            )
        else:
            method_info = f"\n💳 {res['payment_type']}" if res["payment_type"] else ""
            await update.message.reply_text(f"<b>🏪 {merchant}</b>\n━━━━━━━━━━━━━━━━━━━━{method_info}\n\n📌 Basefee: <b>{fmt_rate(res['rate'])}%</b>", parse_mode="HTML", reply_markup=kb_main(is_admin(update)))

        reset_mode(context)
        return

    if mode == MODE_MERCH_ALL:
        merchants = find_merchants(txt)
        if not merchants:
            await update.message.reply_text("❌ Мерч не найден", reply_markup=kb_main(is_admin(update)))
            return
        await send_long(update, list_all_rates_for_merchant(merchants[0]))
        reset_mode(context)
        return

    if mode == MODE_METHOD_ALL:
        await send_long(update, list_all_rates_for_method(txt))
        reset_mode(context)
        return

    if mode == MODE_LIMITS_METHOD_PICK:
        band = context.user_data.get("limits_band", "high")
        await send_long(update, list_rates_for_band(band, txt))
        reset_mode(context)
        return

    if mode == MODE_BELOW:
        parsed = parse_threshold_and_method(txt)
        if not parsed:
            await update.message.reply_text("❌ Формат: <code>10 alfa</code>", parse_mode="HTML", reply_markup=kb_main(is_admin(update)))
            return
        thr, method_q = parsed
        await send_long(update, template_raise(thr, method_q))
        reset_mode(context)
        return

    if mode == MODE_AI:
        ans = ai_answer(txt)
        await update.message.reply_text(f"🤖 {ans}", reply_markup=kb_main(is_admin(update)))
        reset_mode(context)
        return

    if mode == MODE_EXCHANGE:
        if norm(txt) in ("все", "all", "список", "list"):
            await send_long(update, list_all_exchanges())
        else:
            merchants = find_exchange_merchants(txt)
            await send_long(update, format_exchange_info(merchants))
        reset_mode(context)
        return

    if mode == MODE_EDIT_FEE:
        if not is_admin(update):
            reset_mode(context)
            await update.message.reply_text("🚫 Нет доступа", reply_markup=kb_main(is_admin(update)))
            return
        msg = set_fee_line(txt)
        reset_mode(context)
        await update.message.reply_text(msg, reply_markup=kb_main(True))
        return

    if mode == MODE_EDIT_BASE:
        if not is_admin(update):
            reset_mode(context)
            await update.message.reply_text("🚫 Нет доступа", reply_markup=kb_main(is_admin(update)))
            return
        msg = set_base_line(txt)
        reset_mode(context)
        await update.message.reply_text(msg, reply_markup=kb_main(True))
        return

    await update.message.reply_text("👆 Выбери действие на клавиатуре", reply_markup=kb_main(is_admin(update)))


def main():
    load_dan_index()

    # Запуск Metabase планировщика
    start_metabase_scheduler()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("chatid", chatid))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    print("Бот запущен. Остановить: Ctrl+C")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
        read_timeout=30,
        connect_timeout=30,
        pool_timeout=30,
    )


if __name__ == "__main__":
    main()
