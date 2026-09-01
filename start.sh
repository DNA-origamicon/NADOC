#!/usr/bin/env bash
#
# Start NADOC: runs the backend (port 8000) and the web frontend (port 5173)
# together in one window. Press Ctrl-C to stop both.
#
# First time? Run ./setup.sh once before this.
#
# Usage:
#   ./start.sh          # local machine only (default)
#   ./start.sh --tailscale # expose localhost through private Tailscale HTTPS
#   ./start.sh --lan    # explicitly expose to a trusted local network
#
set -euo pipefail

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '\033[1;34m›\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

BACKEND_HOST="127.0.0.1"
FRONTEND_HOST="127.0.0.1"
PUBLIC_URL="http://localhost:5173"
LAN_MODE=0
TAILSCALE_MODE=0
TAILSCALE_SERVE_CONFIGURED=0
case "${1:-}" in
  "") ;;
  --lan) BACKEND_HOST="0.0.0.0"; FRONTEND_HOST="0.0.0.0"; LAN_MODE=1 ;;
  --tailscale) TAILSCALE_MODE=1 ;;
  *) die "Unknown option: $1 (supported: --tailscale, --lan)" ;;
esac
[ "$#" -le 1 ] || die "Too many arguments (supported: --tailscale, --lan)"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

have uv   || die "uv not found. Run ./setup.sh first."
have node || die "Node.js not found. Run ./setup.sh first."
[ -d frontend/node_modules ] || die "Frontend deps missing. Run ./setup.sh first."

if [ "$TAILSCALE_MODE" -eq 1 ]; then
  if have tailscale; then
    TAILSCALE_CMD=(tailscale)
  elif have tailscale.exe; then
    # Recommended WSL2 layout: Tailscale runs once, on the Windows host.
    # Windows Tailscale Serve reaches WSL through localhost forwarding.
    TAILSCALE_CMD=(tailscale.exe)
  else
    die "Tailscale CLI not found. Install and connect Tailscale first."
  fi
  TAILSCALE_IP="$("${TAILSCALE_CMD[@]}" ip -4 2>/dev/null | tr -d '\r' | head -n 1)"
  [ -n "$TAILSCALE_IP" ] || die "No Tailscale IPv4 address found. Is Tailscale connected?"
  TAILSCALE_DNS_NAME="$("${TAILSCALE_CMD[@]}" status --json 2>/dev/null \
    | uv run python -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
  [ -n "$TAILSCALE_DNS_NAME" ] || die "Could not determine this computer's Tailscale DNS name."
  PUBLIC_URL="https://${TAILSCALE_DNS_NAME}:5173"
  export NADOC_PUBLIC_URL="$PUBLIC_URL"
  TOKEN_FILE=".nadoc-peer-token"
  if [ ! -f "$TOKEN_FILE" ]; then
    umask 077
    uv run python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$TOKEN_FILE"
  fi
  chmod 600 "$TOKEN_FILE"
  export NADOC_PEER_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
fi

BACKEND_PID=""
FRONTEND_PID=""
# Some dev-server children temporarily alter terminal flags. Preserve the
# caller's exact state so Ctrl-C cannot leave VS Code's integrated terminal
# with input echo disabled or in a raw-ish mode.
TTY_STATE="$(stty -g 2>/dev/null || true)"
terminate_tree() {
  local pid="$1" child
  [ -n "$pid" ] || return 0
  if have pgrep; then
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
      terminate_tree "$child"
    done
  fi
  kill "$pid" 2>/dev/null || true
}
cleanup() {
  trap - INT TERM EXIT
  info "Shutting down…"
  terminate_tree "$FRONTEND_PID"
  terminate_tree "$BACKEND_PID"
  if [ "$TAILSCALE_SERVE_CONFIGURED" -eq 1 ]; then
    "${TAILSCALE_CMD[@]}" serve --https=5173 off >/dev/null 2>&1 || true
  fi
  wait 2>/dev/null || true
  if [ -n "$TTY_STATE" ]; then
    stty "$TTY_STATE" 2>/dev/null || stty sane 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

bold "Starting NADOC…"

if [ "$LAN_MODE" -eq 1 ]; then
  printf '\033[1;33m⚠ LAN mode: NADOC has no user authentication. Use only on a trusted network.\033[0m\n' >&2
  info "Remote devices may connect to this computer's LAN address."
elif [ "$TAILSCALE_MODE" -eq 1 ]; then
  info "Tailscale-only mode. Tailnet ACLs control who can open NADOC."
  info "The backend remains loopback-only; the frontend proxies API requests."
else
  info "Local-only mode (use ./start.sh --tailscale for private remote access)."
fi

info "Backend  → http://localhost:8000"
uv run uvicorn backend.api.main:app --host "$BACKEND_HOST" --port 8000 &
BACKEND_PID=$!

# Uvicorn opens the health endpoint only after FastAPI's lifespan startup has
# completed. Do not expose the Vite app before that point: its one-shot welcome
# library request otherwise sees the proxy/backend as unavailable and paints an
# empty workspace until the user manually refreshes.
info "Waiting for backend startup…"
uv run python - "http://127.0.0.1:8000/api/health" "$BACKEND_PID" <<'PY'
import os
import sys
import time
import urllib.request

url = sys.argv[1]
pid = int(sys.argv[2])
deadline = time.monotonic() + 120.0
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            if response.status == 200:
                raise SystemExit(0)
    except Exception:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        print("Backend exited before becoming ready.", file=sys.stderr)
        raise SystemExit(1)
    time.sleep(0.2)
print("Backend did not become ready within 120 seconds.", file=sys.stderr)
raise SystemExit(1)
PY
info "Backend ready."

info "Frontend → http://localhost:5173"
( cd frontend && npm run dev -- --host "$FRONTEND_HOST" ) &
FRONTEND_PID=$!

if [ "$TAILSCALE_MODE" -eq 1 ]; then
  info "Tailscale Serve → $PUBLIC_URL"
  "${TAILSCALE_CMD[@]}" serve --bg --https=5173 http://127.0.0.1:5173 \
    || die "Could not configure Tailscale HTTPS Serve."
  TAILSCALE_SERVE_CONFIGURED=1
fi

echo
bold "NADOC is starting. Open this in your browser:"
echo
echo "    $PUBLIC_URL"
if [ "$TAILSCALE_MODE" -eq 1 ]; then
  echo "    http://localhost:5173  (this computer only)"
fi
echo
echo "(Give it a few seconds the first time. Press Ctrl-C here to stop.)"
echo

# Keep both servers running until you press Ctrl-C (portable to macOS bash 3.2).
wait 2>/dev/null || true
