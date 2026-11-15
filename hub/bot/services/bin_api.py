from __future__ import annotations

import aiohttp
import logging
from typing import Optional, Dict
from bot.config import BIN_API_URL, BIN_API_TIMEOUT

logger = logging.getLogger(__name__)


async def lookup_bin(bin_number: str) -> Optional[dict]:
    """Lookup BIN via binlist.net API. Returns parsed dict or None on error."""
    url = f"{BIN_API_URL}{bin_number}"
    headers = {"Accept-Version": "3"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=BIN_API_TIMEOUT)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "bin": bin_number,
                        "brand": data.get("scheme", "N/A"),
                        "card_type": data.get("type", "N/A"),
                        "category": data.get("brand", "N/A"),
                        "bank": data.get("bank", {}).get("name", "N/A") if data.get("bank") else "N/A",
                        "country": data.get("country", {}).get("name", "N/A") if data.get("country") else "N/A",
                        "country_emoji": data.get("country", {}).get("emoji", "") if data.get("country") else "",
                        "prepaid": data.get("prepaid"),
                    }
                elif resp.status == 404:
                    return None
                else:
                    logger.warning(f"BIN API returned status {resp.status} for {bin_number}")
                    return None
    except aiohttp.ClientError as e:
        logger.error(f"BIN API error: {e}")
        return None
    except Exception as e:
        logger.error(f"BIN lookup unexpected error: {e}")
        return None
