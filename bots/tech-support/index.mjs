import "dotenv/config";
import path from "path";
import crypto from "crypto";
import pg from "pg";
import Database from "better-sqlite3";
import { Telegraf, Markup } from "telegraf";
import OpenAI from "openai";
import Fuse from "fuse.js";
import cron from "node-cron";
import * as cheerio from "cheerio";

const bot = new Telegraf(process.env.TELEGRAM_BOT_TOKEN);
const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// Postgres (production) or SQLite (local fallback)
const USE_PG = !!process.env.DATABASE_URL;
let pool;
if (USE_PG) {
  pool = new pg.Pool({ connectionString: process.env.DATABASE_URL, ssl: false });
}

const DB_PATH = path.join(process.cwd(), "rag.sqlite");
const AUTH_DB = path.join(process.cwd(), "auth.sqlite");
const EMBEDDING_MODEL = "text-embedding-3-small";
const CHAT_MODEL = "gpt-4o-mini";
const VISION_MODEL = "gpt-4o";

const ADMIN_TG_IDS = (process.env.ADMIN_TG_ID || "").split(",").map(id => Number(id.trim())).filter(Boolean);
// Без секрета хэши PIN-кодов предсказуемы, поэтому не стартуем с дефолтом
const PASSWORD_SECRET = process.env.PASSWORD_SECRET;
if (!PASSWORD_SECRET) {
  throw new Error("PASSWORD_SECRET is not set");
}

function hashPassword(pin) {
  return crypto.createHmac("sha256", PASSWORD_SECRET).update(String(pin)).digest("hex");
}

// Banks cache: загружается из API при старте
let banksCache = []; // [{id, name, code, icon, currency}, ...]
let banksByCurrency = {}; // { rub: [...], azn: [...], ... }

async function loadBanks() {
  try {
    const res = await fetch("https://api.example.com/api/banks");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    banksCache = await res.json();
    banksByCurrency = {};
    for (const bank of banksCache) {
      const cur = (bank.currency || "").toLowerCase();
      if (!banksByCurrency[cur]) banksByCurrency[cur] = [];
      banksByCurrency[cur].push(bank);
    }
    console.log(`🏦 Загружено ${banksCache.length} банков (${Object.keys(banksByCurrency).join(", ")})`);
  } catch (err) {
    console.error("[Banks Load Error]", err);
  }
}

function findBankByName(name) {
  if (!name) return null;
  const lower = name.toLowerCase();
  return banksCache.find(b =>
    b.name.toLowerCase() === lower ||
    (b.code && b.code.toLowerCase() === lower) ||
    b.name.toLowerCase().includes(lower) ||
    lower.includes(b.name.toLowerCase())
  );
}

function getBanksForCurrency(currency) {
  return banksByCurrency[(currency || "").toLowerCase()] || [];
}

// Context storage: tgId -> [{role, content}, ...]
const userContexts = new Map();
const MAX_CONTEXT_MESSAGES = 5;

// User state: tgId -> { mode: "awaiting_qa" | "awaiting_json" | "constructor", ... }
const adminState = new Map();
const userState = new Map();

// Constructor: tgId -> { step, type, currency, payment_type, bank, amount, ... }


// ─────────────────────────────────────────────────────────────
//  Stability
// ─────────────────────────────────────────────────────────────

process.on("unhandledRejection", (err) => console.error("[unhandledRejection]", err));
process.on("uncaughtException", (err) => console.error("[uncaughtException]", err));
bot.catch((err, ctx) => {
  console.error("[telegraf error]", err);
  try { ctx.reply("Произошла ошибка. Попробуй ещё раз."); } catch {}
});

let busy = false;
const queue = [];
function enqueue(fn) {
  return new Promise((resolve, reject) => {
    queue.push({ fn, resolve, reject });
    pump();
  });
}
async function pump() {
  if (busy) return;
  const job = queue.shift();
  if (!job) return;
  busy = true;
  try { job.resolve(await job.fn()); }
  catch (e) { job.reject(e); }
  finally { busy = false; pump(); }
}
function withTimeout(promise, ms = 35000) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout")), ms)),
  ]);
}

// ─────────────────────────────────────────────────────────────
//  Database Init (Postgres)
// ─────────────────────────────────────────────────────────────

async function initPgTables() {
  if (!USE_PG) return;
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

  // Audit log table
  await pool.query(`
    CREATE TABLE IF NOT EXISTS audit_log (
      id SERIAL PRIMARY KEY,
      tg_id BIGINT,
      action TEXT NOT NULL,
      details TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
  `);

  // Add missing columns and fix column types
  try {
    await pool.query(`ALTER TABLE access_keys ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0`);
    await pool.query(`ALTER TABLE access_keys ADD COLUMN IF NOT EXISTS created_by BIGINT`);
    await pool.query(`ALTER TABLE access_keys ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()`);
    // Expand key column to fit SHA-256 hashes (64 chars)
    await pool.query(`ALTER TABLE access_keys ALTER COLUMN key TYPE TEXT`);
    await pool.query(`ALTER TABLE user_sessions ALTER COLUMN key TYPE TEXT`);
  } catch (e) {
    console.log("[PG Migration] columns:", e.message);
  }

  // Migrate plaintext keys to hashed (one-time, safe to re-run)
  try {
    const res = await pool.query("SELECT key FROM access_keys WHERE LENGTH(key) <= 6");
    for (const row of res.rows) {
      const hashed = hashPassword(row.key);
      await pool.query("UPDATE access_keys SET key = $1 WHERE key = $2", [hashed, row.key]);
    }
    if (res.rows.length > 0) console.log(`🔐 Migrated ${res.rows.length} plaintext keys to hashes`);

    // Also hash keys in user_sessions
    const sessRes = await pool.query("SELECT tg_id, key FROM user_sessions WHERE LENGTH(key) <= 6");
    for (const row of sessRes.rows) {
      const hashed = hashPassword(row.key);
      await pool.query("UPDATE user_sessions SET key = $1 WHERE tg_id = $2", [hashed, row.tg_id]);
    }
    if (sessRes.rows.length > 0) console.log(`🔐 Migrated ${sessRes.rows.length} session keys to hashes`);
  } catch (e) {
    console.log("[PG Migration] key hashing:", e.message);
  }

  console.log("✅ Postgres tables initialized");
}

// ─────────────────────────────────────────────────────────────
//  Auth
// ─────────────────────────────────────────────────────────────

function authDb() {
  const db = new Database(AUTH_DB);
  // Ensure audit_log table exists in SQLite
  db.exec(`
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tg_id INTEGER,
      action TEXT NOT NULL,
      details TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);
  return db;
}
function isAdmin(ctx) { return ADMIN_TG_IDS.includes(Number(ctx.from?.id || 0)); }

async function logAudit(tgId, action, details = null) {
  try {
    if (USE_PG) {
      await pool.query(
        "INSERT INTO audit_log (tg_id, action, details) VALUES ($1, $2, $3)",
        [tgId, action, details]
      );
    } else {
      const db = authDb();
      db.prepare("INSERT INTO audit_log (tg_id, action, details) VALUES (?, ?, ?)").run(tgId, action, details);
      db.close();
    }
  } catch (e) {
    console.error("[Audit]", e.message);
  }
}

async function getAuditLog(limit = 15) {
  if (USE_PG) {
    const res = await pool.query("SELECT tg_id, action, details, created_at FROM audit_log ORDER BY created_at DESC LIMIT $1", [limit]);
    return res.rows;
  }
  const db = authDb();
  const rows = db.prepare("SELECT tg_id, action, details, created_at FROM audit_log ORDER BY created_at DESC LIMIT ?").all(limit);
  db.close();
  return rows;
}

async function isAuthorized(tgId) {
  if (USE_PG) {
    const res = await pool.query("SELECT tg_id FROM user_sessions WHERE tg_id = $1", [tgId]);
    return res.rows.length > 0;
  }
  const db = authDb();
  const row = db.prepare("SELECT tg_id FROM user_sessions WHERE tg_id = ?").get(tgId);
  db.close();
  return !!row;
}

async function authorizeUser(tgId, key) {
  const hashed = hashPassword(key);
  if (USE_PG) {
    await pool.query(
      "INSERT INTO user_sessions (tg_id, key, authorized_at) VALUES ($1, $2, NOW()) ON CONFLICT(tg_id) DO UPDATE SET key=$2, authorized_at=NOW()",
      [tgId, hashed]
    );
    return;
  }
  const db = authDb();
  db.prepare(
    "INSERT INTO user_sessions (tg_id, key, authorized_at) VALUES (?, ?, datetime('now')) ON CONFLICT(tg_id) DO UPDATE SET key=excluded.key, authorized_at=excluded.authorized_at"
  ).run(tgId, hashed);
  db.close();
}

async function validateKey(key) {
  const hashed = hashPassword(key);
  if (USE_PG) {
    const res = await pool.query("SELECT key, revoked FROM access_keys WHERE key = $1", [hashed]);
    return res.rows.length > 0 && res.rows[0].revoked === 0;
  }
  const db = authDb();
  const row = db.prepare("SELECT key, revoked FROM access_keys WHERE key = ?").get(hashed);
  db.close();
  return !!row && row.revoked === 0;
}

async function generateUniquePin() {
  for (let attempt = 0; attempt < 50; attempt++) {
    const pin = String(crypto.randomInt(100000, 999999));
    const hashed = hashPassword(pin);
    if (USE_PG) {
      const res = await pool.query("SELECT key FROM access_keys WHERE key = $1", [hashed]);
      if (res.rows.length === 0) return pin;
    } else {
      const db = authDb();
      const row = db.prepare("SELECT key FROM access_keys WHERE key = ?").get(hashed);
      db.close();
      if (!row) return pin;
    }
  }
  return String(crypto.randomInt(100000, 999999));
}

async function createKey(createdBy) {
  const pin = await generateUniquePin();
  const hashed = hashPassword(pin);
  if (USE_PG) {
    await pool.query("INSERT INTO access_keys (key, created_at, created_by, revoked) VALUES ($1, NOW(), $2, 0)", [hashed, createdBy]);
    return pin; // Return plain PIN to admin (shown once)
  }
  const db = authDb();
  db.prepare("INSERT INTO access_keys (key, created_at, created_by, revoked) VALUES (?, datetime('now'), ?, 0)").run(hashed, createdBy);
  db.close();
  return pin; // Return plain PIN to admin (shown once)
}

async function revokeKey(key) {
  if (USE_PG) {
    await pool.query("UPDATE access_keys SET revoked=1 WHERE key=$1", [key]);
    return;
  }
  const db = authDb();
  db.prepare("UPDATE access_keys SET revoked=1 WHERE key=?").run(key);
  db.close();
}

async function logoutUser(tgId) {
  if (USE_PG) {
    await pool.query("DELETE FROM user_sessions WHERE tg_id=$1", [tgId]);
    return;
  }
  const db = authDb();
  db.prepare("DELETE FROM user_sessions WHERE tg_id=?").run(tgId);
  db.close();
}

async function listKeys() {
  if (USE_PG) {
    const res = await pool.query("SELECT key, created_at, revoked FROM access_keys ORDER BY created_at DESC LIMIT 20");
    return res.rows;
  }
  const db = authDb();
  const rows = db.prepare("SELECT key, created_at, revoked FROM access_keys ORDER BY created_at DESC LIMIT 20").all();
  db.close();
  return rows;
}

async function listSessions() {
  if (USE_PG) {
    const res = await pool.query("SELECT tg_id, authorized_at FROM user_sessions ORDER BY authorized_at DESC");
    return res.rows;
  }
  const db = authDb();
  const rows = db.prepare("SELECT tg_id, authorized_at FROM user_sessions ORDER BY authorized_at DESC").all();
  db.close();
  return rows;
}

// ─────────────────────────────────────────────────────────────
//  RAG
// ─────────────────────────────────────────────────────────────

function cosineSim(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) + 1e-12);
}

async function embed(text) {
  const res = await client.embeddings.create({ model: EMBEDDING_MODEL, input: text });
  return res.data[0].embedding;
}

async function retrieveContexts(query, k = 5) {
  const qEmb = await embed(query);
  let rows;
  if (USE_PG) {
    const res = await pool.query("SELECT content, embedding_json FROM chunks");
    rows = res.rows;
  } else {
    const db = new Database(DB_PATH, { readonly: true });
    rows = db.prepare("SELECT content, embedding_json FROM chunks").all();
    db.close();
  }
  return rows
    .map((r) => ({ content: r.content, score: cosineSim(qEmb, JSON.parse(r.embedding_json)) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, k);
}

// ─────────────────────────────────────────────────────────────
//  Knowledge Base (Admin Training)
// ─────────────────────────────────────────────────────────────

async function initKnowledgeDb() {
  if (USE_PG) return; // PG tables created in initPgTables
  const db = new Database(DB_PATH);
  db.exec(`
    CREATE TABLE IF NOT EXISTS knowledge (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      question TEXT NOT NULL,
      answer TEXT NOT NULL,
      added_by INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);
  db.close();
}

async function addKnowledge(question, answer, addedBy) {
  if (USE_PG) {
    const res = await pool.query(
      "INSERT INTO knowledge (question, answer, added_by) VALUES ($1, $2, $3) RETURNING id",
      [question, answer, addedBy]
    );
    return res.rows[0].id;
  }
  const db = new Database(DB_PATH);
  const result = db.prepare("INSERT INTO knowledge (question, answer, added_by) VALUES (?, ?, ?)").run(question, answer, addedBy);
  db.close();
  return result.lastInsertRowid;
}

async function addKnowledgeWithEmbedding(question, answer, addedBy) {
  const knowledgeId = await addKnowledge(question, answer, addedBy);
  const chunkContent = `Вопрос: ${question}\nОтвет: ${answer}`;
  const embedding = await embed(chunkContent);
  if (USE_PG) {
    await pool.query(
      "INSERT INTO chunks (source, content, embedding_json) VALUES ($1, $2, $3)",
      [`knowledge_${knowledgeId}`, chunkContent, JSON.stringify(embedding)]
    );
  } else {
    const db = new Database(DB_PATH);
    db.prepare("INSERT INTO chunks (source, content, embedding_json) VALUES (?, ?, ?)").run(`knowledge_${knowledgeId}`, chunkContent, JSON.stringify(embedding));
    db.close();
  }
  return knowledgeId;
}

async function listKnowledge(limit = 20) {
  if (USE_PG) {
    const res = await pool.query("SELECT id, question, answer, created_at FROM knowledge ORDER BY id DESC LIMIT $1", [limit]);
    return res.rows;
  }
  const db = new Database(DB_PATH);
  const rows = db.prepare("SELECT id, question, answer, created_at FROM knowledge ORDER BY id DESC LIMIT ?").all(limit);
  db.close();
  return rows;
}

async function deleteKnowledge(id) {
  if (USE_PG) {
    await pool.query("DELETE FROM knowledge WHERE id = $1", [id]);
    await pool.query("DELETE FROM chunks WHERE source = $1", [`knowledge_${id}`]);
    return;
  }
  const db = new Database(DB_PATH);
  db.prepare("DELETE FROM knowledge WHERE id = ?").run(id);
  db.prepare("DELETE FROM chunks WHERE source = ?").run(`knowledge_${id}`);
  db.close();
}

async function getKnowledgeById(id) {
  if (USE_PG) {
    const res = await pool.query("SELECT * FROM knowledge WHERE id = $1", [id]);
    return res.rows[0] || null;
  }
  const db = new Database(DB_PATH);
  const row = db.prepare("SELECT * FROM knowledge WHERE id = ?").get(id);
  db.close();
  return row;
}

// ─────────────────────────────────────────────────────────────
//  Dialog Context Management
// ─────────────────────────────────────────────────────────────

function addToContext(tgId, role, content) {
  if (!userContexts.has(tgId)) {
    userContexts.set(tgId, []);
  }
  const context = userContexts.get(tgId);
  context.push({ role, content });

  // Keep only last N messages
  if (context.length > MAX_CONTEXT_MESSAGES * 2) {
    context.splice(0, 2); // Remove oldest user+assistant pair
  }
}

function getContext(tgId) {
  return userContexts.get(tgId) || [];
}

function clearContext(tgId) {
  userContexts.delete(tgId);
}

// ─────────────────────────────────────────────────────────────
//  Auto Documentation Update
// ─────────────────────────────────────────────────────────────

async function fetchDocPage(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    return await response.text();
  } catch (err) {
    console.error(`[Doc Fetch Error] ${url}:`, err);
    return null;
  }
}

