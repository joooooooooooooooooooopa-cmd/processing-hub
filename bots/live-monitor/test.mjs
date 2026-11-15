/**
 * Tests for Live Monitor Bot v2.1
 * Run: node test.mjs
 */
import {
  esc, num, money, splitMsg, maskRequisite,
  formatOnlineNow, formatMethodsDetailed, formatStats24h, formatRequisitesDetail,
  getMethodsSummarySQL, getTotalSummarySQL,
  getActiveRequisitesSQL, getActiveRequisitesDetailSQL, getTotalActiveRequisitesSQL,
  getPerRequisiteStatsSQL,
  ALLOWED_INTERVALS, CONFIG,
} from "./index.mjs";

let passed = 0;
let failed = 0;

function assert(condition, name) {
  if (condition) {
    passed++;
    console.log(`  ✅ ${name}`);
  } else {
    failed++;
    console.error(`  ❌ ${name}`);
  }
}

function assertIncludes(str, sub, name) {
  assert(str.includes(sub), `${name} — contains "${sub}"`);
}

function assertNotIncludes(str, sub, name) {
  assert(!str.includes(sub), `${name} — NOT contains "${sub}"`);
}

function assertThrows(fn, name) {
  try {
    fn();
    failed++;
    console.error(`  ❌ ${name} — did NOT throw`);
  } catch {
    passed++;
    console.log(`  ✅ ${name}`);
  }
}

// ── SQL Security ────────────────────────────────────────────────────────────

console.log("\n🔒 SQL Security");

assert(ALLOWED_INTERVALS["15 minutes"] === "15 minutes", "15 minutes allowed");
assert(ALLOWED_INTERVALS["24 hours"] === "24 hours", "24 hours allowed");
assertThrows(() => getMethodsSummarySQL("'; DROP TABLE orders; --"), "SQL injection blocked in methods");
assertThrows(() => getTotalSummarySQL("1 hour; DELETE FROM users"), "SQL injection blocked in summary");
assertThrows(() => getMethodsSummarySQL("invalid"), "Unknown interval rejected");

const sql15 = getMethodsSummarySQL("15 minutes");
assertIncludes(sql15, "INTERVAL '15 minutes'", "15 min interval correct");
const sql24 = getMethodsSummarySQL("24 hours");
assertIncludes(sql24, "INTERVAL '24 hours'", "24h interval correct");

// ── SQL Correctness ─────────────────────────────────────────────────────────

console.log("\n📊 SQL Query Correctness");

// Conversion = closed / issued
assertIncludes(sql15, "status IN ('process', 'closed', 'dispute')", "Denominator = issued orders");
assertIncludes(sql15, "status = 'closed'", "Numerator = closed orders");

// Deposit only
assertIncludes(sql15, "type = 'deposit'", "Deposit-only filter");

// No deleted
assertIncludes(sql15, "status != 'deleted'", "Deleted excluded");

// No broken JOINs (user_id/payment_id are NULL)
assertNotIncludes(sql15, "JOIN users", "No JOIN users (user_id is NULL)");
assertNotIncludes(sql15, "JOIN payments", "No JOIN payments (payment_id is NULL)");

// Requisites counted as unique via JSON field
assertIncludes(sql15, "DISTINCT requisites::jsonb->>'requisites'", "Unique requisites via JSON field");

// Volume
assertIncludes(sql15, "SUM(amount)", "Volume calculated");

// Total summary SQL
const totalSql = getTotalSummarySQL("15 minutes");
assertIncludes(totalSql, "total_orders", "Total orders in summary");
assertIncludes(totalSql, "total_requisites", "Total requisites in summary");
assertIncludes(totalSql, "total_volume", "Total volume in summary");
assertIncludes(totalSql, "type = 'deposit'", "Summary filters deposits");

