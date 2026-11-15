"""
Уведомления об отрицательных балансах трейдеров.
Источник: Metabase question #153

Команды бота:
  /report          — полный отчёт
  /htl Alpha        — отчёт по конкретному HTL
  /tl Bravo        — отчёт по конкретному TL
  /list            — список всех HTL / TL с суммарным долгом
  /help            — список команд
"""
import json, time, logging, sys, os, asyncio, io
import requests as http_requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

MSK = timezone(timedelta(hours=3))

def _now_msk() -> datetime:
    return datetime.now(tz=MSK)

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ── Конфиг ────────────────────────────────────────────────────────────────────

NOTIFY_BOT_TOKEN = os.getenv("NOTIFY_BOT_TOKEN", "") or os.getenv("BOT_TOKEN", "")
_raw = os.getenv("NOTIFY_RECIPIENT_IDS", "")
RECIPIENT_IDS: list[int] = [int(x.strip()) for x in _raw.split(",") if x.strip()]

DATABASE_URL          = os.getenv("DATABASE_URL", "")
METABASE_QUESTION_ID  = 153
INTERVAL_HOURS        = 3
ALERT_INTERVAL_SEC    = int(os.getenv("ALERT_INTERVAL_SEC", "300"))  # 5 минут
ALERT_THRESHOLD_USDT  = float(os.getenv("ALERT_THRESHOLD_USDT", "100"))  # -100 USDT

# In-memory state для быстрых алертов (не пишем в БД каждые 5 минут)
_live_state: dict = {}   # name → {"balance": float, "tl": str, "htl": str, "status": str}
_live_state_ready = False  # True после первого опроса (не алертим при старте)

# ── Логирование ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("fpdf").setLevel(logging.WARNING)

# ── Metabase ───────────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))
import metabase as mb


def fetch_traders() -> list[dict]:
    rows = mb.get_client().execute_question(METABASE_QUESTION_ID)
    return rows or []


# ── State (PostgreSQL / JSON fallback) ────────────────────────────────────────

STATE_FILE = Path(__file__).parent / "trader_balances_state.json"


