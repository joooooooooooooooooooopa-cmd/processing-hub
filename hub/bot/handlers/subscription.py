import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery
from bot.config import PRO_PRICE_STARS, PRO_DURATION_DAYS
from bot.services.database import check_subscription, add_subscription
from bot.services.payment import create_pro_invoice, validate_payment_payload
from bot.keyboards.inline import subscription_kb, back_to_menu_kb

router = Router()
logger = logging.getLogger(__name__)

PRO_BENEFITS_TEXT = (
    "⭐ <b>ProcessingHub PRO</b>\n\n"
    f"Стоимость: <b>{PRO_PRICE_STARS} Stars</b> / {PRO_DURATION_DAYS} дней\n\n"
    "<b>Что входит:</b>\n"
    "  ✅ Безлимитные запросы (без дневного лимита)\n"
    "  ✅ Полный глоссарий (все термины)\n"
    "  ✅ Все страны и регионы\n"
    "  ✅ База эквайеров и PSP\n"
    "  ✅ BIN Checker\n"
    "  ✅ Полные новости с аналитикой\n"
    "  ✅ Все платформы\n"
    "  ✅ Карта трафика\n"
    "  ✅ AML/KYC требования\n"
)


@router.message(Command("subscribe", "pro"))
async def cmd_subscribe(message: Message):
    is_pro = await check_subscription(message.from_user.id)
    if is_pro:
        await message.answer(
            "✅ <b>У вас активна PRO подписка!</b>\n\n"
            "Все разделы и функции доступны без ограничений.",
            reply_markup=back_to_menu_kb(),
        )
        return
    await message.answer(PRO_BENEFITS_TEXT, reply_markup=subscription_kb())


@router.callback_query(F.data == "subscribe")
async def cb_subscribe(callback: CallbackQuery):
    is_pro = await check_subscription(callback.from_user.id)
    if is_pro:
        await callback.message.edit_text(
            "✅ <b>У вас активна PRO подписка!</b>\n\n"
            "Все разделы и функции доступны без ограничений.",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(PRO_BENEFITS_TEXT, reply_markup=subscription_kb())
    await callback.answer()


@router.callback_query(F.data == "buy_pro")
async def cb_buy_pro(callback: CallbackQuery):
    is_pro = await check_subscription(callback.from_user.id)
    if is_pro:
        await callback.answer("У вас уже есть PRO подписка!", show_alert=True)
        return

    try:
        invoice_data = create_pro_invoice()
        await callback.message.answer_invoice(**invoice_data)
        await callback.answer()
    except Exception as e:
        logger.error(f"Invoice creation error: {e}")
        await callback.answer("Ошибка создания платежа. Попробуйте позже.", show_alert=True)


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    if validate_payment_payload(query.invoice_payload):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Некорректный платёж. Попробуйте снова.")


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    user_id = message.from_user.id
    payment = message.successful_payment
    payment_id = payment.telegram_payment_charge_id if payment else None

    try:
        await add_subscription(user_id, payment_id=payment_id)
        logger.info(f"PRO subscription activated for user {user_id}, payment_id={payment_id}")
    except Exception as e:
        logger.error(f"Error saving subscription for {user_id}: {e}")

    await message.answer(
        "🎉 <b>Поздравляем!</b>\n\n"
        f"PRO подписка активирована на <b>{PRO_DURATION_DAYS} дней</b>!\n\n"
        "Теперь вам доступны все разделы без ограничений.\n"
        "Приятного использования! 🚀",
        reply_markup=back_to_menu_kb(),
    )
