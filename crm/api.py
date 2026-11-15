"""
FastAPI backend for MerchantCRM Telegram Mini App
"""
import asyncio
import os
import hmac
import hashlib
import json
import urllib.parse
import time
import logging
from datetime import datetime
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from cachetools import TTLCache

import database
import metabase
import storage as storage_module
from config import BOT_TOKEN, ADMIN_IDS, WEBAPP_URL, STATUSES, MOODS, INTEGRATION_STATUSES, RATE_FLEXIBILITY, USE_POSTGRES, DATABASE_URL, hash_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Bounded in-memory cache for dashboards (max 100 entries, 15-minute TTL)
_trader_cache = TTLCache(maxsize=100, ttl=900)
_trader_cache_ttl = 900  # 15 minutes default
_dashboard_cache = TTLCache(maxsize=100, ttl=900)
_dashboard_cache_ttl = 900  # 15 minutes default
_HISTORICAL_TTL = 3600  # 1 hour for historical (past) dates
_revalidating_keys: set = set()  # track background revalidation tasks


def _get_today_msk():
    """Get today's date in Moscow time (UTC+3)."""
    from datetime import datetime, timedelta, timezone
    msk_tz = timezone(timedelta(hours=3))
    return datetime.now(msk_tz).date()


def _is_historical_period(period: str) -> bool:
    """Check if the period refers to a past date (not including today)."""
    from datetime import date
    if not period:
        return False
    today = _get_today_msk()
    # Dashboard uses named periods
    if period in ("yesterday", "month"):
        return True
    if period in ("today",):
        return False
    if period == "week":
        return False  # week includes today
    # Trader/BizDev use YYYY-MM-DD
    try:
        d = date.fromisoformat(period)
        return d < today
    except (ValueError, TypeError):
        return False


def _cache_ttl_for_period(period: str) -> int:
    """Return cache TTL based on whether period is historical."""
    if _is_historical_period(period):
        return _HISTORICAL_TTL
    return 900  # 15 min for today/current


async def _get_dashboard_cached(date_range: str, period: str = "today", merchant: str = None) -> dict:
    """Get full dashboard data using cache when possible, fallback to Metabase."""
    cache_key = f"dashboard:{period}:{merchant}:None:None:None:None"
    ttl = _cache_ttl_for_period(period)

    # Exact match
    if cache_key in _dashboard_cache:
        cached_data, cached_time = _dashboard_cache[cache_key]
        age = time.time() - cached_time
        if age < ttl:
            logger.info(f"[Cache] HIT for {cache_key} (age={age:.0f}s)")
            return cached_data
        logger.info(f"[Cache] Stale hit for {cache_key}, returning stale data")
        return cached_data

    # Try without merchant filter (common case: merchant=None already cached)
    fallback_key = f"dashboard:{period}:None:None:None:None:None"
    if merchant and fallback_key in _dashboard_cache:
        logger.info(f"[Cache] Fallback to unfiltered cache for {period}")
        cached_data, _ = _dashboard_cache[fallback_key]
        return cached_data

    # No cache — fetch from Metabase with graceful timeout
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(metabase.get_full_dashboard, date_range, merchant),
            timeout=30,
        )
        kpi = data.get("kpi", {})
        if any(v is not None for v in kpi.values()):
            _dashboard_cache[cache_key] = (data, time.time())
            logger.info(f"[Cache] Stored valid dashboard data in cache")
        return data
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"[Cache] Dashboard fetch error: {e}, trying fallback")
        # Last resort: return any cached data for this period
        for k, (d, t) in list(_dashboard_cache.items()):
            if k.startswith(f"dashboard:{period}:"):
                logger.warning(f"[Cache] Timeout fallback: returning {k}")
                return d
        # Return empty structure so frontend doesn't hang
        return {
            "kpi": {k: None for k in ["total", "successful", "turnover", "profit", "conversion_pct", "conversion_req_pct", "issued_req", "avg_check", "decline_pct", "avg_profit_per_order", "total_amount_all"]},
            "top_merchants": [], "top_providers": [], "top_methods": [],
            "top_providers_conv": [], "hourly_transactions": [],
            "funnel_statuses": [], "week_dynamics": [], "hourly_profit": [],
        }


def _startup_migrate():
    """On first launch: init schema + migrate SQLite → PostgreSQL if needed."""
    try:
        database.init_db()
        logger.info("[DB] Schema initialised")
    except Exception as e:
        logger.error(f"[DB] init_db failed: {e}")
        return

    if USE_POSTGRES and DATABASE_URL:
        # Fix column types that need BIGINT for Telegram IDs
        try:
            import psycopg2 as _pg
            _c = _pg.connect(DATABASE_URL)
            _c.autocommit = True
            _cur = _c.cursor()
            for _alter in [
                "ALTER TABLE groups ALTER COLUMN id TYPE BIGINT",
                "ALTER TABLE merchants ALTER COLUMN group_id TYPE BIGINT",
            ]:
                try:
                    _cur.execute(_alter)
                    logger.info(f"[DB] Applied: {_alter}")
                except Exception:
                    pass  # Already correct type or table doesn't exist
            _c.close()
        except Exception:
            pass

    if not USE_POSTGRES:
        return

    # Check if merchants table is already populated
    try:
        db = database.get_db()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM merchants")
        row = cur.fetchone()
        count = row[0] if row else 0
        db.close()
    except Exception as e:
        logger.error(f"[DB] count check failed: {e}")
        return

    if count > 0:
        logger.info(f"[DB] PostgreSQL already has {count} merchants — skip migration")
        return

    # Look for bundled seed data: try SQLite first, then JSON export
    import sqlite3 as _sqlite3
    script_dir = Path(__file__).resolve().parent
    sqlite_path = script_dir / "merchants.db"
    json_path = script_dir / "merchants_seed.json"

    if sqlite_path.exists():
        logger.info(f"[DB] Migrating from SQLite: {sqlite_path}")
        _migrate_from_sqlite(sqlite_path)
    elif json_path.exists():
        logger.info(f"[DB] Migrating from JSON seed: {json_path}")
        _migrate_from_json(json_path)
    else:
        logger.info("[DB] No seed data found — starting with empty DB")


def _migrate_table(src, dst, table: str, conflict_clause: str):
    import sqlite3 as _sqlite3
    src_cur = src.cursor()
    src_cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if not src_cur.fetchone():
        return
    src_cur.execute(f"SELECT * FROM {table}")
    rows = src_cur.fetchall()
    if not rows:
        return
    cols = [d[0] for d in src_cur.description]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) {conflict_clause}"
    dst_cur = dst.cursor()
    ok = 0
    for row in rows:
        try:
            dst_cur.execute(sql, list(row))
            ok += 1
        except Exception as e:
            dst.rollback()
            logger.warning(f"[DB] {table} row skip: {e}")
    dst.commit()
    logger.info(f"[DB]   {table}: {ok}/{len(rows)} rows")


def _migrate_from_sqlite(sqlite_path: Path):
    import sqlite3 as _sqlite3
    try:
        import psycopg2 as _pg
        src = _sqlite3.connect(str(sqlite_path))
        src.row_factory = _sqlite3.Row
        dst = _pg.connect(DATABASE_URL)
        dst.autocommit = False
        _do_migrate(src, dst)
        src.close()
        dst.close()
        logger.info("[DB] SQLite migration complete")
    except Exception as e:
        logger.error(f"[DB] SQLite migration failed: {e}")


def _migrate_from_json(json_path: Path):
    import json as _json
    try:
        import psycopg2 as _pg
        with open(json_path, encoding="utf-8") as f:
            data = _json.load(f)
        dst = _pg.connect(DATABASE_URL)
        dst.autocommit = False
        _do_migrate_json(data, dst)
        dst.close()
        logger.info("[DB] JSON seed migration complete")
    except Exception as e:
        logger.error(f"[DB] JSON migration failed: {e}")


def _do_migrate(src, dst):
    import sqlite3 as _sqlite3
    conflict = {
        "merchants":   "ON CONFLICT (name) DO UPDATE SET status=EXCLUDED.status, mood=EXCLUDED.mood, notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at",
        "incidents":   "ON CONFLICT DO NOTHING",
        "incident_comments": "ON CONFLICT DO NOTHING",
        "status_changes":    "ON CONFLICT DO NOTHING",
        "merchant_tags":     "ON CONFLICT DO NOTHING",
        "groups":            "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, type=EXCLUDED.type",
    }
    _fix_sequences = []
    for table, clause in conflict.items():
        _migrate_table(src, dst, table, clause)
        _fix_sequences.append(table)
    _fix_pg_sequences(dst, _fix_sequences)


def _do_migrate_json(data: dict, dst):
    import psycopg2 as _pg
    conflict = {
        "merchants":   "ON CONFLICT (name) DO UPDATE SET status=EXCLUDED.status, mood=EXCLUDED.mood, notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at",
        "incidents":   "ON CONFLICT DO NOTHING",
        "incident_comments": "ON CONFLICT DO NOTHING",
        "status_changes":    "ON CONFLICT DO NOTHING",
        "merchant_tags":     "ON CONFLICT DO NOTHING",
        "groups":            "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, type=EXCLUDED.type",
    }
    dst_cur = dst.cursor()
    for table, rows in data.items():
        if not rows:
            continue
        clause = conflict.get(table, "ON CONFLICT DO NOTHING")
        cols = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) {clause}"
        ok = 0
        for row in rows:
            try:
                dst_cur.execute(sql, [row[c] for c in cols])
                ok += 1
            except Exception as e:
                dst.rollback()
                logger.warning(f"[DB] {table} row skip: {e}")
        dst.commit()
        logger.info(f"[DB]   {table}: {ok}/{len(rows)} rows")
    _fix_pg_sequences(dst, list(data.keys()))


