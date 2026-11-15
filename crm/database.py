"""
Database models and operations for Merchant CRM v2.0
- Incident-based architecture
- Explainability (reason, source, confidence)
- Canonical data normalization
- Idempotent message processing
- Operational metrics
"""
import sqlite3
import hashlib
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from config import DB_PATH, DATABASE_URL, USE_POSTGRES

logger = logging.getLogger(__name__)

# ============ CANONICAL LISTS ============
# These are the ONLY valid values for each field

CANONICAL_STATUSES = [
    'new',           # First contact
    'negotiation',   # Discussing terms
    'integration',   # Technical integration
    'testing',       # Testing phase
    'active',        # Working, traffic flowing
    'paused',        # Temporarily stopped
    'problem',       # Has issues
    'disconnected',  # Turned off
]

CANONICAL_INTEGRATION_STATUSES = [
    'request',       # Application received
    'docs',          # Document exchange
    'tech',          # Technical work
    'testing',       # Testing
    'completed',     # Done
]

CANONICAL_MOODS = [
    'loyal',         # Happy, cooperative
    'neutral',       # Normal
    'difficult',     # Hard to work with
    'aggressive',    # Unhappy, demanding
]

CANONICAL_RATE_FLEXIBILITY = [
    'flexible',      # Will lower rate
    'negotiable',    # Can discuss
    'firm',          # Won't budge
]

CANONICAL_PAYMENT_METHODS = [
    'sbp',           # SBP/СБП
    'c2c',           # Card to card
    'qr',            # QR codes
    'bank_transfer', # Bank transfer
    'alfa',          # Alfa-Bank
    'tinkoff',       # Tinkoff
    'sber',          # Sberbank
    'vtb',           # VTB
    'raiffeisen',    # Raiffeisen
    'other',         # Other methods
]

CANONICAL_INCIDENT_TYPES = [
    'status_degraded',    # Active -> Problem/Disconnected
    'rate_issue',         # Rate problems
    'conversion_drop',    # Conversion dropped
    'integration_stuck',  # Integration taking too long
    'communication',      # Communication issues
    'technical',          # Technical problems
    'compliance',         # Compliance issues
]

CANONICAL_INCIDENT_PRIORITIES = ['P0', 'P1', 'P2', 'P3']

CANONICAL_NAME_SOURCES = [
    'chat_title',    # Extracted from chat name
    'message',       # Mentioned in message
    'manual',        # Manually entered
    'unknown',       # Source unclear
]


