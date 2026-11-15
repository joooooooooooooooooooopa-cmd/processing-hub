from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.config import DATA_DIR
from bot.keyboards.inline import aml_region_kb, back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)

_regions: list[dict] = []
_region_names: list[str] = []
_sanctions_lists: list[str] = []
_red_flags: list[str] = []

try:
    with open(DATA_DIR / "aml.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _regions = _data.get("regions", [])
        _region_names = [r.get("name_ru", r.get("name", r.get("region", ""))) for r in _regions]
        _sanctions_lists = _data.get("global_sanctions_lists", [])
        _red_flags = _data.get("red_flags_universal", [])
except FileNotFoundError:
    logger.warning("aml.json not found")
except Exception as e:
    logger.error(f"Error loading aml: {e}")


def _format_region(r: dict) -> str:
    name = r.get("name_ru", r.get("name", r.get("region", "")))
    text = f"🛡 <b>AML/KYC: {name}</b>\n\n"

    if r.get("regulator"):
        text += f"🏛 <b>Регулятор:</b> {r['regulator']}\n"
    if r.get("framework"):
        text += f"📜 <b>Фреймворк:</b> {r['framework']}\n"
    if r.get("main_law"):
        text += f"📜 <b>Основной закон:</b> {r['main_law']}\n"
    text += "\n"

    if r.get("kyc_levels"):
        text += "👤 <b>Уровни KYC:</b>\n"
        for level in r["kyc_levels"]:
            if isinstance(level, dict):
                lname = level.get("level", "")
                limit = level.get("limit", "")
                reqs = level.get("requirements", [])
                if isinstance(reqs, list):
                    reqs_str = ", ".join(reqs)
                else:
                    reqs_str = str(reqs)
                text += f"  • <b>{lname}</b>"
                if limit:
                    text += f" (до {limit})"
                text += f": {reqs_str}\n"
            else:
                text += f"  • {level}\n"
        text += "\n"

    if r.get("aml_requirements"):
        text += "📋 <b>AML требования:</b>\n"
        for req in r["aml_requirements"]:
            text += f"  • {req}\n"
        text += "\n"

    if r.get("requirements"):
        text += "📋 <b>Требования:</b>\n"
        for req in r["requirements"]:
            text += f"  • {req}\n"
        text += "\n"

    if r.get("sanctions_lists"):
        text += "🔍 <b>Санкционные списки:</b>\n"
        for s in r["sanctions_lists"]:
            text += f"  • {s}\n"
        text += "\n"

    if r.get("red_flags"):
        text += "🚩 <b>Красные флаги:</b>\n"
        for flag in r["red_flags"]:
            text += f"  • {flag}\n"
        text += "\n"

    if r.get("penalties"):
        pen = r["penalties"]
        if isinstance(pen, list):
            text += "⚖️ <b>Штрафы:</b>\n"
            for p in pen:
                text += f"  • {p}\n"
        else:
            text += f"⚖️ <b>Штрафы:</b> {pen}\n"

    if r.get("notes"):
        text += f"\n📝 {r['notes']}"

    return text


@router.message(Command("aml"))
async def cmd_aml(message: Message, is_pro: bool = False):
    if not is_pro:
        await message.answer(
            "🛡 <b>AML/KYC</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.\n"
            "Оформите подписку для доступа.",
            reply_markup=subscription_kb(),
        )
        return
    text = "🛡 <b>AML/KYC требования по регионам</b>\n\n"
    if _sanctions_lists:
        text += "📋 <b>Глобальные санкционные списки:</b>\n"
        for s in _sanctions_lists:
            text += f"  • {s}\n"
        text += "\n"
    text += "Выберите регион:"
    await message.answer(text, reply_markup=aml_region_kb(_region_names))


@router.callback_query(F.data == "aml")
async def cb_aml(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.message.edit_text(
            "🛡 <b>AML/KYC</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return
    text = "🛡 <b>AML/KYC требования по регионам</b>\n\n"
    if _sanctions_lists:
        text += "📋 <b>Глобальные санкционные списки:</b>\n"
        for s in _sanctions_lists:
            text += f"  • {s}\n"
        text += "\n"
    text += "Выберите регион:"
    await callback.message.edit_text(text, reply_markup=aml_region_kb(_region_names))
    await callback.answer()


@router.callback_query(F.data.startswith("aml_r:"))
async def cb_aml_region(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return

    region_name = callback.data.split(":", 1)[1]
    region_data = None
    for r in _regions:
        name = r.get("name", r.get("region", ""))
        if name == region_name:
            region_data = r
            break

    if not region_data:
        await callback.answer("Регион не найден", show_alert=True)
        return

    text = _format_region(region_data)

    if _red_flags:
        text += "\n\n🚩 <b>Универсальные красные флаги:</b>\n"
        for flag in _red_flags[:5]:
            text += f"  • {flag}\n"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Регионы", callback_data="aml"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
