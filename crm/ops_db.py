"""
Database operations for Ops (Incidents & Alerts)
Phase 1: Incidents & Alerts MVP
"""
import logging
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import uuid

from config import DATABASE_URL, USE_POSTGRES

logger = logging.getLogger(__name__)


def get_ops_db():
    """Get PostgreSQL connection for ops tables"""
    if not USE_POSTGRES or not DATABASE_URL:
        raise RuntimeError("Ops features require PostgreSQL (DATABASE_URL must be set)")

    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DATABASE_URL)
    return conn


# ============ INCIDENTS ============

def create_incident(
    type: str,
    severity: str,
    scope: str,
    metric: str,
    current_value: float,
    title: str,
    baseline_value: Optional[float] = None,
    delta_value: Optional[float] = None,
    delta_pct: Optional[float] = None,
    period_from: Optional[datetime] = None,
    period_to: Optional[datetime] = None,
    dimensions: Optional[Dict] = None,
    description: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    rule_id: Optional[str] = None,
) -> str:
    """
    Create a new incident.
    Returns incident_id (UUID as string).
    """
    conn = get_ops_db()
    cursor = conn.cursor()

    incident_id = str(uuid.uuid4())
    dimensions = dimensions or {}
    dedupe_key = dedupe_key or f"{type}|{scope}|{metric}|{json.dumps(dimensions, sort_keys=True)}"

    # Set default period if not provided
    if not period_to:
        period_to = datetime.utcnow()
    if not period_from:
        period_from = period_to - timedelta(hours=1)

    cursor.execute("""
        INSERT INTO incidents (
            id, type, severity, status, scope, metric,
            baseline_value, current_value, delta_value, delta_pct,
            period_from, period_to, dimensions, title, description,
            dedupe_key, rule_id, created_by
        ) VALUES (
            %s, %s, %s, 'open', %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, 'rule'
        )
    """, (
        incident_id, type, severity, scope, metric,
        baseline_value, current_value, delta_value, delta_pct,
        period_from, period_to, json.dumps(dimensions), title, description,
        dedupe_key, rule_id
    ))

    # Add "created" event
    add_incident_event(incident_id, "created", None, {}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Created incident {incident_id}: {title}")
    return incident_id


def update_incident(
    incident_id: str,
    current_value: Optional[float] = None,
    delta_value: Optional[float] = None,
    delta_pct: Optional[float] = None,
) -> bool:
    """
    Update incident values (for refresh during dedupe).
    Returns True if updated.
    """
    conn = get_ops_db()
    cursor = conn.cursor()

    updates = []
    params = []

    if current_value is not None:
        updates.append("current_value = %s")
        params.append(current_value)
    if delta_value is not None:
        updates.append("delta_value = %s")
        params.append(delta_value)
    if delta_pct is not None:
        updates.append("delta_pct = %s")
        params.append(delta_pct)

    if not updates:
        cursor.close()
        conn.close()
        return False

    params.append(incident_id)
    cursor.execute(f"""
        UPDATE incidents
        SET {', '.join(updates)}
        WHERE id = %s
    """, params)

    # Add "refreshed" event
    add_incident_event(incident_id, "refreshed", None, {
        "current_value": current_value,
        "delta_pct": delta_pct
    }, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Updated incident {incident_id}")
    return True


def find_incident_by_dedupe_key(dedupe_key: str) -> Optional[Dict]:
    """
    Find existing open/ack incident by dedupe key.
    Returns incident dict or None.
    """
    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT * FROM incidents
        WHERE dedupe_key = %s
          AND status IN ('open', 'ack')
          AND is_muted = FALSE
        ORDER BY created_at DESC
        LIMIT 1
    """, (dedupe_key,))

    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return dict(row) if row else None


def get_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    scope: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict]:
    """
    Get list of incidents with filters.
    Returns list of incident dicts.
    """
    import psycopg2.extras

    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    where_clauses = []
    params = []

    if status:
        where_clauses.append("status = %s")
        params.append(status)
    if severity:
        where_clauses.append("severity = %s")
        params.append(severity)
    if scope:
        where_clauses.append("scope = %s")
        params.append(scope)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    cursor.execute(f"""
        SELECT * FROM incidents
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [dict(row) for row in rows]


def get_incident(incident_id: str) -> Optional[Dict]:
    """Get single incident by ID"""
    import psycopg2.extras

    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,))
    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return dict(row) if row else None