def get_db():
    """Get database connection. Uses PostgreSQL if DATABASE_URL is set, else SQLite."""
    if USE_POSTGRES and DATABASE_URL:
        from db_pg import get_pg_connection
        return get_pg_connection(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def retry_db_operation(func, max_retries=5, delay=1):
    """Retry database operation on lock errors"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            err = str(e).lower()
            if ("locked" in err or "deadlock" in err or "could not serialize" in err) and attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
            raise


def init_db():
    """Initialize database tables with v2.0 schema"""
    db = get_db()
    cursor = db.cursor()

    # ============ MERCHANTS ============
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

    # ============ INCIDENTS ============
    # One incident = one problem with clear lifecycle
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id),
            FOREIGN KEY (trigger_message_id) REFERENCES message_log(id)
        )
    """)

    # ============ MESSAGE LOG (idempotent) ============
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_hash ON message_log(message_hash)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msg_group ON message_log(group_id)")

    # ============ STATUS CHANGES (with explainability) ============
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id),
            FOREIGN KEY (source_message_id) REFERENCES message_log(id),
            FOREIGN KEY (incident_id) REFERENCES incidents(id)
        )
    """)

    # ============ LEGACY: status_history (keep for migration) ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            source_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id)
        )
    """)

    # ============ GROUPS ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            last_scanned_msg_id INTEGER DEFAULT 0,
            last_scan_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ============ PAYMENT METHODS (canonical) ============
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

    # ============ ACCESS KEYS ============
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

    # ============ ALERTS (for notifications) ============
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (incident_id) REFERENCES incidents(id),
            FOREIGN KEY (merchant_id) REFERENCES merchants(id)
        )
    """)

    # ============ OPERATIONAL METRICS ============
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

    # ============ LEGACY: status_alerts (keep for migration) ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER,
            merchant_name TEXT,
            old_status TEXT,
            new_status TEXT,
            reason TEXT,
            notified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id)
        )
    """)

    # ============ LEGACY: messages (keep for migration) ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_msg_id INTEGER,
            group_id INTEGER,
            group_name TEXT,
            sender_id INTEGER,
            sender_name TEXT,
            text TEXT,
            analysis TEXT,
            merchants_mentioned TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ============ LEGACY: traffic_requests ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS traffic_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER,
            requested_by TEXT,
            amount TEXT,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id)
        )
    """)

    # ============ MERCHANT TAGS ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchant_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
            UNIQUE(merchant_id, tag)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_merchant ON merchant_tags(merchant_id)")

    # ============ PERFORMANCE INDEXES ============
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_merchants_status ON merchants(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_merchant ON incidents(merchant_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_changes_merchant ON status_changes(merchant_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_notified ON alerts(notified)")

    # ============ INCIDENT COMMENTS ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incident_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comments_incident ON incident_comments(incident_id)")

    # ============ ALERT HISTORY (for smart patterns) ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_name TEXT NOT NULL,
            conversion_pct REAL,
            alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_hist_merchant ON alert_history(merchant_name, alerted_at)")

    # ============ CONVERSION HISTORY ============
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_hist_merchant ON conversion_history(merchant_name, date)")

    # ============ SCHEMA MIGRATIONS (safe — db_pg wraps DDL in savepoints) ============
    # Add any missing columns to existing tables. If column already exists, the
    # ALTER TABLE will fail harmlessly (caught by db_pg's DDL savepoint handler
    # in PostgreSQL, or by the except below in SQLite).
    migration_alters = [
        # -- incidents: ensure ALL expected columns exist --
        "ALTER TABLE incidents ADD COLUMN merchant_id BIGINT",
        "ALTER TABLE incidents ADD COLUMN merchant_name TEXT",
        "ALTER TABLE incidents ADD COLUMN incident_type TEXT",
        "ALTER TABLE incidents ADD COLUMN priority TEXT DEFAULT 'P2'",
        "ALTER TABLE incidents ADD COLUMN title TEXT",
        "ALTER TABLE incidents ADD COLUMN description TEXT",
        "ALTER TABLE incidents ADD COLUMN status TEXT DEFAULT 'open'",
        "ALTER TABLE incidents ADD COLUMN assigned_to TEXT",
        "ALTER TABLE incidents ADD COLUMN acknowledged_at TIMESTAMP",
        "ALTER TABLE incidents ADD COLUMN acknowledged_by BIGINT",
        "ALTER TABLE incidents ADD COLUMN resolved_at TIMESTAMP",
        "ALTER TABLE incidents ADD COLUMN resolved_by BIGINT",
        "ALTER TABLE incidents ADD COLUMN resolution_notes TEXT",
        "ALTER TABLE incidents ADD COLUMN trigger_message_id BIGINT",
        "ALTER TABLE incidents ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE incidents ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE incidents ADD COLUMN due_at TIMESTAMP",
        "ALTER TABLE incidents ADD COLUMN assigned_user_name TEXT",
        # -- alerts: ensure ALL expected columns exist --
        "ALTER TABLE alerts ADD COLUMN incident_id BIGINT",
        "ALTER TABLE alerts ADD COLUMN merchant_id BIGINT",
        "ALTER TABLE alerts ADD COLUMN alert_type TEXT",
        "ALTER TABLE alerts ADD COLUMN priority TEXT DEFAULT 'P2'",
        "ALTER TABLE alerts ADD COLUMN title TEXT",
        "ALTER TABLE alerts ADD COLUMN message TEXT",
        "ALTER TABLE alerts ADD COLUMN notified INTEGER DEFAULT 0",
        "ALTER TABLE alerts ADD COLUMN notified_at TIMESTAMP",
        "ALTER TABLE alerts ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        # -- status_changes: ensure columns --
        "ALTER TABLE status_changes ADD COLUMN merchant_id BIGINT",
        "ALTER TABLE status_changes ADD COLUMN field_name TEXT",
        "ALTER TABLE status_changes ADD COLUMN old_value TEXT",
        "ALTER TABLE status_changes ADD COLUMN new_value TEXT",
        "ALTER TABLE status_changes ADD COLUMN reason TEXT",
        "ALTER TABLE status_changes ADD COLUMN confidence REAL",
        "ALTER TABLE status_changes ADD COLUMN source_message_id BIGINT",
        "ALTER TABLE status_changes ADD COLUMN source_chat_id BIGINT",
        "ALTER TABLE status_changes ADD COLUMN source_chat_name TEXT",
        "ALTER TABLE status_changes ADD COLUMN decided_by TEXT DEFAULT 'rule'",
        "ALTER TABLE status_changes ADD COLUMN incident_id BIGINT",
        "ALTER TABLE status_changes ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        # -- message_log: scanner columns --
        "ALTER TABLE message_log ADD COLUMN merchant_id INTEGER",
        # -- groups: scanner columns --
        "ALTER TABLE groups ADD COLUMN merchant_id INTEGER",
        "ALTER TABLE groups ADD COLUMN auto_discovered INTEGER DEFAULT 0",
    ]
    for col_def in migration_alters:
        try:
            cursor.execute(col_def)
        except (sqlite3.OperationalError, Exception):
            pass  # Column already exists or other safe DDL error

    # ============ PostgreSQL: widen INTEGER columns to BIGINT for Telegram IDs ============
    if USE_POSTGRES:
        bigint_alters = [
            # message_log: Telegram IDs can exceed 32-bit
            "ALTER TABLE message_log ALTER COLUMN telegram_msg_id TYPE BIGINT",
            "ALTER TABLE message_log ALTER COLUMN group_id TYPE BIGINT",
            "ALTER TABLE message_log ALTER COLUMN sender_id TYPE BIGINT",
            "ALTER TABLE message_log ALTER COLUMN merchant_id TYPE BIGINT",
            # merchants
            "ALTER TABLE merchants ALTER COLUMN group_id TYPE BIGINT",
            # groups
            "ALTER TABLE groups ALTER COLUMN id TYPE BIGINT",
            "ALTER TABLE groups ALTER COLUMN last_scanned_msg_id TYPE BIGINT",
            "ALTER TABLE groups ALTER COLUMN merchant_id TYPE BIGINT",
            # incidents
            "ALTER TABLE incidents ALTER COLUMN merchant_id TYPE BIGINT",
            "ALTER TABLE incidents ALTER COLUMN acknowledged_by TYPE BIGINT",
            "ALTER TABLE incidents ALTER COLUMN resolved_by TYPE BIGINT",
            "ALTER TABLE incidents ALTER COLUMN trigger_message_id TYPE BIGINT",
            # status_changes
            "ALTER TABLE status_changes ALTER COLUMN merchant_id TYPE BIGINT",
            "ALTER TABLE status_changes ALTER COLUMN source_message_id TYPE BIGINT",
            "ALTER TABLE status_changes ALTER COLUMN source_chat_id TYPE BIGINT",
            # alerts
            "ALTER TABLE alerts ALTER COLUMN incident_id TYPE BIGINT",
            "ALTER TABLE alerts ALTER COLUMN merchant_id TYPE BIGINT",
        ]
        for alter in bigint_alters:
            try:
                cursor.execute(alter)
            except Exception:
                pass  # column already BIGINT or doesn't exist

    # ============ SCANNER: chat summaries cache ============
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

    # ============ SCANNER: service state ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanner_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ============ DIAGNOSTIC: log actual schema for critical tables ============
    if USE_POSTGRES:
        for tbl in ['incidents', 'alerts', 'status_changes']:
            try:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s ORDER BY ordinal_position", (tbl,))
                cols = [r[0] for r in cursor.fetchall()]
                print(f"[DB] Table '{tbl}' columns: {cols}")
            except Exception as e:
                print(f"[DB] Could not inspect '{tbl}': {e}")

    db.commit()
    db.close()
    print("[DB] Database initialized (v2.0 schema + CRM extensions + scanner)")


# ============ CANONICAL VALIDATION ============

def validate_status(status: str) -> Optional[str]:
    """Validate and normalize status. Returns None if invalid."""
    if not status:
        return None
    status = status.lower().strip()
    return status if status in CANONICAL_STATUSES else None


def validate_integration_status(status: str) -> Optional[str]:
    if not status:
        return None
    status = status.lower().strip()
    return status if status in CANONICAL_INTEGRATION_STATUSES else None


def validate_mood(mood: str) -> Optional[str]:
    if not mood:
        return None
    mood = mood.lower().strip()
    return mood if mood in CANONICAL_MOODS else None


def validate_payment_method(method: str) -> Optional[str]:
    """Normalize payment method to canonical form"""
    if not method:
        return None
    method = method.lower().strip()

    # Mapping of aliases to canonical names
    aliases = {
        'сбп': 'sbp', 'sbp': 'sbp', 'спб': 'sbp',
        'c2c': 'c2c', 'карта': 'c2c', 'card': 'c2c', 'p2p': 'c2c',
        'qr': 'qr', 'qr-code': 'qr', 'qr code': 'qr', 'нспк': 'qr',
        'bank': 'bank_transfer', 'банк': 'bank_transfer', 'перевод': 'bank_transfer',
        'alfa': 'alfa', 'альфа': 'alfa', 'alphabank': 'alfa',
        'tinkoff': 'tinkoff', 'тинькофф': 'tinkoff', 'тиньков': 'tinkoff',
        'sber': 'sber', 'сбер': 'sber', 'сбербанк': 'sber',
        'vtb': 'vtb', 'втб': 'vtb',
        'raiffeisen': 'raiffeisen', 'райф': 'raiffeisen',
    }

    return aliases.get(method, 'other')


# ============ MESSAGE DEDUPLICATION ============

def compute_message_hash(group_id: int, telegram_msg_id: int, text: str) -> str:
    """Compute unique hash for message deduplication"""
    content = f"{group_id}:{telegram_msg_id}:{text[:500]}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def is_message_processed(group_id: int, telegram_msg_id: int, text: str) -> bool:
    """Check if message was already processed"""
    msg_hash = compute_message_hash(group_id, telegram_msg_id, text)
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT processed FROM message_log WHERE message_hash = ?", (msg_hash,))
    row = cursor.fetchone()
    db.close()
    return row is not None and row[0] == 1


def log_message(group_id: int, telegram_msg_id: int, group_name: str,
                sender_id: int, sender_name: str, text: str) -> Optional[int]:
    """Log message for processing. Returns message_log.id or None if duplicate."""
    msg_hash = compute_message_hash(group_id, telegram_msg_id, text)

    def _operation():
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute("""
                INSERT INTO message_log (message_hash, telegram_msg_id, group_id, group_name,
                                         sender_id, sender_name, text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (msg_hash, telegram_msg_id, group_id, group_name, sender_id, sender_name, text))
            msg_id = cursor.lastrowid
            db.commit()
            db.close()
            return msg_id
        except sqlite3.IntegrityError:
            # Duplicate
            db.close()
            return None

    return retry_db_operation(_operation)


