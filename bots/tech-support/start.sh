#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "== TechSupportBot =="
echo "Dir: $(pwd)"

# Проверка файлов
if [ ! -f ".env" ]; then
  echo "ERROR: .env not found"
  exit 1
fi

if [ ! -f "auth.sqlite" ]; then
  echo "auth.sqlite not found -> init"
  node auth_init.mjs
fi

# Установка зависимостей (если вдруг папку перенесли)
if [ ! -d "node_modules" ]; then
  echo "node_modules not found -> npm install"
  npm install
fi

# Обновление базы знаний (по желанию можно отключить)
echo "Reindex docs -> rag.sqlite"
node ingest.mjs

echo "Start bot"
node index.mjs