async function parseAndUpdateDocs() {
  console.log("📚 Обновление документации...");

  const docUrls = Object.values(DOC_LINKS).filter(url => url && url.startsWith("http"));
  const uniqueUrls = [...new Set(docUrls)];

  let updatedCount = 0;

  for (const url of uniqueUrls.slice(0, 20)) { // Limit to prevent rate limiting
    const html = await fetchDocPage(url);
    if (!html) continue;

    try {
      const $ = cheerio.load(html);

      // Extract main content (adjust selectors based on readme.io structure)
      const title = $("h1").first().text().trim();
      const content = $("article, .content, .markdown-body")
        .text()
        .replace(/\s+/g, " ")
        .trim()
        .substring(0, 2000);

      if (content.length > 100) {
        if (USE_PG) {
          await pool.query(
            "INSERT INTO doc_updates (url, title, content, updated_at) VALUES ($1, $2, $3, NOW()) ON CONFLICT(url) DO UPDATE SET title=$2, content=$3, updated_at=NOW()",
            [url, title, content]
          );
        } else {
          const db = new Database(DB_PATH);
          db.exec(`CREATE TABLE IF NOT EXISTS doc_updates (url TEXT PRIMARY KEY, title TEXT, content TEXT, updated_at DATETIME)`);
          db.prepare("INSERT OR REPLACE INTO doc_updates (url, title, content, updated_at) VALUES (?, ?, ?, datetime('now'))").run(url, title, content);
          db.close();
        }
        updatedCount++;

        console.log(`✅ Обновлено: ${title}`);
      }
    } catch (err) {
      console.error(`[Parse Error] ${url}:`, err);
    }

    // Delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 1000));
  }

  console.log(`📚 Документация обновлена: ${updatedCount} страниц`);
}

// Schedule documentation + banks updates: every day at 3 AM
cron.schedule("0 3 * * *", async () => {
  try {
    await parseAndUpdateDocs();
    await loadBanks();
  } catch (err) {
    console.error("[Cron Error]", err);
  }
});

// Run initial update on startup
setTimeout(() => {
  parseAndUpdateDocs().catch(console.error);
}, 5000);

// ─────────────────────────────────────────────────────────────
//  Keyboard
// ─────────────────────────────────────────────────────────────

// Порядок кнопок = flow интеграции мерча:
// 1. Начало → 2. Депозиты/Выплаты → 3. Webhooks/Заказы →
// 4. Статусы/Ошибки → 5. Баланс/Банки → 6. Продвинутое →
// 7. Инструменты → 8. Помощь
const mainKeyboard = Markup.keyboard([
  ["🚀 Быстрый старт", "📚 Документация"],
  ["📥 Депозиты", "📤 Выплаты"],
  ["🔔 Webhooks", "📋 Заказы"],
  ["📊 Статусы", "⚠️ Ошибки"],
  ["💰 Баланс", "🏦 Банки"],
  ["🛒 E-commerce", "📎 Аппилы"],
  ["🛠 Конструктор", "🔍 Валидатор"],
  ["✅ Чеклист", "📸 Скриншот"]
]).resize();

const adminKeyboard = Markup.keyboard([
  ["🚀 Быстрый старт", "📚 Документация"],
  ["📥 Депозиты", "📤 Выплаты"],
  ["🔔 Webhooks", "📋 Заказы"],
  ["📊 Статусы", "⚠️ Ошибки"],
  ["💰 Баланс", "🏦 Банки"],
  ["🛒 E-commerce", "📎 Аппилы"],
  ["🛠 Конструктор", "🔍 Валидатор"],
  ["✅ Чеклист", "📸 Скриншот"],
  ["⚙️ Админ панель"]
]).resize();

const adminMenu = Markup.inlineKeyboard([
  [Markup.button.callback("🔑 Создать пароль", "admin_newkey")],
  [Markup.button.callback("📋 Список паролей", "admin_list_keys")],
  [Markup.button.callback("👥 Активные сессии", "admin_sessions")],
  [Markup.button.callback("🚫 Отозвать пароль", "admin_revoke_prompt")],
  [Markup.button.callback("📊 Аудит лог", "admin_audit")],
  [Markup.button.callback("📖 Обучение бота", "admin_training")]
]);

// ─────────────────────────────────────────────────────────────
//  Middleware
// ─────────────────────────────────────────────────────────────

bot.use(async (ctx, next) => {
  const tgId = Number(ctx.from?.id || 0);
  const text = (ctx.message?.text || "").trim();

  if (ADMIN_TG_IDS.includes(tgId)) return next();
  if (text.startsWith("/login") || text.startsWith("/start")) return next();

  // Allow callback queries for login flow
  if (ctx.callbackQuery && ctx.callbackQuery.data === "enter_password") return next();

  if (!(await isAuthorized(tgId))) {
    await ctx.reply(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "        🔐  *Доступ закрыт*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Для работы с ботом введи\n6-значный пароль командой:\n\n" +
      "`/login 123456`",
      { parse_mode: "Markdown" }
    );
    return;
  }
  return next();
});

// ─────────────────────────────────────────────────────────────
//  Commands
// ─────────────────────────────────────────────────────────────

bot.command("start", async (ctx) => {
  const tgId = Number(ctx.from?.id || 0);
  const authorized = ADMIN_TG_IDS.includes(tgId) || await isAuthorized(tgId);

  if (!authorized) {
    return ctx.reply(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "   🤖  *ProcessingHub Tech Bot*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Привет! Я AI-помощник по\nинтеграции ProcessingHub API.\n\n" +
      "🔐 Для начала работы введи\n6-значный пароль:\n\n" +
      "`/login 123456`\n\n" +
      "_Пароль можно получить\nу администратора_",
      { parse_mode: "Markdown" }
    );
  }

  const keyboard = isAdmin(ctx) ? adminKeyboard : mainKeyboard;
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "   🤖  *ProcessingHub Tech Bot*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Привет! Я AI-помощник по\nинтеграции ProcessingHub API.\n\n" +
    "💡 Задай вопрос или выбери\nтему на клавиатуре.\n" +
    "📸 Можешь прислать скриншот\nошибки — я проанализирую.",
    { parse_mode: "Markdown", ...keyboard }
  );
});

bot.command("login", async (ctx) => {
  const tgId = Number(ctx.from?.id || 0);
  const password = ctx.message.text.split(/\s+/)[1];

  if (!password) {
    return ctx.reply(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "        🔐  *Вход в систему*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Введи команду с паролем:\n\n" +
      "`/login 123456`\n\n" +
      "_Замени 123456 на свой\n6-значный пароль_",
      { parse_mode: "Markdown" }
    );
  }

  if (!(await validateKey(password))) {
    await logAudit(tgId, "login_fail", "wrong password");
    return ctx.reply(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "        ❌  *Ошибка входа*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Неверный или отозванный\nпароль. Проверь правильность\nввода или обратись к админу.",
      { parse_mode: "Markdown" }
    );
  }

  await authorizeUser(tgId, password);
  await logAudit(tgId, "login_ok");

  // Try to delete the message with password for security
  try { await ctx.deleteMessage(); } catch {}

  const keyboard = isAdmin(ctx) ? adminKeyboard : mainKeyboard;
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "        ✅  *Добро пожаловать!*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Авторизация прошла успешно.\n\n" +
    "💡 Задай вопрос или выбери\nтему на клавиатуре.",
    { parse_mode: "Markdown", ...keyboard }
  );
});

