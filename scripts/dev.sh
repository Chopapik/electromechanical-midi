#!/usr/bin/env bash
#
# Uruchamia caly lokalny player:
#   - backend FastAPI (python -m host.web.server) na porcie 8000
#   - frontend Vite (npm run dev) na porcie 5173
#
# Uzycie:
#   ./scripts/dev.sh              # real hardware, Serial + frontend dev
#   ./scripts/dev.sh --no-hardware # developer virtual/audio preview (no Serial)
#   ./scripts/dev.sh --port 9000
#
# Ctrl+C konczy oba procesy.
# Backend ustala runtime mode z --no-hardware; Settings wybiera tylko enabled devices.

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

# Refuse to attach the UI to an older backend with a different runtime mode.
"$PYTHON" - "$BACKEND_HOST" "$BACKEND_PORT" "$FRONTEND_PORT" "$@" <<'PY'
import socket
import sys

host, backend, frontend, *args = sys.argv[1:]
for index, arg in enumerate(args[:-1]):
    if arg == '--port':
        backend = args[index + 1]
    elif arg == '--host':
        host = args[index + 1]
for label, address, port in (('Backend', host, backend), ('Frontend', '127.0.0.1', frontend)):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((address, int(port)))
        except OSError as exc:
            sys.exit(f'BLAD: {label}: {address}:{port} jest zajety lub niedostepny ({exc}). '
                     'Zatrzymaj poprzednia aplikacje przed uruchomieniem nowej.')
PY

backend_pid=""
frontend_pid=""

stop_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    stop_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  echo
  echo "==> Zatrzymuje..."

  [[ -n "$frontend_pid" ]] && stop_tree "$frontend_pid"
  [[ -n "$backend_pid" ]] && stop_tree "$backend_pid"

  wait 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

# macOS ships Bash 3.2, which has no wait -n. Exit when either server exits.
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 0.5
done
if ! kill -0 "$backend_pid" 2>/dev/null; then
  wait "$backend_pid"
else
  wait "$frontend_pid"
fi
