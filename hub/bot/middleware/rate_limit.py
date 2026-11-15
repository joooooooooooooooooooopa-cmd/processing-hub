from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from bot.config import FREE_DAILY_LIMIT, ADMIN_ID
from bot.services.database import check_subscription, get_today_usage_count
from bot.keyboards.inline import subscription_kb

SKIP_COMMANDS = {"/start", "/help", "/subscribe", "/pro"}


class RateLimitMiddleware(BaseMiddleware):
    """Check daily usage limit for free users. PRO users bypass."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        # Skip for specific commands
        if isinstance(event, Message) and event.text:
            cmd = event.text.split()[0].split("@")[0].lower()
            if cmd in SKIP_COMMANDS:
                return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data:
            if event.data in ("main_menu", "subscribe", "buy_pro"):
                return await handler(event, data)

        # Admin always bypasses
        if user.id == ADMIN_ID:
            return await handler(event, data)

        # PRO users bypass
        is_pro = await check_subscription(user.id)
        if is_pro:
            return await handler(event, data)

        # Check free limit
        usage = await get_today_usage_count(user.id)
        if usage >= FREE_DAILY_LIMIT:
            text = (
                f"⚠️ <b>Лимит исчерпан</b>\n\n"
                f"Вы использовали все <b>{FREE_DAILY_LIMIT}</b> бесплатных запросов на сегодня.\n\n"
                f"Оформите <b>PRO подписку</b>, чтобы получить безлимитный доступ "
                f"ко всем разделам бота."
            )
            if isinstance(event, CallbackQuery):
                await event.answer("Лимит запросов исчерпан", show_alert=True)
                await event.message.edit_text(text, reply_markup=subscription_kb())
            elif isinstance(event, Message):
                await event.answer(text, reply_markup=subscription_kb())
            return None

        return await handler(event, data)