bot.command("logout", async (ctx) => {
  const tgId = Number(ctx.from?.id || 0);
  await logoutUser(tgId);
  await logAudit(tgId, "logout");
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "        👋  *До встречи!*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Сессия завершена.\nДля повторного входа: `/login`",
    { parse_mode: "Markdown" }
  );
});

bot.command("clear", async (ctx) => {
  const tgId = Number(ctx.from?.id || 0);
  clearContext(tgId);
  ctx.reply("🧹 История диалога очищена. Начнём сначала!");
});

bot.command("newkey", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.reply("⛔ Нет доступа");
  const key = await createKey(ctx.from.id);
  await logAudit(ctx.from.id, "key_created");
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "     🔑  *Новый пароль доступа*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    `         \`${key}\`\n\n` +
    "Пользователь вводит:\n" +
    `\`/login ${key}\`\n\n` +
    "━━━━━━━━━━━━━━━━━━━━",
    { parse_mode: "Markdown" }
  );
});

bot.command("revoke", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.reply("⛔ Нет доступа");
  const input = ctx.message.text.split(/\s+/)[1];
  if (!input) return ctx.reply("Формат: `/revoke <пароль>`", { parse_mode: "Markdown" });
  // Input can be a plain PIN (hash it) or already a hash (from admin UI)
  const keyToRevoke = input.length <= 6 ? hashPassword(input) : input;
  await revokeKey(keyToRevoke);
  await logAudit(ctx.from.id, "key_revoked");
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "     🚫  *Пароль отозван*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Пароль деактивирован.",
    { parse_mode: "Markdown" }
  );
});

bot.command("admin", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.reply("⛔ Нет доступа");
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "       ⚙️  *Админ панель*\n" +
    "━━━━━━━━━━━━━━━━━━━━",
    { parse_mode: "Markdown", ...adminMenu }
  );
});

// ─────────────────────────────────────────────────────────────
//  Admin Callbacks
// ─────────────────────────────────────────────────────────────

bot.action("admin_newkey", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const key = await createKey(ctx.from.id);
  await logAudit(ctx.from.id, "key_created");
  await ctx.answerCbQuery("Пароль создан!");
  ctx.reply(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "     🔑  *Новый пароль доступа*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    `         \`${key}\`\n\n` +
    "Пользователь вводит:\n" +
    `\`/login ${key}\`\n\n` +
    "━━━━━━━━━━━━━━━━━━━━",
    { parse_mode: "Markdown" }
  );
});

bot.action("admin_list_keys", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const keys = await listKeys();

  if (keys.length === 0) {
    return ctx.editMessageText(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "        📋  *Пароли*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Нет созданных паролей",
      { parse_mode: "Markdown", ...adminMenu }
    );
  }

  let text = "━━━━━━━━━━━━━━━━━━━━\n" +
    "      📋  *Пароли доступа*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n";
  keys.forEach((k) => {
    const status = k.revoked ? "🔴" : "🟢";
    const shortHash = k.key.substring(0, 8) + "…";
    const date = new Date(k.created_at).toLocaleDateString("ru-RU");
    text += `${status} \`${shortHash}\`  📅 ${date}\n`;
  });

  ctx.editMessageText(text, { parse_mode: "Markdown", ...adminMenu });
  ctx.answerCbQuery();
});

bot.action("admin_sessions", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const sessions = await listSessions();

  if (sessions.length === 0) {
    return ctx.editMessageText(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "      👥  *Активные сессии*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Нет активных сессий",
      { parse_mode: "Markdown", ...adminMenu }
    );
  }

  let text = "━━━━━━━━━━━━━━━━━━━━\n" +
    "      👥  *Активные сессии*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n";
  sessions.forEach((s, i) => {
    const date = new Date(s.authorized_at).toLocaleDateString("ru-RU");
    text += `${i + 1}. 👤 \`${s.tg_id}\`  📅 ${date}\n`;
  });

  ctx.editMessageText(text, { parse_mode: "Markdown", ...adminMenu });
  ctx.answerCbQuery();
});

bot.action("admin_revoke_prompt", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const keys = (await listKeys()).filter(k => !k.revoked);

  if (keys.length === 0) {
    ctx.answerCbQuery("Нет активных паролей");
    return;
  }

  const buttons = keys.slice(0, 8).map(k => {
    const shortHash = k.key.substring(0, 8) + "…";
    const date = new Date(k.created_at).toLocaleDateString("ru-RU");
    return [Markup.button.callback(`🚫 ${shortHash} (${date})`, `revoke_${k.key}`)];
  });
  buttons.push([Markup.button.callback("« Назад", "admin_back")]);

  ctx.editMessageText(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "   🚫  *Отзыв пароля*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Выбери пароль для отзыва:",
    {
      parse_mode: "Markdown",
      ...Markup.inlineKeyboard(buttons)
    }
  );
  ctx.answerCbQuery();
});

bot.action(/^revoke_(.+)$/, async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const key = ctx.match[1];
  await revokeKey(key);
  await logAudit(ctx.from.id, "key_revoked");
  ctx.answerCbQuery("Пароль отозван!");
  ctx.editMessageText(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "     ✅  *Пароль отозван*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Пароль деактивирован.",
    { parse_mode: "Markdown", ...adminMenu }
  );
});

bot.action("admin_audit", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const logs = await getAuditLog(15);

  if (logs.length === 0) {
    return ctx.editMessageText(
      "━━━━━━━━━━━━━━━━━━━━\n" +
      "       📊  *Аудит лог*\n" +
      "━━━━━━━━━━━━━━━━━━━━\n\n" +
      "Нет записей",
      { parse_mode: "Markdown", ...adminMenu }
    );
  }

  const icons = {
    login_ok: "✅", login_fail: "❌",
    logout: "👋", key_created: "🔑", key_revoked: "🚫"
  };

  let text = "━━━━━━━━━━━━━━━━━━━━\n" +
    "       📊  *Аудит лог*\n" +
    "━━━━━━━━━━━━━━━━━━━━\n\n";
  logs.forEach(l => {
    const icon = icons[l.action] || "📝";
    const date = new Date(l.created_at);
    const time = date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    const detail = l.details ? ` _${l.details}_` : "";
    text += `${icon} \`${l.tg_id}\` ${l.action}${detail}\n     ${time}\n`;
  });

  ctx.editMessageText(text, { parse_mode: "Markdown", ...adminMenu });
  ctx.answerCbQuery();
});

bot.action("admin_back", async (ctx) => {
  adminState.delete(Number(ctx.from?.id || 0));
  ctx.editMessageText(
    "━━━━━━━━━━━━━━━━━━━━\n" +
    "       ⚙️  *Админ панель*\n" +
    "━━━━━━━━━━━━━━━━━━━━",
    { parse_mode: "Markdown", ...adminMenu }
  );
  ctx.answerCbQuery();
});

// ─────────────────────────────────────────────────────────────
//  Training (Knowledge Base) Callbacks
// ─────────────────────────────────────────────────────────────

const trainingMenu = Markup.inlineKeyboard([
  [Markup.button.callback("➕ Добавить знание", "train_add")],
  [Markup.button.callback("📋 Список знаний", "train_list")],
  [Markup.button.callback("« Назад", "admin_back")]
]);

bot.action("admin_training", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  ctx.editMessageText(
    "📖 *Обучение бота*\n━━━━━━━━━━━━━━━━\n\nДобавляй вопросы и ответы — бот будет их использовать при общении с пользователями.",
    { parse_mode: "Markdown", ...trainingMenu }
  );
  ctx.answerCbQuery();
});

bot.action("train_add", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const tgId = Number(ctx.from?.id || 0);
  adminState.set(tgId, "awaiting_qa");
  await ctx.editMessageText(
    "📝 *Добавление знания*\n━━━━━━━━━━━━━━━━━━━━\n\n" +
    "Отправь сообщение в формате:\n\n" +
    "`Вопрос: текст вопроса`\n" +
    "`Ответ: текст ответа`\n\n" +
    "Пример:\n" +
    "`Вопрос: Какие IP адреса в вайт листе?`\n" +
    "`Ответ: Наши серверы работают с IP: 1.2.3.4, 5.6.7.8`\n\n" +
    "Или отправь /cancel для отмены",
    { parse_mode: "Markdown" }
  );
  ctx.answerCbQuery();
});

bot.action("train_list", async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const items = await listKnowledge(10);

  if (items.length === 0) {
    return ctx.editMessageText(
      "📋 *База знаний пуста*\n━━━━━━━━━━━━━━━━\n\nДобавь первое знание через кнопку ниже.",
      { parse_mode: "Markdown", ...trainingMenu }
    );
  }

  let text = "📋 *База знаний:*\n━━━━━━━━━━━━━━━━\n\n";
  items.forEach((item) => {
    const shortQ = item.question.length > 50 ? item.question.substring(0, 50) + "..." : item.question;
    const shortA = item.answer.length > 80 ? item.answer.substring(0, 80) + "..." : item.answer;
    text += `*#${item.id}* ❓ ${shortQ}\n💡 ${shortA}\n\n`;
  });

  const buttons = items.slice(0, 5).map(item => {
    const shortQ = item.question.length > 20 ? item.question.substring(0, 20) + "..." : item.question;
    return [Markup.button.callback(`🗑 #${item.id} ${shortQ}`, `train_del_${item.id}`)];
  });
  buttons.push([Markup.button.callback("« Назад", "admin_training")]);

  ctx.editMessageText(text, {
    parse_mode: "Markdown",
    ...Markup.inlineKeyboard(buttons)
  });
  ctx.answerCbQuery();
});

bot.action(/^train_del_(\d+)$/, async (ctx) => {
  if (!isAdmin(ctx)) return ctx.answerCbQuery("⛔ Нет доступа");
  const id = Number(ctx.match[1]);
  const item = await getKnowledgeById(id);
  if (!item) {
    ctx.answerCbQuery("Знание не найдено");
    return;
  }
  await deleteKnowledge(id);
  ctx.answerCbQuery("Удалено!");
  ctx.editMessageText(
    `✅ Знание #${id} удалено`,
    { parse_mode: "Markdown", ...trainingMenu }
  );
});

// ─────────────────────────────────────────────────────────────
//  Photo Handler (Vision)
// ─────────────────────────────────────────────────────────────

