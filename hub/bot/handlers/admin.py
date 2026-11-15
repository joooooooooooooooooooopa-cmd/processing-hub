import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.config import ADMIN_ID
from bot.services.database import get_stats, get_db
from bot.keyboards.inline import back_to_menu_kb

router = Router()
logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    waiting_broadcast = State()


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _is_admin(message.from_user.id):
        return

    try:
        stats = await get_stats()
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await message.answer("❌ Ошибка получения статистики.")
        return

    top_cmds = ""
    for cmd, cnt in stats.get("top_commands", []):
        top_cmds += f"  <code>{cmd}</code> — {cnt}\n"

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{stats.get('total_users', 0)}</b>\n"
        f"⭐ Активных PRO: <b>{stats.get('active_subs', 0)}</b>\n"
        f"📈 Запросов сегодня: <b>{stats.get('today_requests', 0)}</b>\n\n"
        f"🏆 <b>Топ команд:</b>\n{top_cmds}"
    )

    await message.answer(text, reply_markup=back_to_menu_kb())


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return

    await state.set_state(AdminStates.waiting_broadcast)
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n"
        "Для отмены отправьте /cancel"
    )


@router.message(AdminStates.waiting_broadcast, Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=back_to_menu_kb())


@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
    if not _is_admin(message.from_user.id):
        return

    await state.clear()

    try:
        db = await get_db()
        cur = await db.execute("SELECT user_id FROM users")
        users = await cur.fetchall()
    except Exception as e:
        logger.error(f"Broadcast DB error: {e}")
        await message.answer("❌ Ошибка получения списка пользователей.")
        return

    success = 0
    failed = 0
    status_msg = await message.answer("📢 Рассылка начата...")

    for row in users:
        user_id = row[0]
        try:
            await message.copy_to(chat_id=user_id)
            success += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: {success}\n"
        f"❌ Не доставлено: {failed}\n"
        f"📊 Всего: {success + failed}"
    )