// Active requisites SQL (from payments table)
const activeReqSql = getActiveRequisitesSQL("15 minutes");
assertIncludes(activeReqSql, "FROM orders", "Active req from real orders");
assertIncludes(activeReqSql, "LEFT JOIN payments", "Active req joins payments for limits");
assertIncludes(activeReqSql, "REPLACE", "Active req strips spaces for matching");
assertIncludes(activeReqSql, "min_check", "Active req has min_check");
assertIncludes(activeReqSql, "max_check", "Active req has max_check");

const totalActiveSql = getTotalActiveRequisitesSQL("15 minutes");
assertIncludes(totalActiveSql, "total_requisites", "Total active req count");
assertIncludes(totalActiveSql, "methods_count", "Total active methods count");

const detailSql = getActiveRequisitesDetailSQL("15 minutes");
assertIncludes(detailSql, "LEFT JOIN payments", "Detail joins payments");
assertIncludes(detailSql, "trader_name", "Detail includes trader name");
assertIncludes(detailSql, "FROM orders", "Detail from real orders");

// ── Formatting ──────────────────────────────────────────────────────────────

console.log("\n📝 Formatting Functions");

assert(esc("<b>test</b>") === "&lt;b&gt;test&lt;/b&gt;", "esc escapes HTML");
assert(esc("") === "", "esc empty string");
assert(esc(null) === "", "esc null");

assert(num(0) === "0", "num zero");
assert(num(null) === "-", "num null");
assert(num(undefined) === "-", "num undefined");

assert(money(5000).includes("₽"), "money includes ₽");
assert(money(null) === "-", "money null");

const longText = Array(100).fill("Line of text here").join("\n");
const parts = splitMsg(longText, 200);
assert(parts.length > 1, "splitMsg splits long text");
assert(parts.every(p => p.length <= 200), "splitMsg respects max length");
assert(splitMsg("Short", 4000).length === 1, "splitMsg keeps short text");

// ── formatOnlineNow ─────────────────────────────────────────────────────────

console.log("\n📱 Format Online Now");

assert(formatOnlineNow(null) === "❌ Нажмите 🔄 Обновить", "null handled");
assert(formatOnlineNow({}) === "❌ Нажмите 🔄 Обновить", "empty handled");

const mockOnline = {
  online: {
    summary: { requisites_count: 12, methods_count: 3, min_check: 500, max_check: 200000, total_orders: 100, successful: 45, issued: 60, volume: 500000, conversion: 75.0 },
    methodsSummary: [
      { method: "sbp", requisites_count: 8, min_check: 500, max_check: 200000, limits_detail: [
        { min_check: 500, max_check: 5000, count: 1, traders: [{ trader: "trader_alpha", holder: "Тестов А." }] },
        { min_check: 11000, max_check: 20000, count: 5, traders: [{ trader: "trader_beta", holder: "Иванов И." }, { trader: "trader_beta", holder: "Петров П." }, { trader: "trader_beta", holder: "Сидоров С." }, { trader: "trader_beta", holder: "Козлов К." }, { trader: "trader_beta", holder: "Морозов М." }] },
        { min_check: 50000, max_check: 200000, count: 2, traders: [{ trader: "trader_gamma", holder: "Примеров Б." }, { trader: "trader_gamma", holder: "Образцов В." }] },
      ], orders_count: 60, successful: 30, issued: 40, conversion: 75.0, volume: 300000 },
      { method: "card", requisites_count: 4, min_check: 1000, max_check: 50000, limits_detail: [
        { min_check: 1000, max_check: 50000, count: 4, traders: [{ trader: "trader1", holder: "Трейдер 1" }, { trader: "trader2", holder: "Трейдер 2" }, { trader: "trader3", holder: "Трейдер 3" }, { trader: "trader4", holder: "Трейдер 4" }] },
      ], orders_count: 40, successful: 15, issued: 20, conversion: 75.0, volume: 200000 },
    ]
  }
};