bot.on("photo", async (ctx) => {
  await ctx.reply("🔍 Анализирую скриншот...");
  await ctx.sendChatAction("typing");

  try {
    const photo = ctx.message.photo[ctx.message.photo.length - 1];
    const fileLink = await ctx.telegram.getFileLink(photo.file_id);

    const response = await withTimeout(
      client.chat.completions.create({
        model: VISION_MODEL,
        messages: [
          {
            role: "system",
            content: `Ты — техподдержка ProcessingHub API. Проанализируй скриншот и дай СТРУКТУРИРОВАННЫЙ ответ.

ФОРМАТ ОТВЕТА:
1. ЧТО НА СКРИНШОТЕ: (опиши что видишь — код, ошибку, логи, интерфейс)
2. ПРОБЛЕМА: (конкретная причина ошибки)
3. РЕШЕНИЕ: (точные шаги исправления с примером кода/JSON если применимо)

СПРАВОЧНИК:
• Авторизация: заголовок Authorization: Bearer <API_KEY>
• Content-Type: application/json, Accept: application/json
• Обязательные поля deposit/credit: merchant_id (string), amount (number), currency (string), payment_type (string), bank (number — ID из GET /banks)
• Платёжные методы: sbp, c2c, sng_sbp, sng_c2c, qr_pay, nspk, sim, sber, tbank, alfa, ozon, vtb, psb, gazprom, yandex, quasi-ecomm, sber-invoice, alfa-invoice
• Валюты: RUB, AZN, KGS, TJS, USDT, BOB, KRW
• Статусы: new, opened, process, closed, canceled, expired, failed, wait, chargeback
• Лимит: 15 req/sec

⚠️ НИКОГДА не придумывай информацию. Если не можешь определить проблему по скриншоту — скажи прямо.`
          },
          {
            role: "user",
            content: [
              { type: "text", text: "Проанализируй этот скриншот:" },
              { type: "image_url", image_url: { url: fileLink.href } }
            ]
          }
        ],
        max_tokens: 1000
      }),
      60000
    );

    const answer = response.choices[0]?.message?.content || "Не удалось проанализировать";
    ctx.reply(answer);
  } catch (err) {
    console.error("[Vision Error]", err);
    ctx.reply("❌ Не удалось проанализировать изображение. Попробуй описать ошибку текстом.");
  }
});

// ─────────────────────────────────────────────────────────────
//  Text Handler
// ─────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────
//  Documentation Links
// ─────────────────────────────────────────────────────────────

const DOC_LINKS = {
  main: "https://docs.example.com/docs",
  gettingStarted: "https://docs.example.com/docs/getting-started",
  // Payin (Deposit)
  createDeposit: "https://docs.example.com/docs/payin/create",
  // Payout (Credit)
  createCredit: "https://docs.example.com/docs/payout/create",
  // Orders
  ordersList: "https://docs.example.com/docs/orders/list",
  getOrder: "https://docs.example.com/docs/orders/info",
  cancelOrder: "https://docs.example.com/docs/orders/cancel",
  // E-commerce
  ecommCreate: "https://docs.example.com/docs/ecomm/create",
  ecommConfirm: "https://docs.example.com/docs/ecomm/confirm",
  ecomm: "https://docs.example.com/docs/ecomm",
  ecommCode: "https://docs.example.com/docs/orders/confirm-code",
  ecommReset: "https://docs.example.com/docs/ecomm/code-reset",
  // Account
  profile: "https://docs.example.com/docs/account/profile",
  balance: "https://docs.example.com/docs/account/balance",
  // Files
  upload: "https://docs.example.com/docs/files/upload",
  // Support/Appeals
  supportList: "https://docs.example.com/docs/support/list",
  supportCreate: "https://docs.example.com/docs/support/create",
  supportInfo: "https://docs.example.com/docs/support/info",
  supportUpdate: "https://docs.example.com/docs/support/update",
  supportDelete: "https://docs.example.com/docs/support/delete",
  supportClose: "https://docs.example.com/docs/support/close",
  supportDecline: "https://docs.example.com/docs/support/decline",
  supportResolutions: "https://docs.example.com/docs/support/resolutions",
  supportResolutionCreate: "https://docs.example.com/docs/support/resolution",
  // Reference
  banks: "https://docs.example.com/docs/banks"
};

// Маппинг ключевых слов на ссылки документации
const TOPIC_LINKS = {
  // Общие запросы на ссылку/документацию
  "ссылк": { url: DOC_LINKS.main, title: "Документация API" },
  "документац": { url: DOC_LINKS.main, title: "Документация API" },
  "api": { url: DOC_LINKS.main, title: "Документация API" },
  "апи": { url: DOC_LINKS.main, title: "Документация API" },
  "начало": { url: DOC_LINKS.gettingStarted, title: "Начало работы" },
  "getting started": { url: DOC_LINKS.gettingStarted, title: "Начало работы" },
  "авторизац": { url: DOC_LINKS.gettingStarted, title: "Начало работы" },
  "bearer": { url: DOC_LINKS.gettingStarted, title: "Начало работы" },
  "токен": { url: DOC_LINKS.gettingStarted, title: "Начало работы" },
  // Депозит / Пополнение
  "депозит": { url: DOC_LINKS.createDeposit, title: "Создание депозита" },
  "deposit": { url: DOC_LINKS.createDeposit, title: "Создание депозита" },
  "пополнение": { url: DOC_LINKS.createDeposit, title: "Создание депозита" },
  "payin": { url: DOC_LINKS.createDeposit, title: "Создание депозита" },
  // Выплата
  "выплата": { url: DOC_LINKS.createCredit, title: "Создание выплаты (credit)" },
  "payout": { url: DOC_LINKS.createCredit, title: "Создание выплаты (credit)" },
  "credit": { url: DOC_LINKS.createCredit, title: "Создание выплаты (credit)" },
  "вывод": { url: DOC_LINKS.createCredit, title: "Создание выплаты (credit)" },
  "кредит": { url: DOC_LINKS.createCredit, title: "Создание выплаты (credit)" },
  // Заказы
  "список заказов": { url: DOC_LINKS.ordersList, title: "Список ордеров" },
  "список ордеров": { url: DOC_LINKS.ordersList, title: "Список ордеров" },
  "orders": { url: DOC_LINKS.ordersList, title: "Список ордеров" },
  "ордер": { url: DOC_LINKS.getOrder, title: "Информация об ордере" },
  "order": { url: DOC_LINKS.getOrder, title: "Информация об ордере" },
  "заказ": { url: DOC_LINKS.getOrder, title: "Информация об ордере" },
  "статус заказа": { url: DOC_LINKS.getOrder, title: "Информация об ордере" },
  "статус ордера": { url: DOC_LINKS.getOrder, title: "Информация об ордере" },
  "отмена": { url: DOC_LINKS.cancelOrder, title: "Отмена ордера" },
  "отменить": { url: DOC_LINKS.cancelOrder, title: "Отмена ордера" },
  "cancel": { url: DOC_LINKS.cancelOrder, title: "Отмена ордера" },
  // Баланс
  "баланс": { url: DOC_LINKS.balance, title: "Получение баланса" },
  "balance": { url: DOC_LINKS.balance, title: "Получение баланса" },
  // Профиль
  "профиль": { url: DOC_LINKS.profile, title: "Профиль мерчанта" },
  "profile": { url: DOC_LINKS.profile, title: "Профиль мерчанта" },
  "мерчант": { url: DOC_LINKS.profile, title: "Профиль мерчанта" },
  "merchant": { url: DOC_LINKS.profile, title: "Профиль мерчанта" },
  // E-commerce
  "ecomm": { url: DOC_LINKS.ecommCreate, title: "E-commerce платежи" },
  "ecommerce": { url: DOC_LINKS.ecommCreate, title: "E-commerce платежи" },
  "e-commerce": { url: DOC_LINKS.ecommCreate, title: "E-commerce платежи" },
  "3ds": { url: DOC_LINKS.ecommCode, title: "Подтверждение 3DS кода" },
  "карта": { url: DOC_LINKS.ecommCreate, title: "E-commerce платежи" },
  "card": { url: DOC_LINKS.ecommCreate, title: "E-commerce платежи" },
  "смс код": { url: DOC_LINKS.ecommCode, title: "Подтверждение 3DS кода" },
  "sms": { url: DOC_LINKS.ecommCode, title: "Подтверждение 3DS кода" },
  // Апелляции / Support
  "апелляция": { url: DOC_LINKS.supportCreate, title: "Создание аппила" },
  "аппил": { url: DOC_LINKS.supportList, title: "Список аппилов" },
  "appeal": { url: DOC_LINKS.supportList, title: "Список аппилов" },
  "support": { url: DOC_LINKS.supportList, title: "Список аппилов" },
  "спор": { url: DOC_LINKS.supportCreate, title: "Создание аппила" },
  "тикет": { url: DOC_LINKS.supportCreate, title: "Создание аппила" },
  "обращение": { url: DOC_LINKS.supportCreate, title: "Создание аппила" },
  "резолюция": { url: DOC_LINKS.supportResolutions, title: "Резолюции аппила" },
  "resolution": { url: DOC_LINKS.supportResolutions, title: "Резолюции аппила" },
  // Банки
  "банк": { url: DOC_LINKS.banks, title: "Список банков" },
  "bank": { url: DOC_LINKS.banks, title: "Список банков" },
  "сбп": { url: DOC_LINKS.banks, title: "Список банков" },
  "sbp": { url: DOC_LINKS.banks, title: "Список банков" },
  // Файлы
  "загрузка": { url: DOC_LINKS.upload, title: "Загрузка файлов" },
  "upload": { url: DOC_LINKS.upload, title: "Загрузка файлов" },
  "файл": { url: DOC_LINKS.upload, title: "Загрузка файлов" },
  "чек": { url: DOC_LINKS.upload, title: "Загрузка файлов" }
};

// Fuse.js configuration for fuzzy search
const fuseOptions = {
  keys: ["keyword"],
  threshold: 0.4,
  includeScore: true
};

// Convert TOPIC_LINKS to array for Fuse.js
const topicLinksArray = Object.entries(TOPIC_LINKS).map(([keyword, linkInfo]) => ({
  keyword,
  ...linkInfo
}));

const fuse = new Fuse(topicLinksArray, fuseOptions);

// Функция поиска релевантных ссылок по тексту запроса с fuzzy matching
function findRelevantLinks(query) {
  const lowerQuery = query.toLowerCase();
  const fuseResults = fuse.search(lowerQuery);

  const found = new Map();

  // Add fuzzy matches
  fuseResults.forEach(result => {
    const linkInfo = { url: result.item.url, title: result.item.title };
    found.set(linkInfo.url, linkInfo);
  });

  // Add exact substring matches (higher priority)
  for (const [keyword, linkInfo] of Object.entries(TOPIC_LINKS)) {
    if (lowerQuery.includes(keyword)) {
      found.set(linkInfo.url, linkInfo);
    }
  }

  return Array.from(found.values()).slice(0, 3);
}

// Форматирование ссылок для ответа
function formatLinksForReply(links) {
  if (!links.length) return "";

  let text = "\n\n📖 *Документация:*\n";
  links.forEach(link => {
    text += `• [${link.title}](${link.url})\n`;
  });
  return text;
}

const docsMenu = Markup.inlineKeyboard([
  [Markup.button.url("📖 Вся документация", DOC_LINKS.main)],
  [Markup.button.url("🚀 Начало работы", DOC_LINKS.gettingStarted)],

  [Markup.button.callback("━━━ 📥 PAYIN ━━━", "noop")],
  [Markup.button.url("➕ Создать депозит", DOC_LINKS.createDeposit)],

  [Markup.button.callback("━━━ 📤 PAYOUT ━━━", "noop")],
  [Markup.button.url("➕ Создать выплату (credit)", DOC_LINKS.createCredit)],

  [Markup.button.callback("━━━ 📋 ОРДЕРЫ ━━━", "noop")],
  [
    Markup.button.url("📋 Список", DOC_LINKS.ordersList),
    Markup.button.url("🔍 Инфо", DOC_LINKS.getOrder)
  ],
  [Markup.button.url("❌ Отмена ордера", DOC_LINKS.cancelOrder)],

  [Markup.button.callback("━━━ 🛒 E-COMMERCE ━━━", "noop")],
  [
    Markup.button.url("Создать", DOC_LINKS.ecommCreate),
    Markup.button.url("Карта", DOC_LINKS.ecommConfirm)
  ],
  [
    Markup.button.url("3DS код", DOC_LINKS.ecommCode),
    Markup.button.url("Сброс", DOC_LINKS.ecommReset)
  ],

  [Markup.button.callback("━━━ 📎 АППИЛЫ ━━━", "noop")],
  [
    Markup.button.url("📋 Список", DOC_LINKS.supportList),
    Markup.button.url("➕ Создать", DOC_LINKS.supportCreate)
  ],
  [
    Markup.button.url("🔍 Инфо", DOC_LINKS.supportInfo),
    Markup.button.url("✅ Закрыть", DOC_LINKS.supportClose)
  ],
  [Markup.button.url("📝 Резолюции", DOC_LINKS.supportResolutions)],

  [Markup.button.callback("━━━ 📊 АККАУНТ ━━━", "noop")],
  [
    Markup.button.url("💰 Баланс", DOC_LINKS.balance),
    Markup.button.url("👤 Профиль", DOC_LINKS.profile)
  ],

  [Markup.button.callback("━━━ 📁 ПРОЧЕЕ ━━━", "noop")],
  [
    Markup.button.url("🏦 Банки", DOC_LINKS.banks),
    Markup.button.url("📤 Загрузка", DOC_LINKS.upload)
  ]
]);