def mark_message_processed(message_id: int, result: str = None):
    """Mark message as processed"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE message_log SET processed = 1, processing_result = ? WHERE id = ?
    """, (result, message_id))
    db.commit()
    db.close()


def get_recent_messages(group_id: int, limit: int = 10) -> List[Dict]:
    """Get recent messages from group for context"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM message_log
        WHERE group_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (group_id, limit))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


# ============ MERCHANTS ============

def get_merchant(name: str) -> Optional[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM merchants WHERE LOWER(name) = LOWER(?)", (name,))
    row = cursor.fetchone()
    db.close()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


def get_merchant_by_id(merchant_id: int) -> Optional[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
    row = cursor.fetchone()
    db.close()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


def search_merchants(query: str) -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM merchants
        WHERE LOWER(name) LIKE LOWER(?)
        ORDER BY updated_at DESC
        LIMIT 20
    """, (f"%{query}%",))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def create_or_update_merchant(
    name: str,
    status: str = None,
    integration_status: str = None,
    mood: str = None,
    rate_flexibility: str = None,
    current_rate: float = None,
    min_rate: float = None,
    conversion: float = None,
    payment_methods: str = None,
    limits_info: str = None,
    contact_person: str = None,
    group_id: int = None,
    group_name: str = None,
    notes: str = None,
    name_source: str = 'unknown',
    reason: str = None,
    confidence: float = None,
    source_message_id: int = None,
    decided_by: str = 'rule'
) -> int:
    """Create or update merchant with full explainability"""

    # Validate canonical values
    validated_status = validate_status(status) if status else None
    validated_integration = validate_integration_status(integration_status) if integration_status else None
    validated_mood = validate_mood(mood) if mood else None

    def _operation():
        db = get_db()
        cursor = db.cursor()

        cursor.execute("SELECT * FROM merchants WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        columns = [desc[0] for desc in cursor.description] if row else []
        existing = dict(zip(columns, row)) if row else None

        if existing:
            merchant_id = existing['id']
            updates = []
            values = []

            # Track changes with explainability
            fields_to_update = {
                'status': validated_status,
                'integration_status': validated_integration,
                'mood': validated_mood,
                'rate_flexibility': rate_flexibility,
                'current_rate': current_rate,
                'min_rate': min_rate,
                'conversion': conversion,
                'payment_methods': payment_methods,
                'limits_info': limits_info,
                'contact_person': contact_person,
                'group_id': group_id,
                'group_name': group_name,
                'notes': notes,
                'name_source': name_source if name_source != 'unknown' else None,
            }

            for field, value in fields_to_update.items():
                if value is not None:
                    old_value = existing.get(field)
                    if str(old_value) != str(value):
                        # Log change with explainability
                        cursor.execute("""
                            INSERT INTO status_changes
                            (merchant_id, field_name, old_value, new_value, reason,
                             confidence, source_message_id, decided_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (merchant_id, field, str(old_value), str(value),
                              reason, confidence, source_message_id, decided_by))

                        updates.append(f"{field} = ?")
                        values.append(value)

                        # Check if we need to create incident for status degradation
                        if field == 'status' and old_value in ('active', 'testing', 'integration'):
                            if value in ('problem', 'disconnected'):
                                _create_incident_for_status_change(
                                    cursor, merchant_id, name, old_value, value,
                                    reason, source_message_id
                                )

            if updates:
                updates.append("updated_at = ?")
                values.append(datetime.now())
                values.append(merchant_id)
                cursor.execute(f"UPDATE merchants SET {', '.join(updates)} WHERE id = ?", values)
        else:
            # Insert new merchant
            cursor.execute("""
                INSERT INTO merchants (name, name_source, status, integration_status, mood,
                                      rate_flexibility, current_rate, min_rate, conversion,
                                      payment_methods, limits_info, contact_person,
                                      group_id, group_name, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, name_source, validated_status or 'new', validated_integration,
                  validated_mood or 'neutral', rate_flexibility, current_rate, min_rate,
                  conversion, payment_methods, limits_info, contact_person,
                  group_id, group_name, notes))
            merchant_id = cursor.lastrowid

            # Log initial creation
            cursor.execute("""
                INSERT INTO status_changes
                (merchant_id, field_name, old_value, new_value, reason, confidence, decided_by)
                VALUES (?, 'created', NULL, 'new', ?, ?, ?)
            """, (merchant_id, reason or 'New merchant discovered', confidence, decided_by))

        db.commit()
        db.close()
        return merchant_id

    return retry_db_operation(_operation)


def _create_incident_for_status_change(cursor, merchant_id: int, merchant_name: str,
                                       old_status: str, new_status: str,
                                       reason: str, source_message_id: int):
    """Create incident when status degrades"""
    priority = 'P0' if new_status == 'disconnected' else 'P1'

    cursor.execute("""
        INSERT INTO incidents (merchant_id, merchant_name, incident_type, priority,
                              title, description, trigger_message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (merchant_id, merchant_name, 'status_degraded', priority,
          f"{merchant_name}: {old_status} -> {new_status}",
          reason or f"Status changed from {old_status} to {new_status}",
          source_message_id))

    incident_id = cursor.lastrowid

    # Create alert for notification
    cursor.execute("""
        INSERT INTO alerts (incident_id, merchant_id, alert_type, priority, title, message)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (incident_id, merchant_id, 'incident_opened', priority,
          f"[{priority}] {merchant_name}: Status Degraded",
          f"{old_status} -> {new_status}\n{reason or ''}"))


def get_merchants_by_status(status: str) -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM merchants
        WHERE LOWER(status) = LOWER(?)
        ORDER BY updated_at DESC
    """, (status,))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def get_all_merchants() -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM merchants ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def get_merchant_history(merchant_id: int, limit: int = 50) -> List[Dict]:
    """Get full change history with explainability"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT sc.*, ml.text as source_text, ml.group_name as source_group
        FROM status_changes sc
        LEFT JOIN message_log ml ON sc.source_message_id = ml.id
        WHERE sc.merchant_id = ?
        ORDER BY sc.created_at DESC
        LIMIT ?
    """, (merchant_id, limit))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def explain_merchant_status(merchant_id: int) -> Dict:
    """Explain why merchant has current status"""
    db = get_db()
    cursor = db.cursor()

    # Get current merchant
    cursor.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
    row = cursor.fetchone()
    if not row:
        db.close()
        return {"error": "Merchant not found"}

    columns = [desc[0] for desc in cursor.description]
    merchant = dict(zip(columns, row))

    # Get last status change
    cursor.execute("""
        SELECT sc.*, ml.text as source_text, ml.group_name as source_group
        FROM status_changes sc
        LEFT JOIN message_log ml ON sc.source_message_id = ml.id
        WHERE sc.merchant_id = ? AND sc.field_name = 'status'
        ORDER BY sc.created_at DESC
        LIMIT 1
    """, (merchant_id,))

    last_change = cursor.fetchone()
    change_columns = [desc[0] for desc in cursor.description] if last_change else []

    # Get open incidents
    cursor.execute("""
        SELECT * FROM incidents
        WHERE merchant_id = ? AND status = 'open'
        ORDER BY created_at DESC
    """, (merchant_id,))
    incidents = cursor.fetchall()
    incident_columns = [desc[0] for desc in cursor.description] if incidents else []

    db.close()

    return {
        "merchant": merchant,
        "current_status": merchant['status'],
        "last_change": dict(zip(change_columns, last_change)) if last_change else None,
        "open_incidents": [dict(zip(incident_columns, i)) for i in incidents],
        "explanation": _build_explanation(merchant, last_change, change_columns)
    }


def _build_explanation(merchant: Dict, last_change, columns) -> str:
    """Build human-readable explanation"""
    if not last_change:
        return f"Merchant {merchant['name']} is in status '{merchant['status']}'. No change history available."

    change = dict(zip(columns, last_change))

    parts = [f"Merchant {merchant['name']} is in status '{merchant['status']}'."]

    if change.get('reason'):
        parts.append(f"Reason: {change['reason']}")

    if change.get('confidence'):
        parts.append(f"Confidence: {change['confidence']*100:.0f}%")

    if change.get('decided_by'):
        parts.append(f"Decision by: {change['decided_by']}")

    if change.get('source_text'):
        parts.append(f"Based on message: \"{change['source_text'][:100]}...\"")

    if change.get('source_group'):
        parts.append(f"From chat: {change['source_group']}")

    if change.get('created_at'):
        parts.append(f"Changed at: {change['created_at']}")

    return " | ".join(parts)


# ============ INCIDENTS ============

def create_incident(
    merchant_id: int,
    merchant_name: str,
    incident_type: str,
    title: str,
    description: str = None,
    priority: str = 'P2',
    trigger_message_id: int = None
) -> int:
    """Create new incident"""
    if incident_type not in CANONICAL_INCIDENT_TYPES:
        incident_type = 'technical'
    if priority not in CANONICAL_INCIDENT_PRIORITIES:
        priority = 'P2'

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO incidents (merchant_id, merchant_name, incident_type, priority,
                              title, description, trigger_message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (merchant_id, merchant_name, incident_type, priority, title, description, trigger_message_id))
    incident_id = cursor.lastrowid

    # Create alert
    cursor.execute("""
        INSERT INTO alerts (incident_id, merchant_id, alert_type, priority, title, message)
        VALUES (?, ?, 'incident_opened', ?, ?, ?)
    """, (incident_id, merchant_id, priority, f"[{priority}] {title}", description or ''))

    db.commit()
    db.close()
    return incident_id


def get_open_incidents(merchant_id: int = None) -> List[Dict]:
    """Get open incidents, optionally filtered by merchant"""
    db = get_db()
    cursor = db.cursor()

    if merchant_id:
        cursor.execute("""
            SELECT * FROM incidents
            WHERE status = 'open' AND merchant_id = ?
            ORDER BY
                CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                created_at DESC
        """, (merchant_id,))
    else:
        cursor.execute("""
            SELECT * FROM incidents
            WHERE status = 'open'
            ORDER BY
                CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                created_at DESC
        """)

    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def get_all_incidents(limit: int = 100) -> List[Dict]:
    """Get all incidents"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM incidents
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def acknowledge_incident(incident_id: int, user_id: int) -> bool:
    """Acknowledge incident (mark as being worked on)"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE incidents
        SET acknowledged_at = CURRENT_TIMESTAMP, acknowledged_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND acknowledged_at IS NULL
    """, (user_id, incident_id))
    updated = cursor.rowcount > 0
    db.commit()
    db.close()
    return updated


