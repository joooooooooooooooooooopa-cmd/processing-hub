"""
PostgreSQL compatibility adapter for database.py.

Makes psycopg2 behave like sqlite3 so database.py works unchanged:
  - Replaces ? placeholders with %s
  - Silently skips PRAGMA statements
  - Converts INSERT OR IGNORE  → INSERT ... ON CONFLICT DO NOTHING
  - Converts INSERT OR REPLACE → INSERT ... ON CONFLICT ... DO UPDATE SET ...
  - Converts INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
  - Provides cursor.lastrowid via RETURNING id
"""
import re
from typing import Any, List, Optional, Tuple

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def _adapt_sql(sql: str) -> Tuple[str, bool, bool]:
    """
    Transform SQLite SQL to PostgreSQL SQL.
    Returns (adapted_sql, is_insert, has_returning).
    Returns ('', False, False) for statements to skip (PRAGMA).
    """
    if re.match(r'^\s*PRAGMA\b', sql, re.IGNORECASE):
        return '', False, False

    # INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
    sql = re.sub(
        r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b',
        'SERIAL PRIMARY KEY',
        sql, flags=re.IGNORECASE
    )
    # INTEGER PRIMARY KEY (no AUTOINCREMENT, e.g. explicit Telegram IDs) → BIGINT PRIMARY KEY
    sql = re.sub(
        r'\bINTEGER\s+PRIMARY\s+KEY\b(?!\s+AUTOINCREMENT)',
        'BIGINT PRIMARY KEY',
        sql, flags=re.IGNORECASE
    )

    # CREATE TABLE: strip FOREIGN KEY constraints (PostgreSQL requires referenced
    # tables to already exist; SQLite ignores this. Since we rely on app-level
    # integrity, FK declarations are not needed.)
    # Also change plain INTEGER columns to BIGINT (Telegram IDs can exceed 32-bit).
    # Note: AUTOINCREMENT columns already became SERIAL; PRIMARY KEY columns became BIGINT above.
    if re.match(r'\s*CREATE\s+TABLE', sql, re.IGNORECASE):
        # Replace remaining standalone INTEGER types with BIGINT
        sql = re.sub(r'\bINTEGER\b', 'BIGINT', sql)
        lines = sql.split('\n')
        lines = [l for l in lines if not re.match(r'\s*FOREIGN\s+KEY\b', l, re.IGNORECASE)]
        # Fix trailing comma on the last column/constraint line before closing ')'.
        # Done line-by-line to avoid accidentally matching commas inside UNIQUE(a, b).
        i = len(lines) - 1
        while i >= 0 and not lines[i].strip():
            i -= 1
        if i >= 0 and lines[i].strip() == ')':
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j >= 0 and lines[j].rstrip().endswith(','):
                lines[j] = lines[j].rstrip()[:-1]
        sql = '\n'.join(lines)

    # Detect INSERT variant BEFORE replacing ?→%s (doesn't matter but cleaner)
    is_insert_ignore  = bool(re.search(r'\bINSERT\s+OR\s+IGNORE\b',  sql, re.IGNORECASE))
    is_insert_replace = bool(re.search(r'\bINSERT\s+OR\s+REPLACE\b', sql, re.IGNORECASE))
    is_insert         = bool(re.match(r'\s*INSERT\b', sql, re.IGNORECASE))

    # Replace ? with %s (SQLite → psycopg2 placeholder style)
    sql = sql.replace('?', '%s')

    if is_insert_ignore:
        sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\b', 'INSERT', sql, flags=re.IGNORECASE)
        sql = sql.rstrip().rstrip(';')
        sql += ' ON CONFLICT DO NOTHING'
        return sql, True, False

    if is_insert_replace:
        sql = re.sub(r'\bINSERT\s+OR\s+REPLACE\b', 'INSERT', sql, flags=re.IGNORECASE)
        sql = sql.rstrip().rstrip(';')
        # Parse column list to build ON CONFLICT ... DO UPDATE SET
        m = re.match(r'\s*INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)', sql, re.IGNORECASE)
        if m:
            cols = [c.strip() for c in m.group(2).split(',')]
            conflict_col = 'id' if 'id' in cols else cols[0]
            update_cols  = [c for c in cols if c != conflict_col]
            if update_cols:
                set_clause = ', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)
                sql += f' ON CONFLICT ({conflict_col}) DO UPDATE SET {set_clause}'
            else:
                sql += ' ON CONFLICT DO NOTHING'
            returning_col = 'id' if 'id' in cols else conflict_col
        else:
            sql += ' ON CONFLICT DO NOTHING'
            returning_col = 'id'
        sql += f' RETURNING {returning_col}'
        return sql, True, True

    if is_insert:
        sql = sql.rstrip().rstrip(';')
        if 'RETURNING' not in sql.upper():
            # Only add RETURNING id for tables that have an 'id' column
            # Skip for ON CONFLICT queries on tables without 'id' (e.g. scanner_state)
            if 'ON CONFLICT' in sql.upper():
                m = re.match(r'\s*INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)', sql, re.IGNORECASE)
                if m:
                    cols = [c.strip() for c in m.group(2).split(',')]
                    if 'id' in cols:
                        sql += ' RETURNING id'
                else:
                    sql += ' RETURNING id'
            else:
                sql += ' RETURNING id'
        return sql, True, True

    return sql, False, False