// Handle empty callback for separators
bot.action("noop", (ctx) => ctx.answerCbQuery());

// ─────────────────────────────────────────────────────────────
//  Keyboard Button Content
// ─────────────────────────────────────────────────────────────

const BUTTON_CONTENT = {
  "📚 Документация": "SHOW_DOCS_MENU",
  "⚙️ Админ панель": "SHOW_ADMIN_MENU",

  "🚀 Быстрый старт": `
🚀 *Быстрый старт — ProcessingHub API*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 *Шаги интеграции:*

*1️⃣ Получи API-ключ*
   Токен выдаёт менеджер при регистрации

*2️⃣ Base URL:*
   Dev: \`https://sandbox-api.example.com/api\`
   Prod: \`https://api.example.com/api\`

*3️⃣ Настрой заголовки*
\`\`\`
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json
Accept: application/json
\`\`\`

*4️⃣ Пример запроса (curl):*
\`\`\`
curl -X POST https://sandbox-api.example.com/api/order/deposit \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"merchant_id":"xxx","amount":1000,"currency":"rub","payment_type":"sbp","bank":46}'
\`\`\`

*5️⃣ Настрой Webhook*
   URL указывается в \`callback\\_url\` при создании ордера
   ProcessingHub отправляет POST с \`Authorization: Bearer <token>\`

*📊 Статусы ордеров:*
   \`new\` → \`opened\` → \`process\` → \`closed\`
   Также: \`canceled\`, \`expired\`, \`failed\`, \`wait\`, \`chargeback\`

⚠️ *Лимит:* 15 запросов/сек с одного IP
📖 Версия API: 1.25.22
`,

  "📥 Депозиты": `
📥 *Создание депозита (Payin)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

\`POST /order/deposit\`

*Обязательные поля:*
   • \`merchant\\_id\` — ID мерчанта
   • \`amount\` — сумма (float)
   • \`currency\` — валюта (rub, azn, kgs, tjs, usdt, bob, krw)
   • \`payment\\_type\` — метод (sbp, c2c, sng\\_sbp, sng\\_c2c, qr\\_pay, nspk, sim, sber, tbank, alfa, ozon, vtb, psb, gazprom, yandex, quasi-ecomm, sber-invoice, alfa-invoice)
   • \`bank\` — ID банка (число, получить через GET /banks)

*Опциональные поля:*
   • \`external\\_id\` — ваш ID для сопоставления
   • \`callback\\_url\` — URL для webhook
   • \`allow\\_change\\_amount\` — разрешить изменение суммы
   • \`allow\\_change\\_amount\\_value\` — макс. увеличение
   • \`success\\_url\` / \`failed\\_url\` — редиректы

*Пример запроса:*
\`\`\`json
{
  "merchant_id": "your-id",
  "amount": 1000.00,
  "currency": "rub",
  "payment_type": "sbp",
  "bank": 46,
  "external_id": "order-123",
  "callback_url": "https://example.com/cb"
}
\`\`\`

*Ответ (201):*
\`\`\`json
{
  "id": "uuid",
  "number": 12345,
  "amount": 1000.00,
  "status": "new",
  "type": "deposit",
  "redirect_url": "https://..."
}
\`\`\`

💡 \`redirect\\_url\` — ссылка на форму оплаты
`,

  "📤 Выплаты": `
📤 *Создание выплаты (Payout)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Два эндпоинта:*
   • \`POST /order/credit\` — выплата (credit)
   • \`POST /order/payout\` — выплата (payout)

*Обязательные поля:*
   • \`merchant\\_id\` — ID мерчанта
   • \`amount\` — сумма (float)
   • \`currency\` — валюта
   • \`payment\\_type\` — метод оплаты
   • \`bank\` — ID банка (число, из GET /banks)

*Опциональные поля:*
   • \`external\\_id\` — ваш ID
   • \`callback\\_url\` — URL для webhook
   • \`requisites\` — реквизиты получателя

*Пример запроса:*
\`\`\`json
{
  "merchant_id": "your-id",
  "amount": 500.00,
  "currency": "rub",
  "payment_type": "sbp",
  "bank": 50,
  "requisites": "+79001234567",
  "callback_url": "https://example.com/cb"
}
\`\`\`

💡 Статус webhook придёт на \`callback\\_url\`
`,

  "📋 Заказы": `
📋 *Управление заказами (ордерами)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Список ордеров:*
\`GET /orders/list\`

Фильтры (query params):
   • \`filter[status]\` — new, opened, process, closed, canceled, expired, failed, wait, chargeback
   • \`filter[type]\` — deposit или credit
   • \`filter[currency]\` — rub, usdt и др.
   • \`filter[amount]\` — диапазон "100,200"
   • \`filter[created\\_at]\` — Unix timestamp диапазон
   • \`filter[search]\` — поиск по тексту
   • \`sort\` — сортировка (id, created\\_at, amount, status; "-" для DESC)

*Информация об ордере:*
\`GET /order/{id}\`

*Отмена ордера:*
\`DELETE /order/{id}\`

*Пример:*
\`\`\`
GET /orders/list?filter[status]=new&filter[type]=deposit&sort=-created_at
\`\`\`

*Ответ содержит пагинацию:*
\`meta.total\`, \`meta.current\\_page\`, \`meta.last\\_page\`
`,

  "🛒 E-commerce": `
🛒 *E-commerce платежи (3DS)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Полный flow:*

*1️⃣ Создание:*
\`POST /order/ecomm/create\`

*2️⃣ Подтверждение карты:*
\`POST /order/ecomm/{order}/confirm\`
\`\`\`json
{
  "card": "4111111111111111",
  "holder": "IVAN IVANOV",
  "expire": "12/25",
  "cvv": "123"
}
\`\`\`

*3️⃣ Ввод SMS-кода (3DS):*
\`POST /order/ecomm/{order}/code\`
\`\`\`json
{ "code": "123456" }
\`\`\`

*4️⃣ Сброс кода (если ошибка):*
\`POST /order/ecomm/{order}/reset\`

*Или всё в одном:*
\`POST /order/ecomm\`

💡 \`secondary\\_status\`: \`sms\\_code\\_required\` или \`push\\_code\\_required\`
`,

  "🔔 Webhooks": `
🔔 *Настройка Webhooks*
━━━━━━━━━━━━━━━━━━━━━

📥 *Требования к endpoint:*
   • Только HTTPS
   • Ответ 200 OK за < 5 сек
   • Доступен из интернета

🔑 *Авторизация:*
   ProcessingHub отправляет: \`Authorization: Bearer <token>\`

📦 *Пример webhook payload:*
\`\`\`json
{
  "id": "uuid",
  "number": 2507,
  "amount": 24304,
  "currency": "rub",
  "type": "deposit",
  "status": "closed",
  "payment_type": "c2c",
  "external_id": "your_id",
  "callback_url": "https://..."
}
\`\`\`

📊 *Статусы в webhook:*
   • \`new\` → создан
   • \`opened\` → открыт
   • \`process\` → в обработке
   • \`closed\` → успешно завершён
   • \`canceled\` → отменён
   • \`expired\` → просрочен
   • \`failed\` → ошибка

💡 Webhook приходит при каждой смене статуса
`,

  "📎 Аппилы": `
📎 *Аппилы (Support/Appeals)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Создать аппил:*
\`POST /support\`
\`\`\`json
{
  "description": "Описание проблемы",
  "title": "Заголовок",
  "order_id": "uuid ордера",
  "type": "appeal",
  "uploads": ["file-id-1"]
}
\`\`\`
Обязательно: \`description\`
Опционально: \`title\`, \`order\\_id\`, \`type\`, \`uploads\`

*Список аппилов:*
\`GET /supports\`
Фильтры: \`filter[status]\`, \`filter[type]\`, \`filter[order\\_id]\`, \`filter[merchant\\_id]\`

*Управление:*
   • \`GET /support/{id}\` — детали
   • \`PUT /support/{id}\` — обновить
   • \`DELETE /support/{id}\` — удалить
   • \`PUT /support/{id}/close\` — закрыть
   • \`PUT /support/{id}/decline\` — отклонить

*Резолюции:*
   • \`GET /support/{id}/resolutions\` — список
   • \`POST /support/{id}/resolution\` — добавить ответ
   • \`PUT /support/{id}/resolution/{rid}\` — изменить
   • \`DELETE /support/{id}/resolution/{rid}\` — удалить

💡 Загрузи файлы через \`POST /upload\`, затем передай ID в \`uploads\`
`,

  "💰 Баланс": `
💰 *Баланс и профиль*
━━━━━━━━━━━━━━━━━━━━

*Получить баланс:*
\`GET /balance\`

Возвращает балансы по всем валютам мерчанта.

*Профиль мерчанта:*
\`GET /profile\`

Возвращает данные аккаунта, подключённых мерчантов и настройки.

*Пример запроса:*
\`\`\`
curl -X GET https://api.example.com/api/balance \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Accept: application/json"
\`\`\`
`,

  "🏦 Банки": "SHOW_BANKS_MENU",

  "⚠️ Ошибки": `
⚠️ *HTTP коды и ошибки*
━━━━━━━━━━━━━━━━━━━━━━

🟢 *200* — Запрос выполнен
🟢 *201* — Ресурс создан

🔴 *401 Unauthorized*
   Неверный или отсутствующий Bearer токен
   ➜ Проверь заголовок \`Authorization: Bearer <key>\`

🔴 *403 Forbidden*
   Нет прав на операцию
   ➜ Проверь права мерчанта / IP whitelist

🔴 *409 Conflict*
   Логическая ошибка (дубликат, конфликт)
   ➜ Проверь \`external\\_id\` и параметры

🔴 *422 Validation Error*
   Ошибка валидации полей
   ➜ Проверь обязательные поля: merchant\\_id, amount, currency, payment\\_type, bank (ID банка — число)

🔴 *429 Too Many Requests*
   Превышен лимит 15 req/sec
   ➜ Добавь задержку между запросами

🔴 *500 / 502 / 504* — Ошибка сервера
   ➜ Повтори запрос через 5-10 сек

*Формат ошибки:*
\`\`\`json
{
  "status": 422,
  "message": "Validation error",
  "success": false,
  "errors": {
    "amount": ["The amount field is required."]
  }
}
\`\`\`

*Частые бизнес-ошибки:*
   • Невалидный \`bank\` → запроси \`GET /banks\`
   • Сумма вне лимитов → уточни у менеджера
   • Неверный \`merchant\\_id\` → проверь в \`GET /profile\`
   • \`callback\\_url\` недоступен → проверь HTTPS и 200 ответ

📸 Пришли скриншот ошибки — разберу детально!
`,

  "📸 Скриншот": `
📸 *Анализ скриншотов*
━━━━━━━━━━━━━━━━━━━━━

Пришли скриншот ошибки, и я:

✅ Определю тип ошибки
✅ Найду причину
✅ Подскажу решение

📱 *Что можно прислать:*
   • Ошибки в консоли
   • Ответы API (JSON)
   • Логи сервера
   • Скриншоты из Postman

👇 *Просто отправь изображение!*
`,

  "🔍 Валидатор": "SHOW_VALIDATOR",
  "🛠 Конструктор": "SHOW_CONSTRUCTOR",

  "📊 Статусы": `
📊 *Карта статусов ордеров*
━━━━━━━━━━━━━━━━━━━━━━━━━━

*Основной flow:*
\`new\` → \`opened\` → \`process\` → \`closed\` ✅

*Альтернативные исходы:*
\`new\` → \`canceled\` (отменён вручную)
\`new\` → \`expired\` (истёк таймаут)
\`process\` → \`failed\` (ошибка обработки)
\`process\` → \`wait\` (ожидание подтверждения)
\`closed\` → \`chargeback\` (возврат/оспаривание)

━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 *\`new\`* — ордер создан, ожидает обработки
📌 *\`opened\`* — ордер открыт, доступна форма оплаты
📌 *\`process\`* — платёж в обработке
✅ *\`closed\`* — успешно завершён
❌ *\`canceled\`* — отменён (\`DELETE /order/{id}\`)
⏰ *\`expired\`* — истёк срок оплаты
💥 *\`failed\`* — ошибка при обработке
⏳ *\`wait\`* — ожидание подтверждения
🔄 *\`chargeback\`* — возврат/оспаривание

*Secondary status (для e-commerce):*
   • \`sms\\_code\\_required\` — нужен SMS-код 3DS
   • \`push\\_code\\_required\` — нужен push-код

*Когда приходит webhook?*
   При каждой смене статуса на \`callback\\_url\`

*Финальные статусы (ордер закрыт):*
   \`closed\`, \`canceled\`, \`expired\`, \`failed\`, \`chargeback\`

💡 Проверяй статус через \`GET /order/{id}\`
`,

  "✅ Чеклист": `
✅ *Чеклист интеграции ProcessingHub*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Этап 1 — Подготовка:*
☐ Получить API-ключ от менеджера
☐ Настроить заголовки: \`Authorization: Bearer <key>\`
☐ Определить Base URL: dev или prod
☐ Получить \`merchant\\_id\` через \`GET /profile\`

*Этап 2 — Депозиты (Payin):*
☐ Реализовать \`POST /order/deposit\`
☐ Обработать \`redirect\\_url\` в ответе
☐ Протестировать создание ордера на dev

*Этап 3 — Webhooks:*
☐ Создать HTTPS endpoint для приёма webhook
☐ Передавать URL в \`callback\\_url\`
☐ Обрабатывать все статусы: closed, canceled, expired, failed, wait, chargeback
☐ Отвечать 200 OK за < 5 сек
☐ Верифицировать Bearer токен

*Этап 4 — Выплаты (Payout):*
☐ Реализовать \`POST /order/credit\`
☐ Передавать \`requisites\` получателя
☐ Обработать статусы выплаты

*Этап 5 — Управление ордерами:*
☐ Реализовать \`GET /orders/list\` с фильтрами
☐ Реализовать \`GET /order/{id}\` для проверки
☐ Реализовать \`DELETE /order/{id}\` для отмены

*Этап 6 — Обработка ошибок:*
☐ Обработать 401 (неверный токен)
☐ Обработать 422 (валидация полей)
☐ Обработать 429 (rate limit — макс 15 req/sec)
☐ Retry-логика для 500/502/504

*Этап 7 — Переход на прод:*
☐ Сменить URL: \`dev-api\` → \`api.example.com\`
☐ Получить prod API-ключ
☐ Обновить webhook URL на prod
☐ Проверить реальную транзакцию

💡 Задай вопрос по любому пункту!
`
};

