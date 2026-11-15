"""Unit tests for storage.py - FileStorage only (no PostgreSQL dependency)"""
import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


class TestFileStorageKeys:
    @pytest.fixture(autouse=True)
    def setup_storage(self, tmp_path):
        self.keys_file = str(tmp_path / "keys.json")
        self.alerts_file = str(tmp_path / "alerts.json")
        # Patch config imports to avoid real env vars
        with patch.dict(os.environ, {"DATABASE_URL": "", "ACCESS_KEY": "test-master-key"}):
            with patch("storage.USE_POSTGRES", False):
                from storage import FileStorage
                self.storage = FileStorage(self.keys_file, self.alerts_file)
                yield

    def test_generate_key_format(self):
        key = self.storage.generate_key("TestKey", 123)
        assert key.startswith("PC-")
        parts = key.split("-")
        assert len(parts) == 4  # PC + 3 parts
        assert all(len(p) == 4 for p in parts[1:])

    def test_generate_key_saves_to_file(self):
        key = self.storage.generate_key("Saved", 1)
        with open(self.keys_file) as f:
            data = json.load(f)
        assert key in data["keys"]
        assert data["keys"][key]["name"] == "Saved"

    def test_validate_key_activates(self):
        key = self.storage.generate_key("Activate", 1)
        result = self.storage.validate_key(key, user_id=42)
        assert result is True
        assert self.storage.is_user_authorized(42)

    def test_validate_key_rejects_used(self):
        key = self.storage.generate_key("Used", 1)
        self.storage.validate_key(key, user_id=10)
        result = self.storage.validate_key(key, user_id=20)
        assert result is False

    def test_validate_key_rejects_unknown(self):
        result = self.storage.validate_key("UNKNOWN-KEY", user_id=1)
        assert result is False

    def test_already_authorized_returns_true(self):
        key = self.storage.generate_key("Auth", 1)
        self.storage.validate_key(key, user_id=99)
        # Second call for same user should return True
        result = self.storage.validate_key("any-key", user_id=99)
        assert result is True

    def test_get_all_keys(self):
        self.storage.generate_key("K1", 1)
        self.storage.generate_key("K2", 2)
        keys = self.storage.get_all_keys()
        assert len(keys) == 2

    def test_revoke_key(self):
        key = self.storage.generate_key("Revoke", 1)
        self.storage.validate_key(key, user_id=50)
        assert self.storage.revoke_key(key) is True
        assert self.storage.is_user_authorized(50) is False

    def test_revoke_user(self):
        key = self.storage.generate_key("RevokeU", 1)
        self.storage.validate_key(key, user_id=60)
        assert self.storage.revoke_user(60) is True
        assert self.storage.is_user_authorized(60) is False

    def test_get_authorized_users(self):
        key = self.storage.generate_key("Auth", 1)
        self.storage.validate_key(key, user_id=70)
        users = self.storage.get_authorized_users()
        assert len(users) == 1
        assert users[0]["user_id"] == 70

    def test_get_stats(self):
        self.storage.generate_key("S1", 1)
        key2 = self.storage.generate_key("S2", 2)
        self.storage.validate_key(key2, user_id=80)
        stats = self.storage.get_stats()
        assert stats["total_keys"] == 2
        assert stats["active_keys"] == 2
        assert stats["used_keys"] == 1
        assert stats["authorized_users"] == 1


class TestFileStorageAlerts:
    @pytest.fixture(autouse=True)
    def setup_storage(self, tmp_path):
        self.keys_file = str(tmp_path / "keys.json")
        self.alerts_file = str(tmp_path / "alerts.json")
        with patch.dict(os.environ, {"DATABASE_URL": "", "ACCESS_KEY": "test"}):
            with patch("storage.USE_POSTGRES", False):
                from storage import FileStorage
                self.storage = FileStorage(self.keys_file, self.alerts_file)
                yield

    def test_load_empty_alerts(self):
        alerts = self.storage.load_sent_alerts()
        assert alerts == set()

    def test_save_and_load_alerts(self):
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        alerts = {f"test_alert_{today}", f"another_{today}"}
        self.storage.save_sent_alerts(alerts)
        loaded = self.storage.load_sent_alerts()
        assert loaded == alerts

    def test_old_alerts_filtered(self):
        alerts = {"test_alert_2020-01-01", "test_alert_2020-01-02"}
        self.storage.save_sent_alerts(alerts)
        loaded = self.storage.load_sent_alerts()
        assert len(loaded) == 0  # Old dates filtered out


class TestFileStorageAudit:
    @pytest.fixture(autouse=True)
    def setup_storage(self, tmp_path):
        self.keys_file = str(tmp_path / "keys.json")
        self.alerts_file = str(tmp_path / "alerts.json")
        self.orig_dir = os.getcwd()
        os.chdir(tmp_path)
        with patch.dict(os.environ, {"DATABASE_URL": "", "ACCESS_KEY": "test"}):
            with patch("storage.USE_POSTGRES", False):
                from storage import FileStorage
                self.storage = FileStorage(self.keys_file, self.alerts_file)
                yield
        os.chdir(self.orig_dir)

    def test_log_and_get_audit(self):
        self.storage.log_audit(123, "login", "test login")
        self.storage.log_audit(456, "key_generate", "gen key")
        log = self.storage.get_audit_log(limit=10)
        assert len(log) == 2

    def test_audit_empty(self):
        log = self.storage.get_audit_log()
        assert log == []
