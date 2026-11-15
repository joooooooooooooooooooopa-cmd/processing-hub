"""
Модуль хранения данных с поддержкой PostgreSQL (Railway) и SQLite (локально)

Автоматически определяет тип БД:
- Если DATABASE_URL задан → PostgreSQL
- Иначе → SQLite/JSON файлы
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import hmac as _hmac
from config import DATABASE_URL, USE_POSTGRES, KEYS_FILE, hash_key

logger = logging.getLogger(__name__)

# PostgreSQL адаптер (опционально)
if USE_POSTGRES:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        logger.info("PostgreSQL mode: psycopg2 loaded")
    except ImportError:
        logger.error("psycopg2 не установлен! Выполните: pip install psycopg2-binary")
        USE_POSTGRES = False


class PostgresStorage:
    """Хранилище на PostgreSQL для Railway"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._init_tables()

    @contextmanager
    def _get_conn(self):
        """Получить соединение с БД"""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_tables(self):
        """Создать таблицы если не существуют"""
        with self._get_conn() as conn:
            cur = conn.cursor()

            # Таблица ключей доступа
            cur.execute("""
                CREATE TABLE IF NOT EXISTS access_keys (
                    key VARCHAR(50) PRIMARY KEY,
                    name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by BIGINT,
                    active BOOLEAN DEFAULT TRUE,
                    used_by BIGINT,
                    used_at TIMESTAMP
                )
            """)

            # Таблица отправленных алертов
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sent_alerts (
                    id SERIAL PRIMARY KEY,
                    alert_key VARCHAR(255) UNIQUE,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Аудит лог
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    action VARCHAR(50) NOT NULL,
                    details TEXT,
                    ip VARCHAR(45),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Индексы
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_keys_used_by ON access_keys(used_by)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sent_alerts_key ON sent_alerts(alert_key)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC)
            """)

            # Расширить key колонку для SHA-256 хешей (64 символа)
            try:
                cur.execute("ALTER TABLE access_keys ALTER COLUMN key TYPE TEXT")
            except Exception:
                pass

            logger.info("PostgreSQL: таблицы инициализированы")

    # ============ КЛЮЧИ ДОСТУПА ============

    def generate_key(self, name: str = "", created_by: int = 0) -> str:
        """Создать новый ключ"""
        import secrets
        import string

        chars = string.ascii_uppercase + string.digits
        parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
        key = f"PC-{'-'.join(parts)}"

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO access_keys (key, name, created_by)
                VALUES (%s, %s, %s)
            """, (key, name, created_by))

        return key

    def validate_key(self, key: str, user_id: int) -> bool:
        """Проверить и активировать ключ"""
        from config import ACCESS_KEY

        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Проверяем, авторизован ли уже
            cur.execute("SELECT key FROM access_keys WHERE used_by = %s AND active = TRUE", (user_id,))
            if cur.fetchone():
                return True

            # Мастер-ключ — timing-safe сравнение через HMAC-хеш
            if _hmac.compare_digest(hash_key(key), hash_key(ACCESS_KEY)):
                hashed_master = hash_key(f"master_{user_id}")
                cur.execute("""
                    INSERT INTO access_keys (key, name, created_at, active, used_by, used_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (key) DO NOTHING
                """, (hashed_master, f"Master Key User {user_id}", datetime.now(), True, user_id, datetime.now()))
                return True

            # Проверяем ключ (сначала как plain, потом как хеш)
            hashed = hash_key(key)
            cur.execute("""
                SELECT key, active, used_by FROM access_keys WHERE key = %s OR key = %s
            """, (key, hashed))
            row = cur.fetchone()

            if not row:
                return False
            if not row['active']:
                return False
            if row['used_by'] is not None:
                return False

            # Активируем
            cur.execute("""
                UPDATE access_keys
                SET used_by = %s, used_at = %s
                WHERE key = %s
            """, (user_id, datetime.now(), row['key']))

            return True

    def is_user_authorized(self, user_id: int) -> bool:
        """Проверить авторизацию пользователя"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM access_keys WHERE used_by = %s AND active = TRUE", (user_id,))
            return cur.fetchone() is not None

    def get_all_keys(self) -> List[Dict]:
        """Получить все ключи"""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT key, name, created_at, active, used_by, used_at
                FROM access_keys ORDER BY created_at DESC
            """)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def revoke_key(self, key: str) -> bool:
        """Отозвать ключ"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE access_keys SET active = FALSE WHERE key = %s", (key,))
            return cur.rowcount > 0

    def revoke_user(self, user_id: int) -> bool:
        """Отозвать доступ пользователя"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE access_keys SET active = FALSE, used_by = NULL
                WHERE used_by = %s
            """, (user_id,))
            return cur.rowcount > 0

    def get_authorized_users(self) -> List[Dict]:
        """Получить авторизованных пользователей"""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT used_by as user_id, key, name, used_at
                FROM access_keys
                WHERE used_by IS NOT NULL AND active = TRUE
            """)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> Dict:
        """Статистика по ключам"""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT
                    COUNT(*) as total_keys,
                    COUNT(*) FILTER (WHERE active = TRUE) as active_keys,
                    COUNT(*) FILTER (WHERE used_by IS NOT NULL) as used_keys,
                    COUNT(DISTINCT used_by) FILTER (WHERE used_by IS NOT NULL) as authorized_users
                FROM access_keys
            """)
            return dict(cur.fetchone())

    # ============ АЛЕРТЫ ============

    def load_sent_alerts(self) -> set:
        """Загрузить отправленные алерты за сегодня"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT alert_key FROM sent_alerts
                WHERE alert_key LIKE %s
            """, (f'%_{today}',))
            return {row[0] for row in cur.fetchall()}

    def save_sent_alert(self, alert_key: str):
        """Сохранить отправленный алерт"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sent_alerts (alert_key) VALUES (%s)
                ON CONFLICT (alert_key) DO NOTHING
            """, (alert_key,))

    def save_sent_alerts(self, alerts: set):
        """Сохранить несколько алертов"""
        for alert_key in alerts:
            self.save_sent_alert(alert_key)

    def cleanup_old_alerts(self, days: int = 7):
        """Удалить старые алерты"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM sent_alerts
                WHERE sent_at < %s
            """, (datetime.now() - timedelta(days=days),))
            logger.info(f"Удалено {cur.rowcount} старых алертов")

    # ============ АУДИТ ЛОГ ============

    def log_audit(self, user_id: int, action: str, details: str = None, ip: str = None):
        """Записать событие в аудит лог"""
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO audit_log (user_id, action, details, ip) VALUES (%s, %s, %s, %s)",
                    (user_id, action, details, ip)
                )
        except Exception as e:
            logger.error(f"[Audit] {e}")

    def get_audit_log(self, limit: int = 20) -> List[Dict]:
        """Получить последние записи аудит лога"""
        with self._get_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT user_id, action, details, ip, created_at FROM audit_log ORDER BY created_at DESC LIMIT %s",
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]


class FileStorage:
    """Хранилище на JSON файлах (для локальной разработки)"""

    def __init__(self, keys_file: str = "access_keys.json", alerts_file: str = "sent_alerts.json"):
        self.keys_file = keys_file
        self.alerts_file = alerts_file

    def _load_keys_data(self) -> Dict:
        if not os.path.exists(self.keys_file):
            return {"keys": {}, "used_by": {}}
        try:
            with open(self.keys_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"keys": {}, "used_by": {}}

    def _save_keys_data(self, data: Dict):
        with open(self.keys_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ============ КЛЮЧИ ДОСТУПА ============

    def generate_key(self, name: str = "", created_by: int = 0) -> str:
        import secrets
        import string

        chars = string.ascii_uppercase + string.digits
        parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
        key = f"PC-{'-'.join(parts)}"

        data = self._load_keys_data()
        data["keys"][key] = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "created_by": created_by,
            "active": True,
            "used_by": None,
            "used_at": None,
        }
        self._save_keys_data(data)
        return key

    def validate_key(self, key: str, user_id: int) -> bool:
        from config import ACCESS_KEY

        data = self._load_keys_data()

        if str(user_id) in data.get("used_by", {}):
            return True

        # Мастер-ключ — timing-safe сравнение через HMAC-хеш
        if _hmac.compare_digest(hash_key(key), hash_key(ACCESS_KEY)):
            master_key = hash_key(f"master_{user_id}")
            data["keys"][master_key] = {
                "name": f"Master Key User {user_id}",
                "created_at": datetime.now().isoformat(),
                "active": True,
                "used_by": user_id,
                "used_at": datetime.now().isoformat(),
            }
            data["used_by"][str(user_id)] = master_key
            self._save_keys_data(data)
            return True

        # Проверяем ключ (plain и хеш)
        hashed = hash_key(key)
        found_key = None
        if key in data["keys"]:
            found_key = key
        elif hashed in data["keys"]:
            found_key = hashed

        if not found_key:
            return False

        key_info = data["keys"][found_key]

        if not key_info.get("active", False):
            return False
        if key_info.get("used_by") is not None:
            return False

        key_info["used_by"] = user_id
        key_info["used_at"] = datetime.now().isoformat()
        data["used_by"][str(user_id)] = found_key

        self._save_keys_data(data)
        return True

    def is_user_authorized(self, user_id: int) -> bool:
        data = self._load_keys_data()
        return str(user_id) in data.get("used_by", {})

    def get_all_keys(self) -> List[Dict]:
        data = self._load_keys_data()
        result = []
        for key, info in data["keys"].items():
            result.append({
                "key": key,
                "name": info.get("name", ""),
                "created_at": info.get("created_at", ""),
                "active": info.get("active", False),
                "used_by": info.get("used_by"),
                "used_at": info.get("used_at"),
            })
        return result

    def revoke_key(self, key: str) -> bool:
        data = self._load_keys_data()
        if key not in data["keys"]:
            return False

        data["keys"][key]["active"] = False
        used_by = data["keys"][key].get("used_by")
        if used_by and str(used_by) in data.get("used_by", {}):
            del data["used_by"][str(used_by)]

        self._save_keys_data(data)
        return True

    def revoke_user(self, user_id: int) -> bool:
        data = self._load_keys_data()
        user_key = str(user_id)
        if user_key not in data.get("used_by", {}):
            return False

        key = data["used_by"][user_key]
        if key in data["keys"]:
            data["keys"][key]["active"] = False

        del data["used_by"][user_key]
        self._save_keys_data(data)
        return True

    def get_authorized_users(self) -> List[Dict]:
        data = self._load_keys_data()
        result = []
        for user_id, key in data.get("used_by", {}).items():
            key_info = data["keys"].get(key, {})
            result.append({
                "user_id": int(user_id),
                "key": key,
                "name": key_info.get("name", ""),
                "used_at": key_info.get("used_at", ""),
            })
        return result

    def get_stats(self) -> Dict:
        data = self._load_keys_data()
        total = len(data["keys"])
        active = sum(1 for k in data["keys"].values() if k.get("active", False))
        used = sum(1 for k in data["keys"].values() if k.get("used_by") is not None)
        users = len(data.get("used_by", {}))

        return {
            "total_keys": total,
            "active_keys": active,
            "used_keys": used,
            "authorized_users": users,
        }

    # ============ АЛЕРТЫ ============

    def load_sent_alerts(self) -> set:
        if not os.path.exists(self.alerts_file):
            return set()
        try:
            with open(self.alerts_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                today = datetime.now().strftime('%Y-%m-%d')
                return {k for k in data.get("alerts", []) if today in k}
        except Exception:
            return set()

    def save_sent_alerts(self, alerts: set):
        try:
            with open(self.alerts_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "alerts": list(alerts),
                    "updated": datetime.now().isoformat()
                }, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения алертов: {e}")

    def cleanup_old_alerts(self, days: int = 7):
        """Для совместимости, JSON автоматически чистится при загрузке"""
        pass

    # ============ АУДИТ ЛОГ ============

    def log_audit(self, user_id: int, action: str, details: str = None, ip: str = None):
        """Записать событие в аудит лог (JSON-файл)"""
        try:
            audit_file = "audit_log.json"
            entries = []
            if os.path.exists(audit_file):
                with open(audit_file, 'r') as f:
                    entries = json.load(f)
            entries.append({
                "user_id": user_id, "action": action, "details": details,
                "ip": ip, "created_at": datetime.now().isoformat()
            })
            # Keep last 500 entries
            entries = entries[-500:]
            with open(audit_file, 'w') as f:
                json.dump(entries, f, indent=2)
        except Exception as e:
            logger.error(f"[Audit] {e}")

    def get_audit_log(self, limit: int = 20) -> List[Dict]:
        """Получить последние записи"""
        try:
            audit_file = "audit_log.json"
            if not os.path.exists(audit_file):
                return []
            with open(audit_file, 'r') as f:
                entries = json.load(f)
            return list(reversed(entries[-limit:]))
        except Exception:
            return []


# ============ ГЛОБАЛЬНЫЙ ИНСТАНС ============

_storage = None


def get_storage():
    """Получить хранилище (синглтон)"""
    global _storage
    if _storage is None:
        if USE_POSTGRES and DATABASE_URL:
            logger.info("Используется PostgreSQL хранилище")
            _storage = PostgresStorage(DATABASE_URL)
        else:
            logger.info("Используется файловое хранилище (JSON)")
            _storage = FileStorage(KEYS_FILE)
    return _storage


# ============ УДОБНЫЕ ФУНКЦИИ ============

def generate_key(name: str = "", created_by: int = 0) -> str:
    return get_storage().generate_key(name, created_by)

def validate_key(key: str, user_id: int) -> bool:
    return get_storage().validate_key(key, user_id)

def is_user_authorized(user_id: int) -> bool:
    return get_storage().is_user_authorized(user_id)

def get_all_keys() -> List[Dict]:
    return get_storage().get_all_keys()

def revoke_key(key: str) -> bool:
    return get_storage().revoke_key(key)

def revoke_user(user_id: int) -> bool:
    return get_storage().revoke_user(user_id)

def get_authorized_users() -> List[Dict]:
    return get_storage().get_authorized_users()

def get_stats() -> Dict:
    return get_storage().get_stats()

def load_sent_alerts() -> set:
    return get_storage().load_sent_alerts()

def save_sent_alerts(alerts: set):
    return get_storage().save_sent_alerts(alerts)

def log_audit(user_id: int, action: str, details: str = None, ip: str = None):
    return get_storage().log_audit(user_id, action, details, ip)

def get_audit_log(limit: int = 20) -> List[Dict]:
    return get_storage().get_audit_log(limit)
