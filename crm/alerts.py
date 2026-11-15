"""
ProcessingHub Alert Service v2
Мониторинг трафика и конверсий, алерты в Telegram-группу.
Работает как отдельный сервис, отправляет через HTTP API (без polling).

Улучшения v2:
- Pinned status-сообщение (редактируется каждые 5 мин)
- Алерты восстановления (трафик, баланс, конверсия)
- Ночной режим (00-08 МСК — только критичные)
- Эскалация (5м → 15м → 30м для нет трафика)
- Тренды payout балансов (↑↓ направление)
- Утренний отчёт (09:00 МСК)
"""
import asyncio
import logging
import os
import sys
import time
import requests as http_requests
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("alerts")
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ── Config ────────────────────────────────────────────────────────────────────
MSK = timezone(timedelta(hours=3))

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "0"))

POLL_INTERVAL = int(os.getenv("ALERT_POLL_INTERVAL", "60"))

# Thresholds (in poll cycles, 1 cycle = ~60s)
NO_TRAFFIC_CHECKS = 5         # 5 min
MERCHANT_STOPPED_CHECKS = 60  # 1 hour
TOP_MERCHANT_STOPPED_CHECKS = 30  # 30 min
CONVERSION_MIN_REQUISITES = 10   # min requisites issued to trigger alert
CONVERSION_THRESHOLD = 20.0
TOP_N_MERCHANTS = 5

# Escalation levels for no-traffic (minutes)
ESCALATION_LEVELS = [
    (5, "WARNING", "⚠️"),
    (15, "CRITICAL", "🔴"),
    (30, "EMERGENCY", "🚨🚨🚨"),
]

# Cooldowns (seconds)
COOLDOWN_GLOBAL = 600         # 10 min (escalation handles re-alerts)
COOLDOWN_MERCHANT = 3600      # 60 min
COOLDOWN_CONVERSION = 3600    # 60 min
COOLDOWN_TOP = 1800           # 30 min

# Night mode (MSK hours) — suppress non-critical alerts
NIGHT_START = 0   # 00:00 MSK
NIGHT_END = 8     # 08:00 MSK

# Reports
DAILY_REPORT_HOUR = 23
DAILY_REPORT_MINUTE = 55
MORNING_REPORT_HOUR = 9
MORNING_REPORT_MINUTE = 0

# Payout balance monitoring
PAYOUT_BALANCE_THRESHOLD = 300_000  # руб
PAYOUT_BALANCE_QUESTION_ID = 250    # Metabase question
COOLDOWN_PAYOUT_BALANCE = 1800      # 30 min
PAYOUT_CHECK_INTERVAL = 5           # check every N poll cycles (~5 min)

# Pinned status message update interval (cycles)
STATUS_UPDATE_INTERVAL = 5  # every 5 cycles (~5 min)


# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class MerchantState:
    name: str
    last_known_orders: int = 0
    unchanged_count: int = 0
    last_conversion: float = 0.0
    last_amount: float = 0.0

@dataclass
class AlertState:
    initialized: bool = False
    last_global_total: int = 0
    global_unchanged_count: int = 0
    merchants: Dict[str, MerchantState] = field(default_factory=dict)
    cooldowns: Dict[str, datetime] = field(default_factory=dict)
    last_daily_report_date: Optional[str] = None
    last_morning_report_date: Optional[str] = None
    poll_count: int = 0
    last_payout_balances: Dict[str, float] = field(default_factory=dict)
    # Pinned status message
    status_message_id: Optional[int] = None
    # Recovery tracking
    active_problems: Dict[str, str] = field(default_factory=dict)
    # Escalation: last level sent for no-traffic
    last_escalation_level: int = -1
    # Track previous conversion values for recovery detection
    low_conversion_merchants: Dict[str, float] = field(default_factory=dict)
    # Track global traffic was down
    traffic_was_down: bool = False


def is_on_cooldown(state: AlertState, key: str) -> bool:
    expiry = state.cooldowns.get(key)
    return bool(expiry and datetime.now(MSK) < expiry)