def resolve_incident(incident_id: int, user_id: int, resolution_notes: str = None) -> bool:
    """Resolve incident"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE incidents
        SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP,
            resolved_by = ?, resolution_notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'open'
    """, (user_id, resolution_notes, incident_id))
    updated = cursor.rowcount > 0

    if updated:
        # Create resolution alert
        cursor.execute("SELECT merchant_name, title FROM incidents WHERE id = ?", (incident_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("""
                INSERT INTO alerts (incident_id, alert_type, priority, title, message)
                VALUES (?, 'incident_resolved', 'P3', ?, ?)
            """, (incident_id, f"RESOLVED: {row[0]} - {row[1]}", resolution_notes or 'No notes'))

    db.commit()
    db.close()
    return updated


def get_incident_by_id(incident_id: int) -> Optional[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = cursor.fetchone()
    db.close()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


# ============ ALERTS ============

def get_pending_alerts() -> List[Dict]:
    """Get alerts that haven't been notified yet"""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            SELECT * FROM alerts
            WHERE notified = 0
            ORDER BY
                CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                created_at ASC
        """)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error(f"[DB] get_pending_alerts error: {e}")
        return []
    finally:
        db.close()


def mark_alert_notified(alert_id: int):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE alerts SET notified = 1, notified_at = CURRENT_TIMESTAMP WHERE id = ?
    """, (alert_id,))
    db.commit()
    db.close()


# ============ GROUPS ============

def add_group(group_id: int, name: str, group_type: str = "merchant"):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO groups (id, name, type) VALUES (?, ?, ?)
    """, (group_id, name, group_type))
    db.commit()
    db.close()


def get_groups() -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM groups")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def update_group_last_msg(group_id: int, msg_id: int):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE groups SET last_scanned_msg_id = ?, last_scan_at = CURRENT_TIMESTAMP WHERE id = ?
    """, (msg_id, group_id))
    db.commit()
    db.close()


# ============ STATS & METRICS ============

def get_stats() -> Dict:
    """Get basic stats"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(*) FROM merchants WHERE status NOT IN ('payment_method', 'unknown')")
    total = cursor.fetchone()[0]

    cursor.execute("""
        SELECT status, COUNT(*) FROM merchants
        WHERE status NOT IN ('payment_method', 'unknown')
        GROUP BY status
    """)
    by_status = dict(cursor.fetchall())

    cursor.execute("""
        SELECT integration_status, COUNT(*) FROM merchants
        WHERE status NOT IN ('payment_method', 'unknown') AND integration_status IS NOT NULL
        GROUP BY integration_status
    """)
    by_integration = dict(cursor.fetchall())

    cursor.execute("SELECT COUNT(*) FROM groups")
    groups_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM message_log")
    messages_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM incidents WHERE status = 'open'")
    open_incidents = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM payment_methods")
    methods_count = cursor.fetchone()[0]

    db.close()

    return {
        "total_merchants": total,
        "by_status": by_status,
        "by_integration": by_integration,
        "groups_monitored": groups_count,
        "messages_processed": messages_count,
        "open_incidents": open_incidents,
        "payment_methods": methods_count
    }


def get_operational_metrics() -> Dict:
    """Get operational metrics for quality control"""
    db = get_db()
    cursor = db.cursor()

    # Open incidents by priority
    cursor.execute("""
        SELECT priority, COUNT(*) FROM incidents WHERE status = 'open'
        GROUP BY priority
    """)
    by_priority = dict(cursor.fetchall())

    # Average time to acknowledge (for acknowledged incidents)
    cursor.execute("""
        SELECT AVG(
            EXTRACT(EPOCH FROM (acknowledged_at - created_at)) / 60
        ) FROM incidents WHERE acknowledged_at IS NOT NULL
    """)
    avg_ack_time = cursor.fetchone()[0]

    # Average time to resolve
    cursor.execute("""
        SELECT AVG(
            EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60
        ) FROM incidents WHERE resolved_at IS NOT NULL
    """)
    avg_resolve_time = cursor.fetchone()[0]

    # Incidents opened today
    cursor.execute("""
        SELECT COUNT(*) FROM incidents
        WHERE created_at::date = CURRENT_DATE
    """)
    opened_today = cursor.fetchone()[0]

    # Incidents resolved today
    cursor.execute("""
        SELECT COUNT(*) FROM incidents
        WHERE resolved_at::date = CURRENT_DATE
    """)
    resolved_today = cursor.fetchone()[0]

    # Problem merchants (recurring issues)
    cursor.execute("""
        SELECT merchant_name, COUNT(*) as incident_count
        FROM incidents
        GROUP BY merchant_id
        HAVING COUNT(*) >= 3
        ORDER BY incident_count DESC
        LIMIT 10
    """)
    problem_merchants = cursor.fetchall()

    # Messages processed today
    cursor.execute("""
        SELECT COUNT(*) FROM message_log
        WHERE date(created_at) = date('now')
    """)
    messages_today = cursor.fetchone()[0]

    db.close()

    return {
        "open_by_priority": by_priority,
        "avg_time_to_ack_minutes": round(avg_ack_time, 1) if avg_ack_time else None,
        "avg_time_to_resolve_minutes": round(avg_resolve_time, 1) if avg_resolve_time else None,
        "incidents_opened_today": opened_today,
        "incidents_resolved_today": resolved_today,
        "problem_merchants": [{"name": m[0], "incidents": m[1]} for m in problem_merchants],
        "messages_processed_today": messages_today,
    }


def get_problem_merchants() -> List[Dict]:
    """Get merchants with problem/disconnected status and their incidents"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT m.*,
               (SELECT COUNT(*) FROM incidents WHERE merchant_id = m.id AND status = 'open') as open_incidents,
               (SELECT created_at FROM status_changes
                WHERE merchant_id = m.id AND field_name = 'status' AND new_value IN ('problem', 'disconnected')
                ORDER BY created_at DESC LIMIT 1) as problem_since
        FROM merchants m
        WHERE m.status IN ('problem', 'disconnected')
        ORDER BY
            CASE m.status WHEN 'disconnected' THEN 0 ELSE 1 END,
            m.updated_at DESC
    """)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


# ============ ACCESS KEYS ============

def add_access_key(key: str, created_by: int, note: str = None) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO access_keys (key, created_by, note) VALUES (?, ?, ?)
        """, (key, created_by, note))
        db.commit()
        db.close()
        return True
    except:
        db.close()
        return False


