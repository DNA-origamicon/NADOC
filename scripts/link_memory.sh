#!/usr/bin/env bash
# Point Claude Code's per-machine auto-memory dir at this repo's tracked memory/.
#
# Claude Code reads/writes memory at ~/.claude/projects/<slug>/memory/, which is
# local to each machine and NOT in git. This repo keeps the real memory files in
# ./memory/ (tracked). Run this once on each computer so Claude's auto-memory IS
# the tracked folder — then memory edits land in git and sync via push/pull.
#
# Safe to re-run. Backs up any existing real dir to memory.pre-symlink-bak.
set -euo pipefail

REPO_MEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/memory"
SLUG="-home-joshua-NADOC"   # matches ~/.claude/projects/<slug>; change if your path differs
AUTO="$HOME/.claude/projects/$SLUG/memory"

mkdir -p "$(dirname "$AUTO")"

if [ -L "$AUTO" ]; then
  echo "Already a symlink -> $(readlink "$AUTO"); re-pointing."
  rm "$AUTO"
elif [ -e "$AUTO" ]; then
  echo "Backing up existing $AUTO -> ${AUTO}.pre-symlink-bak"
  mv "$AUTO" "${AUTO}.pre-symlink-bak"
fi

ln -s "$REPO_MEM" "$AUTO"
echo "Linked $AUTO -> $REPO_MEM"
