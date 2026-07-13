#!/usr/bin/env bash
# Guard for `just test` and its variants.
#
# Three protections:
#
#   1. SLOW-LOCK — recipes that CAN run heavy (`slow`) tests refuse to start unless a
#                  *test-dedicated session* is open (scripts/test_session.sh, TTY-only).
#                  Slow suites take minutes; they are not part of the per-change loop.
#   2. LOCK      — refuse to start if another guarded test run is still alive. An
#                  atomic mkdir lock (.nadoc-test.lock/) holds the running pid+label.
#                  Overlapping runs saturate the CPU (pytest runs `-n auto`).
#   3. BUDGET    — agent-facing (fast-only) recipes must finish inside
#                  NADOC_TEST_BUDGET_SEC (default 60s). Over budget prints a loud
#                  banner pointing at the slow-candidate report so the offenders get
#                  relegated to the slow suite. The run's own pass/fail is unchanged.
#
# Usage: scripts/test_guard.sh <label> <gate:1|0> <slow:1|0> -- <command...>
#   gate=1   "is this really necessary?" confirm (non-interactive: NADOC_TEST_CONFIRM=1)
#   slow=1   the command CAN run slow tests -> requires an open test-dedicated session
#   slow=0   fast-only -> no session needed, but the wall-clock budget is enforced
#
# Escape hatches:
#   NADOC_TEST_CONFIRM=1     answer "yes" to the confirm gate up front (for agents)
#   NADOC_TEST_BUDGET_SEC=N  raise/lower the fast-suite wall-clock budget
#   NADOC_TEST_FORCE=1       bypass EVERYTHING (last resort; you own the fallout).
#                            Agents: this one is not yours to set — see CLAUDE.md.
set -uo pipefail

LABEL="${1:?label required}"; shift
GATE="${1:?gate flag required}"; shift
SLOW="${1:?slow flag required}"; shift
[[ "${1:-}" == "--" ]] && shift

LOCKDIR="${NADOC_TEST_LOCK:-.nadoc-test.lock}"
SESSION_MARKER="${NADOC_TEST_SESSION_FILE:-.nadoc-test-session}"
BUDGET="${NADOC_TEST_BUDGET_SEC:-60}"
CANDIDATES=".nadoc-slow-candidates.json"

hr='────────────────────────────────────────────────────────────────────'

if [[ "${NADOC_TEST_FORCE:-}" == "1" ]]; then
  echo "NADOC_TEST_FORCE=1 — bypassing test guard for '$LABEL'." >&2
  exec "$@"
fi

# ---- 1. Slow-lock: heavy suites need an open test-dedicated session ---------
session_open() {
  local exp
  [[ -f "$SESSION_MARKER" ]] || return 1
  exp="$(sed -n 1p "$SESSION_MARKER" 2>/dev/null || true)"
  [[ "$exp" =~ ^[0-9]+$ ]] || return 1
  (( exp > $(date +%s) ))
}

if [[ "$SLOW" == "1" ]] && ! session_open; then
  cat >&2 <<EOF
$hr
REFUSING to run '$LABEL': it can run SLOW tests (real oxDNA/NAMD/mrdna sims,
CanDo-FEM solves, trajectory benchmarks) and no test-dedicated session is open.

Slow suites take minutes and saturate the CPU/GPU. They are deliberately NOT part
of the per-change dev loop.

  Per-change loop (always allowed, <${BUDGET}s):
      just test-smart            # fast suite, scoped to what you changed
      just test-affected <file>  # tighter still

  To run the heavy suites, the USER opens a window in THEIR OWN terminal:
      just test-session          # 4h, TTY-only

Agents: ask the user to open a test-dedicated session. Do not create
$SESSION_MARKER yourself and do not set NADOC_TEST_FORCE.
$hr
EOF
  exit 1
fi

