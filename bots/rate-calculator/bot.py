"""
TopupBot — расчёт пополнений по tx hash из TRON блокчейна.
Саппорт шлёт хеш → бот достаёт сумму USDT, адреса, считает рубли.
"""
import os
import re
import json
import secrets
import logging
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# ──────────────────── config ────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS: set[int] = {
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
}

USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_DECIMALS = 6

TRONSCAN_TX_URL = "https://apilist.tronscanapi.com/api/transaction-info"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

RATE_MARKUP = Decimal("1.01")  # rapira + 1%

TXID_RE = re.compile(r"[a-fA-F0-9]{64}")

WALLETS_FILE = Path(__file__).parent / "wallets.json"
KEYS_FILE = Path(__file__).parent / "keys.json"
MASTER_KEY = os.getenv("MASTER_KEY", "")

# ──────────────────── keys / auth ────────────────────
def load_keys() -> dict:
    if KEYS_FILE.exists():
        try:
            return json.loads(KEYS_FILE.read_text())
        except Exception:
            pass
    return {"keys": [MASTER_KEY], "users": []}


def save_keys(data: dict):
    KEYS_FILE.write_text(json.dumps(data, indent=2))


def init_keys():
    data = load_keys()
    if MASTER_KEY not in data.get("keys", []):
        data.setdefault("keys", []).append(MASTER_KEY)
        save_keys(data)


init_keys()

AUTHORIZED_USERS: set[int] = set(load_keys().get("users", []))


def authorize_user(uid: int):
    AUTHORIZED_USERS.add(uid)
    data = load_keys()
    if uid not in data.get("users", []):
        data.setdefault("users", []).append(uid)
        save_keys(data)