// ─────────────────────────────────────────────────────────────
//  JSON Validator
// ─────────────────────────────────────────────────────────────

const ENDPOINT_SCHEMAS = {
  deposit: {
    endpoint: "POST /order/deposit",
    required: ["merchant_id", "amount", "currency", "payment_type", "bank"],
    optional: ["external_id", "callback_url", "requisites", "allow_change_amount", "allow_change_amount_value", "success_url", "failed_url"],
    types: { merchant_id: "string", amount: "number", currency: "string", payment_type: "string", bank: "number", allow_change_amount: "boolean", allow_change_amount_value: "number" }
  },
  credit: {
    endpoint: "POST /order/credit",
    required: ["merchant_id", "amount", "currency", "payment_type", "bank"],
    optional: ["external_id", "callback_url", "requisites", "allow_change_amount", "allow_change_amount_value", "success_url", "failed_url"],
    types: { merchant_id: "string", amount: "number", currency: "string", payment_type: "string", bank: "number", allow_change_amount: "boolean", allow_change_amount_value: "number" }
  },
  payout: {
    endpoint: "POST /order/payout",
    required: ["merchant_id", "amount", "currency", "payment_type", "bank"],
    optional: ["external_id", "callback_url", "requisites"],
    types: { merchant_id: "string", amount: "number", currency: "string", payment_type: "string", bank: "number" }
  },
  support: {
    endpoint: "POST /support",
    required: ["description"],
    optional: ["title", "order_id", "type", "uploads"],
    types: { description: "string", title: "string", order_id: "string", type: "string" }
  },
  ecomm_confirm: {
    endpoint: "POST /order/ecomm/{order}/confirm",
    required: ["card", "holder", "expire", "cvv"],
    optional: [],
    types: { card: "string", holder: "string", expire: "string", cvv: "string" }
  }
};

const VALID_CURRENCIES = ["rub", "azn", "kgs", "tjs", "usdt", "bob", "krw"];
const VALID_PAYMENT_TYPES = ["sbp", "c2c", "sng_sbp", "sng_c2c", "qr_pay", "nspk", "sim", "sber", "tbank", "alfa", "ozon", "vtb", "psb", "gazprom", "yandex", "quasi-ecomm", "sber-invoice", "alfa-invoice"];

function validateJson(jsonStr) {
  let parsed;
  try {
    parsed = JSON.parse(jsonStr);
  } catch (e) {
    return { ok: false, errors: [`JSON parse error: ${e.message}`], parsed: null, detectedType: null };
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { ok: false, errors: ["Ожидается JSON объект {}"], parsed: null, detectedType: null };
  }

  // Auto-detect endpoint type
  let detectedType = null;
  const keys = Object.keys(parsed);

  if (parsed.card || parsed.cvv || parsed.holder) {
    detectedType = "ecomm_confirm";
  } else if (parsed.description && !parsed.payment_type) {
    detectedType = "support";
  } else if (parsed.payment_type && parsed.amount) {
    detectedType = "deposit"; // could be credit/payout too, same schema
  }

  if (!detectedType) {
    return { ok: true, errors: [], warnings: ["Не удалось определить тип запроса. Убедись, что JSON содержит нужные поля."], parsed, detectedType: null };
  }

  const schema = ENDPOINT_SCHEMAS[detectedType];
  const errors = [];
  const warnings = [];

  // Check required fields
  for (const field of schema.required) {
    if (!(field in parsed)) {
      errors.push(`Отсутствует обязательное поле: \`${field}\``);
    } else if (parsed[field] === "" || parsed[field] === null) {
      errors.push(`Поле \`${field}\` не может быть пустым`);
    }
  }

  // Check types
  for (const [field, expectedType] of Object.entries(schema.types)) {
    if (field in parsed && parsed[field] !== null && parsed[field] !== undefined) {
      const actualType = typeof parsed[field];
      if (actualType !== expectedType) {
        errors.push(`Поле \`${field}\`: ожидается ${expectedType}, получено ${actualType}`);
      }
    }
  }

  // Check unknown fields
  const allKnown = [...schema.required, ...schema.optional];
  for (const key of keys) {
    if (!allKnown.includes(key)) {
      warnings.push(`Неизвестное поле: \`${key}\``);
    }
  }

  // Business validation
  if (parsed.currency && !VALID_CURRENCIES.includes(String(parsed.currency).toLowerCase())) {
    warnings.push(`Валюта \`${parsed.currency}\` не из списка: ${VALID_CURRENCIES.join(", ")}`);
  }
  if (parsed.payment_type && !VALID_PAYMENT_TYPES.includes(String(parsed.payment_type).toLowerCase())) {
    warnings.push(`Метод \`${parsed.payment_type}\` не из списка: ${VALID_PAYMENT_TYPES.join(", ")}`);
  }
  if (parsed.amount !== undefined && (typeof parsed.amount !== "number" || parsed.amount <= 0)) {
    errors.push("`amount` должен быть положительным числом");
  }
  if (parsed.expire && !/^\d{2}\/\d{2}$/.test(parsed.expire)) {
    errors.push("`expire` должен быть в формате MM/YY");
  }
  if (parsed.cvv && !/^\d{3}$/.test(parsed.cvv)) {
    errors.push("`cvv` должен быть 3 цифры");
  }
  if (parsed.callback_url && !parsed.callback_url.startsWith("https://")) {
    warnings.push("`callback_url` должен начинаться с https://");
  }
  // Validate bank against real API list (bank = ID банка, число)
  if (parsed.bank !== undefined && banksCache.length > 0) {
    const bankId = Number(parsed.bank);
    if (isNaN(bankId) || !Number.isInteger(bankId)) {
      errors.push(`\`bank\` должен быть числом (ID банка). Получить список: GET /banks`);
    } else {
      const found = banksCache.find(b => b.id === bankId);
      if (!found) {
        const currency = parsed.currency ? String(parsed.currency).toLowerCase() : null;
        const available = currency ? getBanksForCurrency(currency).slice(0, 5).map(b => `${b.name} (id: ${b.id})`) : [];
        const hint = available.length > 0 ? ` Доступные для ${currency}: ${available.join(", ")}` : "";
        errors.push(`Банк с id=${bankId} не найден.${hint}`);
      } else if (parsed.currency) {
        const cur = String(parsed.currency).toLowerCase();
        if (found.currency !== cur) {
          warnings.push(`Банк \`${found.name}\` (id: ${found.id}) привязан к валюте \`${found.currency}\`, а в запросе \`${cur}\``);
        }
      }
    }
  }

  return { ok: errors.length === 0, errors, warnings, parsed, detectedType };
}

// ─────────────────────────────────────────────────────────────
//  Constructor: inline keyboards
// ─────────────────────────────────────────────────────────────

const constructorTypeMenu = Markup.inlineKeyboard([
  [Markup.button.callback("📥 Депозит (deposit)", "ctr_type_deposit")],
  [Markup.button.callback("📤 Выплата (credit)", "ctr_type_credit")],
  [Markup.button.callback("📤 Выплата (payout)", "ctr_type_payout")],
  [Markup.button.callback("❌ Отмена", "ctr_cancel")]
]);

const constructorCurrencyMenu = Markup.inlineKeyboard([
  [
    Markup.button.callback("RUB", "ctr_cur_rub"),
    Markup.button.callback("AZN", "ctr_cur_azn"),
    Markup.button.callback("KGS", "ctr_cur_kgs")
  ],
  [
    Markup.button.callback("TJS", "ctr_cur_tjs"),
    Markup.button.callback("USDT", "ctr_cur_usdt")
  ],
  [
    Markup.button.callback("BOB", "ctr_cur_bob"),
    Markup.button.callback("KRW", "ctr_cur_krw")
  ],
  [Markup.button.callback("❌ Отмена", "ctr_cancel")]
]);