def remove_access_key(key: str) -> bool:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM access_keys WHERE key = ?", (key,))
    deleted = cursor.rowcount > 0
    db.commit()
    db.close()
    return deleted


def get_access_keys() -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM access_keys ORDER BY created_at DESC")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def is_valid_key(key: str) -> bool:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT 1 FROM access_keys WHERE key = ? AND is_active = 1", (key,))
    result = cursor.fetchone() is not None
    db.close()
    return result


def log_key_usage(key: str, user_id: int):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE access_keys SET used_count = used_count + 1, last_used = CURRENT_TIMESTAMP WHERE key = ?
    """, (key,))
    db.commit()
    db.close()


# ============ PAYMENT METHODS ============

def add_payment_method(name: str, method_type: str = None, rate: float = None,
                       limits_min: float = None, limits_max: float = None,
                       notes: str = None, source_merchant_id: int = None) -> int:
    canonical_type = validate_payment_method(method_type) if method_type else None

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO payment_methods (name, canonical_type, rate, limits_min, limits_max, notes, source_merchant_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, canonical_type, rate, limits_min, limits_max, notes, source_merchant_id))
    mid = cursor.lastrowid
    db.commit()
    db.close()
    return mid


def get_payment_methods() -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payment_methods ORDER BY name")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


# ============ RETRIEVAL FOR AI ============

def get_merchant_context(merchant_name: str) -> Dict:
    """Get full context for a specific merchant (for AI retrieval)"""
    merchant = get_merchant(merchant_name)
    if not merchant:
        return {"error": f"Merchant '{merchant_name}' not found"}

    history = get_merchant_history(merchant['id'], limit=20)
    incidents = get_open_incidents(merchant['id'])

    return {
        "merchant": merchant,
        "recent_changes": history,
        "open_incidents": incidents,
    }


def get_problem_context() -> Dict:
    """Get context about all problem merchants (for AI retrieval)"""
    problems = get_problem_merchants()
    incidents = get_open_incidents()

    return {
        "problem_merchants": problems,
        "open_incidents": incidents,
        "total_problems": len(problems),
        "total_open_incidents": len(incidents),
    }


def get_stats_context() -> Dict:
    """Get stats context for AI"""
    return {
        "basic_stats": get_stats(),
        "operational_metrics": get_operational_metrics(),
    }


# ============ MERCHANT TAGS ============

def add_merchant_tag(merchant_id: int, tag: str) -> bool:
    tag = tag.strip()[:50]
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO merchant_tags (merchant_id, tag) VALUES (?, ?)", (merchant_id, tag))
        db.commit()
        db.close()
        return True
    except Exception:
        db.close()
        return False


def remove_merchant_tag(merchant_id: int, tag: str) -> bool:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM merchant_tags WHERE merchant_id = ? AND tag = ?", (merchant_id, tag))
    deleted = cursor.rowcount > 0
    db.commit()
    db.close()
    return deleted


def get_merchant_tags(merchant_id: int) -> List[str]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT tag FROM merchant_tags WHERE merchant_id = ? ORDER BY created_at", (merchant_id,))
    rows = cursor.fetchall()
    db.close()
    return [r[0] for r in rows]


# ============ MERCHANT FIELD UPDATE ============

def update_merchant_field(merchant_id: int, field: str, value, changed_by_user_id: int = 0) -> bool:
    """Update a single merchant field with audit trail"""
    ALLOWED_FIELDS = {
        'status', 'integration_status', 'mood', 'rate_flexibility',
        'current_rate', 'min_rate', 'conversion', 'payment_methods',
        'contact_person', 'notes', 'limits_info'
    }
    if field not in ALLOWED_FIELDS:
        return False

    # Validate canonical fields
    if field == 'status':
        value = validate_status(value)
        if not value:
            return False
    elif field == 'integration_status':
        value = validate_integration_status(value)
        if not value:
            return False
    elif field == 'mood':
        value = validate_mood(value)
        if not value:
            return False

    def _operation():
        db = get_db()
        cursor = db.cursor()
        cursor.execute(f"SELECT {field} FROM merchants WHERE id = ?", (merchant_id,))
        row = cursor.fetchone()
        if not row:
            db.close()
            return False
        old_value = row[0]
        cursor.execute(f"UPDATE merchants SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                       (value, merchant_id))
        cursor.execute("""
            INSERT INTO status_changes (merchant_id, field_name, old_value, new_value, reason, decided_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (merchant_id, field, str(old_value), str(value), 'Manual update via bot', f'user:{changed_by_user_id}'))
        db.commit()
        db.close()
        return True

    return retry_db_operation(_operation)