def _fix_pg_sequences(dst, tables: list):
    import psycopg2 as _pg
    dst_cur = dst.cursor()
    for tbl in tables:
        try:
            dst_cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tbl}), 1))"
            )
            dst.commit()
        except Exception:
            dst.rollback()


app = FastAPI(title="MerchantCRM API", version="1.0.0")
app.state.limiter = limiter

async def _warmup_trader_cache():
    """Background task to keep trader dashboard cache warm for last 3 days."""
    from datetime import datetime, timedelta, timezone

    async def warmup_date(date_str: str):
        """Warmup cache for a specific date."""
        try:
            cache_key = f"trader:{date_str}:None:None:None:None:None:None:None"
            logger.info(f"[Cache] Warming up trader dashboard for {date_str}")
            data = await asyncio.to_thread(
                metabase.get_trader_dashboard,
                date_str, None, None, None, None, None, None, None,
            )

            # Only cache if data is valid
            kpi = data.get('kpi', {})
            has_valid_data = any(v is not None for v in kpi.values())

            if has_valid_data:
                _trader_cache[cache_key] = (data, time.time())
                logger.info(f"[Cache] Warmed up trader dashboard for {date_str}")
            else:
                logger.warning(f"[Cache] Skipping warmup for {date_str} - all KPIs null")
        except Exception as e:
            logger.error(f"[Cache] Error warming up {date_str}: {e}")

    # Skip initial warmup — done by _sequential_warmup_then_periodic()
    # Periodic warmup every 3 minutes
    while True:
        try:
            await asyncio.sleep(180)  # Wait 3 minutes
            # Use Moscow time (UTC+3)
            msk_tz = timezone(timedelta(hours=3))
            today = datetime.now(msk_tz)
            dates = [
                today.strftime("%Y-%m-%d"),
                (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                (today - timedelta(days=2)).strftime("%Y-%m-%d"),
            ]
            # Refresh all dates
            for date_str in dates:
                await warmup_date(date_str)
        except Exception as e:
            logger.error(f"[Cache] Periodic warmup error: {e}")

async def _warmup_dashboard_cache():
    """Background task to keep main dashboard cache warm for popular periods."""
    from datetime import datetime, timedelta, timezone

    async def warmup_period(period: str):
        """Warmup cache for a specific period."""
        try:
            # Use Moscow time (UTC+3)
            msk_tz = timezone(timedelta(hours=3))
            today = datetime.now(msk_tz).date()

            if period == "today":
                date_range = f"{today}~{today}"
            elif period == "yesterday":
                yesterday = today - timedelta(days=1)
                date_range = f"{yesterday}~{yesterday}"
            elif period == "week":
                date_range = f"{today - timedelta(days=6)}~{today}"
            elif period == "month":
                date_range = f"{today - timedelta(days=29)}~{today}"
            else:
                return

            cache_key = f"dashboard:{period}:None:None:None:None:None"
            logger.info(f"[Cache] Warming up dashboard for period={period}")
            data = await asyncio.to_thread(
                metabase.get_full_dashboard,
                date_range, None, None, None, None, None,
            )

            # Only cache if data is valid
            kpi = data.get('kpi', {})
            has_valid_data = any(v is not None for v in kpi.values())

            if has_valid_data:
                _dashboard_cache[cache_key] = (data, time.time())
                logger.info(f"[Cache] Warmed up dashboard for period={period}")
            else:
                logger.warning(f"[Cache] Skipping warmup for {period} - all KPIs null")
        except Exception as e:
            logger.error(f"[Cache] Error warming up dashboard {period}: {e}")

    # Skip initial warmup — done by _sequential_warmup_then_periodic()
    # Periodic warmup every 3 minutes
    while True:
        try:
            await asyncio.sleep(180)  # Wait 3 minutes
            periods = ["today", "yesterday", "week", "month"]
            for period in periods:
                await warmup_period(period)
        except Exception as e:
            logger.error(f"[Cache] Periodic dashboard warmup error: {e}")

async def _warmup_bizdev_cache():
    """Background task to keep bizdev dashboard cache warm."""
    from datetime import datetime, timedelta, timezone

    async def warmup_date(date_str: str):
        """Warmup bizdev cache for a specific date."""
        try:
            cache_key = f"bizdev:{date_str}"
            logger.info(f"[Cache] Warming up bizdev dashboard for {date_str}")
            data = await asyncio.to_thread(metabase.get_bizdev_dashboard, date_str)

            # Only cache if data is valid
            kpi = data.get('kpi', {})
            has_valid_data = any(v is not None for v in kpi.values())

            if has_valid_data:
                _trader_cache[cache_key] = (data, time.time())
                logger.info(f"[Cache] Warmed up bizdev dashboard for {date_str}")
            else:
                logger.warning(f"[Cache] Skipping bizdev warmup for {date_str} - all KPIs null")
        except Exception as e:
            logger.error(f"[Cache] Error warming up bizdev {date_str}: {e}")

    # Skip initial warmup — done by _sequential_warmup_then_periodic()
    # Periodic warmup every 5 minutes
    while True:
        try:
            await asyncio.sleep(300)  # Wait 5 minutes
            msk_tz = timezone(timedelta(hours=3))
            today = datetime.now(msk_tz).strftime("%Y-%m-%d")
            await warmup_date(today)
        except Exception as e:
            logger.error(f"[Cache] Periodic bizdev warmup error: {e}")


@app.on_event("startup")
async def on_startup():
    # Clear all caches on startup to ensure fresh data
    _trader_cache.clear()
    _dashboard_cache.clear()
    logger.info("[Cache] Cleared all caches on startup")

    await asyncio.to_thread(_startup_migrate)

    # Alert scheduler starts AFTER warmup (inside _sequential_warmup_then_periodic)
    # to avoid competing with dashboard warmup for Metabase resources

    # Start SEQUENTIAL warmup: one dashboard at a time to avoid overloading Metabase
    # Periodic tasks start AFTER initial warmup completes
    asyncio.create_task(_sequential_warmup_then_periodic())


async def _sequential_warmup_then_periodic():
    """Sequential warmup: one dashboard at a time to avoid overloading Metabase."""
    from datetime import datetime, timedelta, timezone

    msk_tz = timezone(timedelta(hours=3))
    today = datetime.now(msk_tz)
    today_str = today.strftime("%Y-%m-%d")
    date_range = f"{today.date()}~{today.date()}"

    # 1. Dashboard today (most important — first thing users see)
    try:
        logger.info("[Cache] Warmup 1/3: dashboard today")
        data = await asyncio.to_thread(metabase.get_full_dashboard, date_range, None, None, None, None, None)
        kpi = data.get('kpi', {})
        if any(v is not None for v in kpi.values()):
            _dashboard_cache[f"dashboard:today:None:None:None:None:None"] = (data, time.time())
            logger.info("[Cache] Warmup 1/3: dashboard today OK")
        else:
            logger.warning("[Cache] Warmup 1/3: dashboard today - all KPIs null")
    except Exception as e:
        logger.error(f"[Cache] Warmup 1/3 failed: {e}")

    await asyncio.sleep(15)  # Let Metabase recover before next heavy request

    # 2. Trader today
    try:
        logger.info("[Cache] Warmup 2/3: trader today")
        data = await asyncio.to_thread(metabase.get_trader_dashboard, today_str, None, None, None, None, None, None, None)
        kpi = data.get('kpi', {})
        if any(v is not None for v in kpi.values()):
            _trader_cache[f"trader:{today_str}:None:None:None:None:None:None:None"] = (data, time.time())
            logger.info("[Cache] Warmup 2/3: trader today OK")
        else:
            logger.warning("[Cache] Warmup 2/3: trader today - all KPIs null")
    except Exception as e:
        logger.error(f"[Cache] Warmup 2/3 failed: {e}")

    await asyncio.sleep(10)  # Let Metabase recover

    # 3. BizDev today (with retry if total_processed is missing)
    for attempt in range(2):
        try:
            logger.info(f"[Cache] Warmup 3/3: bizdev today (attempt {attempt+1})")
            data = await asyncio.to_thread(metabase.get_bizdev_dashboard, today_str)
            kpi = data.get('kpi', {})
            if any(v is not None for v in kpi.values()):
                _trader_cache[f"bizdev:{today_str}"] = (data, time.time())
                if kpi.get('total_processed') is not None:
                    logger.info("[Cache] Warmup 3/3: bizdev today OK (all KPIs)")
                    break
                else:
                    logger.warning("[Cache] Warmup 3/3: bizdev today partial (total_processed=None), retrying...")
                    await asyncio.sleep(10)
                    continue
            else:
                logger.warning("[Cache] Warmup 3/3: bizdev today - all KPIs null")
                if attempt == 0:
                    await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"[Cache] Warmup 3/3 failed: {e}")
            if attempt == 0:
                await asyncio.sleep(10)

    # 4. Dashboard yesterday (second most popular, sequential = no competition)
    await asyncio.sleep(10)
    yesterday = today.date() - timedelta(days=1)
    yesterday_range = f"{yesterday}~{yesterday}"
    try:
        logger.info("[Cache] Warmup 4/4: dashboard yesterday")
        data = await asyncio.to_thread(metabase.get_full_dashboard, yesterday_range, None, None, None, None, None)
        kpi = data.get('kpi', {})
        if any(v is not None for v in kpi.values()):
            _dashboard_cache[f"dashboard:yesterday:None:None:None:None:None"] = (data, time.time())
            logger.info("[Cache] Warmup 4/4: dashboard yesterday OK")
        else:
            logger.warning("[Cache] Warmup 4/4: dashboard yesterday - all KPIs null")
    except Exception as e:
        logger.error(f"[Cache] Warmup 4/4 failed: {e}")

    # 5/5: dashboard week (for heatmap/compare)
    week_start = today.date() - timedelta(days=6)
    week_range = f"{week_start}~{today.date()}"
    try:
        logger.info("[Cache] Warmup 5/5: dashboard week")
        data = await asyncio.to_thread(metabase.get_full_dashboard, week_range, None, None, None, None, None)
        kpi = data.get('kpi', {})
        if any(v is not None for v in kpi.values()):
            _dashboard_cache[f"dashboard:week:None:None:None:None:None"] = (data, time.time())
            logger.info("[Cache] Warmup 5/5: dashboard week OK")
        else:
            logger.warning("[Cache] Warmup 5/5: dashboard week - all KPIs null")
    except Exception as e:
        logger.error(f"[Cache] Warmup 5/5 failed: {e}")

    logger.info("[Cache] Initial warmup done, starting periodic tasks + alert scheduler")

    # Start alert scheduler AFTER warmup (so it doesn't compete for Metabase)
    alert_scheduler.start_scheduler()
    logger.info("[Ops] Alert scheduler started (after warmup)")

    # Now start periodic warmup tasks (they won't compete with initial warmup)
    asyncio.create_task(_warmup_dashboard_cache())
    asyncio.create_task(_warmup_trader_cache())
    asyncio.create_task(_warmup_bizdev_cache())


