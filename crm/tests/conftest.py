"""
Shared fixtures for MerchantCRM tests.
Uses SQLite in-memory database to avoid PostgreSQL dependency.
"""
import sys
import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# config.py без PASSWORD_SECRET падает при импорте — тестам задаём фиктивный
os.environ.setdefault("PASSWORD_SECRET", "test-secret")


@pytest.fixture(autouse=True)
def mock_init_db():
    """Prevent database.py from calling init_db() on import."""
    with patch.dict(os.environ, {"DATABASE_URL": "", "DB_PATH": ":memory:"}):
        yield


@pytest.fixture
def db_conn():
    """Create in-memory SQLite database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_get_db(db_conn):
    """Patch database.get_db to return test connection."""
    # We need a wrapper that returns the same connection
    # but doesn't close it (tests manage lifecycle)
    class NonClosingConn:
        def __init__(self, conn):
            self._conn = conn
        def cursor(self):
            return self._conn.cursor()
        def execute(self, *a, **kw):
            return self._conn.execute(*a, **kw)
        def commit(self):
            self._conn.commit()
        def close(self):
            pass  # Don't actually close
        def rollback(self):
            self._conn.rollback()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    wrapper = NonClosingConn(db_conn)
    with patch("database.get_db", return_value=wrapper):
        yield db_conn


@pytest.fixture
def sample_merchant():
    return {
        "name": "TestMerchant",
        "status": "active",
        "mood": "neutral",
        "integration_status": "completed",
        "current_rate": 5.5,
        "contact_person": "John",
    }


@pytest.fixture
def sample_incident():
    return {
        "merchant_name": "TestMerchant",
        "merchant_id": 1,
        "incident_type": "conversion_drop",
        "title": "Conversion dropped below 20%",
        "priority": "P1",
        "description": "Conversion dropped from 35% to 15%",
    }


def _create_schema(conn):
    """Create all tables in memory."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            name_source TEXT DEFAULT 'unknown',
            status TEXT DEFAULT 'new',
            integration_status TEXT,
            mood TEXT DEFAULT 'neutral',
            rate_flexibility TEXT,
            current_rate REAL,
            min_rate REAL,
            conversion REAL,
            payment_methods TEXT,
            limits_info TEXT,
            contact_person TEXT,
            group_id INTEGER,
            group_name TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            merchant_name TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            priority TEXT DEFAULT 'P2',
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            assigned_to TEXT,
            acknowledged_at TIMESTAMP,
            acknowledged_by INTEGER,
            resolved_at TIMESTAMP,
            resolved_by INTEGER,
            resolution_notes TEXT,
            trigger_message_id INTEGER,
            due_at TIMESTAMP,
            assigned_user_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_hash TEXT UNIQUE NOT NULL,
            telegram_msg_id INTEGER,
            group_id INTEGER NOT NULL,
            group_name TEXT,
            sender_id INTEGER,
            sender_name TEXT,
            text TEXT NOT NULL,
            processed INTEGER DEFAULT 0,
            processing_result TEXT,
            merchant_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_hash ON message_log(message_hash)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            confidence REAL,
            source_message_id INTEGER,
            source_chat_id INTEGER,
            source_chat_name TEXT,
            decided_by TEXT DEFAULT 'rule',
            incident_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            last_scanned_msg_id INTEGER DEFAULT 0,
            last_scan_at TIMESTAMP,
            merchant_id INTEGER,
            auto_discovered INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            created_by INTEGER,
            note TEXT,
            is_active INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            last_used TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            merchant_id INTEGER,
            alert_type TEXT NOT NULL,
            priority TEXT DEFAULT 'P2',
            title TEXT NOT NULL,
            message TEXT,
            notified INTEGER DEFAULT 0,
            notified_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchant_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(merchant_id, tag)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incident_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_name TEXT NOT NULL,
            conversion_pct REAL,
            alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversion_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_name TEXT NOT NULL,
            date TEXT NOT NULL,
            conversion_pct REAL,
            total_orders INTEGER,
            success_orders INTEGER,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(merchant_name, date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            incidents_opened INTEGER DEFAULT 0,
            incidents_closed INTEGER DEFAULT 0,
            avg_time_to_ack_minutes REAL,
            avg_time_to_resolve_minutes REAL,
            merchants_with_problems INTEGER DEFAULT 0,
            messages_processed INTEGER DEFAULT 0,
            ai_calls INTEGER DEFAULT 0,
            rule_decisions INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            canonical_type TEXT,
            rate REAL,
            limits_min REAL,
            limits_max REAL,
            notes TEXT,
            source_merchant_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER,
            merchant_name TEXT,
            old_status TEXT,
            new_status TEXT,
            reason TEXT,
            notified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchant_chat_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL UNIQUE,
            summary_text TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            last_message_at TIMESTAMP,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            model_used TEXT DEFAULT 'gpt-4o-mini'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanner_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