# ============ INCIDENT COMMENTS ============

def add_incident_comment(incident_id: int, user_id: int, user_name: str, text: str) -> int:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO incident_comments (incident_id, user_id, user_name, text)
        VALUES (?, ?, ?, ?)
    """, (incident_id, user_id, user_name, text[:1000]))
    comment_id = cursor.lastrowid
    db.commit()
    db.close()
    return comment_id


def get_incident_comments(incident_id: int) -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM incident_comments WHERE incident_id = ? ORDER BY created_at ASC
    """, (incident_id,))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def get_incident_comment_count(incident_id: int) -> int:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM incident_comments WHERE incident_id = ?", (incident_id,))
    count = cursor.fetchone()[0]
    db.close()
    return count


# ============ INCIDENT ASSIGNMENT & DEADLINES ============

def assign_incident(incident_id: int, user_id: int, user_name: str) -> bool:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE incidents
        SET assigned_to = ?, assigned_user_name = ?,
            acknowledged_at = COALESCE(acknowledged_at, CURRENT_TIMESTAMP),
            acknowledged_by = COALESCE(acknowledged_by, ?),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (str(user_id), user_name, user_id, incident_id))
    updated = cursor.rowcount > 0
    db.commit()
    db.close()
    return updated


def set_incident_due(incident_id: int, due_at: datetime) -> bool:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE incidents SET due_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (due_at.isoformat(), incident_id))
    updated = cursor.rowcount > 0
    db.commit()
    db.close()
    return updated


