from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.config import DATA_DIR
from bot.keyboards.inline import platform_type_kb, platform_list_kb, back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)

_platforms: list[dict] = []

try:
    with open(DATA_DIR / "platforms.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _platforms = _data.get("platforms", [])
except FileNotFoundError:
    logger.warning("platforms.json not found")
except Exception as e:
    logger.error(f"Error loading platforms: {e}")

TYPE_NAMES = {
    "exchange": "Биржи",
    "p2p": "P2P",
    "crypto_card": "Крипто-карты",
    "processing": "Процессинг",
}


def _format_platform_short(p: dict) -> str:
    return f"💻 <b>{p.get('name', '')}</b> — {p.get('type', '')}"


def _format_platform_full(p: dict) -> str:
    text = (
        f"💻 <b>{p.get('name', '')}</b>\n\n"
        f"📋 Тип: {TYPE_NAMES.get(p.get('type', ''), p.get('type', 'N/A'))}\n"
        f"🌍 Регистрация: {p.get('registration_country', 'N/A')}\n"
        f"⚠️ Уровень риска: {p.get('risk_level', 'N/A')}\n"
    )
    if p.get("website"):
        text += f"🔗 Сайт: {p['website']}\n"
    if p.get("services"):
        text += "\n🛠 <b>Сервисы:</b>\n" + "\n".join(f"  • {s}" for s in p["services"])
    if p.get("notes"):
        text += f"\n\n📝 {p['notes']}"
    return text


@router.message(Command("platforms"))
async def cmd_platforms(message: Message, is_pro: bool = False):
    if not is_pro:
        await message.answer(
            "💻 <b>Платформы</b>\n\n"
            "🔒 Полная информация доступна только в <b>PRO</b>.\n"
            "Оформите подписку для доступа.",
            reply_markup=subscription_kb(),
        )
        return
    await message.answer(
        "💻 <b>Платформы</b>\n\n"
        f"Всего в базе: <b>{len(_platforms)}</b>\n\n"
        "Выберите тип:",
        reply_markup=platform_type_kb(),
    )


@router.callback_query(F.data == "platforms")
async def cb_platforms(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.message.edit_text(
            "💻 <b>Платформы</b>\n\n"
            "🔒 Полная информация доступна только в <b>PRO</b>.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "💻 <b>Платформы</b>\n\n"
        f"Всего в базе: <b>{len(_platforms)}</b>\n\n"
        "Выберите тип:",
        reply_markup=platform_type_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plat_t:"))
async def cb_platform_type(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return
    ptype = callback.data.split(":", 1)[1]
    filtered = [
        (i, p["name"]) for i, p in enumerate(_platforms)
        if p.get("type", "").lower() == ptype
    ]
    display_name = TYPE_NAMES.get(ptype, ptype)
    if not filtered:
        await callback.answer("Нет платформ этого типа", show_alert=True)
        return
    await callback.message.edit_text(
        f"💻 <b>{display_name}</b>\n"
        f"Найдено: {len(filtered)}",
        reply_markup=platform_list_kb(filtered),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plat:"))
async def cb_platform_detail(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return
    try:
        idx = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return

    if idx < 0 or idx >= len(_platforms):
        await callback.answer("Платформа не найдена", show_alert=True)
        return

    text = _format_platform_full(_platforms[idx])
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Типы", callback_data="platforms"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ]
    ])
    await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()
