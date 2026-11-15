# Hub bot

Telegram bot and Mini App: a paid reference for payment processing specialists.

| Section | Command | Content |
|---------|---------|---------|
| Glossary | `/glossary` | 200+ processing terms |
| Countries | `/country` | 107 countries: verticals, licensing, acquirers |
| Calendar | `/calendar` | seasonality across 6 verticals |
| Acquirers | `/acquirers` | 52 PSPs/acquirers with ratings |
| BIN checker | `/bin` | card BIN lookup (bank, country, type) |
| News | `/news` | central bank press and crypto news feeds |
| Platforms | `/platforms` | 30 exchanges, P2P and processing platforms |
| Traffic | `/traffic` | traffic map by vertical |
| AML/KYC | `/aml` | requirements for 7 regions |

Free tier: 5 requests a day, basic glossary, 3 countries. PRO (Telegram Stars, monthly): unlimited, all sections, BIN checker.

Stack: Python 3.11, aiogram 3, aiosqlite, aiohttp + BeautifulSoup, Telegram WebApp SDK.

## Environment

Copy `.env.example` to `.env`: `BOT_TOKEN`, `ADMIN_ID`, optional `DB_PATH` (SQLite file).

## Run

```bash
pip install -r requirements.txt
python -m bot.main
```

## Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests
```
