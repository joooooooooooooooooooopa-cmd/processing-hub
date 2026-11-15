import re
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.services.bin_api import lookup_bin
from bot.keyboards.inline import back_to_menu_kb, subscription_kb

router = Router()
logger = logging.getLogger(__name__)

BIN_PATTERN = re.compile(r"^\d{6,8}$")


class BinStates(StatesGroup):
    waiting_bin = State()


@router.message(Command("bin"))
async def cmd_bin(message: Message, state: FSMContext, is_pro: bool = False):
    if not is_pro:
        await message.answer(
            "🔍 <b>BIN Checker</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.\n"
            "Оформите подписку для доступа.",
            reply_markup=subscription_kb(),
        )
        return
    await state.set_state(BinStates.waiting_bin)
    await message.answer(
        "🔍 <b>BIN Checker</b>\n\n"
        "Отправьте первые 6-8 цифр номера карты (BIN):",
        reply_markup=back_to_menu_kb(),
    )


@router.callback_query(F.data == "bin_check")
async def cb_bin_check(callback: CallbackQuery, state: FSMContext, is_pro: bool = False):
    if not is_pro:
        await callback.message.edit_text(
            "🔍 <b>BIN Checker</b>\n\n"
            "🔒 Этот раздел доступен только для <b>PRO</b> пользователей.",
            reply_markup=subscription_kb(),
        )
        await callback.answer()
        return
    await state.set_state(BinStates.waiting_bin)
    await callback.message.edit_text(
        "🔍 <b>BIN Checker</b>\n\n"
        "Отправьте первые 6-8 цифр номера карты (BIN):",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


@router.message(BinStates.waiting_bin)
async def process_bin(message: Message, state: FSMContext):
    text = message.text.strip() if message.text else ""

    if not BIN_PATTERN.match(text):
        await message.answer(
            "⚠️ Некорректный формат. Отправьте 6-8 цифр BIN.\n"
            "Пример: <code>453275</code>",
            reply_markup=back_to_menu_kb(),
        )
        return

    await state.clear()
    wait_msg = await message.answer("🔍 Проверяю BIN...")

    try:
        result = await lookup_bin(text)
    except Exception as e:
        logger.error(f"BIN lookup error: {e}")
        await wait_msg.edit_text(
            "❌ Ошибка при проверке BIN. Попробуйте позже.",
            reply_markup=back_to_menu_kb(),
        )
        return

    if not result:
        await wait_msg.edit_text(
            f"❌ BIN <code>{text}</code> не найден в базе.\n"
            "Проверьте правильность ввода.",
            reply_markup=back_to_menu_kb(),
        )
        return

    prepaid_text = "Да" if result.get("prepaid") else "Нет" if result.get("prepaid") is False else "N/A"

    response = (
        f"🔍 <b>Результат проверки BIN</b>\n\n"
        f"💳 BIN: <code>{result['bin']}</code>\n"
        f"🏦 Банк: <b>{result.get('bank', 'N/A')}</b>\n"
        f"🌍 Страна: {result.get('country_emoji', '')} {result.get('country', 'N/A')}\n"
        f"📋 Тип: {result.get('card_type', 'N/A')}\n"
        f"💎 Бренд: {result.get('brand', 'N/A')}\n"
        f"📂 Категория: {result.get('category', 'N/A')}\n"
        f"🔄 Предоплаченная: {prepaid_text}"
    )

    await wait_msg.edit_text(response, reply_markup=back_to_menu_kb())