def set_cooldown(state: AlertState, key: str, seconds: int):
    state.cooldowns[key] = datetime.now(MSK) + timedelta(seconds=seconds)


def cleanup_cooldowns(state: AlertState):
    now = datetime.now(MSK)
    expired = [k for k, v in state.cooldowns.items() if v < now]
    for k in expired:
        del state.cooldowns[k]


def is_night_mode() -> bool:
    hour = datetime.now(MSK).hour
    return NIGHT_START <= hour < NIGHT_END


def is_critical_alert(alert_text: str) -> bool:
    """Check if alert is critical (should bypass night mode)."""
    critical_keywords = [
        "НЕТ ТРАФИКА", "ОТРИЦАТЕЛЬНЫЙ", "КРИТИЧНО",
        "EMERGENCY", "CRITICAL", "🚨",
    ]
    return any(kw in alert_text for kw in critical_keywords)


# ── Telegram ──────────────────────────────────────────────────────────────────

def get_group_members_tags() -> str:
    """Get mention tags for all group members (admins/members via getChatAdministrators)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatAdministrators"
    try:
        resp = http_requests.post(url, json={"chat_id": ALERT_CHAT_ID}, timeout=15)
        if resp.status_code != 200:
            log.error(f"getChatAdministrators error: {resp.status_code}")
            return ""
        members = resp.json().get("result", [])
        tags = []
        for m in members:
            user = m.get("user", {})
            if user.get("is_bot"):
                continue
            uid = user.get("id")
            first = user.get("first_name", "")
            username = user.get("username")
            if username:
                tags.append(f"@{username}")
            elif uid:
                tags.append(f'<a href="tg://user?id={uid}">{first}</a>')
        return " ".join(tags) if tags else ""
    except Exception as e:
        log.error(f"get_group_members_tags error: {e}")
        return ""


def send_telegram(text: str) -> Optional[int]:
    """Send message, return message_id on success."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = http_requests.post(url, json={
            "chat_id": ALERT_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if resp.status_code != 200:
            log.error(f"Telegram error: {resp.status_code} {resp.text[:200]}")
            return None
        log.info(f"Telegram sent OK ({len(text)} chars)")
        data = resp.json()
        return data.get("result", {}).get("message_id")
    except Exception as e:
        log.error(f"Telegram exception: {e}")
        return None


def edit_telegram(message_id: int, text: str) -> bool:
    """Edit existing message. Returns True on success."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    try:
        resp = http_requests.post(url, json={
            "chat_id": ALERT_CHAT_ID,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if resp.status_code != 200:
            # Message might be deleted or too old
            log.warning(f"Telegram edit error: {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        log.error(f"Telegram edit exception: {e}")
        return False


def pin_telegram(message_id: int):
    """Pin a message in chat (silently)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"
    try:
        http_requests.post(url, json={
            "chat_id": ALERT_CHAT_ID,
            "message_id": message_id,
            "disable_notification": True,
        }, timeout=15)
    except Exception as e:
        log.error(f"Telegram pin exception: {e}")


# ── Data Fetching ─────────────────────────────────────────────────────────────

async def fetch_data():
    """Fetch conversion_today from Metabase. Returns (merchants, totals)."""
    import metabase
    data = await asyncio.to_thread(metabase.get_conversion_today)

    totals = {}
    merchants = []
    for row in (data or []):
        name = str(row.get("Мерчант", ""))
        if "ИТОГО" in name:
            totals = row
        else:
            merchants.append(row)
    return merchants, totals


# ── Alert Checks ──────────────────────────────────────────────────────────────

