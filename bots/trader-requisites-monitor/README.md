# Trader Requisites Monitor

Telegram bot that watches trader-owned requisites and alerts when a requisite keeps getting orders but converts poorly.

- Pulls a Metabase card with per-requisite stats every `CHECK_INTERVAL_MINUTES` (default 20).
- Flags requisites with at least `MIN_ATTEMPTS` orders and conversion below `MIN_CONVERSION_PCT`; marks recurring problems and sharp drops.
- Keeps alert history in PostgreSQL (cleaned weekly), supports an ignore list and Excel export.
- Access by master key; admins are set via `ADMIN_IDS`.

## Environment

Copy `.env.example` to `.env`. Required: `BOT_TOKEN`, `ADMIN_IDS`, `MASTER_KEY`, `METABASE_URL`, `METABASE_EMAIL`, `METABASE_PASSWORD`, `DATABASE_URL`. Thresholds (`MIN_CONVERSION_PCT`, `MIN_ATTEMPTS`, `CRITICAL_DROP_PERCENT`, `RECURRING_ALERT_THRESHOLD`, `SUMMARY_THRESHOLD`, `ALERT_HISTORY_RETENTION_DAYS`, `MAX_COMMENT_LENGTH`) are optional.

## Run

```bash
pip install -r requirements.txt
python bot.py
```

## Tests

No automated tests; the bot needs a live Metabase instance and PostgreSQL.
