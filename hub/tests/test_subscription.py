"""Test subscription logic."""
import pytest
import asyncio
import aiosqlite
from datetime import datetime, timedelta


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def setup_db(path):
    db = await aiosqlite.connect(path)
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            language_code TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            last_active TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            payment_id TEXT
        );
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            command TEXT NOT NULL,
            query TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_create_subscription(db_path):
    db = await setup_db(db_path)
    now = datetime.utcnow()
    expires = now + timedelta(days=30)
    await db.execute(
        "INSERT INTO subscriptions (user_id, started_at, expires_at, payment_id) VALUES (?,?,?,?)",
        (123, now.isoformat(), expires.isoformat(), "pay_123"),
    )
    await db.commit()
    cur = await db.execute("SELECT * FROM subscriptions WHERE user_id=?", (123,))
    row = await cur.fetchone()
    assert row is not None
    await db.close()


@pytest.mark.asyncio
async def test_check_active_subscription(db_path):
    db = await setup_db(db_path)
    now = datetime.utcnow()
    expires = now + timedelta(days=30)
    await db.execute(
        "INSERT INTO subscriptions (user_id, started_at, expires_at) VALUES (?,?,?)",
        (456, now.isoformat(), expires.isoformat()),
    )
    await db.commit()
    cur = await db.execute(
        "SELECT 1 FROM subscriptions WHERE user_id=? AND expires_at > datetime('now')",
        (456,),
    )
    assert await cur.fetchone() is not None
    await db.close()


@pytest.mark.asyncio
async def test_expired_subscription(db_path):
    db = await setup_db(db_path)
    past = datetime.utcnow() - timedelta(days=60)
    expired = past + timedelta(days=30)
    await db.execute(
        "INSERT INTO subscriptions (user_id, started_at, expires_at) VALUES (?,?,?)",
        (789, past.isoformat(), expired.isoformat()),
    )
    await db.commit()
    cur = await db.execute(
        "SELECT 1 FROM subscriptions WHERE user_id=? AND expires_at > datetime('now')",
        (789,),
    )
    assert await cur.fetchone() is None
    await db.close()


def test_payment_payload_validation():
    from bot.services.payment import validate_payment_payload
    assert validate_payment_payload("pro_subscription") is True
    assert validate_payment_payload("invalid") is False
    assert validate_payment_payload("") is False
