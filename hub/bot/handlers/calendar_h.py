from __future__ import annotations

import json
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.config import DATA_DIR
from bot.keyboards.inline import calendar_month_kb, back_to_menu_kb

router = Router()
logger = logging.getLogger(__name__)

_months: list[dict] = []

try:
    with open(DATA_DIR / "calendar.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _months = _data.get("months", [])
except FileNotFoundError:
    logger.warning("calendar.json not found")
except Exception as e:
    logger.error(f"Error loading calendar: {e}")

COLOR_EMOJI = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
}

MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель",
    "Май", "Июнь", "Июль", "Август",
    "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _format_month(m: dict) -> str:
    num = m.get("month", 0)
    name = m.get("name", MONTH_NAMES[num] if 1 <= num <= 12 else "???")
    text = f"📅 <b>{name}</b>\n\n"

    verticals = m.get("verticals", {})
    if not verticals:
        text += "<i>Нет данных по вертикалям</i>"
        return text

    for vert_key, info in verticals.items():
        color = info.get("color", "")
        emoji = COLOR_EMOJI.get(color, "⚪")
        notes = info.get("notes", "")
        text += f"{emoji} <b>{vert_key.capitalize()}</b>"
        if notes:
            text += f" — {notes}"
        text += "\n"

    return text


@router.message(Command("calendar"))
async def cmd_calendar(message: Message):
    if not _months:
        await message.answer("📅 Календарь пока пуст.", reply_markup=back_to_menu_kb())
        return

    current_num = datetime.now().month
    current_month = None
    for m in _months:
        if m.get("month") == current_num:
            current_month = m
            break

    text = "📅 <b>Календарь сезонности вертикалей</b>\n\n"
    if current_month:
        text += f"<b>Текущий месяц:</b>\n\n{_format_month(current_month)}\n\n"
    text += "Выберите месяц для просмотра:"

    await message.answer(text, reply_markup=calendar_month_kb())


@router.callback_query(F.data == "calendar")
async def cb_calendar(callback: CallbackQuery):
    if not _months:
        await callback.message.edit_text("📅 Календарь пока пуст.", reply_markup=back_to_menu_kb())
        await callback.answer()
        return

    current_num = datetime.now().month
    current_month = None
    for m in _months:
        if m.get("month") == current_num:
            current_month = m
            break

    text = "📅 <b>Календарь сезонности вертикалей</b>\n\n"
    if current_month:
        text += f"<b>Текущий месяц:</b>\n\n{_format_month(current_month)}\n\n"
    text += "Выберите месяц для просмотра:"

    await callback.message.edit_text(text, reply_markup=calendar_month_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("cal_m:"))
async def cb_calendar_month(callback: CallbackQuery):
    try:
        num = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return

    month_data = None
    for m in _months:
        if m.get("month") == num:
            month_data = m
            break

    if not month_data:
        await callback.answer("Нет данных за этот месяц", show_alert=True)
        return

    text = _format_month(month_data)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Все месяцы", callback_data="calendar"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ]
    ])

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