# ---- 2. Atomic lock acquire (with stale-lock reclaim) ----------------------
acquire_lock() {
  while true; do
    if mkdir "$LOCKDIR" 2>/dev/null; then
      { echo "$$"; echo "$LABEL"; date '+%Y-%m-%dT%H:%M:%S'; } > "$LOCKDIR/info"
      return 0
    fi
    # Lock exists — is its owner still alive?
    local pid label started
    pid="$(sed -n 1p "$LOCKDIR/info" 2>/dev/null || true)"
    label="$(sed -n 2p "$LOCKDIR/info" 2>/dev/null || true)"
    started="$(sed -n 3p "$LOCKDIR/info" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      cat >&2 <<EOF
$hr
REFUSING to start '$LABEL': a test run is already in progress.
  pid=$pid  label=${label:-?}  started=${started:-?}
Overlapping test runs saturate the CPU/GPU on this machine. Wait for the
running suite to finish, then retry. If you are certain that run is dead,
remove the stale lock:  rm -rf $LOCKDIR
$hr
EOF
      return 1
    fi
    # Owner is gone — reclaim the stale lock and loop to re-acquire.
    echo "Reclaiming stale test lock (pid ${pid:-?} gone)." >&2
    rm -rf "$LOCKDIR"
  done
}

acquire_lock || exit 1
cleanup() { rm -rf "$LOCKDIR"; }
trap cleanup EXIT INT TERM

# ---- 3. "Is this really necessary?" confirmation gate ----------------------
if [[ "$GATE" == "1" && "${NADOC_TEST_CONFIRM:-}" != "1" ]]; then
  if [[ -t 0 ]]; then
    printf '\nIs running '\''%s'\'' really necessary? It runs pytest across every core (and the GPU for sim/FEM groups). [y/N] ' "$LABEL" >&2
    read -r reply
    case "$reply" in
      y|Y|yes|YES) ;;
      *) echo "Aborted — no tests run." >&2; exit 1 ;;
    esac
  else
    cat >&2 <<EOF
$hr
Is running '$LABEL' really necessary?
Repeated/overlapping full-suite runs saturate the CPU/GPU on this machine.
Before re-running, consider a tighter loop that touches far fewer cores:
  just test-affected <file>   # only the area you edited
  just test-file <file>       # a single file
  just test-frontend          # JS only, no backend/GPU load
If this run really is necessary, opt in explicitly and re-invoke:
  NADOC_TEST_CONFIRM=1 just $LABEL
$hr
EOF
    exit 1
  fi
fi

# ---- 4. Run the wrapped command under the held lock, timed ------------------
START=$(date +%s)
"$@"
RC=$?
ELAPSED=$(( $(date +%s) - START ))

# ---- 5. Budget check (fast-only recipes) -----------------------------------
# A per-change suite that creeps past the budget is a *process* failure, not a test
# failure: something heavy leaked into the fast suite. Report it loudly — the fix is
# to relegate the offenders to the slow suite (.claude/skills/triage-slow-tests).
# (Inside a test-dedicated session even the slow=0 recipes may legitimately drain heavy
# groups — `just test-smart` does — so the budget is only enforced outside one.)
if session_open; then
  exit $RC
fi

if [[ "$SLOW" != "1" && "$ELAPSED" -gt "$BUDGET" ]]; then
  cat >&2 <<EOF

$hr
⚠  TEST BUDGET EXCEEDED — '$LABEL' took ${ELAPSED}s (budget ${BUDGET}s).

The per-change suite must stay under ${BUDGET}s or it stops being a per-change
suite. Something heavy has crept into it.

REQUIRED NEXT STEP (agents): launch the triage subagent — do not just move on.
    Agent tool, subagent_type "general-purpose", following
    .claude/skills/triage-slow-tests/SKILL.md
It reads the slowest-test report, decides which tests are genuinely heavy, and
relegates them to the slow suite (\`slow\` + area marker in tests/conftest.py) so
they only run in a test-dedicated session.

Slowest unmarked tests: $CANDIDATES
$hr
EOF
elif [[ "$SLOW" != "1" ]]; then
  printf '\ntest budget: %ss / %ss ok\n' "$ELAPSED" "$BUDGET" >&2
fi

exit $RC
