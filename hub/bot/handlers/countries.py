from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.config import DATA_DIR
from bot.keyboards.inline import (
    country_regions_kb, country_verticals_kb, country_list_kb,
    back_to_menu_kb, subscription_kb,
)

router = Router()
logger = logging.getLogger(__name__)

FREE_COUNTRY_LIMIT = 3

_countries: list[dict] = []
_regions: list[str] = []
_country_by_code: dict[str, dict] = {}

try:
    with open(DATA_DIR / "countries.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _countries = _data.get("countries", [])
        _regions = sorted(set(c.get("region", "Other") for c in _countries))
        _country_by_code = {c["code"]: c for c in _countries if "code" in c}
except FileNotFoundError:
    logger.warning("countries.json not found")
except Exception as e:
    logger.error(f"Error loading countries: {e}")

_free_codes: set[str] = set()
if _countries:
    _free_codes = {c["code"] for c in _countries[:FREE_COUNTRY_LIMIT]}


def _status_emoji(val: str) -> str:
    if not val:
        return "⚪"
    v = val.lower()
    if v in ("legal", "allowed", "yes", "regulated"):
        return "🟢"
    if v in ("restricted", "partially", "gray", "grey"):
        return "🟡"
    if v in ("banned", "illegal", "no", "prohibited"):
        return "🔴"
    return "⚪"


def _get_status(c: dict, vertical: str) -> str:
    v = c.get(vertical)
    if isinstance(v, dict):
        return v.get("status", "N/A")
    return str(v) if v else "N/A"


def _get_vertical_info(c: dict, vertical: str) -> str:
    v = c.get(vertical)
    if isinstance(v, dict):
        status = v.get("status", "N/A")
        notes = v.get("notes", "")
        license_ = v.get("license", "")
        parts = [status]
        if license_:
            parts.append(f"({license_})")
        if notes:
            parts.append(f"— {notes}")
        return " ".join(parts)
    return str(v) if v else "N/A"


def _format_country(c: dict) -> str:
    text = (
        f"🌍 <b>{c.get('name_ru', c.get('name', ''))}</b> ({c.get('code', '')})\n"
        f"📍 Регион: {c.get('region', 'N/A')}\n"
        f"⚠️ Уровень риска: {c.get('risk_level', 'N/A')}\n\n"
        f"<b>Вертикали:</b>\n"
        f"  {_status_emoji(_get_status(c, 'gambling'))} Gambling: {_get_vertical_info(c, 'gambling')}\n"
        f"  {_status_emoji(_get_status(c, 'crypto'))} Crypto: {_get_vertical_info(c, 'crypto')}\n"
        f"  {_status_emoji(_get_status(c, 'forex'))} Forex: {_get_vertical_info(c, 'forex')}\n"
        f"  {_status_emoji(_get_status(c, 'adult'))} Adult: {_get_vertical_info(c, 'adult')}\n"
        f"  {_status_emoji(_get_status(c, 'nutra'))} Nutra: {_get_vertical_info(c, 'nutra')}\n\n"
        f"🏦 <b>Банковская система:</b> {c.get('banking_system', 'N/A')}"
    )
    acquirers = c.get("popular_acquirers")
    if acquirers:
        text += "\n\n💳 <b>Популярные эквайеры:</b>\n" + "\n".join(f"  • {a}" for a in acquirers)
    return text


@router.message(Command("country"))
async def cmd_country(message: Message):
    if not _countries:
        await message.answer("🌍 Данные по странам пока не загружены.", reply_markup=back_to_menu_kb())
        return
    await message.answer(
        "🌍 <b>Страны и платёжная среда</b>\n\n"
        f"Всего стран: <b>{len(_countries)}</b>\n\n"
        "Выберите регион или отправьте название страны текстом:",
        reply_markup=country_regions_kb(_regions),
    )


@router.callback_query(F.data == "countries")
async def cb_countries(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌍 <b>Страны и платёжная среда</b>\n\n"
        f"Всего стран: <b>{len(_countries)}</b>\n\n"
        "Выберите регион или отправьте название страны текстом:",
        reply_markup=country_regions_kb(_regions),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("c_reg:"))
async def cb_country_region(callback: CallbackQuery):
    region = callback.data.split(":", 1)[1]
    filtered = [(c["code"], c.get("name_ru", c.get("name", ""))) for c in _countries if c.get("region") == region]
    if not filtered:
        await callback.answer("Нет стран в этом регионе", show_alert=True)
        return
    await callback.message.edit_text(
        f"🌍 <b>Регион: {region}</b>\n"
        f"Стран: {len(filtered)}\n\n"
        "Выберите страну:",
        reply_markup=country_list_kb(filtered),
    )
    await callback.answer()


@router.callback_query(F.data == "c_verts")
async def cb_country_verts(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌍 <b>Фильтр по вертикали</b>\n\n"
        "Выберите вертикаль для просмотра статуса стран:",
        reply_markup=country_verticals_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("c_vert:"))
async def cb_country_vertical(callback: CallbackQuery):
    vertical = callback.data.split(":", 1)[1]
    vertical_names = {
        "gambling": "Gambling",
        "crypto": "Crypto",
        "forex": "Forex",
        "adult": "Adult",
        "nutra": "Nutra",
    }
    display = vertical_names.get(vertical, vertical)

    allowed = []
    for c in _countries:
        st = _get_status(c, vertical)
        if st.lower() in ("legal", "allowed", "yes", "regulated"):
            allowed.append((c["code"], f"🟢 {c.get('name_ru', c.get('name', ''))}"))

    if not allowed:
        await callback.answer("Нет стран с разрешённым статусом", show_alert=True)
        return

    await callback.message.edit_text(
        f"🌍 <b>{display}</b> — разрешено:\n"
        f"Стран: {len(allowed)}",
        reply_markup=country_list_kb(allowed),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("c:"))
async def cb_country_detail(callback: CallbackQuery, is_pro: bool = False):
    code = callback.data.split(":", 1)[1]
    country = _country_by_code.get(code)
    if not country:
        await callback.answer("Страна не найдена", show_alert=True)
        return

    if not is_pro and code not in _free_codes:
        await callback.message.edit_text(
            "🔒 <b>Эта страна доступна только в PRO</b>\n\n"
            f"Бесплатно доступно {FREE_COUNTRY_LIMIT} стран.\n"
            "Оформите подписку для полного доступа.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return

    text = _format_country(country)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Регионы", callback_data="countries"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
