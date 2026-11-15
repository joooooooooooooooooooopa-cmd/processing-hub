import "dotenv/config";
import pg from "pg";
import Database from "better-sqlite3";

// Use public URL for local access
const PG_URL = process.env.DATABASE_PUBLIC_URL || process.env.DATABASE_URL;
if (!PG_URL) {
  console.error("Set DATABASE_PUBLIC_URL or DATABASE_URL in .env");
  process.exit(1);
}

const pool = new pg.Pool({ connectionString: PG_URL });

async function migrate() {
  console.log("🚀 Creating tables...");
  await pool.query(`
    CREATE TABLE IF NOT EXISTS access_keys (
      key TEXT PRIMARY KEY,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      created_by BIGINT,
      revoked INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS user_sessions (
      tg_id BIGINT PRIMARY KEY,
      key TEXT,
      authorized_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS chunks (
      id SERIAL PRIMARY KEY,
      source TEXT,
      content TEXT,
      embedding_json TEXT
    );
    CREATE TABLE IF NOT EXISTS knowledge (
      id SERIAL PRIMARY KEY,
      question TEXT NOT NULL,
      answer TEXT NOT NULL,
      added_by BIGINT NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS doc_updates (
      url TEXT PRIMARY KEY,
      title TEXT,
      content TEXT,
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
  `);
  console.log("✅ Tables created");

  // Migrate RAG chunks
  const ragDb = new Database("rag.sqlite", { readonly: true });
  const chunks = ragDb.prepare("SELECT source, content, embedding_json FROM chunks").all();
  console.log(`📦 Migrating ${chunks.length} chunks...`);
  for (const c of chunks) {
    await pool.query(
      "INSERT INTO chunks (source, content, embedding_json) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
      [c.source, c.content, c.embedding_json]
    );
  }

  // Migrate knowledge
  try {
    const knowledge = ragDb.prepare("SELECT question, answer, added_by, created_at FROM knowledge").all();
    console.log(`📦 Migrating ${knowledge.length} knowledge entries...`);
    for (const k of knowledge) {
      await pool.query(
        "INSERT INTO knowledge (question, answer, added_by, created_at) VALUES ($1, $2, $3, $4)",
        [k.question, k.answer, k.added_by, k.created_at]
      );
    }
  } catch (e) {
    console.log("No knowledge table in SQLite, skipping");
  }

  // Migrate doc_updates
  try {
    const docs = ragDb.prepare("SELECT url, title, content, updated_at FROM doc_updates").all();
    console.log(`📦 Migrating ${docs.length} doc updates...`);
    for (const d of docs) {
      await pool.query(
        "INSERT INTO doc_updates (url, title, content, updated_at) VALUES ($1, $2, $3, $4) ON CONFLICT(url) DO NOTHING",
        [d.url, d.title, d.content, d.updated_at]
      );
    }
  } catch (e) {
    console.log("No doc_updates table, skipping");
  }
  ragDb.close();

  // Migrate auth
  const authDb = new Database("auth.sqlite", { readonly: true });
  try {
    const keys = authDb.prepare("SELECT key, created_at, created_by, revoked FROM access_keys").all();
    console.log(`📦 Migrating ${keys.length} access keys...`);
    for (const k of keys) {
      await pool.query(
        "INSERT INTO access_keys (key, created_at, created_by, revoked) VALUES ($1, $2, $3, $4) ON CONFLICT(key) DO NOTHING",
        [k.key, k.created_at, k.created_by, k.revoked]
      );
    }
  } catch (e) {
    console.log("No access_keys table, skipping");
  }

  try {
    const sessions = authDb.prepare("SELECT tg_id, key, authorized_at FROM user_sessions").all();
    console.log(`📦 Migrating ${sessions.length} sessions...`);
    for (const s of sessions) {
      await pool.query(
        "INSERT INTO user_sessions (tg_id, key, authorized_at) VALUES ($1, $2, $3) ON CONFLICT(tg_id) DO NOTHING",
        [s.tg_id, s.key, s.authorized_at]
      );
    }
  } catch (e) {
    console.log("No user_sessions table, skipping");
  }
  authDb.close();

  console.log("✅ Migration complete!");
  await pool.end();
}

migrate().catch(err => {
  console.error("❌ Migration failed:", err);
  process.exit(1);
});
