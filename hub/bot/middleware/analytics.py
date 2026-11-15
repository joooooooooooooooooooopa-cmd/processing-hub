from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from bot.services.database import log_usage


class AnalyticsMiddleware(BaseMiddleware):
    """Log every command/callback to usage_log."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        command = ""
        query = None

        if isinstance(event, Message):
            if event.text:
                parts = event.text.split(maxsplit=1)
                command = parts[0].split("@")[0]
                query = parts[1] if len(parts) > 1 else None
            elif event.successful_payment:
                command = "payment"
        elif isinstance(event, CallbackQuery):
            command = f"cb:{event.data}" if event.data else "callback"

        if command:
            try:
                await log_usage(user.id, command, query)
            except Exception:
                pass

        return await handler(event, data)
