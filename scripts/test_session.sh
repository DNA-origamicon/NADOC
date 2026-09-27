#!/usr/bin/env bash
# Test-dedicated session unlock.
#
# Unlocks full/broad regression sweeps, including unrelated long tests. It is not
# required for focused tests or benchmarks directly related to current development,
# regardless of duration or the slow marker. Use `just test-focused TARGET` for those.
# The user deliberately opens a window in their terminal for the broad sweep.
#
#   just test-session         # open a 4-hour window (default)
#   just test-session 1       # open a 1-hour window
#   just test-session status  # is one open? how long left?
#   just test-session off     # close it now
#
# The window is a marker file (.nadoc-test-session, gitignored) holding an expiry
# timestamp. scripts/test_guard.sh refuses broad/full sweep recipes unless the
# marker exists and is unexpired.
#
# WHY A TTY IS REQUIRED: an agent can set any environment variable it likes, so an
# env-var unlock is no unlock at all. Opening the window requires an interactive
# terminal — i.e. a human. Agents request a window only for a necessary broad/full sweep.
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
    echo "test-dedicated session: EXPIRED $(( -left / 60 ))m ago — broad suites are locked."
    return 1
  fi
  echo "test-dedicated session: OPEN — $(( left / 60 ))m left (expires $(date -d "@$exp" '+%H:%M'))"
  return 0
}

case "${1:-}" in
  status) status; exit $? ;;
  off|close|end)
    rm -f "$MARKER"
    echo "test-dedicated session closed — broad suites are locked again."
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

For focused current-development checks, use just test-focused TARGET; no session
is needed, even for slow tests. For a broad/full sweep, ask the user to run

    just test-session

in their own terminal. Then run the broad suite. Do NOT create the
.nadoc-test-session marker yourself and do NOT set NADOC_TEST_FORCE — that
defeats the guard this project deliberately put in place.
────────────────────────────────────────────────────────────────────
EOF
  exit 1
fi

EXPIRY=$(( $(now) + HOURS * 3600 ))
{ echo "$EXPIRY"; date '+%Y-%m-%dT%H:%M:%S'; echo "${HOURS}h"; } > "$MARKER"
echo "test-dedicated session OPEN for ${HOURS}h (until $(date -d "@$EXPIRY" '+%H:%M'))."
echo "Broad suites are now unlocked:  just test  ·  just test-slow  ·  just test-smart"
echo "Close early with:  just test-session off"
