"""Unit tests for database.py"""
import sqlite3
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta


class TestValidation:
    def test_validate_status_valid(self):
        from database import validate_status
        assert validate_status("active") == "active"
        assert validate_status("ACTIVE") == "active"
        assert validate_status(" problem ") == "problem"

    def test_validate_status_invalid(self):
        from database import validate_status
        assert validate_status("invalid_status") is None
        assert validate_status("") is None
        assert validate_status(None) is None

    def test_validate_mood_valid(self):
        from database import validate_mood
        assert validate_mood("loyal") == "loyal"
        assert validate_mood("NEUTRAL") == "neutral"

    def test_validate_mood_invalid(self):
        from database import validate_mood
        assert validate_mood("happy") is None

    def test_validate_payment_method_aliases(self):
        from database import validate_payment_method
        assert validate_payment_method("сбп") == "sbp"
        assert validate_payment_method("sbp") == "sbp"
        assert validate_payment_method("тинькофф") == "tinkoff"
        assert validate_payment_method("карта") == "c2c"
        assert validate_payment_method("unknown_method") == "other"

    def test_validate_integration_status(self):
        from database import validate_integration_status
        assert validate_integration_status("completed") == "completed"
        assert validate_integration_status("invalid") is None


class TestMessageDedup:
    def test_compute_message_hash(self):
        from database import compute_message_hash
        h1 = compute_message_hash(123, 456, "hello")
        h2 = compute_message_hash(123, 456, "hello")
        h3 = compute_message_hash(123, 457, "hello")
        assert h1 == h2  # Same input = same hash
        assert h1 != h3  # Different msg_id = different hash
        assert len(h1) == 32  # SHA256 truncated to 32 chars

    def test_is_message_processed_false_for_new(self, mock_get_db):
        from database import is_message_processed
        assert is_message_processed(123, 456, "hello") is False

    def test_log_message_returns_id(self, mock_get_db):
        from database import log_message
        msg_id = log_message(123, 456, "TestGroup", 789, "User", "Hello world test message")
        assert msg_id is not None
        assert isinstance(msg_id, int)

    def test_log_message_duplicate_returns_none(self, mock_get_db):
        from database import log_message
        msg_id1 = log_message(123, 456, "TestGroup", 789, "User", "Hello world test message")
        msg_id2 = log_message(123, 456, "TestGroup", 789, "User", "Hello world test message")
        assert msg_id1 is not None
        assert msg_id2 is None  # Duplicate


class TestMerchants:
    def _insert_merchant(self, db_conn, name="TestMerchant", status="active"):
        db_conn.execute(
            "INSERT INTO merchants (name, status, mood) VALUES (?, ?, ?)",
            (name, status, "neutral")
        )
        db_conn.commit()

    def test_get_merchant_by_name(self, mock_get_db, db_conn):
        from database import get_merchant
        self._insert_merchant(db_conn)
        m = get_merchant("TestMerchant")
        assert m is not None
        assert m["name"] == "TestMerchant"
        assert m["status"] == "active"

    def test_get_merchant_case_insensitive(self, mock_get_db, db_conn):
        from database import get_merchant
        self._insert_merchant(db_conn)
        m = get_merchant("testmerchant")
        assert m is not None

    def test_get_merchant_not_found(self, mock_get_db, db_conn):
        from database import get_merchant
        m = get_merchant("NonExistent")
        assert m is None

    def test_get_merchant_by_id(self, mock_get_db, db_conn):
        from database import get_merchant_by_id
        self._insert_merchant(db_conn)
        m = get_merchant_by_id(1)
        assert m is not None
        assert m["name"] == "TestMerchant"

    def test_search_merchants(self, mock_get_db, db_conn):
        from database import search_merchants
        self._insert_merchant(db_conn, "Alpha Pay")
        self._insert_merchant(db_conn, "Beta Pay")
        self._insert_merchant(db_conn, "Gamma Bank")
        results = search_merchants("Pay")
        assert len(results) == 2

    def test_get_all_merchants(self, mock_get_db, db_conn):
        from database import get_all_merchants
        self._insert_merchant(db_conn, "M1")
        self._insert_merchant(db_conn, "M2")
        results = get_all_merchants()
        assert len(results) == 2

    def test_create_or_update_merchant_creates_new(self, mock_get_db, db_conn):
        from database import create_or_update_merchant, get_merchant
        mid = create_or_update_merchant("NewMerchant", status="new")
        assert mid is not None
        m = get_merchant("NewMerchant")
        assert m is not None
        assert m["status"] == "new"

    def test_create_or_update_merchant_updates_existing(self, mock_get_db, db_conn):
        from database import create_or_update_merchant, get_merchant
        create_or_update_merchant("ExistingMerchant", status="new")
        create_or_update_merchant("ExistingMerchant", status="active")
        m = get_merchant("ExistingMerchant")
        assert m["status"] == "active"

    def test_create_or_update_tracks_changes(self, mock_get_db, db_conn):
        from database import create_or_update_merchant, get_merchant_history
        mid = create_or_update_merchant("TrackedMerchant", status="new")
        create_or_update_merchant("TrackedMerchant", status="active")
        history = get_merchant_history(mid)
        assert len(history) >= 1
        status_changes = [h for h in history if h["field_name"] == "status"]
        assert any(h["new_value"] == "active" for h in status_changes)

    def test_status_degradation_creates_incident(self, mock_get_db, db_conn):
        from database import create_or_update_merchant, get_open_incidents
        mid = create_or_update_merchant("DegradeMerchant", status="active")
        create_or_update_merchant("DegradeMerchant", status="disconnected")
        incidents = get_open_incidents(mid)
        assert len(incidents) >= 1
        assert incidents[0]["incident_type"] == "status_degraded"