def check_global_no_traffic(state: AlertState, totals: dict) -> List[str]:
    """Check for no traffic with escalation levels. Returns list of alerts."""
    current_total = int(totals.get("Всего", 0) or 0)
    alerts = []

    # Date rollover: total decreased
    if current_total < state.last_global_total:
        log.info(f"Date rollover: {state.last_global_total} -> {current_total}")
        state.last_global_total = current_total
        state.global_unchanged_count = 0
        state.last_escalation_level = -1
        for ms in state.merchants.values():
            ms.last_known_orders = 0
            ms.unchanged_count = 0
        return []

    if current_total <= state.last_global_total:
        state.global_unchanged_count += 1
    else:
        # Traffic resumed — check for recovery
        if state.traffic_was_down:
            state.traffic_was_down = False
            state.last_escalation_level = -1
            ts = datetime.now(MSK).strftime("%H:%M МСК")
            delta = current_total - state.last_global_total
            alerts.append(
                f"✅ <b>Трафик восстановлен!</b>\n"
                f"Новых заявок: +{delta}\n"
                f"Всего за сегодня: {current_total:,}\n"
                f"<i>{ts}</i>"
            )
        state.global_unchanged_count = 0
        state.last_global_total = current_total

    # Escalation: check each level
    minutes = state.global_unchanged_count
    for level_idx, (threshold_min, level_name, icon) in enumerate(ESCALATION_LEVELS):
        if minutes >= threshold_min and level_idx > state.last_escalation_level:
            state.last_escalation_level = level_idx
            state.traffic_was_down = True
            ts = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")

            # Tag all group members on no-traffic alerts
            tags = get_group_members_tags()
            tag_line = f"\n\n{tags}" if tags else ""

            if level_name == "WARNING":
                text = (
                    f"{icon} <b>Нет трафика ({minutes} мин)</b>\n"
                    f"<i>{ts}</i>\n\n"
                    f"Нет новых заявок. Всего за сегодня: {current_total:,}\n"
                    f"Проверьте провайдеров и API"
                    f"{tag_line}"
                )
            elif level_name == "CRITICAL":
                text = (
                    f"{icon} <b>КРИТИЧНО: НЕТ ТРАФИКА {minutes} МИН!</b>\n"
                    f"<i>{ts}</i>\n\n"
                    f"Заявок за сегодня: {current_total:,}\n"
                    f"Требуется немедленная проверка!"
                    f"{tag_line}"
                )
            else:  # EMERGENCY
                text = (
                    f"{icon} <b>АВАРИЯ: НЕТ ТРАФИКА {minutes} МИН!</b>\n"
                    f"<i>{ts}</i>\n\n"
                    f"Заявок за сегодня: {current_total:,}\n"
                    f"СРОЧНО проверьте: провайдеры, API, сервера!\n"
                    f"Трафик отсутствует уже полчаса!"
                    f"{tag_line}"
                )
            alerts.append(text)

    return alerts


def check_merchant_stopped(state: AlertState, merchants: list) -> List[str]:
    alerts = []
    for row in merchants:
        name = str(row.get("Мерчант", "")).strip()
        if not name:
            continue
        total = int(row.get("Всего", 0) or 0)
        if total == 0:
            continue

        ms = state.merchants.get(name)
        if ms is None:
            state.merchants[name] = MerchantState(
                name=name,
                last_known_orders=total,
                last_amount=float(row.get("Сумма успешных", 0) or 0),
                last_conversion=float(row.get("Конверсия в оплату %", 0) or 0),
            )
            continue

        # Date rollover per merchant
        if total < ms.last_known_orders:
            ms.last_known_orders = total
            ms.unchanged_count = 0
        elif total <= ms.last_known_orders:
            ms.unchanged_count += 1
        else:
            ms.unchanged_count = 0
            ms.last_known_orders = total

        ms.last_conversion = float(row.get("Конверсия в оплату %", 0) or 0)
        ms.last_amount = float(row.get("Сумма успешных", 0) or 0)

        if ms.unchanged_count >= MERCHANT_STOPPED_CHECKS:
            key = f"merchant_stopped:{name}"
            if not is_on_cooldown(state, key):
                set_cooldown(state, key, COOLDOWN_MERCHANT)
                alerts.append(f"<code>{name}</code> — {ms.unchanged_count} мин, заявок: {total}")
    return alerts


