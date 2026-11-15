#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f "auth.sqlite" ]; then
  node auth_init.mjs
fi

if [ ! -d "node_modules" ]; then
  npm install
fi

node index.mjs