class TestMerchantFields:
    def _insert_merchant(self, db_conn):
        db_conn.execute(
            "INSERT INTO merchants (name, status, mood, current_rate) VALUES (?, ?, ?, ?)",
            ("FieldTest", "active", "neutral", 5.0)
        )
        db_conn.commit()
        return 1

    def test_update_merchant_field_allowed(self, mock_get_db, db_conn):
        from database import update_merchant_field, get_merchant_by_id
        mid = self._insert_merchant(db_conn)
        result = update_merchant_field(mid, "notes", "Updated notes")
        assert result is True
        m = get_merchant_by_id(mid)
        assert m["notes"] == "Updated notes"

    def test_update_merchant_field_disallowed(self, mock_get_db, db_conn):
        from database import update_merchant_field
        mid = self._insert_merchant(db_conn)
        result = update_merchant_field(mid, "id", "999")
        assert result is False

    def test_update_merchant_field_validates_status(self, mock_get_db, db_conn):
        from database import update_merchant_field
        mid = self._insert_merchant(db_conn)
        result = update_merchant_field(mid, "status", "invalid_status")
        assert result is False


class TestMerchantTags:
    def _insert_merchant(self, db_conn):
        db_conn.execute(
            "INSERT INTO merchants (name, status) VALUES (?, ?)",
            ("TagTest", "active")
        )
        db_conn.commit()
        return 1

    def test_add_and_get_tags(self, mock_get_db, db_conn):
        from database import add_merchant_tag, get_merchant_tags
        mid = self._insert_merchant(db_conn)
        add_merchant_tag(mid, "VIP")
        add_merchant_tag(mid, "HighVolume")
        tags = get_merchant_tags(mid)
        assert "VIP" in tags
        assert "HighVolume" in tags

    def test_remove_tag(self, mock_get_db, db_conn):
        from database import add_merchant_tag, remove_merchant_tag, get_merchant_tags
        mid = self._insert_merchant(db_conn)
        add_merchant_tag(mid, "ToRemove")
        assert remove_merchant_tag(mid, "ToRemove") is True
        tags = get_merchant_tags(mid)
        assert "ToRemove" not in tags


class TestIncidents:
    def _insert_merchant(self, db_conn):
        db_conn.execute(
            "INSERT INTO merchants (name, status) VALUES (?, ?)",
            ("IncidentTest", "active")
        )
        db_conn.commit()
        return 1

    def test_create_incident(self, mock_get_db, db_conn):
        from database import create_incident
        mid = self._insert_merchant(db_conn)
        iid = create_incident(mid, "IncidentTest", "conversion_drop", "Conv dropped", priority="P1")
        assert iid is not None

    def test_get_open_incidents(self, mock_get_db, db_conn):
        from database import create_incident, get_open_incidents
        mid = self._insert_merchant(db_conn)
        create_incident(mid, "IncidentTest", "conversion_drop", "Conv dropped")
        incidents = get_open_incidents()
        assert len(incidents) >= 1

    def test_acknowledge_incident(self, mock_get_db, db_conn):
        from database import create_incident, acknowledge_incident, get_incident_by_id
        mid = self._insert_merchant(db_conn)
        iid = create_incident(mid, "IncidentTest", "conversion_drop", "Conv dropped")
        result = acknowledge_incident(iid, 12345)
        assert result is True
        inc = get_incident_by_id(iid)
        assert inc["acknowledged_by"] == 12345

    def test_resolve_incident(self, mock_get_db, db_conn):
        from database import create_incident, resolve_incident, get_incident_by_id
        mid = self._insert_merchant(db_conn)
        iid = create_incident(mid, "IncidentTest", "conversion_drop", "Conv dropped")
        result = resolve_incident(iid, 12345, "Fixed the issue")
        assert result is True
        inc = get_incident_by_id(iid)
        assert inc["status"] == "resolved"


