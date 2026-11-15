from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.config import DATA_DIR
from bot.keyboards.inline import traffic_vertical_kb, back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)

_verticals: list[dict] = []

try:
    with open(DATA_DIR / "traffic_map.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _verticals = _data.get("verticals", [])
except FileNotFoundError:
    logger.warning("traffic_map.json not found")
except Exception as e:
    logger.error(f"Error loading traffic_map: {e}")


def _format_geo(g) -> str:
    if isinstance(g, dict):
        parts = [g.get("country", "")]
        if g.get("share"):
            parts.append(f"({g['share']})")
        if g.get("avg_deposit"):
            parts.append(f"— avg ${g['avg_deposit']}" if not str(g['avg_deposit']).startswith('$') else f"— avg {g['avg_deposit']}")
        return " ".join(parts)
    return str(g)


def _format_vertical(v: dict) -> str:
    text = (
        f"📊 <b>{v.get('name_ru', v.get('vertical', ''))}</b>\n\n"
    )
    if v.get("top_geos"):
        text += "🌍 <b>Топ ГЕО:</b>\n" + "\n".join(f"  • {_format_geo(g)}" for g in v["top_geos"]) + "\n\n"
    if v.get("traffic_sources"):
        text += "📡 <b>Источники трафика:</b>\n" + "\n".join(f"  • {s}" for s in v["traffic_sources"]) + "\n\n"
    if v.get("avg_check"):
        text += f"💰 <b>Средний чек:</b> {v['avg_check']}\n"
    if v.get("conversion_rate"):
        text += f"📈 <b>Конверсия:</b> {v['conversion_rate']}\n"
    if v.get("payment_methods"):
        text += f"💳 <b>Методы оплаты:</b> {', '.join(v['payment_methods'])}\n"
    if v.get("seasonality"):
        text += f"\n📅 <b>Сезонность:</b> {v['seasonality']}\n"
    if v.get("notes"):
        text += f"\n📝 {v['notes']}"
    return text


@router.message(Command("traffic"))
async def cmd_traffic(message: Message, is_pro: bool = False):
    if not is_pro:
        await message.answer(
            "📊 <b>Карта трафика</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.\n"
            "Оформите подписку для доступа.",
            reply_markup=subscription_kb(),
        )
        return
    await message.answer(
        "📊 <b>Карта трафика по вертикалям</b>\n\n"
        "Выберите вертикаль:",
        reply_markup=traffic_vertical_kb(),
    )


@router.callback_query(F.data == "traffic")
async def cb_traffic(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.message.edit_text(
            "📊 <b>Карта трафика</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "📊 <b>Карта трафика по вертикалям</b>\n\n"
        "Выберите вертикаль:",
        reply_markup=traffic_vertical_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("traf:"))
async def cb_traffic_vertical(callback: CallbackQuery, is_pro: bool = False):
    if not is_pro:
        await callback.answer("Доступно только в PRO", show_alert=True)
        return

    vert_key = callback.data.split(":", 1)[1]
    vert_data = None
    for v in _verticals:
        if v.get("vertical", "").lower() == vert_key:
            vert_data = v
            break

    if not vert_data:
        await callback.answer("Вертикаль не найдена", show_alert=True)
        return

    text = _format_vertical(vert_data)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Вертикали", callback_data="traffic"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
        ]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
