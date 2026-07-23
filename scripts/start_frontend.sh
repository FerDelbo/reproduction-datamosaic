#!/usr/bin/env bash
# DataMosaic frontend launcher
# Usage: ./scripts/start_frontend.sh

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/frontend"

if [ ! -d "node_modules" ]; then
    echo "[*] Installing frontend dependencies (this may take a few minutes)..."
    npm install
fi

echo "[*] Starting DataMosaic frontend on http://localhost:3000 ..."
exec npm start
