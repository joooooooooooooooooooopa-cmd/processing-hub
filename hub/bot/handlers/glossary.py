from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from bot.config import DATA_DIR
from bot.keyboards.inline import glossary_categories_kb, glossary_page_kb, back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)

FREE_TERMS_LIMIT = 50
TERMS_PER_PAGE = 5

# Load glossary data
_terms: list[dict] = []
_categories: list[str] = []

try:
    with open(DATA_DIR / "glossary.json", "r", encoding="utf-8") as f:
        _data = json.load(f)
        _terms = _data.get("terms", [])
        _categories = sorted(set(t.get("category", "Другое") for t in _terms))
except FileNotFoundError:
    logger.warning("glossary.json not found")
except Exception as e:
    logger.error(f"Error loading glossary: {e}")


def _format_term(t: dict) -> str:
    text = (
        f"📖 <b>{t.get('term', '')}</b>"
        f" ({t.get('term_ru', '')})\n\n"
        f"📂 Категория: <i>{t.get('category', '')}</i>\n\n"
        f"📝 {t.get('definition', '')}"
    )
    if t.get("example"):
        text += f"\n\n💡 <b>Пример:</b> {t['example']}"
    if t.get("related"):
        related = ", ".join(t["related"])
        text += f"\n\n🔗 <b>Связанные:</b> {related}"
    return text


@router.message(Command("glossary"))
async def cmd_glossary(message: Message):
    if not _terms:
        await message.answer("📖 Глоссарий пока пуст.", reply_markup=back_to_menu_kb())
        return
    await message.answer(
        "📖 <b>Глоссарий процессинга</b>\n\n"
        f"Всего терминов: <b>{len(_terms)}</b>\n"
        "Выберите категорию:",
        reply_markup=glossary_categories_kb(_categories),
    )


@router.callback_query(F.data == "glossary")
async def cb_glossary(callback: CallbackQuery):
    if not _terms:
        await callback.message.edit_text("📖 Глоссарий пока пуст.", reply_markup=back_to_menu_kb())
        await callback.answer()
        return
    await callback.message.edit_text(
        "📖 <b>Глоссарий процессинга</b>\n\n"
        f"Всего терминов: <b>{len(_terms)}</b>\n"
        "Выберите категорию:",
        reply_markup=glossary_categories_kb(_categories),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gloss_cat:"))
async def cb_glossary_category(callback: CallbackQuery, is_pro: bool = False):
    category = callback.data.split(":", 1)[1]
    await _show_category_page(callback, category, 0, is_pro)


@router.callback_query(F.data.startswith("gloss_p:"))
async def cb_glossary_page(callback: CallbackQuery, is_pro: bool = False):
    parts = callback.data.split(":")
    category = parts[1]
    page = int(parts[2])
    await _show_category_page(callback, category, page, is_pro)


async def _show_category_page(callback: CallbackQuery, category: str, page: int, is_pro: bool):
    filtered = [(i, t) for i, t in enumerate(_terms) if t.get("category") == category]

    if not filtered:
        await callback.answer("Категория пуста", show_alert=True)
        return

    total_pages = (len(filtered) + TERMS_PER_PAGE - 1) // TERMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start = page * TERMS_PER_PAGE
    end = start + TERMS_PER_PAGE
    page_items = filtered[start:end]

    # Free tier: check access
    terms_on_page = []
    for idx, t in page_items:
        if not is_pro and idx >= FREE_TERMS_LIMIT:
            terms_on_page.append((idx, f"🔒 {t.get('term_ru', t.get('term', '???'))}"))
        else:
            terms_on_page.append((idx, t.get("term_ru", t.get("term", "???"))))

    text = (
        f"📂 <b>{category}</b>\n"
        f"Терминов: {len(filtered)}\n\n"
        "Выберите термин:"
    )
    if not is_pro:
        accessible = sum(1 for i, _ in filtered if i < FREE_TERMS_LIMIT)
        text += f"\n\n🆓 Доступно бесплатно: {accessible} из {len(filtered)}"

    await callback.message.edit_text(
        text,
        reply_markup=glossary_page_kb(page, total_pages, category, terms_on_page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gloss_t:"))
async def cb_glossary_term(callback: CallbackQuery, is_pro: bool = False):
    try:
        idx = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка", show_alert=True)
        return

    if idx < 0 or idx >= len(_terms):
        await callback.answer("Термин не найден", show_alert=True)
        return

    if not is_pro and idx >= FREE_TERMS_LIMIT:
        await callback.message.edit_text(
            "🔒 <b>Этот термин доступен только в PRO</b>\n\n"
            "Оформите подписку для полного доступа к глоссарию.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return

    term = _terms[idx]
    category = term.get("category", "")
    text = _format_term(term)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"◀️ {category}", callback_data=f"gloss_cat:{category}")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.inline_query()
async def inline_glossary_search(query: InlineQuery):
    text = query.query.strip().lower()
    if not text or len(text) < 2:
        await query.answer([], cache_time=1)
        return

    results = []
    for i, t in enumerate(_terms[:50]):  # Free: only first 50 in inline
        term_lower = t.get("term", "").lower()
        term_ru_lower = t.get("term_ru", "").lower()
        if text in term_lower or text in term_ru_lower:
            content = InputTextMessageContent(message_text=_format_term(t))
            results.append(
                InlineQueryResultArticle(
                    id=str(i),
                    title=t.get("term", ""),
                    description=t.get("term_ru", ""),
                    input_message_content=content,
                )
            )
        if len(results) >= 10:
            break

    await query.answer(results, cache_time=30)