const onlineMsg = formatOnlineNow(mockOnline);
assertIncludes(onlineMsg, "ОНЛАЙН СЕЙЧАС", "Header present");
assertIncludes(onlineMsg, "Реквизитов", "Shows requisites");
assertNotIncludes(onlineMsg, "Трейдеров", "No traders (data unavailable)");
assertIncludes(onlineMsg, "SBP", "SBP uppercased");
assertIncludes(onlineMsg, "CARD", "CARD uppercased");
assertIncludes(onlineMsg, "Оборот", "Shows volume");
assertIncludes(onlineMsg, "75%", "Shows conversion");
assertIncludes(onlineMsg, "💳", "Shows limit breakdown icon");
assertIncludes(onlineMsg, "<b>5</b> рекв.", "Shows limit count per range");
assertIncludes(onlineMsg, "8 рекв.", "Shows total requisites in header");
assertIncludes(onlineMsg, "trader_alpha", "Shows trader name");
assertIncludes(onlineMsg, "trader_gamma", "Shows another trader name");

const emptyOnline = {
  online: {
    summary: { requisites_count: 0, methods_count: 0, total_orders: 0, successful: 0, issued: 0, volume: 0, conversion: 0 },
    methodsSummary: []
  }
};
assertIncludes(formatOnlineNow(emptyOnline), "Нет активности", "No activity shown");

// ── formatMethodsDetailed ───────────────────────────────────────────────────

console.log("\n📱 Format Methods Detailed");

assert(formatMethodsDetailed(null) === "❌ Нажмите 🔄 Обновить", "null handled");
const methodsMsg = formatMethodsDetailed(mockOnline);
assertIncludes(methodsMsg, "МЕТОДЫ ОНЛАЙН", "Header");
assertIncludes(methodsMsg, "ИТОГО:", "Total section");
assertIncludes(methodsMsg, "Оборот", "Volume in detailed");

// ── formatStats24h ──────────────────────────────────────────────────────────

console.log("\n📊 Format Stats 24h");

assert(formatStats24h(null) === "❌ Нажмите 🔄 Обновить", "null handled");

const mockStats = {
  stats: {
    general: { requisites_count: 30, total_orders: 500, successful: 200, issued: 300, volume: 5000000, conversion: 66.7 },
    byMethod: [
      { method: "sbp", requisites_count: 20, total_orders: 300, successful: 150, issued: 200, conversion: 75.0, volume: 3000000 },
    ]
  }
};

const statsMsg = formatStats24h(mockStats);
assertIncludes(statsMsg, "СТАТИСТИКА 24ч", "Header");
assertNotIncludes(statsMsg, "Трейдеров", "No traders");
assertIncludes(statsMsg, "Оборот", "Volume shown");
assertIncludes(statsMsg, "SBP", "Method shown");

// ── Conversion Icons ────────────────────────────────────────────────────────

console.log("\n🎨 Conversion Icons");

const makeOnline = (conv) => ({
  online: {
    summary: { requisites_count: 1, methods_count: 1, total_orders: 10, successful: 5, issued: 8, volume: 10000, conversion: conv },
    methodsSummary: [{ method: "sbp", requisites_count: 1, limits_detail: [{ min_check: 1000, max_check: 5000, count: 1, traders: [{ trader: "test", holder: "Тест" }] }], orders_count: 10, successful: 5, issued: 8, conversion: conv, volume: 10000 }]
  }
});

assertIncludes(formatOnlineNow(makeOnline(60)), "🟢", "High conv = green");
assertIncludes(formatOnlineNow(makeOnline(35)), "🟡", "Medium conv = yellow");
assertIncludes(formatOnlineNow(makeOnline(10)), "🔴", "Low conv = red");

// ── Per-Requisite Stats SQL ─────────────────────────────────────────────────

console.log("\n📋 Per-Requisite Stats SQL");

