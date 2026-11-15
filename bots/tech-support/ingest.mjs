import "dotenv/config";
import fs from "fs";
import path from "path";
import Database from "better-sqlite3";
import OpenAI from "openai";

const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const DB_PATH = path.join(process.cwd(), "rag.sqlite");
const DOC_PATH = path.join(process.cwd(), "docs", "api_docs.txt");
const EMBEDDING_MODEL = "text-embedding-3-small";

function chunkText(text, maxChars = 2000, overlap = 200) {
  const paras = text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  const chunks = [];
  let buf = "";

  for (const p of paras) {
    if ((buf + "\n\n" + p).length <= maxChars) {
      buf = buf ? buf + "\n\n" + p : p;
    } else {
      if (buf) chunks.push(buf);
      if (overlap > 0 && buf) {
        const tail = buf.slice(Math.max(0, buf.length - overlap));
        buf = tail + "\n\n" + p;
      } else {
        buf = p;
      }
    }
  }
  if (buf) chunks.push(buf);
  return chunks;
}

async function embed(text) {
  const res = await client.embeddings.create({
    model: EMBEDDING_MODEL,
    input: text,
  });
  return res.data[0].embedding;
}

function initDb(db) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS chunks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL,
      content TEXT NOT NULL,
      embedding_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
  `);
}

async function main() {
  if (!fs.existsSync(DOC_PATH)) {
    throw new Error(`Нет файла документации: ${DOC_PATH}`);
  }
  const docText = fs.readFileSync(DOC_PATH, "utf8");
  const chunks = chunkText(docText, 2000, 200);

  console.log(`Chunks: ${chunks.length}`);

  const db = new Database(DB_PATH);
  initDb(db);

  db.prepare("DELETE FROM chunks WHERE source = ?").run("api_docs");

  const insert = db.prepare(
    "INSERT INTO chunks (source, content, embedding_json) VALUES (?, ?, ?)"
  );

  for (let i = 0; i < chunks.length; i++) {
    const content = chunks[i];
    const embedding = await embed(content);
    insert.run("api_docs", content, JSON.stringify(embedding));
    if ((i + 1) % 10 === 0) console.log(`Embedded ${i + 1}/${chunks.length}`);
  }

  db.close();
  console.log("Done. Saved to rag.sqlite");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