def create_incident_manual(merchant_name: str, incident_type: str, priority: str,
                           description: str, user_id: int, due_at: datetime = None) -> int:
    """Create incident manually via bot"""
    if incident_type not in CANONICAL_INCIDENT_TYPES:
        incident_type = 'technical'
    if priority not in CANONICAL_INCIDENT_PRIORITIES:
        priority = 'P2'

    merchant = get_merchant(merchant_name)
    merchant_id = merchant['id'] if merchant else 0

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO incidents (merchant_id, merchant_name, incident_type, priority,
                              title, description, assigned_to, assigned_user_name,
                              acknowledged_at, acknowledged_by, due_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
    """, (merchant_id, merchant_name, incident_type, priority,
          f"[Manual] {merchant_name}: {incident_type}",
          description, str(user_id), f'user:{user_id}',
          user_id, due_at.isoformat() if due_at else None))
    incident_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO alerts (incident_id, merchant_id, alert_type, priority, title, message)
        VALUES (?, ?, 'incident_opened', ?, ?, ?)
    """, (incident_id, merchant_id, priority,
          f"[{priority}] {merchant_name}: {incident_type}", description or ''))

    db.commit()
    db.close()
    return incident_id


def get_overdue_incidents() -> List[Dict]:
    """Get open incidents with due_at in the past or within 1 hour"""
    threshold = (datetime.now() + timedelta(hours=1)).isoformat()
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM incidents
        WHERE status = 'open' AND due_at IS NOT NULL AND due_at <= ?
        ORDER BY due_at ASC
    """, (threshold,))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


# ============ ALERT HISTORY (for smart patterns) ============

def save_alert_history(merchant_name: str, conversion_pct: float, alert_type: str):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO alert_history (merchant_name, conversion_pct, alert_type) VALUES (?, ?, ?)
    """, (merchant_name, conversion_pct, alert_type))
    db.commit()
    db.close()


def get_alert_count_today(merchant_name: str) -> int:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM alert_history
        WHERE merchant_name = ? AND date(alerted_at) = date('now')
    """, (merchant_name,))
    count = cursor.fetchone()[0]
    db.close()
    return count


def get_avg_conversion_last_week(merchant_name: str) -> Optional[float]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT AVG(conversion_pct) FROM alert_history
        WHERE merchant_name = ?
          AND alerted_at >= datetime('now', '-7 days')
          AND conversion_pct IS NOT NULL
    """, (merchant_name,))
    row = cursor.fetchone()
    db.close()
    return row[0] if row and row[0] is not None else None


def is_new_problem(merchant_name: str) -> bool:
    """True if merchant had no alerts in the last 7 days"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM alert_history
        WHERE merchant_name = ? AND alerted_at >= datetime('now', '-7 days')
    """, (merchant_name,))
    count = cursor.fetchone()[0]
    db.close()
    return count == 0


# ============ CONVERSION HISTORY ============

def save_daily_conversion(merchant_name: str, date_str: str, conversion_pct: float,
                           total_orders: int, success_orders: int):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO conversion_history (merchant_name, date, conversion_pct, total_orders, success_orders)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(merchant_name, date) DO UPDATE SET
            conversion_pct = excluded.conversion_pct,
            total_orders = excluded.total_orders,
            success_orders = excluded.success_orders,
            recorded_at = CURRENT_TIMESTAMP
    """, (merchant_name, date_str, conversion_pct, total_orders, success_orders))
    db.commit()
    db.close()


def get_conversion_history(merchant_name: str, days: int = 30) -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM conversion_history
        WHERE merchant_name = ? AND date >= date('now', ?)
        ORDER BY date ASC
    """, (merchant_name, f'-{days} days'))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def get_conversion_trend(merchant_name: str, days: int = 3) -> str:
    """Returns 'declining', 'improving', or 'stable' based on last N days of conversion_history"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT conversion_pct FROM conversion_history
            WHERE merchant_name = ? AND conversion_pct IS NOT NULL
            ORDER BY date DESC LIMIT ?
        """, (merchant_name, days))
        rows = [r[0] for r in cursor.fetchall()]
        db.close()
        if len(rows) < 2:
            return 'stable'
        # rows are newest-first: [today, yesterday, day_before]
        declining = all(rows[i] < rows[i+1] for i in range(len(rows)-1))
        improving = all(rows[i] > rows[i+1] for i in range(len(rows)-1))
        if declining:
            return 'declining'
        if improving:
            return 'improving'
        return 'stable'
    except Exception:
        return 'stable'


# ============ CLEANUP ============

def cleanup_old_data():
    """Remove old message_log and alert_history entries"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM message_log WHERE created_at < datetime('now', '-90 days')")
    msg_deleted = cursor.rowcount
    cursor.execute("DELETE FROM alert_history WHERE alerted_at < datetime('now', '-30 days')")
    alert_deleted = cursor.rowcount
    db.commit()
    db.close()
    return msg_deleted, alert_deleted


# ============ EXPORT HELPERS ============

def get_incidents_for_export(days: int = 30) -> List[Dict]:
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT i.*, COUNT(ic.id) as comment_count
        FROM incidents i
        LEFT JOIN incident_comments ic ON ic.incident_id = i.id
        WHERE i.created_at >= datetime('now', ?)
        GROUP BY i.id
        ORDER BY i.created_at DESC
    """, (f'-{days} days',))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


# ============ LEGACY COMPATIBILITY ============

def save_message(telegram_msg_id: int, group_id: int, group_name: str,
                 sender_id: int, sender_name: str, text: str,
                 analysis: str = None, merchants_mentioned: str = None):
    """Legacy function - redirects to new message_log"""
    log_message(group_id, telegram_msg_id, group_name, sender_id, sender_name, text)