@app.on_event("shutdown")
async def on_shutdown():
    # Stop alert scheduler cleanly
    alert_scheduler.stop_scheduler()
    logger.info("[Ops] Alert scheduler stopped")


# Прод-домен Mini App задаётся окружением, чтобы не зашивать адрес деплоя в код
_ALLOWED_ORIGINS = [
    *[o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()],
    "http://localhost:5173",
    "http://localhost:3000",
]
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["X-Init-Data", "Content-Type", "Authorization"],
)

@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Try again later."})


# ── Auth ──────────────────────────────────────────────────────────────────────

def verify_init_data(raw: str) -> dict:
    """Validate Telegram WebApp initData and return user info."""
    try:
        raw = raw.strip()
        parsed = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True, strict_parsing=False))
        received_hash = parsed.pop("hash", "")
        if not received_hash:
            raise ValueError("No hash in initData")

        # Sort pairs and build check string
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        # Compute secret key (strip token to avoid whitespace issues)
        bot_token = BOT_TOKEN.strip()
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            logger.warning(f"initData hash mismatch. data_check keys: {list(parsed.keys())}")
            raise ValueError("Hash mismatch")

        # Check auth_date is not too old (24 hours)
        auth_date = int(parsed.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            raise ValueError("initData expired")

        user = json.loads(parsed.get("user", "{}"))
        return user
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        logger.warning(f"initData validation error: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid initData: {e}")


def get_current_user(
    request: Request = None,
    x_init_data: str = Header(default=""),
    authorization: str = Header(default="")
):
    """FastAPI dependency: validate initData or Bearer token and check authorization."""
    client_ip = request.client.host if request and request.client else None

    # Try Bearer token auth for standalone PWA (format: "Bearer ACCESS_KEY:USER_ID")
    if authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        try:
            key, user_id_str = token.split(":", 1)
            user_id = int(user_id_str)

            # Verify ACCESS_KEY via timing-safe HMAC hash comparison
            from config import ACCESS_KEY
            if not hmac.compare_digest(hash_key(key), hash_key(ACCESS_KEY)):
                storage_module.log_audit(user_id, "auth_fail", "invalid access key", client_ip)
                raise HTTPException(status_code=401, detail="Invalid access key")

            is_admin = user_id in ADMIN_IDS
            store = storage_module.get_storage()
            is_authorized = is_admin or store.is_user_authorized(user_id)

            if not is_authorized:
                storage_module.log_audit(user_id, "auth_fail", "not authorized", client_ip)
                raise HTTPException(status_code=403, detail="Not authorized")

            return {
                "user_id": user_id,
                "username": f"user{user_id}",
                "first_name": "PWA User",
                "is_admin": is_admin,
            }
        except (ValueError, IndexError):
            raise HTTPException(status_code=401, detail="Invalid Bearer token format")

    # Try Telegram initData auth
    if not x_init_data:
        raise HTTPException(status_code=401, detail="X-Init-Data or Authorization header required")

    user = verify_init_data(x_init_data)
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="No user id in initData")

    is_admin = user_id in ADMIN_IDS
    store = storage_module.get_storage()
    is_authorized = is_admin or store.is_user_authorized(user_id)

    if not is_authorized:
        storage_module.log_audit(user_id, "auth_fail", "not authorized (initData)", client_ip)
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "user_id": user_id,
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "is_admin": is_admin,
    }


# ── Metabase field translation ────────────────────────────────────────────────

def translate_row(row: dict, field_map: dict) -> dict:
    return {field_map.get(k, k): v for k, v in row.items()}


CONVERSION_TODAY_MAP = {
    "Мерчант": "merchant",
    "Всего": "total",
    "Успешных": "successful",
    "Сумма": "amount",
    "Сумма успешных": "amount_successful",
    "Конверсия %": "conversion_pct",
    "Конверсия реквизиты": "conversion_req_pct",
}

HOURLY_MAP = {
    "Час": "hour",
    "Ордеров": "orders",
    "Успешных": "successful",
    "Сумма": "amount",
    "Конверсия %": "conversion_pct",
    "Выдано реквизитов": "issued",
}

COMPARE_MAP = {
    "День": "day",
    "Ордеров": "orders",
    "Успешных": "successful",
    "Сумма": "amount",
    "Сумма успешных": "amount_successful",
    "Конверсия %": "conversion_pct",
}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time())}


# ── Auth verify ───────────────────────────────────────────────────────────────

@app.post("/api/auth/verify")
async def auth_verify(user=Depends(get_current_user)):
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "first_name": user["first_name"],
        "is_admin": user["is_admin"],
        "is_authorized": True,
    }


# ── Live Monitor cache ────────────────────────────────────────────────────────
_live_cache: dict = {}
_LIVE_CACHE_TTL = 60  # 60 seconds for live monitor


@app.get("/api/analytics/live")
async def analytics_live(user=Depends(get_current_user)):
    """Lightweight KPI endpoint for live monitor. 60s cache TTL."""
    now = time.time()
    if _live_cache and now - _live_cache.get("_ts", 0) < _LIVE_CACHE_TTL:
        return _live_cache.get("_data", {})

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    msk = _tz(_td(hours=3))
    _msk_date = _dt.now(msk).date()
    _utc_date = _dt.now(_tz.utc).date()
    _dates_match = (_msk_date == _utc_date)

    if _dates_match:
        # Normal path: Metabase questions use CURRENT_DATE which matches MSK
        try:
            conversion_rows, hourly_rows, compare_rows = await asyncio.gather(
                asyncio.wait_for(asyncio.to_thread(metabase.get_conversion_today), timeout=20),
                asyncio.wait_for(asyncio.to_thread(metabase.get_hourly_stats), timeout=20),
                asyncio.wait_for(asyncio.to_thread(metabase.get_compare_yesterday), timeout=20),
            )
        except asyncio.TimeoutError:
            if _live_cache:
                return _live_cache.get("_data", {})
            raise HTTPException(504, "Metabase timeout")

        # Parse today KPI from conversion rows (last row = ИТОГО)
        total = 0
        successful = 0
        turnover = 0.0
        top_merchants = []
        for r in (conversion_rows or []):
            name = r.get("Мерчант", "")
            if "ИТОГО" in str(name):
                total = r.get("Всего", 0) or 0
                successful = r.get("Успешных", 0) or 0
                turnover = r.get("Сумма", 0.0) or 0.0
            else:
                top_merchants.append({
                    "name": name,
                    "total": r.get("Всего", 0) or 0,
                    "successful": r.get("Успешных", 0) or 0,
                    "amount": r.get("Сумма", 0.0) or 0.0,
                })

        conversion_pct = round(successful / total * 100, 2) if total > 0 else 0.0
        top_merchants.sort(key=lambda x: x["amount"], reverse=True)
        top_merchants = top_merchants[:5]

        profit = None
        today_key = f"dashboard:today:None:None:None:None:None"
        if today_key in _dashboard_cache:
            cached_dash, _ = _dashboard_cache[today_key]
            profit = cached_dash.get("kpi", {}).get("profit")

        yesterday_kpi = {}
        for r in (compare_rows or []):
            day = r.get("Период", r.get("day", ""))
            if "чера" in str(day).lower():
                yesterday_kpi = {
                    "total": r.get("Ордеров", r.get("orders", 0)) or 0,
                    "successful": r.get("Успешных", r.get("successful", 0)) or 0,
                    "conversion_pct": r.get("Конверсия %", r.get("conversion_pct", 0)) or 0,
                    "turnover": r.get("Сумма", r.get("amount", 0.0)) or 0.0,
                }

        hourly = []
        for r in (hourly_rows or []):
            hourly.append({
                "hour": r.get("Час", r.get("hour", 0)),
                "total": r.get("Ордеров", r.get("orders", 0)) or 0,
                "successful": r.get("Успешных", r.get("successful", 0)) or 0,
            })
    else:
        # Timezone mismatch (00:00-02:59 MSK): Metabase CURRENT_DATE = yesterday in UTC.
        # Use full dashboard with explicit MSK date_range for correct data.
        logger.info(f"[Live] MSK/UTC date mismatch ({_msk_date} vs {_utc_date}), using full dashboard")
        date_range = f"{_msk_date}~{_msk_date}"
        yesterday_msk = _msk_date - _td(days=1)
        yesterday_range = f"{yesterday_msk}~{yesterday_msk}"
        try:
            today_data, yesterday_data = await asyncio.gather(
                asyncio.wait_for(
                    asyncio.to_thread(metabase.get_full_dashboard, date_range),
                    timeout=30,
                ),
                asyncio.wait_for(
                    asyncio.to_thread(metabase.get_full_dashboard, yesterday_range),
                    timeout=30,
                ),
            )
        except asyncio.TimeoutError:
            if _live_cache:
                return _live_cache.get("_data", {})
            raise HTTPException(504, "Metabase timeout")

        kpi = today_data.get("kpi", {})
        total = kpi.get("total", 0) or 0
        successful = kpi.get("successful", 0) or 0
        turnover = kpi.get("turnover", 0.0) or 0.0
        conversion_pct = kpi.get("conversion_pct", 0.0) or 0.0
        profit = kpi.get("profit")

        # Top merchants from full dashboard
        top_merchants = []
        for m in (today_data.get("top_merchants") or []):
            top_merchants.append({
                "name": m.get("Мерчант", m.get("name", "")),
                "total": m.get("Всего", m.get("total", 0)) or 0,
                "successful": m.get("Успешных", m.get("successful", 0)) or 0,
                "amount": m.get("Сумма", m.get("amount", 0.0)) or 0.0,
            })
        top_merchants.sort(key=lambda x: x["amount"], reverse=True)
        top_merchants = top_merchants[:5]

        # Yesterday KPI
        ykpi = yesterday_data.get("kpi", {})
        yesterday_kpi = {
            "total": ykpi.get("total", 0) or 0,
            "successful": ykpi.get("successful", 0) or 0,
            "conversion_pct": ykpi.get("conversion_pct", 0.0) or 0.0,
            "turnover": ykpi.get("turnover", 0.0) or 0.0,
        }

        # Hourly from full dashboard
        hourly = []
        for h in (today_data.get("hourly_transactions") or []):
            hourly.append({
                "hour": h.get("Час", h.get("hour", 0)),
                "total": h.get("Ордеров", h.get("total", 0)) or 0,
                "successful": h.get("Успешных", h.get("successful", 0)) or 0,
            })

    result = {
        "kpi": {
            "total": total,
            "successful": successful,
            "conversion_pct": conversion_pct,
            "turnover": turnover,
            "profit": profit,
        },
        "yesterday": yesterday_kpi,
        "hourly": hourly,
        "top_merchants_live": top_merchants,
        "updated_at": _dt.now(msk).isoformat(),
    }

    _live_cache["_data"] = result
    _live_cache["_ts"] = time.time()
    return result


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.get("/api/analytics/dashboard")
async def analytics_dashboard(user=Depends(get_current_user)):
    db_stats, operational, mb_summary = await asyncio.gather(
        asyncio.to_thread(database.get_stats),
        asyncio.to_thread(database.get_operational_metrics),
        asyncio.to_thread(metabase.get_dashboard_summary),
    )
    return {
        "summary": mb_summary or {},
        "db_stats": db_stats or {},
        "operational": operational or {},
    }


