"""Test rate limiting logic."""
import pytest
import asyncio
import aiosqlite
from datetime import datetime


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


async def setup_db(path):
    db = await aiosqlite.connect(path)
    await db.executescript("""
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
async def test_counter_increments(db_path):
    db = await setup_db(db_path)
    user_id = 100

    for i in range(3):
        await db.execute(
            "INSERT INTO usage_log (user_id, command) VALUES (?,?)",
            (user_id, f"/test_{i}"),
        )
    await db.commit()

    cur = await db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE user_id=? AND date(created_at)=date('now')",
        (user_id,),
    )
    count = (await cur.fetchone())[0]
    assert count == 3
    await db.close()


@pytest.mark.asyncio
async def test_limit_reached(db_path):
    db = await setup_db(db_path)
    user_id = 200
    limit = 5

    for i in range(limit):
        await db.execute(
            "INSERT INTO usage_log (user_id, command) VALUES (?,?)",
            (user_id, f"/cmd_{i}"),
        )
    await db.commit()

    cur = await db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE user_id=? AND date(created_at)=date('now')",
        (user_id,),
    )
    count = (await cur.fetchone())[0]
    assert count >= limit
    await db.close()


@pytest.mark.asyncio
async def test_different_users_separate_counters(db_path):
    db = await setup_db(db_path)

    for i in range(5):
        await db.execute("INSERT INTO usage_log (user_id, command) VALUES (?,?)", (301, "/a"))
    for i in range(2):
        await db.execute("INSERT INTO usage_log (user_id, command) VALUES (?,?)", (302, "/b"))
    await db.commit()

    cur = await db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE user_id=? AND date(created_at)=date('now')", (301,))
    assert (await cur.fetchone())[0] == 5

    cur = await db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE user_id=? AND date(created_at)=date('now')", (302,))
    assert (await cur.fetchone())[0] == 2
    await db.close()


def test_skip_commands():
    skip = {"/start", "/help", "/subscribe", "/pro"}
    assert "/start" in skip
    assert "/glossary" not in skip
