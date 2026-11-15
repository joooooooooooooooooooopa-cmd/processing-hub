from __future__ import annotations

import aiosqlite
from datetime import datetime, timedelta
from typing import Optional
from bot.config import DB_PATH, PRO_DURATION_DAYS

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await create_tables(_db)
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


async def create_tables(db: aiosqlite.Connection) -> None:
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
            payment_id TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sub_expires ON subscriptions(expires_at);

        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            command TEXT NOT NULL,
            query TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_log(user_id, created_at);
    """)
    await db.commit()


async def add_user(user_id: int, username: Optional[str] = None,
                   first_name: Optional[str] = None,
                   language_code: Optional[str] = None) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO users (user_id, username, first_name, language_code)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             username=excluded.username,
             first_name=excluded.first_name,
             last_active=datetime('now')""",
        (user_id, username, first_name, language_code),
    )
    await db.commit()


async def get_user(user_id: int) -> Optional[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def check_subscription(user_id: int) -> bool:
    db = await get_db()
    cur = await db.execute(
        "SELECT 1 FROM subscriptions WHERE user_id=? AND expires_at > datetime('now') LIMIT 1",
        (user_id,),
    )
    return await cur.fetchone() is not None


async def add_subscription(user_id: int, payment_id: Optional[str] = None) -> None:
    db = await get_db()
    now = datetime.utcnow()
    expires = now + timedelta(days=PRO_DURATION_DAYS)
    await db.execute(
        "INSERT INTO subscriptions (user_id, started_at, expires_at, payment_id) VALUES (?,?,?,?)",
        (user_id, now.isoformat(), expires.isoformat(), payment_id),
    )
    await db.commit()


async def log_usage(user_id: int, command: str, query: Optional[str] = None) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO usage_log (user_id, command, query) VALUES (?,?,?)",
        (user_id, command, query),
    )
    await db.commit()


async def get_today_usage_count(user_id: int) -> int:
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE user_id=? AND date(created_at)=date('now')",
        (user_id,),
    )
    row = await cur.fetchone()
    return row[0] if row else 0


async def get_stats() -> dict:
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) FROM users")
    total_users = (await cur.fetchone())[0]

    cur = await db.execute(
        "SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE expires_at > datetime('now')"
    )
    active_subs = (await cur.fetchone())[0]

    cur = await db.execute(
        "SELECT command, COUNT(*) as cnt FROM usage_log GROUP BY command ORDER BY cnt DESC LIMIT 10"
    )
    top_commands = [(r[0], r[1]) for r in await cur.fetchall()]

    cur = await db.execute(
        "SELECT COUNT(*) FROM usage_log WHERE date(created_at)=date('now')"
    )
    today_requests = (await cur.fetchone())[0]

    return {
        "total_users": total_users,
        "active_subs": active_subs,
        "top_commands": top_commands,
        "today_requests": today_requests,
    }