@app.get("/api/analytics/conversion-today")
async def analytics_conversion_today(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_conversion_today)
    if not rows:
        return []
    return [translate_row(r, CONVERSION_TODAY_MAP) for r in rows]


@app.get("/api/analytics/hourly")
async def analytics_hourly(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_hourly_stats)
    if not rows:
        return []
    return [translate_row(r, HOURLY_MAP) for r in rows]


@app.get("/api/analytics/compare-yesterday")
async def analytics_compare_yesterday(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_compare_yesterday)
    if not rows:
        return []
    return [translate_row(r, COMPARE_MAP) for r in rows]


@app.get("/api/analytics/full-dashboard")
@limiter.limit("30/minute")
async def analytics_full_dashboard(
    request: Request,
    period: Optional[str] = Query("today", max_length=30),
    merchant: Optional[str] = Query(None, max_length=100),
    provider: Optional[str] = Query(None, max_length=100),
    method: Optional[str] = Query(None, max_length=100),
    bank: Optional[str] = Query(None, max_length=100),
    op_type: Optional[str] = Query(None, max_length=50),
    user=Depends(get_current_user),
):
    """Full Metabase dashboard #6 data with optional filters. Cached for 5 minutes."""
    from datetime import datetime, timedelta, timezone

    # Use Moscow time (UTC+3) for all dates
    msk_tz = timezone(timedelta(hours=3))
    today_msk = datetime.now(msk_tz).date()

    if period == "today":
        date_range = f"{today_msk}~{today_msk}"
    elif period == "yesterday":
        yesterday = today_msk - timedelta(days=1)
        date_range = f"{yesterday}~{yesterday}"
    elif period == "week":
        date_range = f"{today_msk - timedelta(days=6)}~{today_msk}"
    elif period == "month":
        date_range = f"{today_msk - timedelta(days=29)}~{today_msk}"
    else:
        date_range = None  # no date filter

    # Create cache key from all parameters
    cache_key = f"dashboard:{period}:{merchant}:{provider}:{method}:{bank}:{op_type}"
    ttl = _cache_ttl_for_period(period)

    # Check cache
    if cache_key in _dashboard_cache:
        cached_data, cached_time = _dashboard_cache[cache_key]
        age = time.time() - cached_time
        if age < ttl:
            logger.info(f"[Cache] Returning cached dashboard for {cache_key} (age={age:.0f}s, ttl={ttl})")
            return cached_data
        # Stale-while-revalidate: return stale data, refresh in background
        if cache_key not in _revalidating_keys:
            _revalidating_keys.add(cache_key)
            logger.info(f"[Cache] Stale-while-revalidate: returning stale dashboard, refreshing bg")

            async def _bg_refresh_dashboard():
                try:
                    fresh = await asyncio.wait_for(
                        asyncio.to_thread(
                            metabase.get_full_dashboard,
                            date_range, merchant, provider, method, bank, op_type,
                        ),
                        timeout=55,
                    )
                    kpi_fresh = fresh.get('kpi', {})
                    if any(v is not None for v in kpi_fresh.values()):
                        _dashboard_cache[cache_key] = (fresh, time.time())
                        logger.info(f"[Cache] BG refresh dashboard OK for {cache_key}")
                except Exception as e:
                    logger.error(f"[Cache] BG refresh dashboard failed: {e}")
                finally:
                    _revalidating_keys.discard(cache_key)

            asyncio.create_task(_bg_refresh_dashboard())
        return cached_data

    # Fetch fresh data with timeout protection
    logger.info(f"[Cache] Fetching fresh dashboard for {cache_key}")
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(
                metabase.get_full_dashboard,
                date_range, merchant, provider, method, bank, op_type,
            ),
            timeout=100,
        )
    except asyncio.TimeoutError:
        logger.error(f"[Cache] Dashboard fetch timeout for {cache_key}")
        data = {
            "_partial": True,
            "kpi": {},
            "top_merchants": [],
            "top_providers": [],
            "top_methods": [],
            "top_providers_conv": [],
            "hourly_transactions": [],
            "funnel_statuses": [],
            "week_dynamics": [],
            "hourly_profit": [],
        }
        return data

    # Only cache if data is valid
    kpi = data.get('kpi', {})
    has_valid_data = any(v is not None for v in kpi.values())

    if has_valid_data:
        # Store in cache
        _dashboard_cache[cache_key] = (data, time.time())
        logger.info(f"[Cache] Stored valid dashboard data in cache")
    else:
        logger.warning(f"[Cache] Skipping cache - dashboard data has all null KPIs")

    # TTLCache handles eviction automatically

    return data


@app.get("/api/analytics/filter-options")
async def analytics_filter_options(user=Depends(get_current_user)):
    """Return distinct values for filter dropdowns from recent conversion data."""
    rows = await asyncio.to_thread(metabase.get_conversion_today)
    merchants = sorted({
        r.get("Мерчант", "")
        for r in rows
        if r.get("Мерчант") and "ИТОГО" not in str(r.get("Мерчант", ""))
    })
    return {
        "merchants": merchants,
        "periods": [
            {"value": "today", "label": "Сегодня"},
            {"value": "yesterday", "label": "Вчера"},
            {"value": "week", "label": "7 дней"},
            {"value": "month", "label": "30 дней"},
        ],
    }


# ── Merchants ─────────────────────────────────────────────────────────────────

@app.get("/api/merchants/canonical-values")
async def merchants_canonical_values(user=Depends(get_current_user)):
    return {
        "statuses": [s for s in STATUSES if s != "unknown"],
        "moods": [m for m in MOODS if m != "unknown"],
        "integration_statuses": [s for s in INTEGRATION_STATUSES if s != "unknown"],
        "rate_flexibility": [r for r in RATE_FLEXIBILITY if r != "unknown"],
    }