def get_merchants_excluding_methods() -> List[Dict]:
    """Legacy function"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM merchants
        WHERE status NOT IN ('payment_method', 'unknown')
        ORDER BY updated_at DESC
    """)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    db.close()
    return [dict(zip(columns, row)) for row in rows]


def get_stats_excluding_methods() -> Dict:
    """Legacy function"""
    return get_stats()


def log_status_change(merchant_id: int, merchant_name: str, old_status: str,
                      new_status: str, reason: str = None):
    """Legacy function - now handled automatically in create_or_update_merchant"""
    pass


# ============ SCANNER FUNCTIONS ============

def link_message_to_merchant(message_id: int, merchant_id: int):
    """Link a processed message to its identified merchant."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE message_log SET merchant_id = ? WHERE id = ?",
            (merchant_id, message_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Failed to link message {message_id} to merchant {merchant_id}: {e}")
    finally:
        conn.close()


def get_merchant_messages(merchant_id: int, limit: int = 50, offset: int = 0,
                          search: str = "", group_name: str = "") -> List[Dict]:
    """Get recent messages linked to a specific merchant (by merchant_id or group_id)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        base_where = "(merchant_id = ? OR group_id = (SELECT group_id FROM merchants WHERE id = ? AND group_id IS NOT NULL))"
        params: list = [merchant_id, merchant_id]

        if search:
            base_where += " AND text LIKE ?"
            params.append(f"%{search}%")
        if group_name:
            base_where += " AND group_name = ?"
            params.append(group_name)

        cursor.execute(f"""
            SELECT id, telegram_msg_id, group_id, group_name, sender_id, sender_name,
                   text, processed, processing_result, merchant_id, created_at
            FROM message_log
            WHERE {base_where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (*params, limit, offset))
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error(f"[DB] get_merchant_messages error: {e}")
        return []
    finally:
        conn.close()


def count_merchant_messages(merchant_id: int, search: str = "", group_name: str = "") -> int:
    """Count total messages for a merchant."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        base_where = "(merchant_id = ? OR group_id = (SELECT group_id FROM merchants WHERE id = ? AND group_id IS NOT NULL))"
        params: list = [merchant_id, merchant_id]

        if search:
            base_where += " AND text LIKE ?"
            params.append(f"%{search}%")
        if group_name:
            base_where += " AND group_name = ?"
            params.append(group_name)

        cursor.execute(f"SELECT COUNT(*) FROM message_log WHERE {base_where}", params)
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"[DB] count_merchant_messages error: {e}")
        return 0
    finally:
        conn.close()


def get_chat_summary(merchant_id: int) -> Optional[Dict]:
    """Get cached chat summary for a merchant."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM merchant_chat_summaries WHERE merchant_id = ?",
            (merchant_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
    except Exception as e:
        logger.error(f"[DB] get_chat_summary error: {e}")
        return None
    finally:
        conn.close()


def save_chat_summary(merchant_id: int, summary: str, message_count: int,
                      last_message_at: str, model: str = 'gpt-4o-mini'):
    """Save or update merchant chat summary."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO merchant_chat_summaries
            (merchant_id, summary_text, message_count, last_message_at, model_used, generated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (merchant_id, summary, message_count, last_message_at, model))
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] save_chat_summary error: {e}")
    finally:
        conn.close()


def get_scanner_state() -> Dict:
    """Get scanner service state for health monitoring."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT key, value, updated_at FROM scanner_state")
        rows = cursor.fetchall()
        return {row[0]: {'value': row[1], 'updated_at': str(row[2])} for row in rows}
    except Exception as e:
        logger.error(f"[DB] get_scanner_state error: {e}")
        return {}
    finally:
        conn.close()


def set_scanner_state(key: str, value: str):
    """Set scanner state value."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO scanner_state (key, value, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
            """, (key, value))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO scanner_state (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, value))
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] set_scanner_state error: {e}")
    finally:
        conn.close()


def apply_ops_migration():
    """
    Apply Phase 1 Ops migration (incidents, alerts, audit_log tables).
    Safe to run multiple times (idempotent).
    Only works with PostgreSQL.
    """
    if not USE_POSTGRES or not DATABASE_URL:
        logger.info("[Ops Migration] Skipping - PostgreSQL not configured")
        return

    migration_file = Path(__file__).parent / "migrations" / "001_ops_tables.sql"

    if not migration_file.exists():
        logger.warning(f"[Ops Migration] File not found: {migration_file}")
        return

    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()

        # Read and execute migration SQL
        sql = migration_file.read_text(encoding='utf-8')
        cursor.execute(sql)

        conn.close()
        logger.info("[Ops Migration] ✓ Applied 001_ops_tables.sql successfully")

    except Exception as e:
        logger.error(f"[Ops Migration] Failed to apply migration: {e}")
        raise


def apply_scanner_migration():
    """
    Apply Scanner migration (002_scanner_tables.sql).
    Safe to run multiple times (idempotent).
    Only works with PostgreSQL.
    """
    if not USE_POSTGRES or not DATABASE_URL:
        return

    migration_file = Path(__file__).parent / "migrations" / "002_scanner_tables.sql"

    if not migration_file.exists():
        logger.warning(f"[Scanner Migration] File not found: {migration_file}")
        return

    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        sql = migration_file.read_text(encoding='utf-8')
        cursor.execute(sql)
        conn.close()
        logger.info("[Scanner Migration] ✓ Applied 002_scanner_tables.sql successfully")
    except Exception as e:
        logger.error(f"[Scanner Migration] Failed: {e}")


def apply_new_features_migration():
    """Apply new features migration (003_new_features.sql)."""
    if not USE_POSTGRES or not DATABASE_URL:
        return
    migration_file = Path(__file__).parent / "migrations" / "003_new_features.sql"
    if not migration_file.exists():
        return
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        sql = migration_file.read_text(encoding='utf-8')
        for statement in sql.split(';'):
            statement = statement.strip()
            if statement:
                try:
                    cursor.execute(statement)
                except Exception as e:
                    logger.warning(f"[Migration 003] Statement skipped: {e}")
        conn.close()
        logger.info("[Migration] Applied 003_new_features.sql")
    except Exception as e:
        logger.error(f"[Migration 003] Failed: {e}")


# Initialize on import
init_db()
apply_ops_migration()
apply_scanner_migration()
apply_new_features_migration()
