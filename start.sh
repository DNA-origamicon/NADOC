#!/usr/bin/env bash
#
# Start NADOC: runs the backend (port 8000) and the web frontend (port 5173)
# together in one window. Press Ctrl-C to stop both.
#
# First time? Run ./setup.sh once before this.
#
# Usage:
#   ./start.sh          # local machine only (default)
#   ./start.sh --lan    # explicitly expose to a trusted local network
#
set -euo pipefail

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '\033[1;34m›\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

HOST="127.0.0.1"
LAN_MODE=0
case "${1:-}" in
  "") ;;
  --lan) HOST="0.0.0.0"; LAN_MODE=1 ;;
  *) die "Unknown option: $1 (supported: --lan)" ;;
esac
[ "$#" -le 1 ] || die "Too many arguments (supported: --lan)"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

have uv   || die "uv not found. Run ./setup.sh first."
have node || die "Node.js not found. Run ./setup.sh first."
[ -d frontend/node_modules ] || die "Frontend deps missing. Run ./setup.sh first."

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  trap - INT TERM EXIT
  info "Shutting down…"
  [ -n "$FRONTEND_PID" ] && { pkill -P "$FRONTEND_PID" 2>/dev/null || true; kill "$FRONTEND_PID" 2>/dev/null || true; }
  [ -n "$BACKEND_PID"  ] && kill "$BACKEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

bold "Starting NADOC…"

if [ "$LAN_MODE" -eq 1 ]; then
  printf '\033[1;33m⚠ LAN mode: NADOC has no user authentication. Use only on a trusted network.\033[0m\n' >&2
  info "Remote devices may connect to this computer's LAN address."
else
  info "Local-only mode (use ./start.sh --lan to opt in to trusted-LAN access)."
fi

info "Backend  → http://localhost:8000"
uv run uvicorn backend.api.main:app --host "$HOST" --port 8000 &
BACKEND_PID=$!

info "Frontend → http://localhost:5173"
( cd frontend && npm run dev -- --host "$HOST" ) &
FRONTEND_PID=$!

echo
bold "NADOC is starting. Open this in your browser:"
echo
echo "    http://localhost:5173"
echo
echo "(Give it a few seconds the first time. Press Ctrl-C here to stop.)"
echo

# Keep both servers running until you press Ctrl-C (portable to macOS bash 3.2).
wait 2>/dev/null || true