@app.get("/api/admin/audit-log")
async def admin_audit_log(
    limit: int = Query(20, le=100),
    user=Depends(get_current_user),
):
    """Get recent audit log entries (admin only)."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    logs = await asyncio.to_thread(storage_module.get_audit_log, limit)
    return {"entries": logs}


@app.get("/api/merchants")
@limiter.limit("30/minute")
async def merchants_list(
    request: Request,
    search: Optional[str] = Query(None, max_length=200),
    status: Optional[str] = Query(None, max_length=50),
    user=Depends(get_current_user),
):
    if search:
        merchants = await asyncio.to_thread(database.search_merchants, search)
    else:
        merchants = await asyncio.to_thread(database.get_all_merchants)

    if status:
        merchants = [m for m in merchants if m.get("status") == status]

    # Add open incident count per merchant (using new ops schema)
    # Note: Ops incidents use dimensions.merchant_name, not merchant_id
    # For now, set count to 0 (can implement merchant-incident mapping later)
    for m in merchants:
        m["open_incidents_count"] = 0

    return {"items": merchants, "total": len(merchants)}


@app.get("/api/merchants/{merchant_id}")
async def merchant_detail(merchant_id: int, user=Depends(get_current_user)):
    merchant = await asyncio.to_thread(database.get_merchant_by_id, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    history, tags = await asyncio.gather(
        asyncio.to_thread(database.get_merchant_history, merchant_id, 20),
        asyncio.to_thread(database.get_merchant_tags, merchant_id),
    )

    # Note: Ops incidents now use dimensions.merchant_name, not merchant_id
    # Can implement merchant-incident mapping later if needed
    open_incidents = []

    return {
        "merchant": merchant,
        "open_incidents": open_incidents,
        "history": history or [],
        "tags": tags or [],
    }


class UpdateMerchantBody(BaseModel):
    field: str
    value: str


ALLOWED_MERCHANT_FIELDS = {
    "status", "mood", "integration_status", "rate_flexibility",
    "current_rate", "min_rate", "conversion", "contact_person", "notes",
}


@app.patch("/api/merchants/{merchant_id}")
async def merchant_update(
    merchant_id: int,
    body: UpdateMerchantBody,
    user=Depends(get_current_user),
):
    if body.field not in ALLOWED_MERCHANT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Field '{body.field}' is not editable")

    merchant = await asyncio.to_thread(database.get_merchant_by_id, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    value = body.value
    if body.field in ("current_rate", "min_rate", "conversion"):
        try:
            value = float(value)
        except ValueError:
            raise HTTPException(status_code=400, detail="Value must be a number")

    await asyncio.to_thread(
        database.update_merchant_field,
        merchant_id, body.field, value,
        f"Обновлено через Mini App пользователем {user['first_name']} ({user['user_id']})",
        "user",
    )
    return {"success": True, "merchant_id": merchant_id, "field": body.field, "new_value": value}


# ── Merchant Chat History & Scanner ──────────────────────────────────────────

@app.get("/api/merchants/{merchant_id}/messages")
async def merchant_messages(
    merchant_id: int,
    limit: int = 20,
    offset: int = 0,
    search: str = "",
    group_name: str = "",
    user=Depends(get_current_user),
):
    """Get recent chat messages linked to a merchant with pagination."""
    merchant = await asyncio.to_thread(database.get_merchant_by_id, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    clamped_limit = min(limit, 100)
    messages = await asyncio.to_thread(
        database.get_merchant_messages, merchant_id, clamped_limit, offset, search, group_name
    )
    total = await asyncio.to_thread(
        database.count_merchant_messages, merchant_id, search, group_name
    )
    return {
        "merchant_id": merchant_id,
        "messages": [
            {
                "id": m.get("id"),
                "sender_name": m.get("sender_name", ""),
                "text": m.get("text", ""),
                "group_name": m.get("group_name", ""),
                "created_at": str(m.get("created_at", "")),
            }
            for m in messages
        ],
        "total": total,
        "has_more": offset + clamped_limit < total,
    }


@app.get("/api/merchants/{merchant_id}/chat-summary")
async def merchant_chat_summary(
    merchant_id: int,
    force: bool = False,
    user=Depends(get_current_user),
):
    """Get AI-generated chat summary for a merchant. Cached for 3 hours."""
    merchant = await asyncio.to_thread(database.get_merchant_by_id, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    # Check cache (3 hours TTL) unless force regeneration requested
    if not force:
        cached = await asyncio.to_thread(database.get_chat_summary, merchant_id)
        if cached:
            try:
                generated = datetime.fromisoformat(str(cached["generated_at"]))
                if (datetime.now() - generated).total_seconds() < 10800:
                    return {
                        "merchant_id": merchant_id,
                        "summary": cached["summary_text"],
                        "message_count": cached["message_count"],
                        "generated_at": str(cached["generated_at"]),
                        "cached": True,
                    }
            except Exception:
                pass

    # Get messages to summarize
    messages = await asyncio.to_thread(database.get_merchant_messages, merchant_id, 50)
    if not messages:
        return {
            "merchant_id": merchant_id,
            "summary": "Нет сообщений из чатов для этого мерчанта.",
            "message_count": 0,
            "cached": False,
        }

    # Generate AI summary
    summary = await asyncio.to_thread(_generate_chat_summary, merchant, messages)

    # Cache result
    last_msg_at = str(messages[0].get("created_at", "")) if messages else ""
    await asyncio.to_thread(
        database.save_chat_summary, merchant_id, summary,
        len(messages), last_msg_at,
    )

    return {
        "merchant_id": merchant_id,
        "summary": summary,
        "message_count": len(messages),
        "generated_at": datetime.now().isoformat(),
        "cached": False,
    }


def _generate_chat_summary(merchant: dict, messages: list) -> str:
    """Generate AI summary of merchant chat messages."""
    from config import OPENAI_API_KEY, AI_MODEL

    if not OPENAI_API_KEY:
        return "AI-саммари недоступно (OPENAI_API_KEY не настроен)."

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        # Build context (chronological, limit cost)
        msg_texts = []
        for m in messages[:30]:
            sender = m.get("sender_name", "Unknown")
            text = (m.get("text") or "")[:300]
            date = str(m.get("created_at", ""))[:16]
            msg_texts.append(f"[{date}] {sender}: {text}")

        context = "\n".join(reversed(msg_texts))

        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты CRM-аналитик платёжной компании. Суммаризируй историю переписки "
                        "с мерчантом. Фокусируйся на: текущий статус работы, недавние проблемы, "
                        "обсуждение ставок, прогресс интеграции, настроение мерчанта. "
                        "Будь краток (3-5 предложений). Пиши на русском."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Мерчант: {merchant.get('name')}\n"
                        f"Статус в CRM: {merchant.get('status')}\n"
                        f"Последние сообщения из чата:\n{context}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=500,
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Chat summary generation failed: {e}")
        return f"Ошибка генерации саммари: {e}"


@app.get("/api/scanner/status")
async def scanner_status(user=Depends(get_current_user)):
    """Scanner is disabled. Chat analysis uses file upload only."""
    return {
        "status": "disabled",
        "message": "Сканер отключён. Используйте загрузку экспорта чатов.",
        "state": {},
        "groups_monitored": "0",
    }


# In-memory upload task tracking
_upload_tasks: dict = {}


def _extract_text_messages(messages: list) -> list:
    """Extract text messages from Telegram Desktop export format."""
    text_messages = []
    for msg in messages:
        if msg.get("type") != "message":
            continue
        raw_text = msg.get("text", "")
        if isinstance(raw_text, list):
            text = "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in raw_text
            )
        else:
            text = str(raw_text)
        if len(text) < 15:
            continue
        text_messages.append({
            "text": text,
            "sender_name": msg.get("from", "Unknown"),
            "sender_id": msg.get("from_id", ""),
            "telegram_msg_id": msg.get("id", 0),
            "date": msg.get("date", ""),
        })
    return text_messages


@app.post("/api/chat-export/upload")
@limiter.limit("5/minute")
async def upload_chat_export(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload Telegram Desktop chat export (result.json) for analysis.
    Returns task_id for progress tracking via /api/chat-export/status/{task_id}."""
    fname = (file.filename or "").lower()
    if not fname.endswith(".json") and not fname.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only JSON and ZIP files are supported")

    # Read file (max 20MB)
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    # Validate magic bytes
    if fname.endswith(".json"):
        stripped = content.lstrip()
        if stripped and stripped[0:1] not in (b'{', b'['):
            raise HTTPException(status_code=400, detail="File content is not valid JSON")
    elif fname.endswith(".zip"):
        if not content.startswith(b'PK'):
            raise HTTPException(status_code=400, detail="File content is not a valid ZIP")

    # Handle ZIP files
    if fname.endswith(".zip"):
        import zipfile
        import io
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))

            # ZIP bomb protection: check total decompressed size
            total_decompressed = sum(info.file_size for info in zf.infolist())
            if total_decompressed > 100 * 1024 * 1024:  # 100MB max
                raise HTTPException(status_code=400, detail="ZIP too large when decompressed (max 100MB)")

            json_name = None
            for name in zf.namelist():
                if name.endswith("result.json"):
                    json_name = name
                    break
            if not json_name:
                # Try first JSON file
                for name in zf.namelist():
                    if name.endswith(".json"):
                        json_name = name
                        break
            if not json_name:
                raise HTTPException(status_code=400, detail="No JSON file found in ZIP")
            content = zf.read(json_name)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")

    # Audit log
    storage_module.log_audit(
        user["user_id"], "file_upload",
        f"{file.filename} ({len(content)} bytes)",
        request.client.host if request.client else None
    )

    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if "messages" not in data:
        raise HTTPException(status_code=400, detail="Not a Telegram Desktop export (no 'messages' field)")

    chat_name = data.get("name", (file.filename or "export").replace(".json", "").replace(".zip", ""))
    chat_id = data.get("id", 0)

    text_messages = _extract_text_messages(data.get("messages", []))

    if not text_messages:
        return {
            "task_id": None,
            "chat_name": chat_name,
            "total_messages": 0,
            "status": "completed",
            "processed": 0, "updated": 0, "merchants": [],
        }

    # Create background task
    import uuid
    task_id = str(uuid.uuid4())[:8]
    _upload_tasks[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "chat_name": chat_name,
        "total": len(text_messages),
        "processed": 0,
        "updated": 0,
        "merchants": [],
        "error": None,
    }

    asyncio.create_task(_process_upload_bg(task_id, text_messages, chat_name, int(chat_id) if chat_id else 0))

    return {
        "task_id": task_id,
        "chat_name": chat_name,
        "total_messages": len(text_messages),
        "status": "processing",
    }


@app.get("/api/chat-export/status/{task_id}")
async def upload_status(task_id: str, user=Depends(get_current_user)):
    """Poll upload processing progress."""
    task = _upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _process_upload_bg(task_id: str, text_messages: list, chat_name: str, chat_id: int):
    """Background processor for uploaded chat export."""
    import analyzer
    task = _upload_tasks[task_id]
    try:
        for msg in text_messages:
            try:
                sender_id = 0
                sid = msg.get("sender_id", "")
                if isinstance(sid, str) and sid.startswith("user"):
                    try:
                        sender_id = int(sid.replace("user", ""))
                    except ValueError:
                        pass
                elif isinstance(sid, int):
                    sender_id = sid

                result = await asyncio.to_thread(
                    _sync_process_message,
                    msg["text"], chat_name, chat_id,
                    msg["telegram_msg_id"], sender_id, msg["sender_name"],
                )
                task["processed"] += 1
                if result:
                    task["updated"] += 1
                    quick = analyzer.quick_analyze(msg["text"])
                    if quick.get("merchant_name"):
                        if quick["merchant_name"] not in task["merchants"]:
                            task["merchants"].append(quick["merchant_name"])
            except Exception as e:
                logger.error(f"Error processing export message: {e}")
                task["processed"] += 1

        task["status"] = "completed"
    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        logger.error(f"Upload task {task_id} failed: {e}")


