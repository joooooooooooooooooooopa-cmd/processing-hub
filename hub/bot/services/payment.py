from aiogram.types import LabeledPrice
from bot.config import PRO_PRICE_STARS, PRO_DURATION_DAYS


def create_pro_invoice() -> dict:
    """Return kwargs for Bot.send_invoice for Telegram Stars payment."""
    return {
        "title": "ProcessingHub PRO",
        "description": (
            f"PRO подписка на {PRO_DURATION_DAYS} дней.\n"
            "Безлимитные запросы, все разделы, BIN checker, "
            "полные новости и аналитика."
        ),
        "payload": "pro_subscription",
        "currency": "XTR",
        "prices": [LabeledPrice(label="PRO подписка", amount=PRO_PRICE_STARS)],
    }


def validate_payment_payload(payload: str) -> bool:
    """Check that payment payload matches expected value."""
    return payload == "pro_subscription"
