#!/usr/bin/env bash
#
# NADOC one-command setup.
#
# This installs everything NADOC needs and then installs the project itself.
# It is safe to run more than once — anything already installed is skipped.
#
#   What it installs (only if missing):
#     • uv   — Python package/venv manager (also auto-downloads Python 3.12)
#     • Node.js + npm — runs the web frontend
#     • just — short command runner (just dev / just test / ...)
#   Then it:
#     • creates a private Python environment and installs all Python deps (uv sync)
#     • installs all frontend deps (npm install)
#
# Supported: Linux, Windows-via-WSL2 (Ubuntu), and macOS.
# Windows users: run this INSIDE your Ubuntu/WSL2 window, not PowerShell.
#
# Usage:
#   ./setup.sh
#
set -euo pipefail

# ── pretty output ─────────────────────────────────────────────────────────────
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '\033[1;34m›\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

# Always work from the repo root (the folder this script lives in).
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Make sure tools we install into ~/.local/bin are visible immediately.
export PATH="$HOME/.local/bin:$PATH"

# ── detect platform ───────────────────────────────────────────────────────────
case "$(uname -s)" in
  Linux*)  PLATFORM=linux ;;
  Darwin*) PLATFORM=mac ;;
  *)
    die "Unsupported OS '$(uname -s)'. On Windows, install WSL2 (see INSTALL.md) and run this inside Ubuntu."
    ;;
esac

IS_WSL=0
if [ "$PLATFORM" = linux ] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
  IS_WSL=1
fi

bold "NADOC setup"
if [ "$IS_WSL" = 1 ]; then info "Detected: Windows (WSL2 / Ubuntu)"
elif [ "$PLATFORM" = mac ]; then info "Detected: macOS"
else info "Detected: Linux"
fi
echo

# ── macOS: Homebrew (used to install node/just) ───────────────────────────────
if [ "$PLATFORM" = mac ] && ! have brew; then
  info "Installing Homebrew (the macOS package installer)…"
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Put brew on PATH for the rest of this run (Apple Silicon vs Intel paths).
  if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)";
  elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
  ok "Homebrew installed"
fi

# ── Linux: a couple of base packages curl-installers rely on ──────────────────
if [ "$PLATFORM" = linux ] && have apt-get; then
  if ! have curl || ! dpkg -s ca-certificates >/dev/null 2>&1; then
    info "Installing base tools (curl, ca-certificates) — may ask for your password…"
    sudo apt-get update -y
    sudo apt-get install -y curl ca-certificates
    ok "Base tools ready"
  fi
fi

# ── uv (Python manager; also fetches Python 3.12 automatically) ───────────────
if have uv; then
  ok "uv already installed ($(uv --version))"
else
  info "Installing uv (Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  have uv || die "uv installed but not found on PATH. Open a new terminal and re-run ./setup.sh"
  ok "uv installed ($(uv --version))"
fi

# ── Node.js + npm (needs v18 or newer) ────────────────────────────────────────
node_major() { node -v 2>/dev/null | sed -E 's/v([0-9]+).*/\1/'; }
NODE_OK=0
if have node && [ "$(node_major)" -ge 18 ] 2>/dev/null; then NODE_OK=1; fi

if [ "$NODE_OK" = 1 ]; then
  ok "Node.js already installed ($(node -v))"
else
  info "Installing Node.js…"
  if [ "$PLATFORM" = mac ]; then
    brew install node
  elif have apt-get; then
    # NodeSource ships a current LTS (newer than Ubuntu's default).
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
  else
    die "Couldn't auto-install Node.js on this Linux distro. Install Node.js 18+ manually, then re-run ./setup.sh"
  fi
  have node || die "Node.js install finished but 'node' isn't on PATH. Open a new terminal and re-run ./setup.sh"
  ok "Node.js installed ($(node -v), npm $(npm -v))"
fi

# ── just (command runner) ─────────────────────────────────────────────────────
if have just; then
  ok "just already installed ($(just --version))"
else
  info "Installing just (command runner)…"
  if [ "$PLATFORM" = mac ]; then
    brew install just
  else
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
      | bash -s -- --to "$HOME/.local/bin"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  have just || warn "just installed to ~/.local/bin but not yet on PATH (a new terminal will pick it up)."
  ok "just installed"
fi

echo
# ── Python deps ───────────────────────────────────────────────────────────────
info "Setting up Python environment + installing backend deps (this can take a few minutes)…"
# --inexact: install everything the project needs without removing any extra
# tools you've added yourself (e.g. ruff/coverage), so re-running is non-destructive.
uv sync --inexact
ok "Python environment ready (.venv)"

echo
# ── Frontend deps ─────────────────────────────────────────────────────────────
info "Installing frontend deps (npm install)…"
( cd frontend && npm install )
ok "Frontend deps installed"

echo
bold "Setup complete 🎉"
echo
echo "Start NADOC with:"
echo
echo "    ./start.sh"
echo
echo "Then open  http://localhost:5173  in your browser."
if [ "$IS_WSL" = 1 ]; then
  echo
  warn "On older WSL2, localhost may not work — see the WSL2 networking note in INSTALL.md."
fi
if ! have just; then
  echo
  warn "Open a fresh terminal before using 'just' commands so PATH updates take effect."
fi