const constructorPaymentMenu = Markup.inlineKeyboard([
  [
    Markup.button.callback("SBP", "ctr_pay_sbp"),
    Markup.button.callback("C2C", "ctr_pay_c2c"),
    Markup.button.callback("SNG SBP", "ctr_pay_sng_sbp")
  ],
  [
    Markup.button.callback("SNG C2C", "ctr_pay_sng_c2c"),
    Markup.button.callback("QR Pay", "ctr_pay_qr_pay"),
    Markup.button.callback("NSPK", "ctr_pay_nspk")
  ],
  [
    Markup.button.callback("Sber", "ctr_pay_sber"),
    Markup.button.callback("Tbank", "ctr_pay_tbank"),
    Markup.button.callback("Alfa", "ctr_pay_alfa")
  ],
  [
    Markup.button.callback("Ozon", "ctr_pay_ozon"),
    Markup.button.callback("VTB", "ctr_pay_vtb"),
    Markup.button.callback("PSB", "ctr_pay_psb")
  ],
  [
    Markup.button.callback("Gazprom", "ctr_pay_gazprom"),
    Markup.button.callback("Yandex", "ctr_pay_yandex"),
    Markup.button.callback("SIM", "ctr_pay_sim")
  ],
  [Markup.button.callback("❌ Отмена", "ctr_cancel")]
]);

// Constructor callback handlers
bot.action(/^ctr_type_(.+)$/, async (ctx) => {
  const type = ctx.match[1];
  const tgId = Number(ctx.from?.id || 0);
  userState.set(tgId, { mode: "constructor", step: "currency", type });
  await ctx.editMessageText(
    `🛠 *Конструктор запроса*\n━━━━━━━━━━━━━━━━━━━━\n\n` +
    `Тип: *${type}*\n\n` +
    `Выбери валюту:`,
    { parse_mode: "Markdown", ...constructorCurrencyMenu }
  );
  ctx.answerCbQuery();
});

bot.action(/^ctr_cur_(.+)$/, async (ctx) => {
  const currency = ctx.match[1];
  const tgId = Number(ctx.from?.id || 0);
  const state = userState.get(tgId);
  if (!state || state.mode !== "constructor") return ctx.answerCbQuery("Сессия истекла");
  state.currency = currency;
  state.step = "payment_type";
  await ctx.editMessageText(
    `🛠 *Конструктор запроса*\n━━━━━━━━━━━━━━━━━━━━\n\n` +
    `Тип: *${state.type}*\nВалюта: *${currency.toUpperCase()}*\n\n` +
    `Выбери платёжный метод:`,
    { parse_mode: "Markdown", ...constructorPaymentMenu }
  );
  ctx.answerCbQuery();
});

bot.action(/^ctr_pay_(.+)$/, async (ctx) => {
  const paymentType = ctx.match[1];
  const tgId = Number(ctx.from?.id || 0);
  const state = userState.get(tgId);
  if (!state || state.mode !== "constructor") return ctx.answerCbQuery("Сессия истекла");
  state.payment_type = paymentType;
  state.step = "amount";
  const availBanks = getBanksForCurrency(state.currency).slice(0, 10).map(b => `${b.name} (id: ${b.id})`);
  const bankHint = availBanks.length > 0 ? `\n\n*Банки (${state.currency.toUpperCase()}):*\n${availBanks.join("\n")}` : "";
  await ctx.editMessageText(
    `🛠 *Конструктор запроса*\n━━━━━━━━━━━━━━━━━━━━\n\n` +
    `Тип: *${state.type}*\nВалюта: *${state.currency.toUpperCase()}*\nМетод: *${paymentType}*\n\n` +
    `Введи сумму и ID банка через пробел:\n` +
    `Например: \`1000 46\`` +
    bankHint + `\n\nИли /cancel для отмены`,
    { parse_mode: "Markdown" }
  );
  ctx.answerCbQuery();
});

bot.action("ctr_cancel", async (ctx) => {
  const tgId = Number(ctx.from?.id || 0);
  userState.delete(tgId);
  await ctx.editMessageText("❌ Конструктор отменён");
  ctx.answerCbQuery();
});

bot.command("cancel", async (ctx) => {
  const tgId = Number(ctx.from?.id || 0);
  if (adminState.has(tgId)) {
    adminState.delete(tgId);
  }
  if (userState.has(tgId)) {
    userState.delete(tgId);
  }
  const keyboard = isAdmin(ctx) ? adminKeyboard : mainKeyboard;
  ctx.reply("❌ Отменено", keyboard);
});