def is_allowed(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in AUTHORIZED_USERS


def check_key(key: str) -> bool:
    data = load_keys()
    return key in data.get("keys", [])


# ──────────────────── wallets ────────────────────
def load_wallets() -> set[str]:
    if WALLETS_FILE.exists():
        try:
            data = json.loads(WALLETS_FILE.read_text())
            return set(data)
        except Exception:
            pass
    return set()


def save_wallets(wallets: set[str]):
    WALLETS_FILE.write_text(json.dumps(sorted(wallets), indent=2, ensure_ascii=False))


OUR_WALLETS = load_wallets()


# ──────────────────── blockchain ────────────────────
async def fetch_tx(txid: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(TRONSCAN_TX_URL, params={"hash": txid})
        r.raise_for_status()
        return r.json()


def extract_usdt_transfers(tx: dict) -> list[dict]:
    transfers = tx.get("trc20TransferInfo") or []
    out = []
    for t in transfers:
        if t.get("contract_address") != USDT_CONTRACT:
            continue
        raw = t.get("amount_str") or "0"
        amount = Decimal(raw) / Decimal(10 ** USDT_DECIMALS)
        out.append({
            "amount": amount,
            "from": t.get("from_address", ""),
            "to": t.get("to_address", ""),
        })
    return out


# ──────────────────── rate ────────────────────
async def get_usdt_rub_rate() -> Decimal:
    """CoinGecko USDT→RUB (ближе всего к rapira)."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(COINGECKO_URL, params={"ids": "tether", "vs_currencies": "rub"})
        r.raise_for_status()
        price = r.json()["tether"]["rub"]
        return Decimal(str(price))


# ──────────────────── formatting ────────────────────
def fmt_amount(v: Decimal) -> str:
    """1552.123 → '1 552.12'  (2 знака, пробелы-разделители)"""
    rounded = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    int_part, dec_part = str(rounded).split(".")
    # пробелы как разделитель тысяч
    int_part = f"{int(int_part):,}".replace(",", " ")
    return f"{int_part}.{dec_part}"


def wallet_tag(addr: str) -> str:
    if addr in OUR_WALLETS:
        return " ✅ наш"
    return " ⚠️ НЕ наш" if OUR_WALLETS else ""


def build_topup_message(txid: str, transfers: list[dict], rate: Decimal) -> str:
    if not transfers:
        return f"Hash: <code>{txid}</code>\n\n❌ USDT переводов не найдено."

    lines = ["<b>Расчёт пополнения</b>", ""]

    for i, t in enumerate(transfers, 1):
        amount = t["amount"]
        effective_rate = (rate * RATE_MARKUP).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rub = (amount * effective_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if len(transfers) > 1:
            lines.append(f"<b>── Перевод {i} ──</b>")

        lines.append(f"Hash: <code>{txid}</code>")
        lines.append("")
        lines.append(f"From: <code>{t['from']}</code>")
        lines.append(f"To:   <code>{t['to']}</code>{wallet_tag(t['to'])}")
        lines.append("")
        lines.append(f"Получено в блокчейне: <b>{fmt_amount(amount)} USDT</b>")
        lines.append(f"Курс: {fmt_amount(effective_rate)} ₽/USDT")
        lines.append(f"К зачислению: <b>{fmt_amount(rub)} ₽</b>")
        lines.append("")

    return "\n".join(lines).strip()


def build_topup_from_amount(amount: Decimal, rate: Decimal) -> str:
    effective_rate = (rate * RATE_MARKUP).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rub = (amount * effective_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return (
        "<b>Расчёт пополнения</b>\n"
        "\n"
        f"Сумма: <b>{fmt_amount(amount)} USDT</b>\n"
        f"Курс: {fmt_amount(effective_rate)} ₽/USDT\n"
        f"К зачислению: <b>{fmt_amount(rub)} ₽</b>"
    )


# ──────────────────── handlers ────────────────────
def is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid in ADMIN_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    if not is_allowed(uid):
        await update.message.reply_text("🔐 Введите ключ доступа:")
        return
    await update.message.reply_text(
        "<b>TopupBot</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Пришли <b>tx hash</b> (64 hex) — получишь расчёт пополнения.\n"
        "Или пришли <b>сумму USDT</b> — ручной расчёт.\n\n"
        "<b>Команды админа:</b>\n"
        "/add_wallet &lt;адрес&gt; — добавить наш кошелёк\n"
        "/remove_wallet &lt;адрес&gt; — удалить кошелёк\n"
        "/wallets — список наших кошельков\n"
        "/gen_key — сгенерировать ключ доступа\n"
        "/keys — список активных ключей\n"
        "/revoke_key &lt;ключ&gt; — отозвать ключ",
        parse_mode="HTML",
    )


async def cmd_gen_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 Нет доступа")
        return
    key = f"KEY-{secrets.token_urlsafe(12)}"
    data = load_keys()
    data.setdefault("keys", []).append(key)
    save_keys(data)
    await update.message.reply_text(
        f"✅ Новый ключ:\n<code>{key}</code>\n\nОтправьте его пользователю — он введёт его боту для доступа.",
        parse_mode="HTML",
    )


async def cmd_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 Нет доступа")
        return
    data = load_keys()
    keys = data.get("keys", [])
    users = data.get("users", [])
    lines = ["<b>Ключи доступа:</b>", ""]
    for k in keys:
        lines.append(f"<code>{k}</code>")
    lines.append("")
    lines.append(f"<b>Авторизованных пользователей:</b> {len(users)}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_revoke_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 Нет доступа")
        return
    if not context.args:
        await update.message.reply_text("Формат: /revoke_key KEY-...")
        return
    key = context.args[0].strip()
    data = load_keys()
    if key in data.get("keys", []):
        data["keys"].remove(key)
        save_keys(data)
        await update.message.reply_text(f"✅ Ключ отозван:\n<code>{key}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Ключ не найден")


async def cmd_add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 Нет доступа")
        return
    if not context.args:
        await update.message.reply_text("Формат: /add_wallet TАдрес...")
        return
    addr = context.args[0].strip()
    if not re.fullmatch(r"T[a-zA-Z0-9]{33}", addr):
        await update.message.reply_text("❌ Невалидный TRON-адрес (должен начинаться с T, 34 символа)")
        return
    OUR_WALLETS.add(addr)
    save_wallets(OUR_WALLETS)
    await update.message.reply_text(f"✅ Кошелёк добавлен:\n<code>{addr}</code>", parse_mode="HTML")


async def cmd_remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 Нет доступа")
        return
    if not context.args:
        await update.message.reply_text("Формат: /remove_wallet TАдрес...")
        return
    addr = context.args[0].strip()
    if addr in OUR_WALLETS:
        OUR_WALLETS.discard(addr)
        save_wallets(OUR_WALLETS)
        await update.message.reply_text(f"✅ Кошелёк удалён:\n<code>{addr}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Кошелёк не найден в списке")


async def cmd_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 Нет доступа")
        return
    if not OUR_WALLETS:
        await update.message.reply_text("Список пуст. Добавь: /add_wallet TАдрес...")
        return
    lines = ["<b>Наши кошельки:</b>", ""]
    for w in sorted(OUR_WALLETS):
        lines.append(f"<code>{w}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    uid = update.effective_user.id if update.effective_user else 0

    # 0) проверка ключа для неавторизованных
    if not is_allowed(uid):
        if text.startswith("KEY-") and check_key(text):
            authorize_user(uid)
            await update.message.reply_text("✅ Доступ разрешён! Теперь можешь отправлять хеши и суммы.")
            return
        elif text.startswith("KEY-"):
            await update.message.reply_text("❌ Неверный ключ")
            return
        await update.message.reply_text("🔐 Введите ключ доступа:")
        return

    # 1) tx hash
    m = TXID_RE.search(text)
    if m:
        txid = m.group(0)
        await update.message.reply_text("⏳ Проверяю транзакцию...")
        try:
            tx = await fetch_tx(txid)
            transfers = extract_usdt_transfers(tx)
            rate = await get_usdt_rub_rate()
            reply = build_topup_message(txid, transfers, rate)
            await update.message.reply_text(reply, parse_mode="HTML")
        except Exception as e:
            log.exception("tx fetch error")
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    # 2) число → ручной расчёт
    clean = text.replace(" ", "").replace(",", ".").replace("₽", "").replace("$", "")
    try:
        amount = Decimal(clean)
        if amount <= 0:
            return
    except Exception:
        return

    try:
        rate = await get_usdt_rub_rate()
        reply = build_topup_from_amount(amount, rate)
        await update.message.reply_text(reply, parse_mode="HTML")
    except Exception as e:
        log.exception("rate fetch error")
        await update.message.reply_text(f"❌ Ошибка получения курса: {e}")


# ──────────────────── main ────────────────────
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add_wallet", cmd_add_wallet))
    app.add_handler(CommandHandler("remove_wallet", cmd_remove_wallet))
    app.add_handler(CommandHandler("wallets", cmd_wallets))
    app.add_handler(CommandHandler("gen_key", cmd_gen_key))
    app.add_handler(CommandHandler("keys", cmd_keys))
    app.add_handler(CommandHandler("revoke_key", cmd_revoke_key))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("TopupBot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