class TestIncidentComments:
    def _create_incident(self, db_conn):
        db_conn.execute(
            "INSERT INTO merchants (name, status) VALUES (?, ?)",
            ("CommentTest", "active")
        )
        db_conn.execute(
            "INSERT INTO incidents (merchant_id, merchant_name, incident_type, title) VALUES (?, ?, ?, ?)",
            (1, "CommentTest", "technical", "Test incident")
        )
        db_conn.commit()
        return 1

    def test_add_and_get_comments(self, mock_get_db, db_conn):
        from database import add_incident_comment, get_incident_comments
        iid = self._create_incident(db_conn)
        add_incident_comment(iid, 123, "User1", "First comment")
        add_incident_comment(iid, 456, "User2", "Second comment")
        comments = get_incident_comments(iid)
        assert len(comments) == 2
        assert comments[0]["text"] == "First comment"


class TestAlerts:
    def test_get_pending_alerts(self, mock_get_db, db_conn):
        from database import get_pending_alerts
        db_conn.execute(
            "INSERT INTO alerts (alert_type, title, notified) VALUES (?, ?, ?)",
            ("test_alert", "Test Alert", 0)
        )
        db_conn.commit()
        alerts = get_pending_alerts()
        assert len(alerts) == 1

    def test_mark_alert_notified(self, mock_get_db, db_conn):
        from database import get_pending_alerts, mark_alert_notified
        db_conn.execute(
            "INSERT INTO alerts (alert_type, title, notified) VALUES (?, ?, ?)",
            ("test_alert", "Test Alert", 0)
        )
        db_conn.commit()
        alerts = get_pending_alerts()
        mark_alert_notified(alerts[0]["id"])
        alerts_after = get_pending_alerts()
        assert len(alerts_after) == 0


class TestConversionHistory:
    def test_save_and_get_conversion(self, mock_get_db, db_conn):
        from database import save_daily_conversion, get_conversion_history
        # Даты от сегодняшнего дня: запрос берёт окно последних N дней, фиксированные даты со временем выпадают из него
        today = datetime.now().date()
        save_daily_conversion("TestM", (today - timedelta(days=2)).isoformat(), 45.5, 100, 45)
        save_daily_conversion("TestM", (today - timedelta(days=1)).isoformat(), 50.0, 120, 60)
        history = get_conversion_history("TestM", days=30)
        assert len(history) == 2

    def test_conversion_trend_stable(self, mock_get_db, db_conn):
        from database import save_daily_conversion, get_conversion_trend
        save_daily_conversion("TrendM", "2026-03-01", 50.0, 100, 50)
        save_daily_conversion("TrendM", "2026-03-02", 50.0, 100, 50)
        trend = get_conversion_trend("TrendM")
        assert trend == "stable"

    def test_conversion_trend_declining(self, mock_get_db, db_conn):
        from database import save_daily_conversion, get_conversion_trend
        save_daily_conversion("DecM", "2026-03-01", 50.0, 100, 50)
        save_daily_conversion("DecM", "2026-03-02", 40.0, 100, 40)
        save_daily_conversion("DecM", "2026-03-03", 30.0, 100, 30)
        trend = get_conversion_trend("DecM")
        assert trend == "declining"


class TestStats:
    def test_get_stats(self, mock_get_db, db_conn):
        from database import get_stats
        db_conn.execute("INSERT INTO merchants (name, status) VALUES (?, ?)", ("S1", "active"))
        db_conn.execute("INSERT INTO merchants (name, status) VALUES (?, ?)", ("S2", "problem"))
        db_conn.commit()
        stats = get_stats()
        assert stats["total_merchants"] == 2
        assert stats["by_status"]["active"] == 1
        assert stats["by_status"]["problem"] == 1


class TestOverdueIncidents:
    def test_get_overdue_incidents(self, mock_get_db, db_conn):
        from database import get_overdue_incidents
        # Insert overdue incident
        past = (datetime.now() - timedelta(hours=2)).isoformat()
        db_conn.execute(
            "INSERT INTO merchants (name, status) VALUES (?, ?)", ("Overdue", "active")
        )
        db_conn.execute(
            "INSERT INTO incidents (merchant_id, merchant_name, incident_type, title, due_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, "Overdue", "technical", "Overdue test", past, "open")
        )
        db_conn.commit()
        overdue = get_overdue_incidents()
        assert len(overdue) >= 1


class TestCleanup:
    def test_cleanup_old_data(self, mock_get_db, db_conn):
        from database import cleanup_old_data
        # Insert old message
        db_conn.execute(
            "INSERT INTO message_log (message_hash, group_id, text, created_at) VALUES (?, ?, ?, ?)",
            ("old_hash", 123, "old message", "2020-01-01 00:00:00")
        )
        db_conn.commit()
        msg_deleted, alert_deleted = cleanup_old_data()
        assert msg_deleted >= 1