bot.on("text", async (ctx) => {
  const raw = ctx.message.text.trim();
  console.log(`[Text] from=${ctx.from?.id} raw="${raw}"`);

  if (!raw || raw.startsWith("/")) return;

  // Handle admin training state
  const tgId = Number(ctx.from?.id || 0);
  if (adminState.get(tgId) === "awaiting_qa" && isAdmin(ctx)) {
    adminState.delete(tgId);

    // Парсим формат "Вопрос: ...\nОтвет: ..."
    const qMatch = raw.match(/(?:^|\n)\s*(?:вопрос|q)\s*[:：]\s*(.+)/i);
    const aMatch = raw.match(/(?:^|\n)\s*(?:ответ|a)\s*[:：]\s*([\s\S]+)/i);

    if (!qMatch || !aMatch) {
      await ctx.reply(
        "❌ Неверный формат. Используй:\n\n" +
        "`Вопрос: текст вопроса`\n" +
        "`Ответ: текст ответа`\n\n" +
        "Попробуй ещё раз через админ панель → Обучение бота",
        { parse_mode: "Markdown" }
      );
      return;
    }

    const question = qMatch[1].trim();
    let answer = aMatch[1].trim();
    // Убираем "Ответ:" если вопрос захватил часть ответа
    answer = answer.replace(/^(?:вопрос|q)\s*[:：].*/im, "").trim();

    try {
      await ctx.reply("⏳ Сохраняю и генерирую embedding...");
      const knowledgeId = await addKnowledgeWithEmbedding(question, answer, tgId);
      await ctx.reply(
        `✅ *Знание #${knowledgeId} добавлено!*\n\n` +
        `❓ *Вопрос:* ${question}\n` +
        `💡 *Ответ:* ${answer}\n\n` +
        `Бот теперь будет использовать это при ответах.`,
        { parse_mode: "Markdown" }
      );
    } catch (err) {
      console.error("[Training Error]", err);
      await ctx.reply("❌ Ошибка при сохранении. Попробуй ещё раз.");
    }
    return;
  }

  // Handle user state (validator / constructor)
  const uState = userState.get(tgId);
  if (uState) {
    // Validator: awaiting JSON
    if (uState.mode === "awaiting_json") {
      userState.delete(tgId);
      const result = validateJson(raw);
      let reply = "";

      if (result.parsed === null) {
        reply = `❌ *Ошибка парсинга JSON*\n━━━━━━━━━━━━━━━━━━━━\n\n${result.errors.map(e => `• ${e}`).join("\n")}\n\n💡 Убедись, что отправляешь валидный JSON`;
      } else {
        const typeLabel = result.detectedType ? `Определён как: *${ENDPOINT_SCHEMAS[result.detectedType]?.endpoint || result.detectedType}*` : "⚠️ Тип запроса не определён";
        reply = `🔍 *Результат валидации*\n━━━━━━━━━━━━━━━━━━━━\n\n${typeLabel}\n`;

        if (result.errors.length > 0) {
          reply += `\n❌ *Ошибки (${result.errors.length}):*\n${result.errors.map(e => `   • ${e}`).join("\n")}\n`;
        }
        if (result.warnings && result.warnings.length > 0) {
          reply += `\n⚠️ *Предупреждения:*\n${result.warnings.map(w => `   • ${w}`).join("\n")}\n`;
        }
        if (result.ok && result.errors.length === 0) {
          reply += `\n✅ *JSON валиден!* Запрос готов к отправке.`;
        }
      }
      return ctx.reply(reply, { parse_mode: "Markdown" });
    }

    // Constructor: awaiting amount + bank ID
    if (uState.mode === "constructor" && uState.step === "amount") {
      const parts = raw.split(/\s+/);
      const amount = parseFloat(parts[0]);

      if (isNaN(amount) || amount <= 0) {
        return ctx.reply("❌ Неверная сумма. Введи число больше 0.\nНапример: `1000 46`\n\nПопробуй ещё раз или /cancel для отмены", { parse_mode: "Markdown" });
      }

      const bankId = parts[1] ? parseInt(parts[1]) : null;
      if (bankId !== null && (isNaN(bankId) || bankId <= 0)) {
        return ctx.reply("❌ ID банка должен быть числом.\nНапример: `1000 46` (Сбербанк)\n\nПопробуй ещё раз или /cancel для отмены", { parse_mode: "Markdown" });
      }

      // Validate bank exists
      const finalBankId = bankId || 46;
      const bankInfo = banksCache.find(b => b.id === finalBankId);
      if (!bankInfo) {
        return ctx.reply(`❌ Банк с id=${finalBankId} не найден.\nПроверь ID через кнопку 🏦 Банки или напиши валюту (rub, azn)\n\nПопробуй ещё раз или /cancel для отмены`, { parse_mode: "Markdown" });
      }

      // Check bank currency matches selected currency
      const selectedCur = uState.currency.toLowerCase();
      if (bankInfo.currency !== selectedCur) {
        return ctx.reply(`⚠️ Банк *${bankInfo.name}* (id: ${bankInfo.id}) привязан к валюте *${bankInfo.currency.toUpperCase()}*, а ты выбрал *${selectedCur.toUpperCase()}*.\n\nВведи ID банка для ${selectedCur.toUpperCase()} или /cancel`, { parse_mode: "Markdown" });
      }

      userState.delete(tgId);

      const body = {
        merchant_id: "YOUR_MERCHANT_ID",
        amount,
        currency: uState.currency,
        payment_type: uState.payment_type,
        bank: finalBankId,
        external_id: "your-unique-id",
        callback_url: "https://your-site.com/webhook"
      };

      if (uState.type === "credit" || uState.type === "payout") {
        body.requisites = "+79001234567";
      }

      const endpoint = uState.type === "payout" ? "/order/payout" : uState.type === "credit" ? "/order/credit" : "/order/deposit";
      const jsonStr = JSON.stringify(body, null, 2);
      const bankLabel = `${bankInfo.name} (id: ${bankInfo.id})`;

      const reply =
        `✅ *Готовый запрос*\n━━━━━━━━━━━━━━━━━━━━\n\n` +
        `*Endpoint:* \`POST ${endpoint}\`\n` +
        `*Банк:* ${bankLabel}\n\n` +
        `*JSON body:*\n\`\`\`json\n${jsonStr}\n\`\`\`\n\n` +
        `*curl:*\n\`\`\`\ncurl -X POST https://sandbox-api.example.com/api${endpoint} \\\n` +
        `  -H "Authorization: Bearer YOUR_API_KEY" \\\n` +
        `  -H "Content-Type: application/json" \\\n` +
        `  -d '${JSON.stringify(body)}'\n\`\`\`\n\n` +
        `💡 Замени \`YOUR_MERCHANT_ID\`, \`YOUR_API_KEY\` и \`callback\\_url\` на свои значения`;

      return ctx.reply(reply, { parse_mode: "Markdown" });
    }
  }

  // Handle keyboard buttons
  if (BUTTON_CONTENT[raw]) {
    if (BUTTON_CONTENT[raw] === "SHOW_DOCS_MENU") {
      return ctx.reply(
        "📚 *Документация ProcessingHub API*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыбери раздел — откроется прямая ссылка:",
        { parse_mode: "Markdown", ...docsMenu }
      );
    }
    if (BUTTON_CONTENT[raw] === "SHOW_ADMIN_MENU") {
      if (!isAdmin(ctx)) return ctx.reply("⛔ Нет доступа");
      return ctx.reply(
        "━━━━━━━━━━━━━━━━━━━━\n" +
        "       ⚙️  *Админ панель*\n" +
        "━━━━━━━━━━━━━━━━━━━━",
        { parse_mode: "Markdown", ...adminMenu }
      );
    }
    if (BUTTON_CONTENT[raw] === "SHOW_VALIDATOR") {
      userState.set(tgId, { mode: "awaiting_json" });
      return ctx.reply(
        "🔍 *Валидатор запросов*\n━━━━━━━━━━━━━━━━━━━━\n\n" +
        "Отправь JSON тело запроса, и я проверю:\n\n" +
        "✅ Обязательные поля\n" +
        "✅ Типы данных\n" +
        "✅ Валюты и методы оплаты\n" +
        "✅ Формат полей (expire, cvv, URL)\n\n" +
        "Автоматически определю тип запроса:\n" +
        "deposit, credit, payout, support, ecomm\n\n" +
        "*Пример:*\n" +
        "```json\n" +
        '{"merchant_id":"xxx","amount":1000,"currency":"rub","payment_type":"sbp","bank":46}\n' +
        "```\n\n" +
        "Или /cancel для отмены",
        { parse_mode: "Markdown" }
      );
    }
    if (BUTTON_CONTENT[raw] === "SHOW_CONSTRUCTOR") {
      return ctx.reply(
        "🛠 *Конструктор запроса*\n━━━━━━━━━━━━━━━━━━━━\n\n" +
        "Выбери тип операции:",
        { parse_mode: "Markdown", ...constructorTypeMenu }
      );
    }
    if (BUTTON_CONTENT[raw] === "SHOW_BANKS_MENU") {
      const currencies = Object.keys(banksByCurrency).sort();
      let text = "🏦 *Банки и платёжные методы*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n";
      text += `Всего банков: *${banksCache.length}*\n\n`;

      for (const cur of currencies) {
        const banks = banksByCurrency[cur];
        const names = banks.slice(0, 6).map(b => `${b.name} (${b.id})`).join(", ");
        const more = banks.length > 6 ? ` и ещё ${banks.length - 6}` : "";
        text += `*${cur.toUpperCase()}* (${banks.length}): ${names}${more}\n\n`;
      }

      text += "*Платёжные методы (\\`payment\\_type\\`):*\n";
      text += "   • \\`sbp\\` — СБП\n   • \\`c2c\\` — карта на карту\n   • \\`sng\\_sbp\\` — СБП СНГ\n";
      text += "   • \\`qr\\_pay\\` — QR НСПК\n   • \\`sber\\` / \\`tbank\\` / \\`alfa\\` — внутрибанк\n\n";
      text += "💡 Напиши валюту (например `rub` или `azn`) — покажу полный список банков с ID";

      return ctx.reply(text, { parse_mode: "Markdown" });
    }
    return ctx.reply(BUTTON_CONTENT[raw], { parse_mode: "Markdown" });
  }

  // Intercept currency codes → show banks list
  const lowerRaw = raw.toLowerCase().trim();
  if (banksByCurrency[lowerRaw]) {
    console.log(`[Banks] Currency intercept: "${lowerRaw}"`);
    const banks = banksByCurrency[lowerRaw];
    let text = `🏦 <b>Банки для ${lowerRaw.toUpperCase()}</b> (${banks.length}):\n━━━━━━━━━━━━━━━━━━━━\n\n`;
    banks.forEach((b, i) => {
      const name = b.name.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      text += `${i + 1}. ${name} — <b>id: ${b.id}</b>\n`;
    });
    text += `\n💡 Используй <b>id</b> банка в поле <code>"bank"</code> при создании ордера`;
    return ctx.reply(text, { parse_mode: "HTML" });
  }

  await ctx.sendChatAction("typing");

  const answer = await enqueue(async () => {
    let ragContext = "";
    try {
      const contexts = await withTimeout(retrieveContexts(raw, 5), 20000);
      if (contexts.length) {
        ragContext = contexts.map(c => c.content).join("\n\n");
      }
    } catch {}

    // Get conversation history
    const history = getContext(tgId);

    const messages = [
      {
        role: "system",
        content: `Ты — техподдержка ProcessingHub API. Отвечай СТРОГО на основе фактов ниже.

⚠️ КРИТИЧЕСКИЕ ПРАВИЛА:
1. НИКОГДА не придумывай информацию. Если не знаешь точный ответ — скажи: "Точной информации у меня нет, уточни у своего менеджера ProcessingHub."
2. НЕ выдумывай параметры, эндпоинты, статусы или поведение API, которых нет в этом справочнике.
3. Отвечай КОНКРЕТНО: с примерами кода/JSON, указывай обязательные и опциональные поля.
4. Без воды, без обобщений, без "обычно" или "как правило" — только точные факты.
5. Если вопрос не про ProcessingHub API — вежливо скажи, что отвечаешь только по API.

━━━ СПРАВОЧНИК API v1.25.22 ━━━

BASE URLs:
• Dev: https://sandbox-api.example.com/api
• Prod: https://api.example.com/api

АВТОРИЗАЦИЯ:
• Заголовок: Authorization: Bearer <API_KEY>
• Также обязательно: Content-Type: application/json, Accept: application/json
• Webhooks от ProcessingHub приходят с Bearer Token в заголовке Authorization

ENDPOINTS:
Депозиты:    POST /order/deposit
Выплаты:     POST /order/credit | POST /order/payout
Заказы:      GET /orders/list | GET /order/{id} | DELETE /order/{id}
E-commerce:  POST /order/ecomm/create | POST /order/ecomm/{order}/confirm | POST /order/ecomm/{order}/code | POST /order/ecomm/{order}/reset | POST /order/ecomm
Аккаунт:     GET /balance | GET /profile
Файлы:       POST /upload
Банки:       GET /banks
Аппилы:      POST /support | GET /supports | GET /support/{id} | PUT /support/{id} | DELETE /support/{id} | PUT /support/{id}/close | PUT /support/{id}/decline
Резолюции:   GET /support/{id}/resolutions | POST /support/{id}/resolution | PUT /support/{id}/resolution/{rid} | DELETE /support/{id}/resolution/{rid}

СТАТУСЫ ОРДЕРОВ: new, opened, process, closed, canceled, expired, failed, wait, chargeback
SECONDARY_STATUS: sms_code_required, push_code_required

ПЛАТЁЖНЫЕ МЕТОДЫ: sbp, c2c, sng_sbp, sng_c2c, qr_pay, nspk, sim, sber, tbank, alfa, ozon, vtb, psb, gazprom, yandex, quasi-ecomm, sber-invoice, alfa-invoice
ВАЛЮТЫ: RUB, AZN, KGS, TJS, USDT, BOB, KRW
ЛИМИТ: 15 req/sec с одного IP

ОБЯЗАТЕЛЬНЫЕ ПОЛЯ deposit/credit:
merchant_id (string), amount (number), currency (string), payment_type (string), bank (number — ID банка из GET /banks)

ВАЖНО: поле bank — это числовой ID банка, НЕ название. Список банков: GET /banks → [{id, name, currency}]. Пример: "bank": 46 (Сбербанк), "bank": 50 (Тинькофф).

ОПЦИОНАЛЬНЫЕ ПОЛЯ deposit/credit:
external_id, callback_url, requisites, allow_change_amount, allow_change_amount_value, success_url, failed_url

DOCS:
• Главная: https://docs.example.com/docs
• Начало: https://docs.example.com/docs/getting-started
• Депозит: https://docs.example.com/docs/payin/create
• Выплата: https://docs.example.com/docs/payout/create
• Список ордеров: https://docs.example.com/docs/orders/list
• Инфо ордера: https://docs.example.com/docs/orders/info
• Отмена ордера: https://docs.example.com/docs/orders/cancel
• E-comm создать: https://docs.example.com/docs/ecomm/create
• E-comm подтвердить: https://docs.example.com/docs/ecomm/confirm
• E-comm код: https://docs.example.com/docs/orders/confirm-code
• E-comm сброс: https://docs.example.com/docs/ecomm/code-reset
• Баланс: https://docs.example.com/docs/account/balance
• Профиль: https://docs.example.com/docs/account/profile
• Банки: https://docs.example.com/docs/banks
• Загрузка файлов: https://docs.example.com/docs/files/upload
• Аппилы список: https://docs.example.com/docs/support/list
• Аппил создать: https://docs.example.com/docs/support/create
• Аппил инфо: https://docs.example.com/docs/support/info
• Аппил закрыть: https://docs.example.com/docs/support/close

${ragContext ? `КОНТЕКСТ ИЗ ДОКУМЕНТАЦИИ (может содержать неточности — используй ТОЛЬКО если совпадает с фактами выше):\n${ragContext}` : ""}`
      },
      ...history,
      { role: "user", content: raw }
    ];

    try {
      const resp = await withTimeout(
        client.chat.completions.create({
          model: CHAT_MODEL,
          messages,
          max_tokens: 1500,
          temperature: 0.1,
        }),
        35000
      );
      const assistantReply = resp.choices[0]?.message?.content || "Не удалось сформировать ответ.";

      // Save to context
      addToContext(tgId, "user", raw);
      addToContext(tgId, "assistant", assistantReply);

      return assistantReply;
    } catch (err) {
      console.error("[OpenAI Error]", err);
      return "❌ Ошибка при обработке запроса. Попробуй ещё раз.";
    }
  });

  // Добавляем релевантные ссылки на документацию
  const relevantLinks = findRelevantLinks(raw);
  const linksText = formatLinksForReply(relevantLinks);

  ctx.reply(answer + linksText, { parse_mode: "Markdown", disable_web_page_preview: true });
});

// ─────────────────────────────────────────────────────────────
//  Launch
// ─────────────────────────────────────────────────────────────

const WEBHOOK_DOMAIN = process.env.WEBHOOK_DOMAIN;
const PORT = process.env.PORT || 3000;

// Initialize DB tables before launch
async function startBot() {
  await initPgTables();
  await initKnowledgeDb();
  await loadBanks();

  if (USE_PG) {
    console.log("🐘 Используется Postgres");
  } else {
    console.log("📦 Используется SQLite (локально)");
  }

  if (WEBHOOK_DOMAIN) {
    bot.launch({
      webhook: {
        domain: WEBHOOK_DOMAIN,
        port: PORT,
        hookPath: "/webhook"
      }
    });
    console.log(`🤖 ProcessingHub Tech Support Bot запущен в webhook режиме`);
    console.log(`📡 Webhook URL: ${WEBHOOK_DOMAIN}/webhook`);
    console.log(`🔌 Port: ${PORT}`);
  } else {
    bot.launch();
    console.log("🤖 ProcessingHub Tech Support Bot запущен в polling режиме");
  }
}

startBot().catch(err => {
  console.error("❌ Ошибка запуска:", err);
  process.exit(1);
});

// Graceful shutdown
async function shutdown(signal) {
  console.log(`\n⚠️ Получен сигнал ${signal}, завершаем работу...`);

  // Wait for queue to finish
  let attempts = 0;
  while (queue.length > 0 && attempts < 50) {
    console.log(`⏳ Ожидаем завершения ${queue.length} задач...`);
    await new Promise(r => setTimeout(r, 100));
    attempts++;
  }

  await bot.stop(signal);
  console.log("✅ Бот остановлен");
  process.exit(0);
}

process.once("SIGINT", () => shutdown("SIGINT"));
process.once("SIGTERM", () => shutdown("SIGTERM"));