def _pg_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def _ensure_table():
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trader_balance_state (
                    name TEXT PRIMARY KEY,
                    balance_usdt DOUBLE PRECISION NOT NULL,
                    status TEXT NOT NULL,
                    tl TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()


def load_state() -> dict:
    if DATABASE_URL:
        try:
            _ensure_table()
            with _pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT name, balance_usdt, status, tl FROM trader_balance_state")
                    rows = cur.fetchall()
            return {r[0]: {"balance": r[1], "status": r[2], "tl": r[3] or "—"} for r in rows}
        except Exception as e:
            log.warning(f"PG load error: {e}")
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    if DATABASE_URL:
        try:
            _ensure_table()
            with _pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM trader_balance_state")
                    for name, v in state.items():
                        cur.execute(
                            "INSERT INTO trader_balance_state (name,balance_usdt,status,tl,updated_at) VALUES (%s,%s,%s,%s,NOW())",
                            (name, v["balance"], v["status"], v["tl"]),
                        )
                conn.commit()
            return
        except Exception as e:
            log.warning(f"PG save error: {e}")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def rows_to_state(rows: list[dict]) -> dict:
    state = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        if name:
            state[name] = {
                "balance": round(float(r.get("total_balance_usdt") or 0), 2),
                "status": r.get("status", ""),
                "tl": r.get("teamlead") or "—",
            }
    return state


# ── Форматирование ────────────────────────────────────────────────────────────

def _usdt(v: float) -> str:
    return f"{v:+.2f} USDT"


def _fiat(v: float, cur: str) -> str:
    return f"{v:+,.0f} {cur.upper()}"


def _badge(name: str, bal: float, prev: dict) -> str:
    if name not in prev:
        return "🆕 "
    d = bal - prev[name]["balance"]
    if d < -0.5:
        return "📉 "
    if d > 0.5:
        return "📈 "
    return ""


def _build_tree(rows: list[dict]) -> dict:
    """Строим дерево HTL → TL → [traders], сортируем по долгу."""
    tree: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        htl = (r.get("headteamlead") or "—").strip() or "—"
        tl  = (r.get("teamlead") or "—").strip() or "—"
        tree[htl][tl].append(r)
    return tree


def _tl_debt(traders: list[dict]) -> float:
    return sum(float(t.get("total_balance_usdt") or 0) for t in traders
               if float(t.get("total_balance_usdt") or 0) < 0)


def _format_trader_line(r: dict, prev: dict) -> str:
    name   = (r.get("name") or "").strip()
    bal    = float(r.get("total_balance_usdt") or 0)
    fiat   = float(r.get("balance_fiat") or 0)
    cur    = r.get("currency_fiat") or "rub"
    status = r.get("status", "")
    badge  = _badge(name, bal, prev)
    icon   = "🔴" if status == "NOT_COVERED" else "🟡"
    return (
        f"  {icon} {badge}<code>{name}</code>\n"
        f"       {_usdt(bal)}  ({_fiat(fiat, cur)})"
    )


def build_block_for_tl(
    tl: str,
    traders: list[dict],
    prev: dict,
    show_header: bool = True,
) -> str:
    """Блок для одного TL."""
    # Сортировка: NOT_COVERED сначала, внутри — по убыванию долга
    traders_sorted = sorted(
        traders,
        key=lambda r: (
            0 if r.get("status") == "NOT_COVERED" else 1,
            float(r.get("total_balance_usdt") or 0),
        ),
    )
    nc    = sum(1 for t in traders_sorted if t.get("status") == "NOT_COVERED")
    debt  = _tl_debt(traders_sorted)
    lines = []
    if show_header:
        lines.append(
            f"📋 <b>TL: {tl}</b>  "
            f"[{len(traders_sorted)} чел | 🔴 {nc} | долг: {_usdt(debt)}]"
        )
    for r in traders_sorted:
        lines.append(_format_trader_line(r, prev))
    return "\n".join(lines)


def build_block_for_htl(
    htl: str,
    tl_map: dict[str, list],
    prev: dict,
    show_header: bool = True,
) -> list[str]:
    """Список блоков (строк) для одного HTL. Может быть несколько частей."""
    total_nc   = sum(
        sum(1 for t in traders if t.get("status") == "NOT_COVERED")
        for traders in tl_map.values()
    )
    total_debt = sum(_tl_debt(traders) for traders in tl_map.values())

    parts = []
    header_lines = []
    if show_header:
        header_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        header_lines.append(
            f"🏢 <b>HTL: {htl}</b>  "
            f"[🔴 {total_nc} NOT_COVERED | долг: {_usdt(total_debt)}]"
        )
        header_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    parts.append("\n".join(header_lines))

    # Сортируем TL по долгу (самый большой долг сверху)
    sorted_tls = sorted(tl_map.items(), key=lambda kv: _tl_debt(kv[1]))
    for tl, traders in sorted_tls:
        parts.append(build_block_for_tl(tl, traders, prev))

    return parts


def build_full_report(rows: list[dict], prev: dict) -> list[str]:
    """Полный отчёт, возвращает список частей (каждая ≤ 4000 символов)."""
    tree = _build_tree(rows)
    ts   = _now_msk().strftime("%d.%m.%Y %H:%M")
    nc_total = sum(1 for r in rows if r.get("status") == "NOT_COVERED")
    debt_total = sum(
        float(r.get("total_balance_usdt") or 0) for r in rows
        if float(r.get("total_balance_usdt") or 0) < 0
    )

    header = (
        f"🚨 <b>Отрицательные балансы трейдеров</b>\n"
        f"<i>{ts}</i>\n\n"
        f"💰 <b>Суммарный долг NOT_COVERED: {_usdt(debt_total)}</b>\n"
        f"Трейдеров в минусе: {nc_total} из {len(rows)}"
    )

    chunks = [header]

    # HTL «—» (без назначения) выводим последними
    htl_order = sorted(tree.keys(), key=lambda h: (h == "—", h))

    for htl in htl_order:
        tl_map = tree[htl]
        parts = build_block_for_htl(htl, tl_map, prev)
        chunks.extend(parts)

    return _split_chunks(chunks)


def build_htl_report(htl: str, rows: list[dict], prev: dict) -> list[str]:
    tree = _build_tree(rows)
    if htl not in tree:
        return [f"HTL <b>{htl}</b> не найден.\n\nДоступные: {', '.join(sorted(tree.keys()))}"]
    ts = _now_msk().strftime("%d.%m.%Y %H:%M")
    parts = build_block_for_htl(htl, tree[htl], prev)
    parts.insert(0, f"<b>Отчёт по HTL: {htl}</b>  <i>{ts}</i>")
    return _split_chunks(parts)


def build_tl_report(tl: str, rows: list[dict], prev: dict) -> list[str]:
    # Собираем всех трейдеров этого TL (независимо от HTL)
    traders = [r for r in rows if (r.get("teamlead") or "—").strip() == tl]
    if not traders:
        all_tls = sorted({(r.get("teamlead") or "—").strip() for r in rows})
        return [f"TL <b>{tl}</b> не найден.\n\nДоступные: {', '.join(all_tls)}"]
    ts = _now_msk().strftime("%d.%m.%Y %H:%M")
    block = build_block_for_tl(tl, traders, prev)
    return _split_chunks([f"<b>Отчёт по TL: {tl}</b>  <i>{ts}</i>", block])


def build_list_report(rows: list[dict]) -> str:
    tree = _build_tree(rows)
    lines = ["📊 <b>HTL / TL — суммарные долги</b>\n"]
    htl_order = sorted(tree.keys(), key=lambda h: (h == "—", h))
    for htl in htl_order:
        tl_map = tree[htl]
        htl_debt = sum(_tl_debt(t) for t in tl_map.values())
        htl_nc   = sum(sum(1 for x in t if x.get("status")=="NOT_COVERED") for t in tl_map.values())
        lines.append(f"🏢 <b>HTL: {htl}</b>  [{_usdt(htl_debt)} | 🔴 {htl_nc}]")
        for tl, traders in sorted(tl_map.items(), key=lambda kv: _tl_debt(kv[1])):
            debt = _tl_debt(traders)
            nc   = sum(1 for t in traders if t.get("status")=="NOT_COVERED")
            lines.append(f"   📋 TL: {tl}  [{_usdt(debt)} | 🔴 {nc} | {len(traders)} чел]")
        lines.append("")
    return "\n".join(lines)


def build_alert(prev: dict, now: dict):
    alerts = []
    for name, cur in now.items():
        if cur["balance"] >= 0:
            continue
        if name not in prev:
            alerts.append(f"🆕 Новый: <code>{name}</code>  {_usdt(cur['balance'])}  TL: {cur['tl']}")
        else:
            delta = cur["balance"] - prev[name]["balance"]
            if delta < -100:
                alerts.append(
                    f"📉 <code>{name}</code>  {_usdt(prev[name]['balance'])} → {_usdt(cur['balance'])}"
                    f"  (Δ {delta:+.2f})  TL: {cur['tl']}"
                )
    if not alerts:
        return None
    ts = _now_msk().strftime("%d.%m.%Y %H:%M")
    return f"⚡️ <b>АЛЕРТ — изменения балансов</b>  <i>{ts}</i>\n\n" + "\n".join(alerts)


def _split_chunks(parts: list[str], limit: int = 4000) -> list[str]:
    """Объединяем части в сообщения до 4000 символов."""
    result = []
    cur = ""
    for part in parts:
        if not part.strip():
            continue
        sep = "\n\n" if cur else ""
        if len(cur) + len(sep) + len(part) <= limit:
            cur += sep + part
        else:
            if cur:
                result.append(cur)
            cur = part
    if cur:
        result.append(cur)
    return result or ["Нет данных"]


# ── PDF генерация ─────────────────────────────────────────────────────────────

def _find_dejavu_font() -> str:
    """Ищем DejaVuSans.ttf на известных путях."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


def generate_pdf(title: str, rows: list[dict], prev: dict) -> bytes:
    """
    Генерирует PDF с таблицей трейдеров (кириллица через DejaVuSans).
    Возвращает bytes PDF-файла.
    """
    from fpdf import FPDF

    font_path = _find_dejavu_font()
    use_unicode = bool(font_path)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()

    if use_unicode:
        pdf.add_font("DejaVu", "", font_path, uni=True)
        pdf.add_font("DejaVu", "B", font_path, uni=True)
        regular = "DejaVu"
    else:
        regular = "Helvetica"

    # Заголовок
    pdf.set_font(regular, "B", 14)
    ts = _now_msk().strftime("%d.%m.%Y %H:%M МСК")
    pdf.cell(0, 8, f"{title}   {ts}", ln=True, align="C")
    pdf.ln(3)

    # Сортируем: NOT_COVERED первые, внутри — по убыванию долга
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            0 if r.get("status") == "NOT_COVERED" else 1,
            float(r.get("total_balance_usdt") or 0),
        ),
    )

    # Группируем по HTL → TL для отображения заголовков
    tree = _build_tree(sorted_rows)
    htl_order = sorted(tree.keys(), key=lambda h: (h == "—", h))

    # Ширины колонок (A4 landscape = 297mm, margins 10+10)
    COL = {"htl": 22, "tl": 22, "name": 44, "bal_usdt": 30, "bal_fiat": 32, "cur": 12, "status": 28, "change": 22}
    col_order = ["htl", "tl", "name", "bal_usdt", "bal_fiat", "cur", "status", "change"]
    headers   = ["HTL", "TL", "Трейдер", "Баланс USDT", "Баланс фиат", "Валюта", "Статус", "Δ"]

    # Шапка таблицы
    pdf.set_font(regular, "B", 8)
    pdf.set_fill_color(50, 50, 50)
    pdf.set_text_color(255, 255, 255)
    for h, col in zip(headers, col_order):
        pdf.cell(COL[col], 7, h, border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)

    pdf.set_font(regular, "", 7)

    for htl in htl_order:
        tl_map = tree[htl]
        tl_order_sorted = sorted(tl_map.items(), key=lambda kv: _tl_debt(kv[1]))

        for tl, traders in tl_order_sorted:
            traders_sorted = sorted(
                traders,
                key=lambda r: (
                    0 if r.get("status") == "NOT_COVERED" else 1,
                    float(r.get("total_balance_usdt") or 0),
                ),
            )
            for i, r in enumerate(traders_sorted):
                name   = (r.get("name") or "").strip()
                bal    = float(r.get("total_balance_usdt") or 0)
                fiat   = float(r.get("balance_fiat") or 0)
                cur    = (r.get("currency_fiat") or "rub").upper()
                status = r.get("status", "")

                # Цвет строки
                if status == "NOT_COVERED":
                    pdf.set_fill_color(255, 220, 220)  # красноватый
                else:
                    pdf.set_fill_color(255, 250, 200)  # жёлтоватый
                fill = True

                # Δ изменение
                if name in prev:
                    delta = bal - prev[name]["balance"]
                    if abs(delta) < 0.5:
                        change_str = "="
                    elif delta < 0:
                        change_str = f"{delta:+.1f}"
                    else:
                        change_str = f"+{delta:.1f}"
                else:
                    change_str = "NEW"

                row_data = {
                    "htl":      htl,
                    "tl":       tl,
                    "name":     name,
                    "bal_usdt": f"{bal:+.2f}",
                    "bal_fiat": f"{fiat:+,.0f}",
                    "cur":      cur,
                    "status":   status,
                    "change":   change_str,
                }
                for col in col_order:
                    pdf.cell(COL[col], 5, row_data[col], border=1, align="C" if col not in ("name","htl","tl") else "L", fill=fill)
                pdf.ln()

    # Итог
    pdf.ln(3)
    pdf.set_font(regular, "B", 9)
    nc_total   = sum(1 for r in rows if r.get("status") == "NOT_COVERED")
    debt_total = sum(float(r.get("total_balance_usdt") or 0) for r in rows if float(r.get("total_balance_usdt") or 0) < 0)
    pdf.cell(0, 6, f"Итого: {len(rows)} трейдеров | NOT_COVERED: {nc_total} | Суммарный долг: {debt_total:+.2f} USDT", ln=True)

    # Возвращаем bytes
    return bytes(pdf.output())


# ── Telegram send ──────────────────────────────────────────────────────────────

async def _send(bot, chat_id: int, text: str):
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"send {chat_id}: {e}")


async def broadcast_chunks(bot, chunks: list[str]):
    for chunk in chunks:
        for cid in RECIPIENT_IDS:
            await _send(bot, cid, chunk)
            await asyncio.sleep(0.3)
        if len(chunks) > 1:
            await asyncio.sleep(0.5)


# ── Основная проверка ──────────────────────────────────────────────────────────

async def run_check(bot):
    log.info("Запуск проверки...")
    rows = await asyncio.to_thread(fetch_traders)
    if not rows:
        log.warning("Данные из Metabase не получены.")
        return

    prev  = await asyncio.to_thread(load_state)
    now   = rows_to_state(rows)

    nc = sum(1 for r in rows if r.get("status") == "NOT_COVERED")
    log.info(f"Трейдеров: {len(rows)}, NOT_COVERED: {nc}")

    alert = build_alert(prev, now)
    if alert:
        await broadcast_chunks(bot, [alert])
        await asyncio.sleep(1)

    chunks = build_full_report(rows, prev)
    await broadcast_chunks(bot, chunks)

    await asyncio.to_thread(save_state, now)
    log.info("Готово.")


# ── Клавиатура ────────────────────────────────────────────────────────────────

def make_keyboard(rows: list[dict]) -> ReplyKeyboardMarkup:
    """Строим кнопки: строка ввода → кнопки HTL и TL."""
    tree = _build_tree(rows)

    # Строка 1: главные действия
    row0 = [KeyboardButton("📊 Полный отчёт"), KeyboardButton("📋 Список HTL/TL")]

    buttons = [row0]

    # HTL блоки (по одному на строку + TL в следующей строке)
    htl_order = sorted(tree.keys(), key=lambda h: (h == "—", h))
    for htl in htl_order:
        tl_map = tree[htl]
        htl_debt = sum(_tl_debt(t) for t in tl_map.values())
        htl_nc   = sum(sum(1 for x in t if x.get("status") == "NOT_COVERED") for t in tl_map.values())
        htl_label = f"🏢 HTL: {htl}  [{htl_nc}🔴 {htl_debt:+.0f}$]"
        buttons.append([KeyboardButton(htl_label)])

        # TL внутри этого HTL — по 3 в строке
        tl_names = sorted(tl_map.keys(), key=lambda tl: _tl_debt(tl_map[tl]))
        row_tl = []
        for tl in tl_names:
            traders = tl_map[tl]
            nc = sum(1 for t in traders if t.get("status") == "NOT_COVERED")
            debt = _tl_debt(traders)
            row_tl.append(KeyboardButton(f"TL: {tl} [{nc}🔴]"))
            if len(row_tl) == 3:
                buttons.append(row_tl)
                row_tl = []
        if row_tl:
            buttons.append(row_tl)

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)


# ── Bot обработчики ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = await asyncio.to_thread(fetch_traders)
    kb = make_keyboard(rows)
    await update.message.reply_text(
        "👋 <b>Notifier — балансы трейдеров</b>\n"
        "Выбери нужный блок кнопкой ниже 👇",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def _send_pdf(bot, chat_id: int, pdf_bytes: bytes, filename: str):
    """Отправляем PDF-документ."""
    try:
        buf = io.BytesIO(pdf_bytes)
        buf.name = filename
        await bot.send_document(chat_id=chat_id, document=buf, filename=filename)
    except Exception as e:
        log.error(f"send_pdf {chat_id}: {e}")


async def handle_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обрабатываем нажатия кнопок (текстовые сообщения)."""
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    rows = await asyncio.to_thread(fetch_traders)
    prev = await asyncio.to_thread(load_state)

    if text.startswith("📊"):
        # Полный отчёт — только текст (слишком большой для PDF одним блоком)
        await update.message.reply_text("⏳ Загружаю полный отчёт...")
        chunks = build_full_report(rows, prev)
        for chunk in chunks:
            await _send(ctx.bot, chat_id, chunk)

    elif text.startswith("📋 Список"):
        # Сводка
        await update.message.reply_text("⏳ Загружаю...")
        await _send(ctx.bot, chat_id, build_list_report(rows))

    elif text.startswith("🏢 HTL:"):
        # Извлекаем имя HTL: "🏢 HTL: Alpha  [...]"
        htl = text.split("HTL:")[1].strip().split("[")[0].strip()
        await update.message.reply_text(f"⏳ Отчёт по HTL: {htl}...")
        chunks = build_htl_report(htl, rows, prev)
        for chunk in chunks:
            await _send(ctx.bot, chat_id, chunk)
        # PDF только трейдеры этого HTL
        tree = _build_tree(rows)
        htl_rows = [r for r in rows if (r.get("headteamlead") or "—").strip() == htl]
        if htl_rows:
            ts_str = _now_msk().strftime("%Y%m%d_%H%M")
            pdf_bytes = await asyncio.to_thread(generate_pdf, f"HTL: {htl}", htl_rows, prev)
            await _send_pdf(ctx.bot, chat_id, pdf_bytes, f"HTL_{htl}_{ts_str}.pdf")

    elif text.startswith("TL:"):
        # Извлекаем имя TL: "TL: Bravo [2🔴]"
        tl = text.split("TL:")[1].strip().split("[")[0].strip()
        await update.message.reply_text(f"⏳ Отчёт по TL: {tl}...")
        chunks = build_tl_report(tl, rows, prev)
        for chunk in chunks:
            await _send(ctx.bot, chat_id, chunk)
        # PDF только трейдеры этого TL
        tl_rows = [r for r in rows if (r.get("teamlead") or "—").strip() == tl]
        if tl_rows:
            ts_str = _now_msk().strftime("%Y%m%d_%H%M")
            pdf_bytes = await asyncio.to_thread(generate_pdf, f"TL: {tl}", tl_rows, prev)
            await _send_pdf(ctx.bot, chat_id, pdf_bytes, f"TL_{tl}_{ts_str}.pdf")

    else:
        # Неизвестное — показываем клавиатуру
        kb = make_keyboard(rows)
        await update.message.reply_text(
            "Выбери действие 👇", reply_markup=kb
        )


# ── Быстрые алерты (каждые N минут) ──────────────────────────────────────────

async def alert_check_job(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Запускается каждые ALERT_INTERVAL_SEC секунд.
    Алертит если баланс трейдера уходит в минус на >= ALERT_THRESHOLD_USDT USDT:
      - трейдер был в плюсе/нуле → теперь < -THRESHOLD
      - трейдер был в минусе → баланс ухудшился на >= THRESHOLD
    """
    global _live_state, _live_state_ready

    try:
        rows = await asyncio.to_thread(fetch_traders)
        if not rows:
            return

        alerts = []

        for r in rows:
            name   = (r.get("name") or "").strip()
            if not name:
                continue
            bal    = float(r.get("total_balance_usdt") or 0)
            tl     = (r.get("teamlead") or "—").strip()
            htl    = (r.get("headteamlead") or "—").strip()
            status = r.get("status", "")
            fiat   = float(r.get("balance_fiat") or 0)
            cur    = (r.get("currency_fiat") or "rub").upper()

            if not _live_state_ready:
                # Первый запуск — просто запоминаем состояние, не алертим
                _live_state[name] = {"balance": bal, "tl": tl, "htl": htl, "status": status}
                continue

            prev_bal = _live_state.get(name, {}).get("balance", 0)

            triggered = False
            reason = ""

            if prev_bal >= 0 and bal <= -ALERT_THRESHOLD_USDT:
                # Был в плюсе — ушёл в минус на 100+
                triggered = True
                reason = f"ушёл в минус: {prev_bal:+.2f} → {bal:+.2f} USDT"

            elif prev_bal < 0 and bal < prev_bal and (bal - prev_bal) <= -ALERT_THRESHOLD_USDT:
                # Был в минусе — ещё ухудшился на 100+
                triggered = True
                delta = bal - prev_bal
                reason = f"долг вырос: {prev_bal:+.2f} → {bal:+.2f} USDT (Δ {delta:+.2f})"

            if triggered:
                icon = "🔴" if status == "NOT_COVERED" else "🟡"
                fiat_str = f"{fiat:+,.0f} {cur}"
                alerts.append(
                    f"{icon} <code>{name}</code>\n"
                    f"   {reason}\n"
                    f"   Фиат: {fiat_str} | TL: {tl} | HTL: {htl}"
                )

            # Обновляем in-memory state
            _live_state[name] = {"balance": bal, "tl": tl, "htl": htl, "status": status}

        if not _live_state_ready:
            _live_state_ready = True
            log.info(f"Alert monitor: инициализирован ({len(_live_state)} трейдеров). Порог: {ALERT_THRESHOLD_USDT} USDT")
            return

        if alerts:
            ts = _now_msk().strftime("%d.%m.%Y %H:%M МСК")
            header = (
                f"⚡️ <b>МГНОВЕННЫЙ АЛЕРТ — баланс в минусе!</b>\n"
                f"<i>{ts}</i>\n\n"
            )
            text = header + "\n\n".join(alerts)
            for cid in RECIPIENT_IDS:
                await _send(ctx.bot, cid, text)
            log.info(f"Alert: отправлено {len(alerts)} алертов")

    except Exception as e:
        log.error(f"alert_check_job error: {e}", exc_info=True)


# ── Scheduler job ─────────────────────────────────────────────────────────────

async def scheduled_job(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await run_check(ctx.bot)
    except Exception as e:
        log.error(f"scheduled_job error: {e}", exc_info=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not NOTIFY_BOT_TOKEN:
        log.error("NOTIFY_BOT_TOKEN не задан! Установите env var.")
        sys.exit(1)

    log.info(f"Запуск бота... Token: {NOTIFY_BOT_TOKEN[:10]}***, Recipients: {RECIPIENT_IDS}")

    app = (
        Application.builder()
        .token(NOTIFY_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button))

    # Расписание 1: полный отчёт каждые 3 часа (первый через 30 сек)
    job_queue = app.job_queue
    job_queue.run_repeating(
        scheduled_job,
        interval=INTERVAL_HOURS * 3600,
        first=30,
        name="negative_balance_report",
    )

    # Расписание 2: быстрые алерты каждые ALERT_INTERVAL_SEC секунд
    # first=10 — инициализация состояния почти сразу, без алерта
    job_queue.run_repeating(
        alert_check_job,
        interval=ALERT_INTERVAL_SEC,
        first=10,
        name="live_alert_check",
    )

    log.info(
        f"Бот запущен. Полный отчёт каждые {INTERVAL_HOURS} ч. "
        f"Алерты каждые {ALERT_INTERVAL_SEC} сек (порог {ALERT_THRESHOLD_USDT} USDT). "
        f"Получатели: {RECIPIENT_IDS}"
    )
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
