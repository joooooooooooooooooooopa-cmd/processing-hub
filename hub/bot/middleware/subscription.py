from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from bot.services.database import check_subscription


class SubscriptionMiddleware(BaseMiddleware):
    """Adds 'is_pro' flag to handler data dict."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Update):
            if event.message and event.message.from_user:
                user_id = event.message.from_user.id
            elif event.callback_query and event.callback_query.from_user:
                user_id = event.callback_query.from_user.id
        else:
            user = getattr(event, "from_user", None)
            if user:
                user_id = user.id

        if user_id:
            data["is_pro"] = await check_subscription(user_id)
        else:
            data["is_pro"] = False

        return await handler(event, data)