def check_top_merchant_stopped(state: AlertState, merchants: list) -> List[str]:
    ranked = sorted(
        [r for r in merchants if float(r.get("Сумма успешных", 0) or 0) > 0],
        key=lambda r: float(r.get("Сумма успешных", 0) or 0),
        reverse=True,
    )
    top_names = [str(r.get("Мерчант", "")).strip() for r in ranked[:TOP_N_MERCHANTS]]

    alerts = []
    for i, name in enumerate(top_names, 1):
        ms = state.merchants.get(name)
        if ms and ms.unchanged_count >= TOP_MERCHANT_STOPPED_CHECKS:
            key = f"top_stopped:{name}"
            if not is_on_cooldown(state, key):
                set_cooldown(state, key, COOLDOWN_TOP)
                ts = datetime.now(MSK).strftime("%H:%M МСК")
                alerts.append(
                    f"🔴 <b>ТОП мерчант остановился!</b>\n"
                    f"<code>{name}</code> (#{i} по обороту)\n"
                    f"Нет новых заявок {ms.unchanged_count} мин\n"
                    f"<i>{ts}</i>"
                )
    return alerts


def check_conversion_drop(state: AlertState, merchants: list) -> Tuple[List[str], List[str]]:
    """Returns (drop_alerts, recovery_alerts)."""
    drop_alerts = []
    recovery_alerts = []

    current_low = {}

    for row in merchants:
        name = str(row.get("Мерчант", "")).strip()
        with_requisites = int(row.get("С реквизитами", 0) or 0)
        conversion = float(row.get("Конверсия в оплату %", 0) or 0)
        successful = int(row.get("Успешных", 0) or 0)

        if with_requisites < CONVERSION_MIN_REQUISITES:
            continue

        if conversion < CONVERSION_THRESHOLD:
            current_low[name] = conversion
            key = f"conversion_drop:{name}"
            if not is_on_cooldown(state, key):
                set_cooldown(state, key, COOLDOWN_CONVERSION)
                drop_alerts.append(
                    f"<code>{name}</code> — <b>{conversion:.1f}%</b> "
                    f"(реквизитов: {with_requisites}, оплатили: {successful})"
                )
        else:
            # Was low, now recovered
            if name in state.low_conversion_merchants:
                old_conv = state.low_conversion_merchants[name]
                ts = datetime.now(MSK).strftime("%H:%M МСК")
                recovery_alerts.append(
                    f"✅ <b>Конверсия восстановилась</b>\n"
                    f"<code>{name}</code> — <b>{conversion:.1f}%</b> (было: {old_conv:.1f}%)\n"
                    f"<i>{ts}</i>"
                )

    state.low_conversion_merchants = current_low
    return drop_alerts, recovery_alerts


def fmt_amount(n: float) -> str:
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} млрд"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f} млн"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.0f} тыс"
    return f"{n:,.0f}"


# ── Payout Balance Check ─────────────────────────────────────────────────────

async def fetch_payout_balances() -> List[Dict]:
    """Fetch payout merchant balances from Metabase question #250."""
    import metabase
    try:
        rows = await asyncio.to_thread(
            metabase.get_client().execute_question, PAYOUT_BALANCE_QUESTION_ID
        )
        return rows or []
    except Exception as e:
        log.error(f"Payout balance fetch error: {e}")
        return []


