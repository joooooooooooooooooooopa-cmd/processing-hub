from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from bot.services.news_parser import get_latest_news
from bot.keyboards.inline import back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)


def _format_news_free(items: list[dict]) -> str:
    if not items:
        return "📰 Новостей пока нет. Попробуйте позже."
    text = "📰 <b>Последние новости</b>\n\n"
    for i, item in enumerate(items[:10], 1):
        source = item.get("source", "")
        date = item.get("date", "")
        title = item.get("title", "Без заголовка")
        text += f"{i}. <b>{title}</b>\n"
        if source or date:
            text += f"   <i>{source}"
            if date:
                text += f" | {date}"
            text += "</i>\n"
        text += "\n"
    text += "\n🔒 Полные статьи с аналитикой доступны в <b>PRO</b>."
    return text


def _format_news_pro(items: list[dict]) -> str:
    if not items:
        return "📰 Новостей пока нет. Попробуйте позже."
    text = "📰 <b>Последние новости</b>\n\n"
    for i, item in enumerate(items[:10], 1):
        source = item.get("source", "")
        date = item.get("date", "")
        title = item.get("title", "Без заголовка")
        summary = item.get("summary", "")
        url = item.get("url", "")
        text += f"{i}. <b>{title}</b>\n"
        if source or date:
            text += f"   <i>{source}"
            if date:
                text += f" | {date}"
            text += "</i>\n"
        if summary:
            text += f"   {summary}\n"
        if url:
            text += f"   🔗 <a href=\"{url}\">Читать</a>\n"
        text += "\n"
    return text


@router.message(Command("news"))
async def cmd_news(message: Message, is_pro: bool = False):
    wait_msg = await message.answer("📰 Загружаю новости...")
    try:
        items = await get_latest_news()
    except Exception as e:
        logger.error(f"News fetch error: {e}")
        await wait_msg.edit_text(
            "❌ Ошибка загрузки новостей. Попробуйте позже.",
            reply_markup=back_to_menu_kb(),
        )
        return

    if is_pro:
        text = _format_news_pro(items)
        await wait_msg.edit_text(text, reply_markup=back_to_menu_kb(), disable_web_page_preview=True)
    else:
        text = _format_news_free(items)
        await wait_msg.edit_text(text, reply_markup=subscription_kb())


@router.callback_query(F.data == "news")
async def cb_news(callback: CallbackQuery, is_pro: bool = False):
    await callback.answer()
    try:
        items = await get_latest_news()
    except Exception as e:
        logger.error(f"News fetch error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка загрузки новостей. Попробуйте позже.",
            reply_markup=back_to_menu_kb(),
        )
        return

    if is_pro:
        text = _format_news_pro(items)
        await callback.message.edit_text(text, reply_markup=back_to_menu_kb(), disable_web_page_preview=True)
    else:
        text = _format_news_free(items)
        await callback.message.edit_text(text, reply_markup=subscription_kb())
