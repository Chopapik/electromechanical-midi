#!/usr/bin/env bash
#
# Uruchamia caly lokalny player:
#   - backend FastAPI (python -m host.web.server) na porcie 8000
#   - frontend Vite (npm run dev) na porcie 5173
#
# Uzycie:
#   ./scripts/dev.sh              # backend + frontend dev
#   ./scripts/dev.sh --no-hardware
#   ./scripts/dev.sh --port 9000
#
# Ctrl+C konczy oba procesy.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "BLAD: nie widze npm (Node.js). Zainstaluj Node 18+." >&2
  exit 1
fi

if [[ ! -d "$ROOT/web/node_modules" ]]; then
  echo "==> Instaluje zaleznosci frontendu (npm install)"
  (cd "$ROOT/web" && npm install --no-audit --no-fund)
fi

backend_pid=""
frontend_pid=""

cleanup() {
  echo
  echo "==> Zatrzymuje..."

  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true

  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "==> Backend:  http://$BACKEND_HOST:$BACKEND_PORT"
"$PYTHON" -m host.web.server --host "$BACKEND_HOST" --port "$BACKEND_PORT" "$@" &
backend_pid=$!

echo "==> Frontend: http://127.0.0.1:$FRONTEND_PORT  (Vite, proxy /api i /ws -> backend)"
(cd "$ROOT/web" && npm run dev -- --port "$FRONTEND_PORT" --strictPort) &
frontend_pid=$!

echo
echo "Otwórz: http://127.0.0.1:$FRONTEND_PORT"
echo "Ctrl+C konczy oba procesy."
echo

wait -n "$backend_pid" "$frontend_pid" 2>/dev/null || wait