def _sync_process_message(text, chat_name, group_id, telegram_msg_id, sender_id, sender_name):
    """Synchronous wrapper for process_message (for use with asyncio.to_thread)."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        from scheduler import process_message
        return loop.run_until_complete(
            process_message(text, chat_name, group_id, telegram_msg_id, sender_id, sender_name)
        )
    finally:
        loop.close()


# ── Old Incidents endpoints removed (replaced by OPS Phase 1 endpoints below) ─────


# ── Extended Analytics ────────────────────────────────────────────────────────

@app.get("/api/analytics/canceled")
async def analytics_canceled(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_canceled_analysis)
    return rows or []


@app.get("/api/analytics/banks")
async def analytics_banks(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_stats_by_bank)
    return rows or []


@app.get("/api/analytics/weekly")
async def analytics_weekly(user=Depends(get_current_user)):
    summary, by_day = await asyncio.gather(
        asyncio.to_thread(metabase.get_weekly_stats),
        asyncio.to_thread(metabase.get_weekly_by_day),
    )
    return {"summary": summary or {}, "by_day": by_day or []}


@app.get("/api/analytics/monthly")
async def analytics_monthly(user=Depends(get_current_user)):
    data = await asyncio.to_thread(metabase.get_monthly_stats)
    return data or {}


@app.get("/api/analytics/unpaid")
async def analytics_unpaid(user=Depends(get_current_user)):
    data = await asyncio.to_thread(metabase.get_unpaid_orders)
    return data or {}


@app.get("/api/analytics/bad-clients")
async def analytics_bad_clients(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_bad_clients)
    return rows or []


@app.get("/api/analytics/rates")
async def analytics_rates(user=Depends(get_current_user)):
    rows = await asyncio.to_thread(metabase.get_rates_by_method)
    return rows or []


# ── Messages / Chats ──────────────────────────────────────────────────────────

@app.get("/api/messages")
async def messages_list(user=Depends(get_current_user)):
    groups = await asyncio.to_thread(database.get_groups)
    result = []
    for g in groups:
        gid = g.get("id")
        msgs = await asyncio.to_thread(database.get_recent_messages, gid, 20)
        result.append({
            "id": gid,
            "name": g.get("name", ""),
            "type": g.get("group_type", ""),
            "messages": [
                {
                    "id": m.get("id"),
                    "sender": m.get("sender_name", ""),
                    "text": m.get("text", ""),
                    "created_at": str(m.get("created_at", "")),
                }
                for m in msgs
            ],
        })
    return result


@app.get("/api/analytics/trader-dashboard")
@limiter.limit("30/minute")
async def analytics_trader_dashboard(
    request: Request,
    period: Optional[str] = Query(None, max_length=30),
    trader: Optional[str] = Query(None, max_length=100),
    method: Optional[str] = Query(None, max_length=100),
    bank: Optional[str] = Query(None, max_length=100),
    tla: Optional[str] = Query(None, max_length=100),
    htl: Optional[str] = Query(None, max_length=100),
    agent: Optional[str] = Query(None, max_length=100),
    merchant: Optional[str] = Query(None, max_length=100),
    user=Depends(get_current_user),
):
    """Trader dashboard #13 data with optional filters. Cached for 5 minutes."""
    from datetime import datetime, timedelta, timezone

    # Use Moscow time (UTC+3) for default date
    if period is None:
        msk_tz = timezone(timedelta(hours=3))
        period = datetime.now(msk_tz).strftime("%Y-%m-%d")

    # Create cache key from all parameters
    cache_key = f"trader:{period}:{trader}:{method}:{bank}:{tla}:{htl}:{agent}:{merchant}"
    ttl = _cache_ttl_for_period(period)

    # Check cache
    if cache_key in _trader_cache:
        cached_data, cached_time = _trader_cache[cache_key]
        age = time.time() - cached_time
        if age < ttl:
            logger.info(f"[Cache] Returning cached trader dashboard for {cache_key} (age={age:.0f}s, ttl={ttl})")
            return cached_data
        # Stale-while-revalidate: return stale data, refresh in background
        if cache_key not in _revalidating_keys:
            _revalidating_keys.add(cache_key)
            logger.info(f"[Cache] Stale-while-revalidate: returning stale trader, refreshing bg")

            async def _bg_refresh_trader():
                try:
                    fresh = await asyncio.wait_for(
                        asyncio.to_thread(
                            metabase.get_trader_dashboard,
                            period, trader, method, bank, tla, htl, agent, merchant,
                        ),
                        timeout=40,
                    )
                    kpi_fresh = fresh.get('kpi', {})
                    if any(v is not None for v in kpi_fresh.values()):
                        _trader_cache[cache_key] = (fresh, time.time())
                        logger.info(f"[Cache] BG refresh trader OK for {cache_key}")
                except Exception as e:
                    logger.error(f"[Cache] BG refresh trader failed: {e}")
                finally:
                    _revalidating_keys.discard(cache_key)

            asyncio.create_task(_bg_refresh_trader())
        return cached_data

    # Fetch fresh data with timeout protection
    logger.info(f"[Cache] Fetching fresh trader dashboard for {cache_key}")
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(
                metabase.get_trader_dashboard,
                period, trader, method, bank, tla, htl, agent, merchant,
            ),
            timeout=90,
        )
    except asyncio.TimeoutError:
        logger.error(f"[Cache] Trader fetch timeout for {cache_key}")
        data = {
            "_partial": True,
            "kpi": {},
            "by_methods": [],
            "by_banks": [],
            "bank_method": [],
        }
        return data

    # Only cache if data is valid (at least one KPI is not null)
    kpi = data.get('kpi', {})
    has_valid_data = any(v is not None for v in kpi.values())

    if has_valid_data:
        # Store in cache
        _trader_cache[cache_key] = (data, time.time())
        logger.info(f"[Cache] Stored valid trader data in cache")
    else:
        logger.warning(f"[Cache] Skipping cache - trader data has all null KPIs")

    # TTLCache handles eviction automatically

    return data


@app.get("/api/analytics/trader-filter-options")
async def analytics_trader_filter_options(user=Depends(get_current_user)):
    """Get filter options for trader dashboard (methods, banks, etc). Cached for 10 minutes."""
    cache_key = "trader_filter_options"

    # Check cache
    if cache_key in _trader_cache:
        cached_data, cached_time = _trader_cache[cache_key]
        if time.time() - cached_time < 600:  # 10 minute TTL
            logger.info(f"[Cache] Returning cached trader filter options")
            return cached_data

    # Fetch fresh data
    logger.info(f"[Cache] Fetching fresh trader filter options")
    data = await asyncio.to_thread(metabase.get_trader_filter_options)

    # Store in cache
    _trader_cache[cache_key] = (data, time.time())

    return data


@app.get("/api/analytics/bizdev-dashboard")
@limiter.limit("30/minute")
async def analytics_bizdev_dashboard(
    request: Request,
    period: Optional[str] = Query(None, max_length=30),
    user=Depends(get_current_user),
):
    """BizDev dashboard with providers, methods, hourly stats. Cached for 5 minutes."""
    from datetime import datetime, timedelta, timezone

    # Use Moscow time (UTC+3) for default date
    if period is None:
        msk_tz = timezone(timedelta(hours=3))
        period = datetime.now(msk_tz).strftime("%Y-%m-%d")

    # Create cache key
    cache_key = f"bizdev:{period}"
    ttl = _cache_ttl_for_period(period)

    # Check cache
    if cache_key in _trader_cache:
        cached_data, cached_time = _trader_cache[cache_key]
        age = time.time() - cached_time
        if age < ttl:
            logger.info(f"[Cache] Returning cached bizdev dashboard for {cache_key} (age={age:.0f}s, ttl={ttl})")
            return cached_data
        # Stale-while-revalidate: return stale data, refresh in background
        if cache_key not in _revalidating_keys:
            _revalidating_keys.add(cache_key)
            logger.info(f"[Cache] Stale-while-revalidate: returning stale bizdev, refreshing bg")

            async def _bg_refresh_bizdev():
                try:
                    fresh = await asyncio.wait_for(
                        asyncio.to_thread(metabase.get_bizdev_dashboard, period),
                        timeout=40,
                    )
                    kpi_fresh = fresh.get('kpi', {})
                    if any(v is not None for v in kpi_fresh.values()):
                        _trader_cache[cache_key] = (fresh, time.time())
                        logger.info(f"[Cache] BG refresh bizdev OK for {cache_key}")
                except Exception as e:
                    logger.error(f"[Cache] BG refresh bizdev failed: {e}")
                finally:
                    _revalidating_keys.discard(cache_key)

            asyncio.create_task(_bg_refresh_bizdev())
        return cached_data

    # Fetch fresh data with timeout protection
    logger.info(f"[Cache] Fetching fresh bizdev dashboard for {cache_key}")
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(metabase.get_bizdev_dashboard, period),
            timeout=40,
        )
    except asyncio.TimeoutError:
        logger.error(f"[Cache] Bizdev fetch timeout for {cache_key}")
        data = {
            "_partial": True,
            "kpi": {},
            "hourly_issued": [],
            "methods_pie_count": [],
            "methods_pie_profit": [],
            "providers_table": [],
        }
        return data

    # Only cache if data is valid
    kpi = data.get('kpi', {})
    has_valid_data = any(v is not None for v in kpi.values())

    if has_valid_data:
        _trader_cache[cache_key] = (data, time.time())
        logger.info(f"[Cache] Stored valid bizdev data in cache")
    else:
        logger.warning(f"[Cache] Skipping cache - bizdev data has all null KPIs")

    # TTLCache handles eviction automatically

    return data