def check_payout_balances(state: AlertState, balances: List[Dict]) -> Tuple[List[str], List[str]]:
    """Returns (problem_alerts, recovery_alerts)."""
    problem_alerts = []
    recovery_alerts = []

    for row in balances:
        name = str(row.get("merchant_name", ""))
        balance = float(row.get("balance_rub", 0) or 0)
        short_name = name.replace("Merchant ", "")

        prev_balance = state.last_payout_balances.get(name)
        state.last_payout_balances[name] = balance

        # Trend arrow
        trend = ""
        if prev_balance is not None:
            diff = balance - prev_balance
            if abs(diff) > 1000:  # ignore noise < 1k
                arrow = "↑" if diff > 0 else "↓"
                trend = f" {arrow} {fmt_amount(abs(diff))}"

        if balance >= PAYOUT_BALANCE_THRESHOLD:
            # Recovery: was below, now above
            if prev_balance is not None and prev_balance < PAYOUT_BALANCE_THRESHOLD:
                ts = datetime.now(MSK).strftime("%H:%M МСК")
                recovery_alerts.append(
                    f"✅ <b>Payout баланс пополнен</b>\n"
                    f"<code>{short_name}</code>\n"
                    f"Баланс: <b>{balance:,.0f} ₽</b>{trend}\n"
                    f"<i>{ts}</i>"
                )
            continue

        key = f"payout_balance:{name}"
        if is_on_cooldown(state, key):
            continue
        set_cooldown(state, key, COOLDOWN_PAYOUT_BALANCE)

        ts = datetime.now(MSK).strftime("%H:%M МСК")

        if balance < 0:
            icon = "🚨"
            severity = "ОТРИЦАТЕЛЬНЫЙ БАЛАНС"
        elif balance < 100_000:
            icon = "🔴"
            severity = "КРИТИЧНО НИЗКИЙ"
        else:
            icon = "⚠️"
            severity = "НИЖЕ ПОРОГА"

        problem_alerts.append(
            f"{icon} <b>Payout баланс: {severity}</b>\n"
            f"<code>{short_name}</code>\n"
            f"Баланс: <b>{balance:,.0f} ₽</b>{trend} (порог: {PAYOUT_BALANCE_THRESHOLD:,} ₽)\n"
            f"<i>{ts}</i>"
        )
    return problem_alerts, recovery_alerts


# ── Pinned Status Message ────────────────────────────────────────────────────

