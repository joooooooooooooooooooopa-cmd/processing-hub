import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN
from bot.services.database import close_db

from bot.middleware.subscription import SubscriptionMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware
from bot.middleware.analytics import AnalyticsMiddleware

from bot.handlers import start, glossary, countries, calendar_h, acquirers
from bot.handlers import bin_checker, news, platforms, traffic, aml
from bot.handlers import subscription, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    return Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # Register middleware (order matters: analytics -> subscription -> rate_limit)
    dp.message.middleware(AnalyticsMiddleware())
    dp.callback_query.middleware(AnalyticsMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())

    # Register routers
    dp.include_router(start.router)
    dp.include_router(glossary.router)
    dp.include_router(countries.router)
    dp.include_router(calendar_h.router)
    dp.include_router(acquirers.router)
    dp.include_router(bin_checker.router)
    dp.include_router(news.router)
    dp.include_router(platforms.router)
    dp.include_router(traffic.router)
    dp.include_router(aml.router)
    dp.include_router(subscription.router)
    dp.include_router(admin.router)

    return dp


async def main():
    bot = create_bot()
    dp = create_dispatcher()

    logger.info("ProcessingHub Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
