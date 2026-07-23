#!/usr/bin/env bash
# DataMosaic backend launcher
# Usage: ./scripts/start_backend.sh

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f "llm/.env" ]; then
    echo "[!] llm/.env not found. Copying from llm/.env.example ..."
    cp llm/.env.example llm/.env
    echo "[!] Please edit llm/.env with your API keys before continuing."
    exit 1
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5000}"
echo "[*] Starting DataMosaic backend on http://${HOST}:${PORT} (WebSocket: ws://localhost:8765) ..."
export HOST PORT
cd backend
exec python app.py
