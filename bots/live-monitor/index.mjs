import "dotenv/config";
import { Telegraf, Markup } from "telegraf";
import fs from "fs";

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const ADMIN_TG_IDS = (process.env.ADMIN_TG_ID || "").split(",").map(id => id.trim()).filter(Boolean);

// Metabase конфигурация
const METABASE_URL = process.env.METABASE_URL || "https://metabase.example.com";
const METABASE_EMAIL = process.env.METABASE_EMAIL;
const METABASE_PASSWORD = process.env.METABASE_PASSWORD;

const CONFIG = {
  KEYS_FILE: "keys.json",
  DATA_FILE: "data.json",
  ONLINE_INTERVAL: 15, // минут - считать онлайн
};

const bot = new Telegraf(BOT_TOKEN);

// Хранилище данных
let cachedData = null;
let lastUpdate = null;
let metabaseSession = null;
let postgresDbId = null;

// ============ METABASE API ============

async function getMetabaseSession(forceRefresh = false) {
  if (metabaseSession && !forceRefresh) return metabaseSession;

  metabaseSession = null;

  const response = await fetch(`${METABASE_URL}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: METABASE_EMAIL,
      password: METABASE_PASSWORD
    })
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'No error body');
    console.error(`❌ Metabase auth failed: ${response.status} - ${errorText}`);
    throw new Error(`Metabase auth failed: ${response.status}`);
  }

  const data = await response.json();
  metabaseSession = data.id;
  console.log("✅ Metabase авторизация успешна");
  return metabaseSession;
}

async function getPostgresDbId(_retry = false) {
  if (postgresDbId && !_retry) return postgresDbId;

  const session = await getMetabaseSession();
  const dbResponse = await fetch(`${METABASE_URL}/api/database`, {
    headers: { "X-Metabase-Session": session }
  });

  // Если сессия протухла — обновить и повторить
  if (dbResponse.status === 401 && !_retry) {
    console.log("🔄 Сессия истекла (db), обновляю...");
    await getMetabaseSession(true);
    return getPostgresDbId(true);
  }

  if (!dbResponse.ok) {
    const errorText = await dbResponse.text().catch(() => "");
    throw new Error(`Database list failed: ${dbResponse.status} ${errorText.slice(0, 200)}`);
  }

  const result = await dbResponse.json();

  // API может вернуть { data: [...] } или просто массив
  const databases = Array.isArray(result) ? result : (result.data || []);

  console.log("📊 Доступные базы:", databases.map(d => d.name).join(", "));

  // Ищем Main DB (PostgreSQL)
  let db = databases.find(d =>
    d.name && d.name.includes("PC") && d.name.toLowerCase().includes("base")
  );

  if (!db) {
    // Fallback - любой postgres
    db = databases.find(d =>
      d.engine && d.engine === "postgres"
    );
  }

  if (!db) {
    throw new Error("PostgreSQL database not found. Available: " + databases.map(d => `${d.name}(${d.engine})`).join(", "));
  }

  console.log("✅ Используем базу:", db.name, "ID:", db.id);
  postgresDbId = db.id;
  return postgresDbId;
}

async function executeQuery(sql, _retry = false) {
  const session = await getMetabaseSession();
  const dbId = await getPostgresDbId();

  // Используем POST к /api/dataset с native query
  const response = await fetch(`${METABASE_URL}/api/dataset`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Metabase-Session": session
    },
    body: JSON.stringify({
      database: dbId,
      type: "native",
      native: {
        query: sql,
        "template-tags": {}
      },
      parameters: []
    })
  });

  // Если сессия протухла — обновить и повторить
  if (response.status === 401 && !_retry) {
    console.log("🔄 Сессия истекла, обновляю...");
    await getMetabaseSession(true);
    return executeQuery(sql, true);
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(`Query failed: ${response.status} ${errorText.slice(0, 200)}`);
  }

  const result = await response.json();

  if (result.error) {
    console.error("Query error:", result.error);
    throw new Error(result.error);
  }

  if (!result.data || !result.data.rows) {
    console.error("No data in result:", JSON.stringify(result).slice(0, 200));
    throw new Error("No data returned");
  }

  // Преобразуем в удобный формат
  const columns = result.data.cols.map(c => c.name);
  return result.data.rows.map(row => {
    const obj = {};
    columns.forEach((col, i) => obj[col] = row[i]);
    return obj;
  });
}

// ============ SQL ЗАПРОСЫ ============

// FIX: Allowed intervals whitelist (prevents SQL injection)
const ALLOWED_INTERVALS = {
  "15 minutes": "15 minutes",
  "24 hours": "24 hours",
  "1 hour": "1 hour",
  "6 hours": "6 hours",
};

function getMethodsSummarySQL(intervalKey) {
  const interval = ALLOWED_INTERVALS[intervalKey];
  if (!interval) throw new Error(`Invalid interval: ${intervalKey}`);

  // Note: user_id and payment_id are NULL in current DB schema.
  // Traders/requisites counted via requisites JSON field (filled when order gets a requisite).
  return `
    SELECT
      payment_type AS method,
      COUNT(DISTINCT requisites::jsonb->>'requisites') AS requisites_count,
      COUNT(*) AS orders_count,
      COUNT(*) FILTER (WHERE status = 'closed') AS successful,
      COUNT(*) FILTER (WHERE status IN ('process', 'closed', 'dispute')) AS issued,
      ROUND(
        COUNT(*) FILTER (WHERE status = 'closed') * 100.0
        / NULLIF(COUNT(*) FILTER (WHERE status IN ('process', 'closed', 'dispute')), 0),
        1
      ) AS conversion,
      ROUND(SUM(amount) FILTER (WHERE status = 'closed'), 0) AS volume
    FROM orders
    WHERE created_at >= NOW() - INTERVAL '${interval}'
      AND type = 'deposit'
      AND status != 'deleted'
    GROUP BY payment_type
    ORDER BY orders_count DESC
  `;
}

function getTotalSummarySQL(intervalKey) {
  const interval = ALLOWED_INTERVALS[intervalKey];
  if (!interval) throw new Error(`Invalid interval: ${intervalKey}`);

  return `
    SELECT
      COUNT(*) AS total_orders,
      COUNT(DISTINCT requisites::jsonb->>'requisites') AS total_requisites,
      COUNT(*) FILTER (WHERE status = 'closed') AS total_successful,
      COUNT(*) FILTER (WHERE status IN ('process', 'closed', 'dispute')) AS total_issued,
      ROUND(SUM(amount) FILTER (WHERE status = 'closed'), 0) AS total_volume
    FROM orders
    WHERE created_at >= NOW() - INTERVAL '${interval}'
      AND type = 'deposit'
      AND status != 'deleted'
  `;
}

// Real online requisites: from actual orders in the interval, joined to payments for limits/trader
function getActiveRequisitesSQL(intervalKey) {
  const interval = ALLOWED_INTERVALS[intervalKey];
  if (!interval) throw new Error(`Invalid interval: ${intervalKey}`);

  return `
    WITH active_reqs AS (
      SELECT payment_type,
        REPLACE(requisites::jsonb->>'requisites', ' ', '') AS req_clean,
        (ARRAY_AGG(exchange_platform_id) FILTER (WHERE exchange_platform_id IS NOT NULL))[1] AS ep_id
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '${interval}'
        AND type = 'deposit' AND status != 'deleted'
        AND requisites IS NOT NULL AND requisites != '' AND requisites != '{}'
        AND requisites::jsonb->>'requisites' IS NOT NULL
      GROUP BY payment_type, REPLACE(requisites::jsonb->>'requisites', ' ', '')
    )
    SELECT
      ar.payment_type AS method,
      COUNT(*) AS requisites_count,
      MIN(COALESCE(p.deposit_order_min_amount, ep.min_amount, ep_pay.ep_min)) AS min_check,
      MAX(COALESCE(p.deposit_order_max_amount, ep.max_amount, ep_pay.ep_max)) AS max_check
    FROM active_reqs ar
    LEFT JOIN payments p ON REPLACE(p.requisites::jsonb->>'requisites', ' ', '') = ar.req_clean
      AND p.type = ar.payment_type AND p.deleted_at IS NULL
    LEFT JOIN exchange_platforms ep ON ep.id = ar.ep_id
    LEFT JOIN LATERAL (
      SELECT MIN(p2.deposit_order_min_amount) AS ep_min, MAX(p2.deposit_order_max_amount) AS ep_max
      FROM payments p2
      WHERE p2.user_id = ep.user_id AND p2.type = ar.payment_type
        AND p2.deleted_at IS NULL
        AND (p2.deposit_order_min_amount IS NOT NULL OR p2.deposit_order_max_amount IS NOT NULL)
    ) ep_pay ON true
    GROUP BY ar.payment_type
    ORDER BY requisites_count DESC
  `;
}

// Detail: each real online requisite with trader name, limits, and provider
function getActiveRequisitesDetailSQL(intervalKey) {
  const interval = ALLOWED_INTERVALS[intervalKey];
  if (!interval) throw new Error(`Invalid interval: ${intervalKey}`);

  return `
    WITH active_reqs AS (
      SELECT DISTINCT payment_type,
        REPLACE(requisites::jsonb->>'requisites', ' ', '') AS req_clean,
        (ARRAY_AGG(exchange_platform_id) FILTER (WHERE exchange_platform_id IS NOT NULL))[1] AS ep_id
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '${interval}'
        AND type = 'deposit' AND status != 'deleted'
        AND requisites IS NOT NULL AND requisites != '' AND requisites != '{}'
        AND requisites::jsonb->>'requisites' IS NOT NULL
      GROUP BY payment_type, REPLACE(requisites::jsonb->>'requisites', ' ', '')
    )
    SELECT
      ar.payment_type AS method,
      COALESCE(u.name, '') AS trader_name,
      COALESCE(p.deposit_order_min_amount, ep.min_amount, ep_pay.ep_min, 0) AS min_check,
      COALESCE(p.deposit_order_max_amount, ep.max_amount, ep_pay.ep_max, 0) AS max_check,
      COALESCE(ep.name, '') AS provider_name
    FROM active_reqs ar
    LEFT JOIN payments p ON REPLACE(p.requisites::jsonb->>'requisites', ' ', '') = ar.req_clean
      AND p.type = ar.payment_type AND p.deleted_at IS NULL
    LEFT JOIN users u ON u.id = p.user_id
    LEFT JOIN exchange_platforms ep ON ep.id = ar.ep_id
    LEFT JOIN LATERAL (
      SELECT MIN(p2.deposit_order_min_amount) AS ep_min, MAX(p2.deposit_order_max_amount) AS ep_max
      FROM payments p2
      WHERE p2.user_id = ep.user_id AND p2.type = ar.payment_type
        AND p2.deleted_at IS NULL
        AND (p2.deposit_order_min_amount IS NOT NULL OR p2.deposit_order_max_amount IS NOT NULL)
    ) ep_pay ON true
    ORDER BY ar.payment_type, min_check, max_check
  `;
}

// Per-requisite stats: volume, orders, conversion, limits, trader/provider per each requisite
function getPerRequisiteStatsSQL(intervalKey) {
  const interval = ALLOWED_INTERVALS[intervalKey];
  if (!interval) throw new Error(`Invalid interval: ${intervalKey}`);

  return `
    WITH reqs AS (
      SELECT
        payment_type,
        requisites::jsonb->>'requisites' AS req_value,
        COUNT(*) AS orders,
        COUNT(*) FILTER (WHERE status = 'closed') AS successful,
        COUNT(*) FILTER (WHERE status IN ('process', 'closed', 'dispute')) AS issued,
        ROUND(SUM(amount) FILTER (WHERE status = 'closed'), 0) AS volume,
        (ARRAY_AGG(exchange_platform_id) FILTER (WHERE exchange_platform_id IS NOT NULL))[1] AS ep_id
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '${interval}'
        AND type = 'deposit' AND status != 'deleted'
        AND requisites IS NOT NULL AND requisites != '' AND requisites != '{}'
        AND requisites::jsonb->>'requisites' IS NOT NULL
      GROUP BY payment_type, requisites::jsonb->>'requisites'
    )
    SELECT
      r.payment_type AS method,
      r.req_value,
      r.orders,
      r.successful,
      r.issued,
      r.volume,
      COALESCE(u.name, '') AS trader_name,
      COALESCE(ep.name, '') AS provider_name,
      COALESCE(p.deposit_order_min_amount, ep.min_amount, ep_pay.ep_min, 0) AS min_check,
      COALESCE(p.deposit_order_max_amount, ep.max_amount, ep_pay.ep_max, 0) AS max_check
    FROM reqs r
    LEFT JOIN payments p ON REPLACE(p.requisites::jsonb->>'requisites', ' ', '') = REPLACE(r.req_value, ' ', '')
      AND p.type = r.payment_type AND p.deleted_at IS NULL
    LEFT JOIN users u ON u.id = p.user_id
    LEFT JOIN exchange_platforms ep ON ep.id = r.ep_id
    LEFT JOIN LATERAL (
      SELECT MIN(p2.deposit_order_min_amount) AS ep_min, MAX(p2.deposit_order_max_amount) AS ep_max
      FROM payments p2
      WHERE p2.user_id = ep.user_id AND p2.type = r.payment_type
        AND p2.deleted_at IS NULL
        AND (p2.deposit_order_min_amount IS NOT NULL OR p2.deposit_order_max_amount IS NOT NULL)
    ) ep_pay ON true
    ORDER BY r.payment_type, r.volume DESC NULLS LAST
  `;
}

function getTotalActiveRequisitesSQL(intervalKey) {
  const interval = ALLOWED_INTERVALS[intervalKey];
  if (!interval) throw new Error(`Invalid interval: ${intervalKey}`);

  return `
    WITH active_reqs AS (
      SELECT payment_type,
        REPLACE(requisites::jsonb->>'requisites', ' ', '') AS req_clean,
        (ARRAY_AGG(exchange_platform_id) FILTER (WHERE exchange_platform_id IS NOT NULL))[1] AS ep_id
      FROM orders
      WHERE created_at >= NOW() - INTERVAL '${interval}'
        AND type = 'deposit' AND status != 'deleted'
        AND requisites IS NOT NULL AND requisites != '' AND requisites != '{}'
        AND requisites::jsonb->>'requisites' IS NOT NULL
      GROUP BY payment_type, REPLACE(requisites::jsonb->>'requisites', ' ', '')
    )
    SELECT
      COUNT(*) AS total_requisites,
      COUNT(DISTINCT ar.payment_type) AS methods_count,
      MIN(COALESCE(p.deposit_order_min_amount, ep.min_amount, ep_pay.ep_min)) AS min_check,
      MAX(COALESCE(p.deposit_order_max_amount, ep.max_amount, ep_pay.ep_max)) AS max_check
    FROM active_reqs ar
    LEFT JOIN payments p ON REPLACE(p.requisites::jsonb->>'requisites', ' ', '') = ar.req_clean
      AND p.type = ar.payment_type AND p.deleted_at IS NULL
    LEFT JOIN exchange_platforms ep ON ep.id = ar.ep_id
    LEFT JOIN LATERAL (
      SELECT MIN(p2.deposit_order_min_amount) AS ep_min, MAX(p2.deposit_order_max_amount) AS ep_max
      FROM payments p2
      WHERE p2.user_id = ep.user_id AND p2.type = ar.payment_type
        AND p2.deleted_at IS NULL
        AND (p2.deposit_order_min_amount IS NOT NULL OR p2.deposit_order_max_amount IS NOT NULL)
    ) ep_pay ON true
  `;
}

// ============ ЗАГРУЗКА ДАННЫХ ============

async function fetchOnlineData() {
  console.log("🔄 Загружаю онлайн данные (PostgreSQL)...");

  try {
    const [ordersByMethod, ordersTotals, activeByMethod, activeTotals, activeDetail] = await Promise.all([
      executeQuery(getMethodsSummarySQL("15 minutes")),
      executeQuery(getTotalSummarySQL("15 minutes")),
      executeQuery(getActiveRequisitesSQL("15 minutes")),
      executeQuery(getTotalActiveRequisitesSQL("15 minutes")),
      executeQuery(getActiveRequisitesDetailSQL("15 minutes")),
    ]);
    console.log(`✅ Получено ${ordersByMethod.length} методов (заявки 15 мин), ${activeByMethod.length} методов (активные рекв.)`);

    // Build a map of active requisites by method
    const activeMap = {};
    activeByMethod.forEach(row => {
      activeMap[row.method] = {
        requisites_count: Number(row.requisites_count) || 0,
        min_check: Number(row.min_check) || 0,
        max_check: Number(row.max_check) || 0,
      };
    });

    // Build detail breakdown: method -> [{min_check, max_check, count, traders}]
    const detailRaw = {};
    activeDetail.forEach(row => {
      const method = row.method;
      const key = `${row.min_check}|${row.max_check}`;
      if (!detailRaw[method]) detailRaw[method] = {};
      if (!detailRaw[method][key]) {
        detailRaw[method][key] = {
          min_check: Number(row.min_check) || 0,
          max_check: Number(row.max_check) || 0,
          traders: [],
        };
      }
      const trader = String(row.trader_name || '—');
      const provider = String(row.provider_name || '');
      detailRaw[method][key].traders.push({ trader, provider });
    });
    // Convert to array format
    const detailMap = {};
    for (const method of Object.keys(detailRaw)) {
      detailMap[method] = Object.values(detailRaw[method]).map(d => ({
        min_check: d.min_check,
        max_check: d.max_check,
        count: d.traders.length,
        traders: d.traders,
      }));
    }

    // Merge: all methods from both sources
    const allMethods = new Set([
      ...ordersByMethod.map(r => r.method),
      ...activeByMethod.map(r => r.method),
    ]);

    const ordersMap = {};
    ordersByMethod.forEach(row => { ordersMap[row.method] = row; });

    const methodsArray = Array.from(allMethods).map(method => {
      const o = ordersMap[method] || {};
      const a = activeMap[method] || {};
      return {
        method,
        requisites_count: a.requisites_count || 0,
        min_check: a.min_check || 0,
        max_check: a.max_check || 0,
        limits_detail: detailMap[method] || [],
        orders_count: Number(o.orders_count) || 0,
        successful: Number(o.successful) || 0,
        issued: Number(o.issued) || 0,
        conversion: Number(o.conversion) || 0,
        volume: Number(o.volume) || 0,
      };
    }).sort((a, b) => b.requisites_count - a.requisites_count || b.orders_count - a.orders_count);

    const at = activeTotals[0] || {};
    const ot = ordersTotals[0] || {};

    return {
      methodsSummary: methodsArray,
      summary: {
        requisites_count: Number(at.total_requisites) || 0,
        methods_count: Number(at.methods_count) || 0,
        min_check: Number(at.min_check) || 0,
        max_check: Number(at.max_check) || 0,
        total_orders: Number(ot.total_orders) || 0,
        successful: Number(ot.total_successful) || 0,
        issued: Number(ot.total_issued) || 0,
        volume: Number(ot.total_volume) || 0,
        conversion: Number(ot.total_issued) > 0
          ? Math.round(Number(ot.total_successful) * 100 / Number(ot.total_issued) * 10) / 10
          : 0
      }
    };

  } catch (err) {
    console.error("❌ Ошибка загрузки онлайн:", err.message);
    throw err;
  }
}

async function fetchStats24h() {
  console.log("🔄 Загружаю статистику 24ч (PostgreSQL)...");

  try {
    const [data, totalsData] = await Promise.all([
      executeQuery(getMethodsSummarySQL("24 hours")),
      executeQuery(getTotalSummarySQL("24 hours")),
    ]);
    console.log(`✅ Получено ${data.length} методов (24ч)`);

    const methodsArray = data.map(row => ({
      method: row.method,
      requisites_count: Number(row.requisites_count) || 0,
      total_orders: Number(row.orders_count) || 0,
      successful: Number(row.successful) || 0,
      issued: Number(row.issued) || 0,
      conversion: Number(row.conversion) || 0,
      volume: Number(row.volume) || 0,
    }));

    const t = totalsData[0] || {};

    return {
      byMethod: methodsArray,
      general: {
        requisites_count: Number(t.total_requisites) || 0,
        total_orders: Number(t.total_orders) || 0,
        successful: Number(t.total_successful) || 0,
        issued: Number(t.total_issued) || 0,
        volume: Number(t.total_volume) || 0,
        conversion: Number(t.total_issued) > 0
          ? Math.round(Number(t.total_successful) * 100 / Number(t.total_issued) * 10) / 10
          : 0
      }
    };

  } catch (err) {
    console.error("❌ Ошибка загрузки 24ч:", err.message);
    throw err;
  }
}

async function fetchRequisitesDetail() {
  console.log("🔄 Загружаю детали реквизитов (PostgreSQL)...");

  try {
    const rows = await executeQuery(getPerRequisiteStatsSQL("15 minutes"));
    console.log(`✅ Получено ${rows.length} реквизитов с деталями`);

    const byMethod = {};
    let totalOrders = 0, totalSuccessful = 0, totalIssued = 0, totalVolume = 0;

    for (const row of rows) {
      const method = row.method;
      if (!byMethod[method]) byMethod[method] = [];
      const entry = {
        req_value: row.req_value,
        orders: Number(row.orders) || 0,
        successful: Number(row.successful) || 0,
        issued: Number(row.issued) || 0,
        volume: Number(row.volume) || 0,
        trader_name: row.trader_name || '',
        provider_name: row.provider_name || '',
        min_check: Number(row.min_check) || 0,
        max_check: Number(row.max_check) || 0,
      };
      byMethod[method].push(entry);
      totalOrders += entry.orders;
      totalSuccessful += entry.successful;
      totalIssued += entry.issued;
      totalVolume += entry.volume;
    }

    return {
      byMethod,
      totals: {
        requisites: rows.length,
        methods: Object.keys(byMethod).length,
        orders: totalOrders,
        successful: totalSuccessful,
        issued: totalIssued,
        volume: totalVolume,
      }
    };
  } catch (err) {
    console.error("❌ Ошибка загрузки деталей реквизитов:", err.message);
    throw err;
  }
}

// Always fetch fresh data
async function fetchAllData() {
  const [online, stats] = await Promise.all([
    fetchOnlineData(),
    fetchStats24h()
  ]);

  cachedData = { online, stats };
  lastUpdate = new Date();
  saveCachedData();

  console.log(`✅ Данные: ${online.summary.requisites_count} рекв. онлайн, ${stats.general.total_orders} заявок за 24ч`);
  return cachedData;
}

// ============ ПЕРСИСТЕНТНОЕ ХРАНЕНИЕ ============

function loadKeysFromFile() {
  try {
    if (fs.existsSync(CONFIG.KEYS_FILE)) {
      const data = JSON.parse(fs.readFileSync(CONFIG.KEYS_FILE, "utf-8"));
      return new Map(data.keys.map(k => [k.key, { ...k, createdAt: new Date(k.createdAt) }]));
    }
  } catch (e) {}
  return new Map();
}

function saveKeysToFile(keys) {
  try {
    let data = { keys: [], users: [] };
    if (fs.existsSync(CONFIG.KEYS_FILE)) {
      data = JSON.parse(fs.readFileSync(CONFIG.KEYS_FILE, "utf-8"));
    }
    data.keys = Array.from(keys.entries()).map(([key, val]) => ({ key, ...val }));
    fs.writeFileSync(CONFIG.KEYS_FILE, JSON.stringify(data, null, 2));
  } catch (e) {}
}

function loadUsersFromFile() {
  try {
    if (fs.existsSync(CONFIG.KEYS_FILE)) {
      const data = JSON.parse(fs.readFileSync(CONFIG.KEYS_FILE, "utf-8"));
      return new Set(data.users || []);
    }
  } catch (e) {}
  return new Set();
}

function saveUsersToFile(users) {
  try {
    let data = { keys: [], users: [] };
    if (fs.existsSync(CONFIG.KEYS_FILE)) {
      data = JSON.parse(fs.readFileSync(CONFIG.KEYS_FILE, "utf-8"));
    }
    data.users = Array.from(users);
    fs.writeFileSync(CONFIG.KEYS_FILE, JSON.stringify(data, null, 2));
  } catch (e) {}
}

function saveCachedData() {
  try {
    fs.writeFileSync(CONFIG.DATA_FILE, JSON.stringify({
      data: cachedData,
      lastUpdate: lastUpdate?.toISOString()
    }));
  } catch (e) {}
}

// Загрузка при старте
const accessKeys = loadKeysFromFile();
const authorizedUsers = loadUsersFromFile();
ADMIN_TG_IDS.forEach(id => authorizedUsers.add(id));

// ============ ПРОВЕРКА ДОСТУПА ============

function isAdmin(ctx) {
  return ADMIN_TG_IDS.includes(ctx.from.id.toString());
}

function isAuthorized(ctx) {
  return authorizedUsers.has(ctx.from.id.toString()) || isAdmin(ctx);
}

function generateKey() {
  return 'KEY-' + Math.random().toString(36).substring(2, 10).toUpperCase();
}

// ============ МЕНЮ ============

function getMainMenu(ctx) {
  const buttons = [
    ["🟢 Онлайн сейчас", "📋 Детали рекв."],
    ["📱 По методам", "📊 Статистика 24ч"],
    ["🔄 Обновить"]
  ];
  if (isAdmin(ctx)) buttons.push(["⚙️ Админ"]);
  return Markup.keyboard(buttons).resize();
}

function getAdminMenu() {
  return Markup.keyboard([
    ["🔑 Создать ключ", "📋 Ключи"],
    ["👥 Пользователи", "◀️ Назад"]
  ]).resize();
}

// ============ ФОРМАТИРОВАНИЕ ============

function esc(text) {
  if (!text) return '';
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function num(n) {
  if (!n && n !== 0) return '-';
  return Number(n).toLocaleString('ru-RU');
}

function money(n) {
  if (!n && n !== 0) return '-';
  return Number(n).toLocaleString('ru-RU') + ' ₽';
}

function maskRequisite(val) {
  if (!val) return '—';
  const s = String(val).replace(/\s/g, '');
  if (s.length <= 8) return s;
  return s.slice(0, 4) + '****' + s.slice(-4);
}

function formatRequisitesDetail(data) {
  if (!data?.requisitesDetail) return "❌ Нажмите 🔄 Обновить";

  const { byMethod, totals } = data.requisitesDetail;
  const time = lastUpdate?.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }) || '-';

  let msg = `📋 <b>ДЕТАЛИ РЕКВИЗИТОВ</b> (${CONFIG.ONLINE_INTERVAL} мин)\n`;
  msg += `━━━━━━━━━━━━━━━━━━━━━\n\n`;

  // Totals
  msg += `📋 Реквизитов: <b>${num(totals.requisites)}</b> | Методов: <b>${num(totals.methods)}</b>\n`;
  msg += `📝 Заявок: <b>${num(totals.orders)}</b> (✅ ${num(totals.successful)})\n`;
  msg += `💰 Оборот: <b>${money(totals.volume)}</b>\n`;
  if (totals.issued > 0) {
    msg += `📈 Конверсия: <b>${Math.round(totals.successful * 1000 / totals.issued) / 10}%</b>\n`;
  }
  msg += `\n`;

  const methods = Object.keys(byMethod).sort((a, b) => {
    const va = byMethod[a].reduce((s, r) => s + (Number(r.volume) || 0), 0);
    const vb = byMethod[b].reduce((s, r) => s + (Number(r.volume) || 0), 0);
    return vb - va;
  });

  if (methods.length === 0) {
    msg += `Нет активности\n`;
  }

  for (const method of methods) {
    const reqs = byMethod[method];
    const methodVolume = reqs.reduce((s, r) => s + (Number(r.volume) || 0), 0);
    const methodOrders = reqs.reduce((s, r) => s + (Number(r.orders) || 0), 0);
    const methodSuccessful = reqs.reduce((s, r) => s + (Number(r.successful) || 0), 0);
    const methodIssued = reqs.reduce((s, r) => s + (Number(r.issued) || 0), 0);
    const methodConv = methodIssued > 0 ? Math.round(methodSuccessful * 1000 / methodIssued) / 10 : 0;
    const traders = new Set(reqs.map(r => r.trader_name).filter(Boolean));

    const icon = methodConv >= 50 ? "🟢" : methodConv >= 30 ? "🟡" : "🔴";
    msg += `${icon} <b>${esc(method).toUpperCase()}</b> — ${reqs.length} рекв.`;
    if (traders.size > 0) msg += ` | ${traders.size} трейд.`;
    msg += `\n`;
    msg += `💰 Оборот: <b>${money(methodVolume)}</b> | 📈 ${methodConv}%\n`;
    msg += `━━━━━━━━━━━━━━━━━━━━━\n`;

    for (const r of reqs) {
      const masked = maskRequisite(r.req_value);
      const conv = Number(r.issued) > 0 ? Math.round(Number(r.successful) * 1000 / Number(r.issued)) / 10 : 0;

      // Owner line
      let owner = '';
      if (r.trader_name) {
        owner = r.provider_name ? `👤 ${esc(r.trader_name)} (${esc(r.provider_name)})` : `👤 ${esc(r.trader_name)}`;
      } else if (r.provider_name) {
        owner = `🏢 ${esc(r.provider_name)}`;
      }

      msg += `\n  <code>${masked}</code>`;
      if (owner) msg += ` ${owner}`;
      msg += `\n`;

      // Limits
      const hasLimits = Number(r.min_check) > 0 || Number(r.max_check) > 0;
      if (hasLimits) {
        msg += `  💳 ${money(r.min_check)} — ${money(r.max_check)}\n`;
      }

      // Stats
      msg += `  💰 ${money(r.volume)} (${num(r.orders)} заявок, ${r.successful} ✅)\n`;
      if (Number(r.issued) > 0) {
        msg += `  📈 Конверсия: ${conv}%\n`;
      }
    }

    msg += `\n`;
  }

  msg += `🕐 ${time}`;
  return msg;
}

function formatOnlineNow(data) {
  if (!data?.online) return "❌ Нажмите 🔄 Обновить";

  const { summary, methodsSummary } = data.online;
  const time = lastUpdate?.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }) || '-';

  let msg = `🟢 <b>ОНЛАЙН СЕЙЧАС</b> (${CONFIG.ONLINE_INTERVAL} мин)\n`;
  msg += `━━━━━━━━━━━━━━━━━━━━━\n\n`;

  // Общая сводка
  msg += `📋 Реквизитов онлайн: <b>${num(summary.requisites_count)}</b>\n`;
  msg += `📱 Методов: <b>${num(summary.methods_count)}</b>\n`;
  if (summary.min_check || summary.max_check) {
    msg += `💳 Чек: <b>${money(summary.min_check)} — ${money(summary.max_check)}</b>\n`;
  }
  msg += `📝 Заявок: <b>${num(summary.total_orders)}</b> (✅ ${num(summary.successful)})\n`;
  msg += `💰 Оборот: <b>${money(summary.volume)}</b>\n`;
  msg += `📈 Конверсия: <b>${summary.conversion || 0}%</b>\n\n`;

  // По методам
  msg += `📱 <b>ПО МЕТОДАМ:</b>\n`;
  msg += `━━━━━━━━━━━━━━━━━━━━━\n`;

  if (methodsSummary?.length > 0) {
    // Filter: only show methods with requisites or successful orders
    const activeMethods = methodsSummary.filter(m => m.requisites_count > 0 || m.successful > 0);
    if (activeMethods.length > 0) {
      activeMethods.forEach(m => {
        const icon = m.conversion >= 50 ? "🟢" : m.conversion >= 30 ? "🟡" : "🔴";
        msg += `\n${icon} <b>${esc(m.method).toUpperCase()}</b> (${m.requisites_count} рекв.)\n`;
        if (m.limits_detail?.length > 0) {
          // Split known (with trader/limits) and unknown (provider requisites)
          m.limits_detail.forEach(d => {
            const hasLimits = d.min_check > 0 || d.max_check > 0;
            if (hasLimits) {
              msg += `  💳 ${money(d.min_check)}${d.max_check ? ' — ' + money(d.max_check) : '+'}: <b>${d.count}</b> рекв.\n`;
            } else {
              msg += `  💳 лимит не задан: <b>${d.count}</b> рекв.\n`;
            }
            if (d.traders?.length > 0) {
              d.traders.forEach(t => {
                const name = typeof t === 'object' ? t.trader : t;
                const prov = typeof t === 'object' ? t.provider : '';
                if (name && name !== '—') {
                  msg += prov ? `      👤 <b>${esc(name)}</b> (${esc(prov)})\n` : `      👤 <b>${esc(name)}</b>\n`;
                } else if (prov) {
                  msg += `      🏢 <b>${esc(prov)}</b>\n`;
                }
              });
            }
          });
        }
        if (m.orders_count > 0) {
          msg += `  📝 Заявок: ${num(m.orders_count)} (✅ ${m.successful})\n`;
          msg += `  💰 Оборот: <b>${money(m.volume)}</b>\n`;
          msg += `  📈 Конверсия: <b>${m.conversion}%</b>\n`;
        }
      });
    } else {
      msg += `\nНет активности\n`;
    }
  } else {
    msg += `\nНет активности\n`;
  }

  msg += `\n🕐 ${time}`;
  return msg;
}

function formatMethodsDetailed(data) {
  if (!data?.online?.methodsSummary) return "❌ Нажмите 🔄 Обновить";

  const { methodsSummary, summary } = data.online;
  const time = lastUpdate?.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }) || '-';

  let msg = `📱 <b>МЕТОДЫ ОНЛАЙН</b> (${CONFIG.ONLINE_INTERVAL} мин)\n`;
  msg += `━━━━━━━━━━━━━━━━━━━━━\n\n`;

  if (methodsSummary.length === 0) {
    msg += "Нет активности";
    return msg;
  }

  // Общий итог
  msg += `📊 <b>ИТОГО:</b>\n`;
  msg += `  📋 Реквизитов: <b>${num(summary.requisites_count)}</b>\n`;
  if (summary.min_check || summary.max_check) {
    msg += `  💳 Чек: <b>${money(summary.min_check)} — ${money(summary.max_check)}</b>\n`;
  }
  msg += `  💰 Оборот: <b>${money(summary.volume)}</b>\n\n`;

  const activeMethods = methodsSummary.filter(m => m.requisites_count > 0 || m.successful > 0);
  activeMethods.forEach(m => {
    const icon = m.conversion >= 50 ? "🟢" : m.conversion >= 30 ? "🟡" : "🔴";
    msg += `${icon} <b>${esc(m.method).toUpperCase()}</b> (${m.requisites_count} рекв.)\n`;
    msg += `━━━━━━━━━━━━━━━━━━━━━\n`;
    if (m.limits_detail?.length > 0) {
      m.limits_detail.forEach(d => {
        const hasLimits = d.min_check > 0 || d.max_check > 0;
        if (hasLimits) {
          msg += `💳 ${money(d.min_check)}${d.max_check ? ' — ' + money(d.max_check) : '+'}: <b>${d.count}</b> рекв.\n`;
        } else {
          msg += `💳 лимит не задан: <b>${d.count}</b> рекв.\n`;
        }
        if (d.traders?.length > 0) {
          d.traders.forEach(t => {
            const name = typeof t === 'object' ? t.trader : t;
            const prov = typeof t === 'object' ? t.provider : '';
            if (name && name !== '—') {
              msg += prov ? `    👤 <b>${esc(name)}</b> (${esc(prov)})\n` : `    👤 <b>${esc(name)}</b>\n`;
            } else if (prov) {
              msg += `    🏢 <b>${esc(prov)}</b>\n`;
            }
          });
        }
      });
    }
    if (m.orders_count > 0) {
      msg += `📝 Заявок: <b>${num(m.orders_count)}</b> (✅ ${m.successful})\n`;
      msg += `💰 Оборот: <b>${money(m.volume)}</b>\n`;
      msg += `📈 Конверсия: <b>${m.conversion}%</b>\n`;
    }
    msg += `\n`;
  });

  msg += `🕐 ${time}`;
  return msg;
}

function formatStats24h(data) {
  if (!data?.stats) return "❌ Нажмите 🔄 Обновить";

  const { general, byMethod } = data.stats;
  const time = lastUpdate?.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }) || '-';

  let msg = `📊 <b>СТАТИСТИКА 24ч</b>\n`;
  msg += `━━━━━━━━━━━━━━━━━━━━━\n\n`;

  msg += `📋 Реквизитов: <b>${num(general.requisites_count)}</b>\n`;
  msg += `📝 Заявок: <b>${num(general.total_orders)}</b>\n`;
  msg += `✅ Успешных: <b>${num(general.successful)}</b>\n`;
  msg += `💰 Оборот: <b>${money(general.volume)}</b>\n`;
  msg += `📈 Конверсия: <b>${general.conversion || 0}%</b>\n\n`;

  msg += `📱 <b>По методам:</b>\n`;
  if (byMethod?.length > 0) {
    byMethod.forEach(m => {
      const icon = m.conversion >= 50 ? "🟢" : m.conversion >= 30 ? "🟡" : "🔴";
      msg += `\n${icon} <b>${esc(m.method).toUpperCase()}</b>\n`;
      msg += `  📋 ${m.requisites_count} рекв. | 📝 ${num(m.total_orders)} заявок\n`;
      msg += `  ✅ ${m.successful} успешных | 📈 ${m.conversion}%\n`;
      msg += `  💰 Оборот: ${money(m.volume)}\n`;
    });
  }

  msg += `\n🕐 ${time}`;
  return msg;
}

// ============ ОБРАБОТЧИКИ ============

bot.start(async (ctx) => {
  if (isAuthorized(ctx)) {
    await ctx.reply(
      `👋 <b>Live Monitor</b>\n\n⚡ Данные в реальном времени из Metabase\n\nВыберите действие:`,
      { parse_mode: "HTML", ...getMainMenu(ctx) }
    );
  } else {
    await ctx.reply(
      `🔐 Введите ключ доступа:\n\n<code>KEY-XXXXXXXX</code>`,
      { parse_mode: "HTML", ...Markup.removeKeyboard() }
    );
  }
});

bot.hears(/^KEY-[A-Z0-9]+$/i, async (ctx) => {
  const key = ctx.message.text.toUpperCase();
  if (accessKeys.has(key)) {
    authorizedUsers.add(ctx.from.id.toString());
    saveUsersToFile(authorizedUsers);
    await ctx.reply(`✅ Доступ разрешён!`, getMainMenu(ctx));
  } else {
    await ctx.reply(`❌ Неверный ключ`);
  }
});

bot.hears("🟢 Онлайн сейчас", async (ctx) => {
  if (!isAuthorized(ctx)) return;

  const msg = await ctx.reply("⏳ Загружаю...");

  try {
    await fetchAllData();
    const text = formatOnlineNow(cachedData);

    if (text.length > 4000) {
      await ctx.telegram.deleteMessage(ctx.chat.id, msg.message_id);
      const parts = splitMsg(text, 4000);
      for (const part of parts) {
        await ctx.reply(part, { parse_mode: "HTML" });
      }
      await ctx.reply("⬆️", Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_online")]]));
    } else {
      await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, text, {
        parse_mode: "HTML",
        reply_markup: Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_online")]]).reply_markup
      });
    }
  } catch (e) {
    await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, `❌ Ошибка: ${esc(e.message)}`, { parse_mode: "HTML" });
  }
});

// FIX: Handle refresh_online callback
bot.action("refresh_online", async (ctx) => {
  try {
    await ctx.answerCbQuery("⏳ Обновляю...");
    await fetchAllData();
    const text = formatOnlineNow(cachedData);

    if (text.length > 4000) {
      await ctx.deleteMessage();
      const parts = splitMsg(text, 4000);
      for (const part of parts) {
        await ctx.reply(part, { parse_mode: "HTML" });
      }
      await ctx.reply("⬆️", Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_online")]]));
    } else {
      await ctx.editMessageText(text, {
        parse_mode: "HTML",
        reply_markup: Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_online")]]).reply_markup
      });
    }
  } catch (e) {
    await ctx.answerCbQuery(`❌ ${e.message.slice(0, 50)}`);
  }
});

bot.hears("📱 По методам", async (ctx) => {
  if (!isAuthorized(ctx)) return;

  const msg = await ctx.reply("⏳ Загружаю...");

  try {
    await fetchAllData();
    const text = formatMethodsDetailed(cachedData);

    if (text.length > 4000) {
      await ctx.telegram.deleteMessage(ctx.chat.id, msg.message_id);
      const parts = splitMsg(text, 4000);
      for (const part of parts) {
        await ctx.reply(part, { parse_mode: "HTML" });
      }
    } else {
      await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, text, { parse_mode: "HTML" });
    }
  } catch (e) {
    await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, `❌ Ошибка: ${esc(e.message)}`, { parse_mode: "HTML" });
  }
});

bot.hears("📊 Статистика 24ч", async (ctx) => {
  if (!isAuthorized(ctx)) return;

  const msg = await ctx.reply("⏳ Загружаю...");

  try {
    await fetchAllData();
    await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, formatStats24h(cachedData), { parse_mode: "HTML" });
  } catch (e) {
    await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, `❌ Ошибка: ${esc(e.message)}`, { parse_mode: "HTML" });
  }
});

bot.hears("📋 Детали рекв.", async (ctx) => {
  if (!isAuthorized(ctx)) return;

  const msg = await ctx.reply("⏳ Загружаю детали...");

  try {
    const requisitesDetail = await fetchRequisitesDetail();
    cachedData = { ...cachedData, requisitesDetail };
    lastUpdate = new Date();
    const text = formatRequisitesDetail(cachedData);

    if (text.length > 4000) {
      await ctx.telegram.deleteMessage(ctx.chat.id, msg.message_id);
      const parts = splitMsg(text, 4000);
      for (const part of parts) {
        await ctx.reply(part, { parse_mode: "HTML" });
      }
      await ctx.reply("⬆️", Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_requisites")]]));
    } else {
      await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, text, {
        parse_mode: "HTML",
        reply_markup: Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_requisites")]]).reply_markup
      });
    }
  } catch (e) {
    await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, `❌ Ошибка: ${esc(e.message)}`, { parse_mode: "HTML" });
  }
});

bot.action("refresh_requisites", async (ctx) => {
  try {
    await ctx.answerCbQuery("⏳ Обновляю...");
    const requisitesDetail = await fetchRequisitesDetail();
    cachedData = { ...cachedData, requisitesDetail };
    lastUpdate = new Date();
    const text = formatRequisitesDetail(cachedData);

    if (text.length > 4000) {
      await ctx.deleteMessage();
      const parts = splitMsg(text, 4000);
      for (const part of parts) {
        await ctx.reply(part, { parse_mode: "HTML" });
      }
      await ctx.reply("⬆️", Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_requisites")]]));
    } else {
      await ctx.editMessageText(text, {
        parse_mode: "HTML",
        reply_markup: Markup.inlineKeyboard([[Markup.button.callback("🔄 Обновить", "refresh_requisites")]]).reply_markup
      });
    }
  } catch (e) {
    await ctx.answerCbQuery(`❌ ${e.message.slice(0, 50)}`);
  }
});

bot.hears("🔄 Обновить", async (ctx) => {
  if (!isAuthorized(ctx)) return;

  const msg = await ctx.reply("⏳ Обновляю...");

  try {
    const start = Date.now();
    await fetchAllData();
    const ms = Date.now() - start;

    await ctx.telegram.editMessageText(
      ctx.chat.id, msg.message_id, null,
      `✅ Обновлено за ${ms}мс!\n\n` + formatOnlineNow(cachedData),
      { parse_mode: "HTML" }
    );
  } catch (e) {
    await ctx.telegram.editMessageText(ctx.chat.id, msg.message_id, null, `❌ ${esc(e.message)}`, { parse_mode: "HTML" });
  }
});

function splitMsg(text, max) {
  const parts = [];
  let cur = "";
  text.split('\n').forEach(line => {
    if (cur.length + line.length + 1 > max) {
      parts.push(cur);
      cur = line;
    } else {
      cur += (cur ? '\n' : '') + line;
    }
  });
  if (cur) parts.push(cur);
  return parts;
}

// ============ АДМИН ============

bot.hears("⚙️ Админ", async (ctx) => {
  if (!isAdmin(ctx)) return;
  await ctx.reply("⚙️ Админ-панель:", getAdminMenu());
});

bot.hears("◀️ Назад", async (ctx) => {
  await ctx.reply("Главное меню:", getMainMenu(ctx));
});

bot.hears("🔑 Создать ключ", async (ctx) => {
  if (!isAdmin(ctx)) return;
  const key = generateKey();
  accessKeys.set(key, { createdAt: new Date(), createdBy: ctx.from.id });
  saveKeysToFile(accessKeys);
  await ctx.reply(`✅ Ключ:\n\n<code>${key}</code>`, { parse_mode: "HTML" });
});

bot.hears("📋 Ключи", async (ctx) => {
  if (!isAdmin(ctx)) return;
  if (accessKeys.size === 0) {
    await ctx.reply("Нет ключей");
    return;
  }
  let msg = "📋 <b>Ключи:</b>\n\n";
  accessKeys.forEach((data, key) => {
    msg += `<code>${key}</code> (${data.createdAt.toLocaleDateString('ru-RU')})\n`;
  });
  await ctx.reply(msg, { parse_mode: "HTML" });
});

bot.hears("👥 Пользователи", async (ctx) => {
  if (!isAdmin(ctx)) return;
  await ctx.reply(`👥 Пользователей: ${authorizedUsers.size}`);
});

bot.on("text", async (ctx) => {
  if (!isAdmin(ctx)) return;
  const text = ctx.message.text.toUpperCase();
  if (text.startsWith("KEY-") && accessKeys.has(text)) {
    accessKeys.delete(text);
    saveKeysToFile(accessKeys);
    await ctx.reply(`✅ Ключ удалён`);
  }
});

// ============ ЭКСПОРТ ДЛЯ ТЕСТОВ ============

export {
  esc, num, money, splitMsg, maskRequisite,
  formatOnlineNow, formatMethodsDetailed, formatStats24h, formatRequisitesDetail,
  getMethodsSummarySQL, getTotalSummarySQL,
  getActiveRequisitesSQL, getActiveRequisitesDetailSQL, getTotalActiveRequisitesSQL,
  getPerRequisiteStatsSQL,
  ALLOWED_INTERVALS, CONFIG,
};

// ============ ЗАПУСК ============

async function main() {
  console.log("🚀 Live Monitor Bot v2.1");
  console.log(`📊 Metabase: ${METABASE_URL}`);

  // Проверяем подключение к Metabase
  try {
    await getMetabaseSession();
    console.log("✅ Metabase подключен");
  } catch (e) {
    console.error("❌ Metabase недоступен:", e.message);
    console.error("⚠️ Проверь переменные окружения METABASE_EMAIL и METABASE_PASSWORD");
  }

  // Очищаем webhook перед запуском
  console.log("🧹 Очищаю webhook...");
  try {
    await bot.telegram.deleteWebhook({ drop_pending_updates: true });
    console.log("✅ Webhook удален");
  } catch (e) {
    console.log("⚠️ Ошибка удаления webhook:", e.message);
  }

  // Запускаем бота
  try {
    await bot.launch({ dropPendingUpdates: true });
    console.log("✅ Бот запущен!");
  } catch (error) {
    console.error("❌ Ошибка запуска:", error.message);
    if (error.message.includes("409") || error.message.includes("Conflict")) {
      console.log("⏳ Жду 35с пока Telegram освободит polling...");
      try { bot.stop(); } catch (_) {}
      await new Promise(r => setTimeout(r, 35000));
      await bot.launch({ dropPendingUpdates: true });
      console.log("✅ Бот запущен (после retry)!");
    } else {
      throw error;
    }
  }
}

main().catch(err => {
  console.error("💥 Критическая ошибка:", err);
  process.exit(1);
});

process.once('SIGINT', () => {
  console.log("🛑 Останавливаю бота...");
  bot.stop('SIGINT');
});

process.once('SIGTERM', () => {
  console.log("🛑 Останавливаю бота...");
  bot.stop('SIGTERM');
});
