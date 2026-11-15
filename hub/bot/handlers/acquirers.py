from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.config import DATA_DIR
from bot.keyboards.inline import acquirer_filter_kb, acquirer_list_kb, back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)

_acquirers: list[dict] = []

try:
    with open(DATA_DIR / "acquirers.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _acquirers = _data.get("acquirers", [])
except FileNotFoundError:
    logger.warning("acquirers.json not found")
except Exception as e:
    logger.error(f"Error loading acquirers: {e}")


def _risk_emoji(level: str) -> str:
    if not level:
        return "⚪"
    l = level.lower()
    if l == "low":
        return "🟢"
    if l == "medium":
        return "🟡"
    if l == "high":
        return "🔴"
    return "⚪"


def _format_acquirer(a: dict) -> str:
    text = (
        f"🏦 <b>{a.get('name', '')}</b>\n\n"
        f"📋 Тип: {a.get('type', 'N/A')}\n"
        f"{_risk_emoji(a.get('risk_level'))} Уровень риска: {a.get('risk_level', 'N/A')}\n"
        f"⭐ Рейтинг: {a.get('rating', 'N/A')}\n\n"
    )
    if a.get("verticals"):
        text += f"🎯 <b>Вертикали:</b> {', '.join(a['verticals'])}\n"
    if a.get("regions"):
        text += f"🌍 <b>Регионы:</b> {', '.join(a['regions'])}\n"
    text += "\n"
    if a.get("min_volume"):
        text += f"💰 Мин. объём: {a['min_volume']}\n"
    if a.get("rolling_reserve"):
        text += f"🔒 Rolling Reserve: {a['rolling_reserve']}\n"
    if a.get("chargeback_threshold"):
        text += f"⚠️ Chargeback порог: {a['chargeback_threshold']}\n"
    if a.get("settlement"):
        text += f"📆 Расчёт: {a['settlement']}\n"
    if a.get("description"):
        text += f"\n📝 {a['description']}\n"
    if a.get("pros"):
        text += "\n✅ <b>Плюсы:</b>\n" + "\n".join(f"  • {p}" for p in a["pros"])
    if a.get("cons"):
        text += "\n\n❌ <b>Минусы:</b>\n" + "\n".join(f"  • {c}" for c in a["cons"])
    return text


@router.message(Command("acquirers"))
async def cmd_acquirers(message: Message, is_pro: bool = False):
    if not is_pro:
        await message.answer(
            "🏦 <b>Эквайеры и PSP</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.\n"
            "Оформите подписку для доступа к базе эквайеров.",
            reply_markup=subscription_kb(),
        )
        return
    await message.answer(
        "🏦 <b>Эквайеры и PSP</b>\n\n"
        f"Всего в базе: <b>{len(_acquirers)}</b>\n\n"
        "Фильтруйте по вертикали или уровню риска:",
        reply_markup=acquirer_filter_kb(),
    )


@router.callback_query(F.data == "acquirers")
async def cb_acquirers(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.message.edit_text(
            "🏦 <b>Эквайеры и PSP</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "🏦 <b>Эквайеры и PSP</b>\n\n"
        f"Всего в базе: <b>{len(_acquirers)}</b>\n\n"
        "Фильтруйте по вертикали или уровню риска:",
        reply_markup=acquirer_filter_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acq_v:"))
async def cb_acq_vertical(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return
    vertical = callback.data.split(":", 1)[1]
    filtered = [
        (i, a["name"]) for i, a in enumerate(_acquirers)
        if vertical in [v.lower() for v in (a.get("verticals") or [])]
    ]
    if not filtered:
        await callback.answer("Нет эквайеров для этой вертикали", show_alert=True)
        return
    await callback.message.edit_text(
        f"🏦 <b>Эквайеры: {vertical.capitalize()}</b>\n"
        f"Найдено: {len(filtered)}",
        reply_markup=acquirer_list_kb(filtered),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acq_r:"))
async def cb_acq_risk(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return
    level = callback.data.split(":", 1)[1]
    filtered = [
        (i, a["name"]) for i, a in enumerate(_acquirers)
        if (a.get("risk_level") or "").lower() == level
    ]
    if not filtered:
        await callback.answer("Нет эквайеров с таким уровнем риска", show_alert=True)
        return
    await callback.message.edit_text(
        f"🏦 <b>Эквайеры: Risk {level.capitalize()}</b>\n"
        f"Найдено: {len(filtered)}",
        reply_markup=acquirer_list_kb(filtered),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acq:"))
async def cb_acq_detail(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return
    try:
        idx = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return

    if idx < 0 or idx >= len(_acquirers):
        await callback.answer("Эквайер не найден", show_alert=True)
        return

    text = _format_acquirer(_acquirers[idx])
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Фильтры", callback_data="acquirers"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