class PgCursor:
    """Wraps psycopg2 cursor to behave like sqlite3.Cursor."""

    def __init__(self, pg_cursor):
        self._cur = pg_cursor
        self.lastrowid: Optional[int] = None
        self.rowcount: int = 0

    @property
    def description(self):
        return self._cur.description

    def execute(self, sql: str, params=None):
        adapted, is_insert, has_returning = _adapt_sql(sql)
        if not adapted:
            self.lastrowid = None
            return self

        is_ddl = bool(re.match(r'\s*(CREATE|DROP|ALTER)\b', adapted, re.IGNORECASE))

        if is_ddl:
            # Wrap DDL in a SAVEPOINT so a failure (e.g. wrong column in IF NOT EXISTS
            # schema) doesn't abort the whole transaction. Log and continue on error.
            sp = f'dbpg_sp_{abs(hash(adapted[:40]))}'
            try:
                self._cur.execute(f'SAVEPOINT {sp}')
            except Exception:
                pass
            try:
                self._cur.execute(adapted)
                self._cur.execute(f'RELEASE SAVEPOINT {sp}')
            except Exception as e:
                try:
                    self._cur.execute(f'ROLLBACK TO SAVEPOINT {sp}')
                    self._cur.execute(f'RELEASE SAVEPOINT {sp}')
                except Exception:
                    pass
                import sys
                print(f'[db_pg] DDL warning (skipped): {e}', file=sys.stderr)
            self.rowcount = 0
            self.lastrowid = None
            return self

        if params is not None:
            self._cur.execute(adapted, params)
        else:
            self._cur.execute(adapted)

        self.rowcount = self._cur.rowcount

        if is_insert and has_returning:
            try:
                row = self._cur.fetchone()
                self.lastrowid = row[0] if row else None
            except Exception:
                self.lastrowid = None
        else:
            self.lastrowid = None

        return self

    def executemany(self, sql: str, params_list):
        adapted, is_insert, has_returning = _adapt_sql(sql)
        if not adapted:
            return
        if has_returning:
            for p in params_list:
                self._cur.execute(adapted, p)
        else:
            self._cur.executemany(adapted, params_list)
        self.rowcount = self._cur.rowcount

    def fetchall(self) -> List:
        try:
            return self._cur.fetchall()
        except Exception:
            return []

    def fetchone(self) -> Optional[Any]:
        try:
            return self._cur.fetchone()
        except Exception:
            return None

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class PgConnection:
    """Wraps psycopg2 connection to behave like sqlite3.Connection."""

    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = False

    def cursor(self) -> PgCursor:
        return PgCursor(self._conn.cursor())

    def execute(self, sql: str, params=None) -> PgCursor:
        """Support connection.execute() pattern used by sqlite3."""
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_pg_connection(database_url: str) -> PgConnection:
    if not HAS_PSYCOPG2:
        raise ImportError("psycopg2 not installed. Run: pip install psycopg2-binary")
    return PgConnection(database_url)