def build_status_message(state: AlertState, totals: dict, merchants: list) -> str:
    """Build the pinned status message text."""
    now = datetime.now(MSK)
    ts = now.strftime("%H:%M МСК")
    current_total = int(totals.get("Всего", 0) or 0)
    successful = int(totals.get("Успешных", 0) or 0)
    conv = float(totals.get("Конверсия в оплату %", 0) or 0)

    lines = [
        f"📊 <b>Статус системы</b> (обновлено {ts})",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Traffic status
    if state.global_unchanged_count >= NO_TRAFFIC_CHECKS:
        lines.append(f"🔴 Трафик: НЕТ ЗАЯВОК ({state.global_unchanged_count} мин)")
    else:
        lines.append(f"✅ Трафик: {current_total:,} заявок, {successful:,} успешных ({conv:.1f}%)")

    # Stopped merchants
    stopped_names = []
    for ms in state.merchants.values():
        if ms.unchanged_count >= TOP_MERCHANT_STOPPED_CHECKS:
            stopped_names.append(f"{ms.name} ({ms.unchanged_count}м)")
    if stopped_names:
        lines.append(f"⚠️ Без трафика: {', '.join(stopped_names[:5])}")
        if len(stopped_names) > 5:
            lines.append(f"   ...и ещё {len(stopped_names) - 5}")

    # Low conversion
    if state.low_conversion_merchants:
        low_items = [f"{n} ({v:.0f}%)" for n, v in state.low_conversion_merchants.items()]
        lines.append(f"📉 Низкая конверсия: {', '.join(low_items[:3])}")
        if len(low_items) > 3:
            lines.append(f"   ...и ещё {len(low_items) - 3}")

    # Payout balances
    if state.last_payout_balances:
        lines.append("")
        lines.append("💳 <b>Payout балансы:</b>")
        for name, bal in sorted(state.last_payout_balances.items()):
            short = name.replace("Merchant ", "")
            icon = "🔴" if bal < 0 else ("⚠️" if bal < PAYOUT_BALANCE_THRESHOLD else "✅")
            lines.append(f"  {icon} <code>{short}</code> — {fmt_amount(bal)} ₽")

    # Night mode indicator
    if is_night_mode():
        lines.append("")
        lines.append("🌙 Ночной режим (только критичные алерты)")

    return "\n".join(lines)


async def update_status_message(state: AlertState, totals: dict, merchants: list):
    """Update or create the pinned status message."""
    text = build_status_message(state, totals, merchants)

    if state.status_message_id:
        ok = edit_telegram(state.status_message_id, text)
        if ok:
            return
        # Edit failed — message deleted or too old, send new
        log.info("Status message edit failed, sending new")

    msg_id = send_telegram(text)
    if msg_id:
        state.status_message_id = msg_id
        pin_telegram(msg_id)
        log.info(f"New status message pinned: {msg_id}")


# ── Reports ──────────────────────────────────────────────────────────────────

async def build_report_data():
    """Fetch all data needed for daily/morning reports."""
    import metabase
    summary, compare, merchants_data, hourly = await asyncio.gather(
        asyncio.to_thread(metabase.get_today_summary),
        asyncio.to_thread(metabase.get_compare_yesterday),
        asyncio.to_thread(metabase.get_merchants_today),
        asyncio.to_thread(metabase.get_hourly_stats),
    )
    return summary, compare, merchants_data, hourly


async def check_daily_report(state: AlertState) -> Optional[str]:
    now = datetime.now(MSK)
    today_str = now.strftime("%Y-%m-%d")

    if state.last_daily_report_date == today_str:
        return None
    if now.hour != DAILY_REPORT_HOUR or now.minute < DAILY_REPORT_MINUTE:
        return None

    state.last_daily_report_date = today_str

    import metabase
    try:
        summary, compare, merchants_data, hourly = await build_report_data()
    except Exception as e:
        log.error(f"Daily report fetch error: {e}")
        return None

    total = int((summary or {}).get("total_orders", 0) or 0)
    successful = int((summary or {}).get("successful_orders", 0) or 0)
    amount = float((summary or {}).get("successful_amount", 0) or 0)
    conv = float((summary or {}).get("conversion", 0) or 0)

    yesterday_total = 0
    yesterday_conv = 0.0
    for row in (compare or []):
        day = str(row.get("День", row.get("Период", "")))
        if "чера" in day.lower():
            yesterday_total = int(row.get("Ордеров", row.get("orders", 0)) or 0)
            yesterday_conv = float(row.get("Конверсия %", row.get("conversion_pct", 0)) or 0)

    delta_pct = ((total - yesterday_total) / yesterday_total * 100) if yesterday_total else 0
    arrow = "📈" if delta_pct > 0 else "📉" if delta_pct < 0 else "➡️"

    top = sorted(
        (merchants_data or []),
        key=lambda r: float(r.get("Сумма успешных", r.get("Сумма", 0)) or 0),
        reverse=True,
    )[:5]
    top_lines = []
    for i, m in enumerate(top, 1):
        mname = m.get("Мерчант", "?")
        msum = float(m.get("Сумма успешных", m.get("Сумма", 0)) or 0)
        mconv = float(m.get("Конверсия %", 0) or 0)
        top_lines.append(f"  {i}. <code>{mname}</code> — {fmt_amount(msum)}₽ ({mconv:.1f}%)")

    peak = {}
    if hourly:
        peak = max(hourly, key=lambda r: int(r.get("Ордеров", r.get("orders", 0)) or 0))
    peak_hour = peak.get("Час", peak.get("hour", "?"))
    peak_orders = int(peak.get("Ордеров", peak.get("orders", 0)) or 0)

    # Payout balances
    payout_lines = []
    try:
        payout_data = await asyncio.to_thread(
            metabase.get_client().execute_question, PAYOUT_BALANCE_QUESTION_ID
        )
        for row in (payout_data or []):
            pname = str(row.get("merchant_name", "")).replace("Merchant ", "")
            pbal = float(row.get("balance_rub", 0) or 0)
            icon = "🔴" if pbal < PAYOUT_BALANCE_THRESHOLD else "✅"
            payout_lines.append(f"  {icon} <code>{pname}</code> — {fmt_amount(pbal)} ₽")
    except Exception as e:
        log.error(f"Daily report payout fetch error: {e}")

    payout_section = ""
    if payout_lines:
        payout_section = "\n\n💳 <b>Payout балансы:</b>\n" + "\n".join(payout_lines)

    ts = now.strftime("%d.%m.%Y")
    return (
        f"📊 <b>Итоги дня {ts}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Заявок: <b>{total:,}</b>  {arrow} {delta_pct:+.1f}% vs вчера\n"
        f"✅ Успешных: <b>{successful:,}</b>\n"
        f"💰 Оборот: <b>{fmt_amount(amount)} ₽</b>\n"
        f"📈 Конверсия: <b>{conv:.1f}%</b> (вчера: {yesterday_conv:.1f}%)\n\n"
        f"🏆 <b>ТОП-5 мерчантов:</b>\n"
        + "\n".join(top_lines) + "\n\n"
        f"⏰ Пиковый час: {peak_hour}:00 ({peak_orders:,} заявок)"
        + payout_section + "\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )


async def check_morning_report(state: AlertState) -> Optional[str]:
    """Morning report at 09:00 MSK — yesterday summary + current payout balances."""
    now = datetime.now(MSK)
    today_str = now.strftime("%Y-%m-%d")

    if state.last_morning_report_date == today_str:
        return None
    if now.hour != MORNING_REPORT_HOUR or now.minute < MORNING_REPORT_MINUTE:
        return None

    state.last_morning_report_date = today_str

    import metabase
    try:
        compare = await asyncio.to_thread(metabase.get_compare_yesterday)
    except Exception as e:
        log.error(f"Morning report fetch error: {e}")
        return None

    yesterday_total = 0
    yesterday_successful = 0
    yesterday_conv = 0.0
    yesterday_amount = 0.0
    for row in (compare or []):
        day = str(row.get("День", row.get("Период", "")))
        if "чера" in day.lower():
            yesterday_total = int(row.get("Ордеров", row.get("orders", 0)) or 0)
            yesterday_successful = int(row.get("Успешных", row.get("successful", 0)) or 0)
            yesterday_conv = float(row.get("Конверсия %", row.get("conversion_pct", 0)) or 0)
            yesterday_amount = float(row.get("Сумма", row.get("amount", 0)) or 0)

    # Payout balances
    payout_lines = []
    try:
        payout_data = await asyncio.to_thread(
            metabase.get_client().execute_question, PAYOUT_BALANCE_QUESTION_ID
        )
        for row in (payout_data or []):
            pname = str(row.get("merchant_name", "")).replace("Merchant ", "")
            pbal = float(row.get("balance_rub", 0) or 0)
            icon = "🔴" if pbal < PAYOUT_BALANCE_THRESHOLD else "✅"
            payout_lines.append(f"  {icon} <code>{pname}</code> — {fmt_amount(pbal)} ₽")
    except Exception as e:
        log.error(f"Morning report payout fetch error: {e}")

    # Stopped merchants from state
    stopped_lines = []
    for ms in state.merchants.values():
        if ms.unchanged_count >= MERCHANT_STOPPED_CHECKS:
            stopped_lines.append(f"  ⚠️ <code>{ms.name}</code> — {ms.unchanged_count} мин без заявок")

    payout_section = ""
    if payout_lines:
        payout_section = "\n\n💳 <b>Payout балансы:</b>\n" + "\n".join(payout_lines)

    stopped_section = ""
    if stopped_lines:
        stopped_section = "\n\n⚠️ <b>Без трафика с ночи:</b>\n" + "\n".join(stopped_lines[:10])

    yesterday = (now - timedelta(days=1)).strftime("%d.%m.%Y")
    return (
        f"☀️ <b>Доброе утро! Сводка на {now.strftime('%d.%m.%Y')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 <b>Вчера ({yesterday}):</b>\n"
        f"  📦 Заявок: {yesterday_total:,}\n"
        f"  ✅ Успешных: {yesterday_successful:,}\n"
        f"  💰 Оборот: {fmt_amount(yesterday_amount)} ₽\n"
        f"  📈 Конверсия: {yesterday_conv:.1f}%"
        + payout_section
        + stopped_section + "\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Batch Helper ──────────────────────────────────────────────────────────────

def batch_alerts(alerts: List[str], header: str) -> List[str]:
    if not alerts:
        return []
    chunks = []
    current = header
    for alert in alerts:
        candidate = current + "\n\n" + alert
        if len(candidate) > 4000:
            chunks.append(current)
            current = header + "\n\n" + alert
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


# ── Main Loop ─────────────────────────────────────────────────────────────────

async def main_loop():
    state = AlertState()
    log.info(f"Alert service v2 starting. Chat: {ALERT_CHAT_ID}, Poll: {POLL_INTERVAL}s")

    send_telegram(
        "🟢 <b>Alert service v2 запущен</b>\n"
        f"Интервал: {POLL_INTERVAL}с\n"
        f"Алерты: нет трафика (эскалация 5→15→30м), "
        f"мерчант остановился (1ч), топ-мерч (30м), "
        f"конверсия &lt;{CONVERSION_THRESHOLD}%, "
        f"payout баланс &lt;{PAYOUT_BALANCE_THRESHOLD:,}₽\n"
        f"Отчёты: утренний (09:00), вечерний (23:55)\n"
        f"Pinned статус, алерты восстановления, ночной режим"
    )

    while True:
        try:
            cleanup_cooldowns(state)

            merchants, totals = await fetch_data()

            if not totals:
                log.warning("No data from Metabase, skipping cycle")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            all_alerts: List[str] = []
            night = is_night_mode()

            if state.initialized:
                state.poll_count += 1

                # 1. Global no-traffic (with escalation) — always active
                traffic_alerts = check_global_no_traffic(state, totals)
                all_alerts.extend(traffic_alerts)

                # 2. Merchant stopped — batched, skip in night mode
                if not night:
                    stopped = check_merchant_stopped(state, merchants)
                    if stopped:
                        ts = datetime.now(MSK).strftime("%H:%M МСК")
                        all_alerts.extend(batch_alerts(
                            stopped,
                            f"⚠️ <b>Мерчанты без трафика</b> ({len(stopped)} шт.) — <i>{ts}</i>"
                        ))
                else:
                    # Still update state silently at night
                    check_merchant_stopped(state, merchants)

                # 3. Top merchant stopped — always active (critical)
                top_stopped = check_top_merchant_stopped(state, merchants)
                all_alerts.extend(top_stopped)

                # 4. Conversion drop + recovery
                if not night:
                    conv_drops, conv_recoveries = check_conversion_drop(state, merchants)
                    if conv_drops:
                        all_alerts.extend(batch_alerts(
                            conv_drops, "📉 <b>Низкая конверсия в оплату:</b>"
                        ))
                    all_alerts.extend(conv_recoveries)
                else:
                    check_conversion_drop(state, merchants)

                # 5. Payout balance check (every N cycles) — always active
                if state.poll_count % PAYOUT_CHECK_INTERVAL == 0:
                    payout_data = await fetch_payout_balances()
                    payout_problems, payout_recoveries = check_payout_balances(state, payout_data)
                    if payout_problems:
                        all_alerts.extend(
                            batch_alerts(payout_problems, "💰 <b>Payout балансы:</b>")
                        )
                    all_alerts.extend(payout_recoveries)

                # 6. Pinned status message (every N cycles)
                if state.poll_count % STATUS_UPDATE_INTERVAL == 0:
                    await update_status_message(state, totals, merchants)

                # 7. Morning report (09:00)
                morning = await check_morning_report(state)
                if morning:
                    all_alerts.append(morning)

                # 8. Daily report (23:55)
                report = await check_daily_report(state)
                if report:
                    all_alerts.append(report)

            else:
                # First poll: initialize state silently
                check_global_no_traffic(state, totals)
                check_merchant_stopped(state, merchants)
                check_conversion_drop(state, merchants)
                state.initialized = True
                log.info(
                    f"Initialized: {len(state.merchants)} merchants, "
                    f"global total={state.last_global_total}"
                )
                # Send initial status message
                await update_status_message(state, totals, merchants)

            # Night mode filter: only send critical alerts
            if night:
                all_alerts = [a for a in all_alerts if is_critical_alert(a)]

            for alert_msg in all_alerts:
                send_telegram(alert_msg)
                await asyncio.sleep(0.5)

        except Exception as e:
            log.error(f"Main loop error: {e}", exc_info=True)

        await asyncio.sleep(POLL_INTERVAL)


def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!")
        sys.exit(1)

    log.info(f"Starting alert service v2... Token: {BOT_TOKEN[:10]}***, Chat: {ALERT_CHAT_ID}")
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
