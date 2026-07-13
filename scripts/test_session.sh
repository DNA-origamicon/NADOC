#!/usr/bin/env bash
# Test-dedicated session unlock.
#
# The heavy (`slow`-marked) suites — real oxDNA/NAMD/mrdna sims, CanDo-FEM solves,
# trajectory/benchmark runs — take minutes and saturate CPU/GPU. They are NOT part
# of the per-change dev loop. They run ONLY inside a *test-dedicated session*: a
# window YOU open, on purpose, in YOUR terminal.
#
#   just test-session         # open a 4-hour window (default)
#   just test-session 1       # open a 1-hour window
#   just test-session status  # is one open? how long left?
#   just test-session off     # close it now
#
# The window is a marker file (.nadoc-test-session, gitignored) holding an expiry
# timestamp. scripts/test_guard.sh refuses every slow-capable recipe unless the
# marker exists and is unexpired.
#
# WHY A TTY IS REQUIRED: an agent can set any environment variable it likes, so an
# env-var unlock is no unlock at all. Opening the window requires an interactive
# terminal — i.e. a human. An agent that wants slow tests must ASK you to open one.
# (Agents: do not hand-write .nadoc-test-session. That is the same as disabling the
# guard, and it is forbidden — see CLAUDE.md → Test policy.)
set -uo pipefail

MARKER="${NADOC_TEST_SESSION_FILE:-.nadoc-test-session}"
DEFAULT_HOURS=4

now() { date +%s; }

read_expiry() {
  [[ -f "$MARKER" ]] || return 1
  local exp
  exp="$(sed -n 1p "$MARKER" 2>/dev/null || true)"
  [[ "$exp" =~ ^[0-9]+$ ]] || return 1
  echo "$exp"
}

status() {
  local exp left
  if ! exp="$(read_expiry)"; then
    echo "test-dedicated session: CLOSED (no $MARKER)"
    return 1
  fi
  left=$(( exp - $(now) ))
  if (( left <= 0 )); then
    echo "test-dedicated session: EXPIRED $(( -left / 60 ))m ago — slow suites are locked."
    return 1
  fi
  echo "test-dedicated session: OPEN — $(( left / 60 ))m left (expires $(date -d "@$exp" '+%H:%M'))"
  return 0
}

case "${1:-}" in
  status) status; exit $? ;;
  off|close|end)
    rm -f "$MARKER"
    echo "test-dedicated session closed — slow suites are locked again."
    exit 0
    ;;
esac

HOURS="${1:-$DEFAULT_HOURS}"
if ! [[ "$HOURS" =~ ^[0-9]+$ ]] || (( HOURS < 1 || HOURS > 24 )); then
  echo "usage: just test-session [HOURS 1-24 | status | off]" >&2
  exit 2
fi

if [[ ! -t 0 ]]; then
  cat >&2 <<'EOF'
────────────────────────────────────────────────────────────────────
REFUSED: a test-dedicated session can only be opened from an interactive
terminal (a human at a keyboard).

If you are an agent: STOP and ask the user to run

    just test-session

in their own terminal. Then re-run the slow suite. Do NOT create the
.nadoc-test-session marker yourself and do NOT set NADOC_TEST_FORCE — that
defeats the guard this project deliberately put in place.
────────────────────────────────────────────────────────────────────
EOF
  exit 1
fi

EXPIRY=$(( $(now) + HOURS * 3600 ))
{ echo "$EXPIRY"; date '+%Y-%m-%dT%H:%M:%S'; echo "${HOURS}h"; } > "$MARKER"
echo "test-dedicated session OPEN for ${HOURS}h (until $(date -d "@$EXPIRY" '+%H:%M'))."
echo "Slow suites are now unlocked:  just test  ·  just test-slow  ·  just test-smart"
echo "Close early with:  just test-session off"