const perReqSql = getPerRequisiteStatsSQL("15 minutes");
assertIncludes(perReqSql, "FROM orders", "Per-req from real orders");
assertIncludes(perReqSql, "LEFT JOIN payments", "Per-req joins payments");
assertIncludes(perReqSql, "LEFT JOIN users", "Per-req joins users for trader name");
assertIncludes(perReqSql, "LEFT JOIN exchange_platforms", "Per-req joins exchange_platforms");
assertIncludes(perReqSql, "SUM(amount)", "Per-req calculates volume");
assertIncludes(perReqSql, "req_value", "Per-req returns req_value");
assertIncludes(perReqSql, "trader_name", "Per-req returns trader_name");
assertIncludes(perReqSql, "provider_name", "Per-req returns provider_name");
assertIncludes(perReqSql, "min_check", "Per-req returns min_check");
assertIncludes(perReqSql, "max_check", "Per-req returns max_check");
assertThrows(() => getPerRequisiteStatsSQL("invalid"), "Per-req SQL injection blocked");

// ── maskRequisite ──────────────────────────────────────────────────────────

console.log("\n🔒 maskRequisite");

assert(maskRequisite("79001234567") === "7900****4567", "Masks phone number");
assert(maskRequisite("1234567890123456") === "1234****3456", "Masks card number");
assert(maskRequisite("short") === "short", "Short values not masked");
assert(maskRequisite("7 900 111 22 33") === "7900****2233", "Strips spaces before masking");
assert(maskRequisite(null) === "—", "Null returns dash");
assert(maskRequisite("") === "—", "Empty returns dash");

// ── formatRequisitesDetail ─────────────────────────────────────────────────

console.log("\n📋 Format Requisites Detail");

assert(formatRequisitesDetail(null) === "❌ Нажмите 🔄 Обновить", "null handled");
assert(formatRequisitesDetail({}) === "❌ Нажмите 🔄 Обновить", "empty handled");

const mockReqDetail = {
  requisitesDetail: {
    byMethod: {
      sbp: [
        { req_value: "79001112233", orders: 10, successful: 7, issued: 9, volume: 45000, trader_name: "trader_alpha", provider_name: "", min_check: 500, max_check: 5000 },
        { req_value: "79123456789", orders: 5, successful: 3, issued: 4, volume: 120000, trader_name: "trader_beta", provider_name: "Provider X", min_check: 11000, max_check: 20000 },
        { req_value: "79005556677", orders: 2, successful: 1, issued: 2, volume: 180000, trader_name: "", provider_name: "Provider Y", min_check: 50000, max_check: 200000 },
      ],
      card: [
        { req_value: "4111111111111111", orders: 8, successful: 4, issued: 6, volume: 95000, trader_name: "trader1", provider_name: "", min_check: 1000, max_check: 50000 },
      ],
    },
    totals: { requisites: 4, methods: 2, orders: 25, successful: 15, issued: 21, volume: 440000 }
  }
};

const reqMsg = formatRequisitesDetail(mockReqDetail);
assertIncludes(reqMsg, "ДЕТАЛИ РЕКВИЗИТОВ", "Header present");
assertIncludes(reqMsg, "Реквизитов: <b>4</b>", "Total requisites");
assertIncludes(reqMsg, "SBP", "Method shown");
assertIncludes(reqMsg, "CARD", "Card method shown");
assertIncludes(reqMsg, "7900****2233", "Masked requisite shown");
assertIncludes(reqMsg, "trader_alpha", "Trader name shown");
assertIncludes(reqMsg, "Provider Y", "Provider name shown");
assertIncludes(reqMsg, "Оборот", "Volume shown");
assertIncludes(reqMsg, "Конверсия", "Conversion shown");
assertIncludes(reqMsg, "500", "Min check shown");
assertIncludes(reqMsg, "трейд.", "Traders count shown");

const emptyReqDetail = {
  requisitesDetail: {
    byMethod: {},
    totals: { requisites: 0, methods: 0, orders: 0, successful: 0, issued: 0, volume: 0 }
  }
};
assertIncludes(formatRequisitesDetail(emptyReqDetail), "Нет активности", "Empty shows no activity");

// ── Cache ───────────────────────────────────────────────────────────────────

console.log("\n💾 Cache");

assert(CONFIG.ONLINE_INTERVAL === 15, "Online interval 15min");

// ── Summary ─────────────────────────────────────────────────────────────────

console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);

if (failed > 0) process.exit(1);
process.exit(0);