def ack_incident(incident_id: str, user_id: Optional[str] = None) -> bool:
    """Acknowledge incident"""
    conn = get_ops_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE incidents
        SET status = 'ack', ack_at = NOW()
        WHERE id = %s AND status = 'open'
    """, (incident_id,))

    updated = cursor.rowcount > 0

    if updated:
        add_incident_event(incident_id, "ack", user_id, {}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Acknowledged incident {incident_id}")
    return updated


def resolve_incident(incident_id: str, user_id: Optional[str] = None) -> bool:
    """Resolve incident"""
    conn = get_ops_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE incidents
        SET status = 'resolved', resolved_at = NOW()
        WHERE id = %s AND status IN ('open', 'ack')
    """, (incident_id,))

    updated = cursor.rowcount > 0

    if updated:
        add_incident_event(incident_id, "resolve", user_id, {}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Resolved incident {incident_id}")
    return updated


def reopen_incident(incident_id: str, user_id: Optional[str] = None) -> bool:
    """Reopen incident"""
    conn = get_ops_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE incidents
        SET status = 'reopened', resolved_at = NULL
        WHERE id = %s AND status = 'resolved'
    """, (incident_id,))

    updated = cursor.rowcount > 0

    if updated:
        add_incident_event(incident_id, "reopen", user_id, {}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Reopened incident {incident_id}")
    return updated


def assign_incident(incident_id: str, owner_user_id: str, user_id: Optional[str] = None) -> bool:
    """Assign incident to owner"""
    conn = get_ops_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE incidents
        SET owner_user_id = %s
        WHERE id = %s
    """, (owner_user_id, incident_id))

    updated = cursor.rowcount > 0

    if updated:
        add_incident_event(incident_id, "assign", user_id, {"owner_user_id": owner_user_id}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Assigned incident {incident_id} to {owner_user_id}")
    return updated


def mute_incident(incident_id: str, minutes: Optional[int] = None, until: Optional[datetime] = None, user_id: Optional[str] = None) -> bool:
    """Mute incident"""
    conn = get_ops_db()
    cursor = conn.cursor()

    if until:
        mute_until = until
    elif minutes:
        mute_until = datetime.utcnow() + timedelta(minutes=minutes)
    else:
        mute_until = None

    cursor.execute("""
        UPDATE incidents
        SET is_muted = TRUE, mute_until = %s
        WHERE id = %s
    """, (mute_until, incident_id))

    updated = cursor.rowcount > 0

    if updated:
        add_incident_event(incident_id, "mute", user_id, {"mute_until": str(mute_until) if mute_until else None}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Muted incident {incident_id} until {mute_until}")
    return updated


def unmute_incident(incident_id: str, user_id: Optional[str] = None) -> bool:
    """Unmute incident"""
    conn = get_ops_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE incidents
        SET is_muted = FALSE, mute_until = NULL
        WHERE id = %s
    """, (incident_id,))

    updated = cursor.rowcount > 0

    if updated:
        add_incident_event(incident_id, "unmute", user_id, {}, cursor=cursor)

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"[Ops] Unmuted incident {incident_id}")
    return updated


def add_incident_event(incident_id: str, event_type: str, user_id: Optional[str], payload: Dict, cursor=None) -> str:
    """
    Add event to incident timeline.
    If cursor is provided, uses it (for transactions), otherwise creates new connection.
    """
    event_id = str(uuid.uuid4())
    close_after = False

    if cursor is None:
        conn = get_ops_db()
        cursor = conn.cursor()
        close_after = True

    cursor.execute("""
        INSERT INTO incident_events (id, incident_id, event_type, actor_user_id, payload)
        VALUES (%s, %s, %s, %s, %s)
    """, (event_id, incident_id, event_type, user_id, json.dumps(payload)))

    if close_after:
        conn.commit()
        cursor.close()
        conn.close()

    return event_id


def get_incident_events(incident_id: str) -> List[Dict]:
    """Get timeline events for incident"""
    import psycopg2.extras

    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT * FROM incident_events
        WHERE incident_id = %s
        ORDER BY created_at ASC
    """, (incident_id,))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [dict(row) for row in rows]


# ============ ALERTS ============

def get_enabled_alerts() -> List[Dict]:
    """Get all enabled alerts"""
    import psycopg2.extras

    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT * FROM alerts
        WHERE enabled = TRUE
        ORDER BY created_at ASC
    """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [dict(row) for row in rows]


def create_alert_fire(alert_id: str, context: Dict, incident_id: Optional[str] = None) -> str:
    """Record alert fire"""
    conn = get_ops_db()
    cursor = conn.cursor()

    fire_id = str(uuid.uuid4())

    cursor.execute("""
        INSERT INTO alert_fires (id, alert_id, context, incident_id)
        VALUES (%s, %s, %s, %s)
    """, (fire_id, alert_id, json.dumps(context), incident_id))

    conn.commit()
    cursor.close()
    conn.close()

    return fire_id


def get_last_alert_fire(alert_id: str) -> Optional[Dict]:
    """Get last fire time for cooldown check"""
    import psycopg2.extras

    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT * FROM alert_fires
        WHERE alert_id = %s
        ORDER BY fired_at DESC
        LIMIT 1
    """, (alert_id,))

    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return dict(row) if row else None


