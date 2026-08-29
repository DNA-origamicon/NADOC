#!/usr/bin/env bash
#
# Start NADOC: runs the backend (port 8000) and the web frontend (port 5173)
# together in one window. Press Ctrl-C to stop both.
#
# First time? Run ./setup.sh once before this.
#
# Usage:
#   ./start.sh          # local machine only (default)
#   ./start.sh --tailscale # expose the frontend only on this machine's tailnet IP
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
TAILSCALE_WINDOWS_PROXY=0
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
    # Windows Tailscale Serve reaches WSL through its localhost forwarding.
    TAILSCALE_CMD=(tailscale.exe)
    TAILSCALE_WINDOWS_PROXY=1
  else
    die "Tailscale CLI not found. Install and connect Tailscale first."
  fi
  TAILSCALE_IP="$("${TAILSCALE_CMD[@]}" ip -4 2>/dev/null | tr -d '\r' | head -n 1)"
  if [ "$TAILSCALE_WINDOWS_PROXY" -eq 0 ]; then
    FRONTEND_HOST="$TAILSCALE_IP"
  fi
  [ -n "$TAILSCALE_IP" ] || die "No Tailscale IPv4 address found. Is Tailscale connected?"
  PUBLIC_URL="http://${TAILSCALE_IP}:5173"
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
cleanup() {
  trap - INT TERM EXIT
  info "Shutting down…"
  [ -n "$FRONTEND_PID" ] && { pkill -P "$FRONTEND_PID" 2>/dev/null || true; kill "$FRONTEND_PID" 2>/dev/null || true; }
  [ -n "$BACKEND_PID"  ] && kill "$BACKEND_PID" 2>/dev/null || true
  if [ "$TAILSCALE_SERVE_CONFIGURED" -eq 1 ]; then
    "${TAILSCALE_CMD[@]}" serve --http=5173 off >/dev/null 2>&1 || true
  fi
  wait 2>/dev/null || true
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

info "Frontend → http://localhost:5173"
( cd frontend && npm run dev -- --host "$FRONTEND_HOST" ) &
FRONTEND_PID=$!

if [ "$TAILSCALE_WINDOWS_PROXY" -eq 1 ]; then
  info "Tailscale Serve → http://${TAILSCALE_IP}:5173"
  "${TAILSCALE_CMD[@]}" serve --bg --http=5173 http://127.0.0.1:5173 \
    || die "Could not configure Windows Tailscale Serve."
  TAILSCALE_SERVE_CONFIGURED=1
fi

echo
bold "NADOC is starting. Open this in your browser:"
echo
echo "    $PUBLIC_URL"
echo
echo "(Give it a few seconds the first time. Press Ctrl-C here to stop.)"
echo

# Keep both servers running until you press Ctrl-C (portable to macOS bash 3.2).
wait 2>/dev/null || true
