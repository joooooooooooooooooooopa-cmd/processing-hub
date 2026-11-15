#!/usr/bin/env python3
"""
Migrate merchants.db (SQLite) data → Railway PostgreSQL.

Usage:
    DATABASE_URL=postgresql://... python migrate_sqlite_to_pg.py [path/to/merchants.db]

Run once to seed PostgreSQL with existing CRM data.
"""
import sys
import os
import sqlite3

def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "merchants.db"
    database_url = os.environ.get("DATABASE_URL", "")

    if not database_url:
        print("ERROR: DATABASE_URL env var not set")
        sys.exit(1)

    if not os.path.exists(db_path):
        print(f"ERROR: SQLite file not found: {db_path}")
        sys.exit(1)

    import psycopg2

    print(f"Source: {db_path}")
    print(f"Target: PostgreSQL ({database_url[:40]}...)")
    print()

    src = sqlite3.connect(db_path)
    src.row_factory = sqlite3.Row
    dst = psycopg2.connect(database_url)
    dst.autocommit = False

    tables = [
        "merchants",
        "incidents",
        "incident_comments",
        "status_changes",
        "status_history",
        "message_log",
        "groups",
        "payment_methods",
        "access_keys",
        "alerts",
        "metrics_daily",
        "status_alerts",
        "messages",
        "traffic_requests",
        "merchant_tags",
        "alert_history",
        "conversion_history",
    ]

    # First: make sure schema exists in PostgreSQL
    print("Initialising PostgreSQL schema via database.py...")
    os.environ["DATABASE_URL"] = database_url
    # Force USE_POSTGRES
    import config
    config.DATABASE_URL = database_url
    config.USE_POSTGRES  = True

    import database as db_module
    db_module.init_db()
    print("  Schema OK")
    print()

    src_cur = src.cursor()
    dst_cur = dst.cursor()

    total = 0
    for table in tables:
        # Check if table exists in SQLite
        src_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not src_cur.fetchone():
            continue

        src_cur.execute(f"SELECT * FROM {table}")
        rows = src_cur.fetchall()
        if not rows:
            print(f"  {table}: 0 rows (skip)")
            continue

        cols = [d[0] for d in src_cur.description]
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)

        # Build ON CONFLICT clause per table
        if table == "merchants":
            conflict = "ON CONFLICT (name) DO UPDATE SET " + ", ".join(
                f"{c} = EXCLUDED.{c}" for c in cols if c not in ("id", "name")
            )
        elif table == "groups":
            conflict = "ON CONFLICT (id) DO UPDATE SET " + ", ".join(
                f"{c} = EXCLUDED.{c}" for c in cols if c != "id"
            )
        elif table == "message_log":
            conflict = "ON CONFLICT (message_hash) DO NOTHING"
        elif table == "merchant_tags":
            conflict = "ON CONFLICT (merchant_id, tag) DO NOTHING"
        elif table == "incidents":
            conflict = "ON CONFLICT DO NOTHING"
        else:
            conflict = "ON CONFLICT DO NOTHING"

        insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) {conflict}"

        count = 0
        for row in rows:
            try:
                dst_cur.execute(insert_sql, list(row))
                count += 1
            except Exception as e:
                print(f"  WARNING {table} row skip: {e}")

        dst.commit()
        print(f"  {table}: {count}/{len(rows)} rows migrated")
        total += count

    # Fix sequences after explicit id inserts
    print()
    print("Fixing PostgreSQL sequences...")
    for table in ["merchants", "incidents", "incident_comments", "status_changes",
                  "message_log", "payment_methods", "access_keys", "alerts",
                  "metrics_daily", "status_alerts", "messages", "traffic_requests",
                  "merchant_tags", "alert_history", "conversion_history"]:
        try:
            dst_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")
            dst.commit()
        except Exception:
            dst.rollback()

    print()
    print(f"Done. Total rows migrated: {total}")
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
