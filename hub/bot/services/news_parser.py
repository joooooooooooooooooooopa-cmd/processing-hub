import aiohttp
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from bot.services.cache import cache
from bot.config import NEWS_CACHE_TTL

logger = logging.getLogger(__name__)

CACHE_KEY = "news:latest"


async def parse_cbr_news() -> list[dict]:
    """Parse press releases from cbr.ru."""
    url = "https://cbr.ru/press/"
    items = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return items
                html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        for article in soup.select(".news-list .news-list__item, .landing-press .press_item")[:5]:
            title_el = article.select_one("a")
            date_el = article.select_one(".news-list__item-date, .press_item_date, time")
            if title_el:
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                link = f"https://cbr.ru{href}" if href.startswith("/") else href
                date_text = date_el.get_text(strip=True) if date_el else ""
                items.append({
                    "title": title,
                    "source": "ЦБ РФ",
                    "date": date_text,
                    "summary": "",
                    "url": link,
                })
    except Exception as e:
        logger.error(f"CBR news parse error: {e}")
    return items


async def parse_crypto_news() -> list[dict]:
    """Parse crypto news from CoinDesk RSS."""
    url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
    items = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return items
                xml = await resp.text()
        soup = BeautifulSoup(xml, "xml")
        for item in soup.find_all("item")[:5]:
            title = item.find("title").get_text(strip=True) if item.find("title") else ""
            link = item.find("link").get_text(strip=True) if item.find("link") else ""
            pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
            desc = item.find("description").get_text(strip=True) if item.find("description") else ""
            items.append({
                "title": title,
                "source": "CoinDesk",
                "date": pub_date,
                "summary": desc[:300] if desc else "",
                "url": link,
            })
    except Exception as e:
        logger.error(f"Crypto news parse error: {e}")
    return items


async def get_latest_news(force: bool = False) -> list[dict]:
    """Aggregate news from all sources, use cache."""
    if not force:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return cached

    cbr = await parse_cbr_news()
    crypto = await parse_crypto_news()

    all_news = cbr + crypto
    all_news.sort(key=lambda x: x.get("date", ""), reverse=True)

    cache.set(CACHE_KEY, all_news, ttl=NEWS_CACHE_TTL)
    return all_news
