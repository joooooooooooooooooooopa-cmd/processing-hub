"""
Utility functions, constants, and shared helpers extracted from bot.py.
This module should NOT import from other handlers/* modules.
"""

import html
import logging
import sys
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ConversationHandler

from config import ADMIN_IDS
import keys
import database

# Московский часовой пояс (UTC+3)
MSK = timezone(timedelta(hours=3))


def escape(text: str) -> str:
    """Экранировать HTML символы в тексте"""
    if not text:
        return ""
    return html.escape(str(text))


# Настройка логирования - выводим в stdout для Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Уменьшаем уровень логов для библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


# ============ ДОСТУП ============

def is_authenticated(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid in ADMIN_IDS:
        return True
    return keys.is_user_authorized(uid)


def is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid in ADMIN_IDS


# ============ КНОПКИ ГЛАВНОГО МЕНЮ ============

# Аналитика
BTN_TODAY = "📊 Сводка за сегодня"

# Сравнение и проблемы
BTN_CANCELED = "❌ Анализ отменённых заявок"
BTN_ALERTS = "🚨 Проверить проблемы"
BTN_CONVERSION = "📈 Конверсия подробно"
BTN_LOW_CONVERSION = "⚠️ Конверсия сейчас"
BTN_BAD_CLIENTS = "🚫 Плохие пользователи"

# Инструменты
BTN_SEARCH = "🔍 Найти мерчанта"
BTN_EXPORT = "📤 Выгрузить отчёт"
BTN_RATES = "💰 Ставки и комиссии"

# CRM
BTN_ADD_MERCHANT = "➕ Добавить мерчанта"
BTN_EDIT_MERCHANT = "✏️ Редактировать мерчанта"
BTN_INCIDENTS = "📋 Инциденты"
BTN_NEW_INCIDENT = "🚨 Создать инцидент"

# Загрузка и сводка
BTN_UPLOAD_EXPORT = "📂 Загрузить выгрузку"
BTN_ACTIVE_SUMMARY = "📝 Сводка по активным"

# Пейаут
BTN_PAYOUT = "📤 PaycrowOUT"
BTN_METHOD_OVERVIEW = "📋 Обзор по методам"

# Админ
BTN_ADMIN = "🔐 Админ-панель"

# ConversationHandler states
(MERCH_NAME, MERCH_STATUS, MERCH_RATE, MERCH_CONTACT, MERCH_NOTES) = range(5)
(EDIT_FIND, EDIT_FIELD, EDIT_VALUE) = range(5, 8)
(INC_MERCHANT, INC_TYPE, INC_PRIORITY, INC_DESC, INC_DUE) = range(8, 13)
(INC_COMMENT_TEXT,) = range(13, 14)
(INC_CLOSE_NOTES,) = range(14, 15)
(MERCH_TAG_INPUT,) = range(15, 16)


# ============ CRM: УТИЛИТЫ ============

def time_ago(dt_str: str) -> str:
    """Относительное время: '5 минут назад', 'сегодня 14:30', '3 дня назад'"""
    if not dt_str:
        return "—"
    try:
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(str(dt_str)[:19], fmt[:len(fmt)])
                break
            except ValueError:
                continue
        else:
            return str(dt_str)[:16]
        now = datetime.now(MSK).replace(tzinfo=None)
        diff = now - dt
        secs = diff.total_seconds()
        if secs < 60:
            return "только что"
        if secs < 3600:
            m = int(secs // 60)
            return f"{m} мин назад"
        if secs < 86400:
            h = int(secs // 3600)
            return f"сегодня {dt.strftime('%H:%M')}"
        if secs < 172800:
            return f"вчера {dt.strftime('%H:%M')}"
        days = int(secs // 86400)
        if days < 30:
            return f"{days} дн. назад"
        return dt.strftime('%d.%m.%Y')
    except Exception:
        return str(dt_str)[:16]


def calculate_merchant_score(m: dict) -> int:
    """Скоринг мерчанта 0–100 на основе статуса, конверсии, настроения"""
    score = 50  # базовый балл
    status_scores = {
        'active': 30, 'testing': 20, 'integration': 15, 'negotiation': 10,
        'new': 5, 'paused': 0, 'problem': -20, 'disconnected': -30,
    }
    score += status_scores.get(m.get('status', ''), 0)
    conv = m.get('conversion') or 0
    if conv > 80:
        score += 30
    elif conv > 60:
        score += 20
    elif conv > 40:
        score += 10
    elif conv > 0 and conv < 20:
        score -= 10
    mood_scores = {'loyal': 15, 'positive': 10, 'neutral': 0, 'negative': -15, 'aggressive': -20}
    score += mood_scores.get(m.get('mood', ''), 0)
    # Штраф за открытые P0/P1 инциденты
    try:
        incidents = database.get_open_incidents(merchant_id=m.get('id'))
        for inc in incidents:
            if inc.get('priority') in ('P0', 'P1'):
                score -= 10
    except Exception:
        pass
    return max(0, min(100, score))


def score_emoji(score: int) -> str:
    if score >= 80:
        return "🟢"
    if score >= 60:
        return "🟡"
    if score >= 40:
        return "🟠"
    return "🔴"


# ============ ВИЗУАЛЬНЫЕ ЭЛЕМЕНТЫ ============

def progress_bar(value: float, max_value: float, width: int = 10) -> str:
    """Визуальный прогресс-бар"""
    if max_value <= 0:
        return "░" * width
    filled = int((value / max_value) * width)
    filled = min(filled, width)
    return "▓" * filled + "░" * (width - filled)


def trend_icon(current: float, previous: float) -> str:
    """Иконка тренда"""
    if previous == 0:
        return "➡️"
    change = ((current - previous) / previous) * 100
    if change > 10:
        return "🚀"
    elif change > 0:
        return "📈"
    elif change < -10:
        return "📉"
    elif change < 0:
        return "⬇️"
    return "➡️"


def trend_text(current: float, previous: float) -> str:
    """Текст тренда с процентом"""
    if previous == 0:
        return "нет данных"
    change = ((current - previous) / previous) * 100
    if change > 0:
        return f"+{change:.1f}%"
    else:
        return f"{change:.1f}%"


def conv_status(conv: float) -> str:
    """Статус конверсии (в процентах 0-100)"""
    if conv >= 40:
        return "🟢 Отлично"
    elif conv >= 25:
        return "🟡 Хорошо"
    elif conv >= 15:
        return "🟠 Средне"
    else:
        return "🔴 Плохо"


def format_money(amount: float) -> str:
    """Форматирование суммы"""
    if amount >= 1_000_000:
        return f"{amount/1_000_000:.2f} млн ₽"
    elif amount >= 1_000:
        return f"{amount/1_000:.1f} тыс ₽"
    else:
        return f"{amount:.0f} ₽"


def format_number(num: float) -> str:
    """Форматирование числа"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return f"{num:,.0f}"