# ============ AUDIT LOG ============

def log_audit(user_id: Optional[str], action: str, resource_type: str, resource_id: str, payload: Dict = None):
    """Write audit log entry"""
    conn = get_ops_db()
    cursor = conn.cursor()

    log_id = str(uuid.uuid4())
    payload = payload or {}

    cursor.execute("""
        INSERT INTO audit_log (id, user_id, action, resource_type, resource_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (log_id, user_id, action, resource_type, resource_id, json.dumps(payload)))

    conn.commit()
    cursor.close()
    conn.close()


# ============ AUTO-RESOLVE ============

def get_auto_resolve_candidates() -> List[Dict]:
    """Get open incidents configured for auto-resolve."""
    import psycopg2.extras
    conn = get_ops_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute("""
            SELECT * FROM incidents
            WHERE status IN ('open', 'ack')
              AND auto_resolve_minutes IS NOT NULL
              AND is_muted = FALSE
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def auto_resolve_incident(incident_id: str, reason: str, metric_value: float = None, threshold: float = None) -> bool:
    """Auto-resolve an incident when metric returns to normal."""
    conn = get_ops_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE incidents
            SET status = 'resolved', resolved_at = NOW()
            WHERE id = %s AND status IN ('open', 'ack')
        """, (incident_id,))

        updated = cursor.rowcount > 0

        if updated:
            add_incident_event(incident_id, "auto_resolve", "system", {
                "reason": reason,
                "metric_value": metric_value,
                "threshold": threshold,
            }, cursor=cursor)

            # Log to auto-resolve history
            cursor.execute("""
                INSERT INTO incident_auto_resolve_log (incident_id, resolved_reason, metric_value, threshold)
                VALUES (%s, %s, %s, %s)
            """, (incident_id, reason, metric_value, threshold))

        conn.commit()
        logger.info(f"[Ops] Auto-resolved incident {incident_id}: {reason}")
        return updated
    except Exception as e:
        conn.rollback()
        logger.error(f"[Ops] Error auto-resolving incident {incident_id}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def configure_auto_resolve(incident_id: str, minutes: int, metric_threshold: float = None) -> bool:
    """Configure auto-resolve for an incident."""
    conn = get_ops_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE incidents
            SET auto_resolve_minutes = %s, auto_resolve_metric_threshold = %s
            WHERE id = %s
        """, (minutes, metric_threshold, incident_id))

        updated = cursor.rowcount > 0
        conn.commit()
        return updated
    finally:
        cursor.close()
        conn.close()
