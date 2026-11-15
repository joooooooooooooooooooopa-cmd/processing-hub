from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from bot.config import ADMIN_ID
from bot.services.database import add_user, check_subscription, add_subscription
from bot.keyboards.inline import main_menu_kb

router = Router()

WELCOME_TEXT = (
    "🏦 <b>ProcessingHub Bot</b>\n\n"
    "Ваш справочник по миру процессинга и платежей.\n\n"
    "📖 <b>Глоссарий</b> — термины процессинга\n"
    "🌍 <b>Страны</b> — платёжная инфраструктура по странам\n"
    "📅 <b>Календарь</b> — сезонность вертикалей\n"
    "🏦 <b>Эквайеры</b> — база эквайеров и PSP\n"
    "🔍 <b>BIN Checker</b> — проверка BIN карт\n"
    "📰 <b>Новости</b> — новости финтех и регуляции\n"
    "💻 <b>Платформы</b> — биржи, P2P, процессинги\n"
    "📊 <b>Трафик</b> — карта трафика по вертикалям\n"
    "🛡 <b>AML</b> — требования AML/KYC по регионам\n\n"
    "Бесплатно: 5 запросов в день.\n"
    "⭐ <b>PRO</b> — безлимит и полный доступ."
)

HELP_TEXT = (
    "📋 <b>Команды бота</b>\n\n"
    "/start — Главное меню\n"
    "/help — Список команд\n"
    "/glossary — Глоссарий терминов\n"
    "/country — Страны и платёжная среда\n"
    "/calendar — Календарь сезонности\n"
    "/acquirers — Эквайеры и PSP\n"
    "/bin — Проверка BIN карты\n"
    "/news — Новости\n"
    "/platforms — Платформы\n"
    "/traffic — Карта трафика\n"
    "/aml — AML/KYC требования\n"
    "/subscribe — PRO подписка\n"
    "/pro — PRO подписка\n"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    await add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        language_code=user.language_code,
    )
    # Auto-PRO for admin
    if user.id == ADMIN_ID:
        if not await check_subscription(user.id):
            await add_subscription(user.id, payment_id="admin_grant")
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()
