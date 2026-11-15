import "dotenv/config";
import Database from "better-sqlite3";
import path from "path";

const AUTH_DB = path.join(process.cwd(), "auth.sqlite");

const db = new Database(AUTH_DB);
db.exec(`
  CREATE TABLE IF NOT EXISTS access_keys (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
  );

  CREATE TABLE IF NOT EXISTS user_sessions (
    tg_id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    authorized_at TEXT NOT NULL
  );
`);

db.close();
console.log("auth.sqlite initialized");

