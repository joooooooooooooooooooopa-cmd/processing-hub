import fs from "fs";
import path from "path";
import { chromium } from "playwright";

const START_URL = "https://docs.example.com/";
const OUT_DIR = path.join(process.cwd(), "docs");
const OUT_TXT = path.join(OUT_DIR, "api_docs.txt");

// Ограничители, чтобы не уйти в бесконечность
const MAX_PAGES = 300;
const NAV_TIMEOUT_MS = 45000;

// Ссылки, которые обычно не нужно парсить как страницы доки
const SKIP_EXT = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".zip", ".css", ".js", ".map"]);

function normalizeUrl(u) {
  try {
    const url = new URL(u);
    url.hash = "";
    // ReadMe иногда использует параметры; оставим pathname+search
    return url.toString();
  } catch {
    return null;
  }
}

function shouldSkipUrl(u) {
  try {
    const url = new URL(u);
    if (url.hostname !== "docs.example.com") return true;

    const p = url.pathname.toLowerCase();
    for (const ext of SKIP_EXT) {
      if (p.endsWith(ext)) return true;
    }

    // Служебные разделы/поиск/логин и т.п. (при необходимости добавишь)
    if (p.includes("/auth")) return false; // это как раз важно в доке
    if (p.includes("/login")) return true;

    return false;
  } catch {
    return true;
  }
}

async function extractText(page) {
  // Пытаемся вытащить основное содержимое статьи
  const text = await page.evaluate(() => {
    const pick = (sel) => document.querySelector(sel);

    // Часто у ReadMe контент в <article> или в main
    const candidates = [
      "article",
      "main",
      "[data-testid='page-content']",
      ".rm-Content",
      ".HubPage-content",
      ".DocPage-content",
    ];

    let root = null;
    for (const sel of candidates) {
      const el = pick(sel);
      if (el && el.innerText && el.innerText.trim().length > 200) {
        root = el;
        break;
      }
    }

    if (!root) root = document.body;

    // Убираем мусорные элементы, если есть
    for (const sel of ["nav", "header", "footer", "aside"]) {
      root.querySelectorAll?.(sel)?.forEach((n) => n.remove());
    }

    const txt = (root.innerText || "").trim();
    return txt;
  });

  // Лёгкая чистка
  return text
    .replace(/\r/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

async function collectLinks(page) {
  const links = await page.evaluate(() => {
    return Array.from(document.querySelectorAll("a[href]"))
      .map((a) => a.getAttribute("href"))
      .filter(Boolean);
  });

  const abs = [];
  for (const href of links) {
    try {
      const u = new URL(href, page.url()).toString();
      abs.push(u);
    } catch {}
  }
  return abs;
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari",
  });
  const page = await context.newPage();

  const queue = [START_URL];
  const seen = new Set();
  const pages = [];

  while (queue.length && pages.length < MAX_PAGES) {
    const current = normalizeUrl(queue.shift());
    if (!current) continue;
    if (seen.has(current)) continue;
    if (shouldSkipUrl(current)) continue;

    seen.add(current);

    try {
      await page.goto(current, { waitUntil: "networkidle", timeout: NAV_TIMEOUT_MS });

      // Иногда нужно чуть подождать, чтобы контент точно прорисовался
      await page.waitForTimeout(600);

      const text = await extractText(page);

      // Пропускаем пустые/очень короткие страницы
      if (text.length > 200) {
        pages.push({ url: current, text });
        console.log(`[OK] ${pages.length} ${current} (${text.length} chars)`);
      } else {
        console.log(`[SKIP] ${current} (too short)`);
      }

      const links = await collectLinks(page);
      for (const l of links) {
        const n = normalizeUrl(l);
        if (!n) continue;
        if (!seen.has(n) && !shouldSkipUrl(n)) queue.push(n);
      }
    } catch (e) {
      console.log(`[ERR] ${current}: ${e?.message || e}`);
    }
  }

  await browser.close();

  // Собираем один текстовый файл для дальнейшего ingest
  const out = pages
    .map(
      (p, i) =>
        `=== PAGE ${i + 1} ===\nURL: ${p.url}\n\n${p.text}\n`
    )
    .join("\n\n");

  fs.writeFileSync(OUT_TXT, out, "utf8");

  console.log(`\nSaved: ${OUT_TXT}`);
  console.log(`Pages saved: ${pages.length}`);
  console.log(`Unique URLs seen: ${seen.size}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