# ============ OPS: INCIDENTS & ALERTS (Phase 1) ============

from ops_models import (
    Incident, IncidentListResponse, IncidentDetailResponse,
    IncidentAckRequest, IncidentResolveRequest, IncidentReopenRequest,
    IncidentAssignRequest, IncidentMuteRequest, IncidentUnmuteRequest,
    HealthResponse
)
import ops_db
import alert_scheduler


@app.get("/api/incidents", response_model=IncidentListResponse)
@limiter.limit("30/minute")
async def get_incidents_list(
    request: Request,
    status: Optional[str] = Query(None, max_length=50),
    severity: Optional[str] = Query(None, max_length=50),
    scope: Optional[str] = Query(None, max_length=50),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
):
    """Get list of incidents with filters"""
    try:
        incidents = await asyncio.to_thread(
            ops_db.get_incidents,
            status=status,
            severity=severity,
            scope=scope,
            limit=limit,
            offset=offset
        )
        return {"incidents": incidents, "total": len(incidents)}
    except Exception as e:
        logger.error(f"[Ops] Error fetching incidents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident_detail(
    incident_id: str,
    user=Depends(get_current_user),
):
    """Get incident detail with timeline"""
    try:
        incident = await asyncio.to_thread(ops_db.get_incident, incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

        events = await asyncio.to_thread(ops_db.get_incident_events, incident_id)
        return {"incident": incident, "events": events}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error fetching incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/incidents/{incident_id}/ack")
async def ack_incident(
    incident_id: str,
    request: IncidentAckRequest,
    user=Depends(get_current_user),
):
    """Acknowledge incident"""
    try:
        success = await asyncio.to_thread(
            ops_db.ack_incident,
            incident_id,
            request.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Incident not found or already acked")

        # Audit log
        await asyncio.to_thread(
            ops_db.log_audit,
            request.user_id,
            "incident.ack",
            "incident",
            incident_id,
            {}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error acking incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    request: IncidentResolveRequest,
    user=Depends(get_current_user),
):
    """Resolve incident"""
    try:
        success = await asyncio.to_thread(
            ops_db.resolve_incident,
            incident_id,
            request.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Incident not found or already resolved")

        # Audit log
        await asyncio.to_thread(
            ops_db.log_audit,
            request.user_id,
            "incident.resolve",
            "incident",
            incident_id,
            {}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error resolving incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/incidents/{incident_id}/reopen")
async def reopen_incident(
    incident_id: str,
    request: IncidentReopenRequest,
    user=Depends(get_current_user),
):
    """Reopen incident"""
    try:
        success = await asyncio.to_thread(
            ops_db.reopen_incident,
            incident_id,
            request.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Incident not found or not resolved")

        # Audit log
        await asyncio.to_thread(
            ops_db.log_audit,
            request.user_id,
            "incident.reopen",
            "incident",
            incident_id,
            {}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error reopening incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/incidents/{incident_id}/assign")
async def assign_incident(
    incident_id: str,
    request: IncidentAssignRequest,
    user=Depends(get_current_user),
):
    """Assign incident to owner"""
    try:
        success = await asyncio.to_thread(
            ops_db.assign_incident,
            incident_id,
            request.owner_user_id,
            request.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Incident not found")

        # Audit log
        await asyncio.to_thread(
            ops_db.log_audit,
            request.user_id,
            "incident.assign",
            "incident",
            incident_id,
            {"owner_user_id": request.owner_user_id}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error assigning incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/incidents/{incident_id}/mute")
async def mute_incident(
    incident_id: str,
    request: IncidentMuteRequest,
    user=Depends(get_current_user),
):
    """Mute incident"""
    try:
        success = await asyncio.to_thread(
            ops_db.mute_incident,
            incident_id,
            request.minutes,
            request.until,
            request.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Incident not found")

        # Audit log
        await asyncio.to_thread(
            ops_db.log_audit,
            request.user_id,
            "incident.mute",
            "incident",
            incident_id,
            {"minutes": request.minutes, "until": str(request.until) if request.until else None}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error muting incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/incidents/{incident_id}/unmute")
async def unmute_incident(
    incident_id: str,
    request: IncidentUnmuteRequest,
    user=Depends(get_current_user),
):
    """Unmute incident"""
    try:
        success = await asyncio.to_thread(
            ops_db.unmute_incident,
            incident_id,
            request.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Incident not found")

        # Audit log
        await asyncio.to_thread(
            ops_db.log_audit,
            request.user_id,
            "incident.unmute",
            "incident",
            incident_id,
            {}
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Ops] Error unmuting incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    from datetime import datetime

    status = "ok"
    db_ok = False
    metabase_ok = False

    # Check database
    try:
        conn = ops_db.get_ops_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        db_ok = True
    except Exception as e:
        logger.error(f"[Health] DB check failed: {e}")
        status = "degraded"

    # Check Metabase
    try:
        await asyncio.to_thread(metabase.get_client)
        metabase_ok = True
    except Exception as e:
        logger.error(f"[Health] Metabase check failed: {e}")
        status = "degraded"

    if not db_ok and not metabase_ok:
        status = "error"

    return {
        "status": status,
        "database": db_ok,
        "metabase": metabase_ok,
        "cache": {
            "dashboard_cache_size": len(_dashboard_cache),
            "trader_cache_size": len(_trader_cache)
        },
        "timestamp": datetime.utcnow()
    }


@app.get("/api/alerts/scheduler/status")
async def get_scheduler_status(user=Depends(get_current_user)):
    """Get alert scheduler status"""
    scheduler = alert_scheduler.get_scheduler()
    return scheduler.get_status()


@app.post("/api/alerts/scheduler/trigger")
async def trigger_scheduler_now(user=Depends(get_current_user)):
    """Manually trigger alert check (for testing)"""
    scheduler = alert_scheduler.get_scheduler()
    result = await scheduler.trigger_now()
    return result


# ── Analytics: Period Comparison ───────────────────────────────────────────────

@app.get("/api/analytics/compare-periods")
@limiter.limit("20/minute")
async def analytics_compare_periods(
    request: Request,
    period1: Optional[str] = Query(None, max_length=30),
    period2: Optional[str] = Query(None, max_length=30),
    period1_start: Optional[str] = Query(None, max_length=10),
    period1_end: Optional[str] = Query(None, max_length=10),
    period2_start: Optional[str] = Query(None, max_length=10),
    period2_end: Optional[str] = Query(None, max_length=10),
    merchant: Optional[str] = Query(None, max_length=100),
    user=Depends(get_current_user),
):
    """Compare two periods side by side. Accepts named periods or date ranges."""
    from datetime import datetime, timedelta, timezone

    msk_tz = timezone(timedelta(hours=3))
    today = datetime.now(msk_tz).date()

    def resolve_period(p):
        if p == "today":
            return f"{today}~{today}", "today"
        elif p == "yesterday":
            d = today - timedelta(days=1)
            return f"{d}~{d}", "yesterday"
        elif p == "this_week":
            return f"{today - timedelta(days=6)}~{today}", "week"
        elif p == "last_week":
            end = today - timedelta(days=7)
            start = end - timedelta(days=6)
            return f"{start}~{end}", "last_week"
        elif p == "this_month":
            return f"{today - timedelta(days=29)}~{today}", "month"
        elif p == "last_month":
            end = today - timedelta(days=30)
            start = end - timedelta(days=29)
            return f"{start}~{end}", "last_month"
        return None, p

    # Support both: named periods (period1/period2) and raw dates (period1_start/period1_end)
    if period1_start and period1_end:
        range1 = f"{period1_start}~{period1_end}"
        p1_cache = "today" if period1_start == str(today) else ("yesterday" if period1_end == str(today - timedelta(days=1)) else period1_start)
    elif period1:
        range1, p1_cache = resolve_period(period1)
    else:
        range1, p1_cache = resolve_period("this_week")

    if period2_start and period2_end:
        range2 = f"{period2_start}~{period2_end}"
        p2_cache = "today" if period2_start == str(today) else ("yesterday" if period2_end == str(today - timedelta(days=1)) else period2_start)
    elif period2:
        range2, p2_cache = resolve_period(period2)
    else:
        range2, p2_cache = resolve_period("last_week")

    if not range1 or not range2:
        raise HTTPException(400, "Invalid period parameters")

    try:
        data1, data2 = await asyncio.gather(
            _get_dashboard_cached(range1, p1_cache, merchant),
            _get_dashboard_cached(range2, p2_cache, merchant),
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Metabase timeout")

    kpi1 = data1.get("kpi", {})
    kpi2 = data2.get("kpi", {})

    deltas = {}
    for key in set(list(kpi1.keys()) + list(kpi2.keys())):
        v1 = kpi1.get(key)
        v2 = kpi2.get(key)
        if v1 is not None and v2 is not None and v2 != 0:
            deltas[key] = {
                "period1": v1,
                "period2": v2,
                "delta": round(v1 - v2, 2),
                "delta_pct": round((v1 - v2) / abs(v2) * 100, 2),
            }
        else:
            deltas[key] = {"period1": v1, "period2": v2, "delta": None, "delta_pct": None}

    return {
        "period1": {"label": period1, "range": range1, "kpi": kpi1, "top_merchants": data1.get("top_merchants", [])},
        "period2": {"label": period2, "range": range2, "kpi": kpi2, "top_merchants": data2.get("top_merchants", [])},
        "deltas": deltas,
    }


# ── Analytics: Heatmap ────────────────────────────────────────────────────────

@app.get("/api/analytics/heatmap")
async def analytics_heatmap(
    metric: str = Query("orders", max_length=50),
    days: int = Query(7, le=30),
    user=Depends(get_current_user),
):
    """Activity heatmap: 7x24 grid (day_of_week x hour)."""
    from datetime import datetime, timedelta, timezone
    import collections

    msk_tz = timezone(timedelta(hours=3))
    today = datetime.now(msk_tz).date()

    # Map to cached periods to avoid Metabase calls
    if days <= 7:
        date_range = f"{today - timedelta(days=6)}~{today}"
        period_name = "week"
    else:
        # 14 and 30 days both use month cache
        date_range = f"{today - timedelta(days=29)}~{today}"
        period_name = "month"

    try:
        data = await _get_dashboard_cached(date_range, period_name)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Metabase timeout")

    hourly = data.get("hourly_transactions", [])

    # Build 7x24 matrix
    matrix = [[0.0 for _ in range(24)] for _ in range(7)]
    counts = [[0 for _ in range(24)] for _ in range(7)]

    for h in hourly:
        hour = int(h.get("Час", h.get("hour", 0)) or 0)
        value = float(h.get("Ордеров", h.get("total", h.get("orders", 0))) or 0)
        if metric == "successful":
            value = float(h.get("Успешных", h.get("successful", 0)) or 0)
        elif metric == "conversion":
            total = float(h.get("Ордеров", h.get("total", 1)) or 1)
            succ = float(h.get("Успешных", h.get("successful", 0)) or 0)
            value = round(succ / total * 100, 2) if total > 0 else 0

        dow = today.weekday()
        if 0 <= hour < 24:
            matrix[dow][hour] += value
            counts[dow][hour] += 1

    # Average where multiple days contributed to same cell
    for d in range(7):
        for h_idx in range(24):
            if counts[d][h_idx] > 1:
                matrix[d][h_idx] = round(matrix[d][h_idx] / counts[d][h_idx], 2)

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "metric": metric,
        "days": days,
        "matrix": matrix,
        "day_labels": day_names,
        "hour_labels": list(range(24)),
        "max_value": max(max(row) for row in matrix) if any(any(r) for r in matrix) else 0,
    }


# ── Analytics: Funnel ─────────────────────────────────────────────────────────

@app.get("/api/analytics/funnel")
async def analytics_funnel(
    period: str = Query("today", max_length=30),
    merchant: Optional[str] = Query(None, max_length=100),
    user=Depends(get_current_user),
):
    """N-stage conversion funnel with drop-off percentages."""
    from datetime import datetime, timedelta, timezone

    msk_tz = timezone(timedelta(hours=3))
    today = datetime.now(msk_tz).date()

    if period == "today":
        date_range = f"{today}~{today}"
    elif period == "yesterday":
        d = today - timedelta(days=1)
        date_range = f"{d}~{d}"
    elif period == "week":
        date_range = f"{today - timedelta(days=6)}~{today}"
    else:
        date_range = f"{today}~{today}"

    try:
        data = await _get_dashboard_cached(date_range, period, merchant)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Metabase timeout")

    kpi = data.get("kpi", {})
    funnel_data = data.get("funnel_statuses", [])

    # Build stages from KPI
    total = kpi.get("total", 0) or 0
    issued = kpi.get("issued", kpi.get("total_issued", 0)) or 0
    successful = kpi.get("successful", 0) or 0

    stages = [
        {"name": "Ордера", "value": total, "pct": 100.0},
        {"name": "Выдано реквизитов", "value": issued, "pct": round(issued / total * 100, 2) if total > 0 else 0},
        {"name": "Оплачено", "value": successful, "pct": round(successful / total * 100, 2) if total > 0 else 0},
    ]

    # Add additional funnel stages from Metabase if available
    if funnel_data:
        for f in funnel_data:
            name = f.get("Статус", f.get("status", ""))
            count = int(f.get("Кол-во", f.get("count", 0)) or 0)
            if name and count > 0 and name not in [s["name"] for s in stages]:
                stages.append({
                    "name": name,
                    "value": count,
                    "pct": round(count / total * 100, 2) if total > 0 else 0,
                })

    # Calculate drop-off between stages
    for i in range(1, len(stages)):
        prev = stages[i-1]["value"]
        curr = stages[i]["value"]
        stages[i]["drop_off"] = prev - curr if prev > 0 else 0
        stages[i]["drop_off_pct"] = round((prev - curr) / prev * 100, 2) if prev > 0 else 0

    return {"stages": stages, "period": period}


# ── Incidents: Auto-resolve Config ────────────────────────────────────────────

@app.post("/api/incidents/{incident_id}/auto-resolve-config")
async def set_auto_resolve_config(
    incident_id: str,
    minutes: int = Query(..., ge=5, le=1440),
    threshold: Optional[float] = Query(None),
    user=Depends(get_current_user),
):
    """Configure auto-resolve for an incident."""
    success = await asyncio.to_thread(
        ops_db.configure_auto_resolve, incident_id, minutes, threshold
    )
    if not success:
        raise HTTPException(404, "Incident not found")
    return {"success": True, "auto_resolve_minutes": minutes, "threshold": threshold}


# ── Exports (CSV / Excel / PDF) ──────────────────────────────────────────────

@app.get("/api/exports/{export_type}")
@limiter.limit("10/minute")
async def export_data(
    request: Request,
    export_type: str,
    screen: str = Query("dashboard", max_length=50),
    period: str = Query("today", max_length=30),
    merchant: Optional[str] = Query(None, max_length=100),
    user=Depends(get_current_user),
):
    """Export dashboard data as CSV, Excel, or PDF."""
    from fastapi.responses import StreamingResponse
    import io, csv

    if export_type not in ("csv", "excel", "pdf"):
        raise HTTPException(400, "export_type must be: csv, excel, pdf")

    from datetime import datetime as _dt, timedelta, timezone
    msk_tz = timezone(timedelta(hours=3))
    today = _dt.now(msk_tz).date()

    if period == "today":
        date_range = f"{today}~{today}"
    elif period == "yesterday":
        d = today - timedelta(days=1)
        date_range = f"{d}~{d}"
    elif period == "week":
        date_range = f"{today - timedelta(days=6)}~{today}"
    elif period == "month":
        date_range = f"{today - timedelta(days=29)}~{today}"
    else:
        date_range = f"{today}~{today}"

    if screen == "dashboard":
        data = await asyncio.wait_for(
            asyncio.to_thread(metabase.get_full_dashboard, date_range, merchant), timeout=60
        )
    elif screen == "traders":
        data = await asyncio.wait_for(
            asyncio.to_thread(metabase.get_trader_dashboard, period), timeout=60
        )
    elif screen == "merchants":
        merchants = await asyncio.to_thread(database.get_all_merchants)
        data = {"merchants": merchants}
    else:
        raise HTTPException(400, f"Unknown screen: {screen}")

    if export_type == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        if screen == "dashboard":
            kpi = data.get("kpi", {})
            writer.writerow(["Metric", "Value"])
            for k, v in kpi.items():
                writer.writerow([k, v])
            writer.writerow([])

            top = data.get("top_merchants", [])
            if top:
                headers = list(top[0].keys()) if top else []
                writer.writerow(headers)
                for row in top:
                    writer.writerow([row.get(h, "") for h in headers])
        elif screen == "merchants":
            items = data.get("merchants", [])
            if items:
                headers = ["id", "name", "status", "mood", "current_rate", "conversion", "contact_person"]
                writer.writerow(headers)
                for m in items:
                    writer.writerow([m.get(h, "") for h in headers])

        content = output.getvalue()
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=processinghub_{screen}_{period}.csv"}
        )

    elif export_type == "excel":
        try:
            from openpyxl import Workbook
        except ImportError:
            raise HTTPException(500, "openpyxl not installed. Run: pip install openpyxl")

        wb = Workbook()
        ws = wb.active
        ws.title = screen.capitalize()

        if screen == "dashboard":
            kpi = data.get("kpi", {})
            ws.append(["Metric", "Value"])
            for k, v in kpi.items():
                ws.append([k, v])
            ws.append([])
            top = data.get("top_merchants", [])
            if top:
                headers = list(top[0].keys())
                ws.append(headers)
                for row in top:
                    ws.append([row.get(h, "") for h in headers])
        elif screen == "merchants":
            items = data.get("merchants", [])
            headers = ["id", "name", "status", "mood", "current_rate", "conversion", "contact_person"]
            ws.append(headers)
            for m in items:
                ws.append([m.get(h, "") for h in headers])

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=processinghub_{screen}_{period}.xlsx"}
        )

    elif export_type == "pdf":
        try:
            from fpdf import FPDF
        except ImportError:
            raise HTTPException(500, "fpdf2 not installed")

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"ProcessingHub {screen.capitalize()} Report", ln=True, align="C")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, f"Period: {period} | Generated: {_dt.now(msk_tz).strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
        pdf.ln(5)

        if screen == "dashboard":
            kpi = data.get("kpi", {})
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "KPI Summary", ln=True)
            pdf.set_font("Helvetica", "", 10)
            for k, v in kpi.items():
                pdf.cell(80, 7, str(k), border=1)
                pdf.cell(60, 7, str(v), border=1, ln=True)

        output = io.BytesIO()
        pdf_bytes = pdf.output()
        output.write(pdf_bytes)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=processinghub_{screen}_{period}.pdf"}
        )


# ── Static files (React frontend) ─────────────────────────────────────────────

DIST_DIR = Path(__file__).parent / "webapp" / "dist"

if DIST_DIR.exists():
    # Hashed assets (/assets/*) — immutable, cache for 1 year
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(DIST_DIR / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file = DIST_DIR / full_path
        if file.exists() and file.is_file():
            # Hashed files are immutable
            headers = {}
            if any(file.name.endswith(ext) for ext in ('.js', '.css')):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(file, headers=headers)
        return FileResponse(DIST_DIR / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
