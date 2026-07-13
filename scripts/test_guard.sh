#!/usr/bin/env bash
# Guard for `just test` and its variants.
#
# Repeatedly / concurrently invoking the test suites saturates the CPU (pytest
# runs `-n auto` across every core) and, for the sim/FEM groups, the GPU. Two
# protections:
#
#   1. LOCK  — refuse to start if another guarded test run is still alive. An
#              atomic mkdir lock (.nadoc-test.lock/) holds the running pid+label.
#   2. GATE  — a deliberate "is this really necessary?" prompt on the heavy
#              full-suite variants. Interactive callers answer y/N; non-interactive
#              callers (agents / CI) must opt in with NADOC_TEST_CONFIRM=1.
#
# Usage: scripts/test_guard.sh <label> <gate:1|0> -- <command...>
#   gate=1  lock + confirm  (full-suite variants: test, test-fast, test-smart, test-all)
#   gate=0  lock only       (tight loops: test-affected, test-file)
#
# Escape hatches:
#   NADOC_TEST_CONFIRM=1   answer "yes" to the gate up front (for agents)
#   NADOC_TEST_FORCE=1     bypass BOTH lock and gate (last resort; you own the fallout)
set -uo pipefail

LABEL="${1:?label required}"; shift
GATE="${1:?gate flag required}"; shift
[[ "${1:-}" == "--" ]] && shift

LOCKDIR="${NADOC_TEST_LOCK:-.nadoc-test.lock}"

hr='────────────────────────────────────────────────────────────────────'

if [[ "${NADOC_TEST_FORCE:-}" == "1" ]]; then
  echo "NADOC_TEST_FORCE=1 — bypassing test guard for '$LABEL'." >&2
  exec "$@"
fi

# ---- 1. Atomic lock acquire (with stale-lock reclaim) ----------------------
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

# ---- 2. "Is this really necessary?" confirmation gate ----------------------
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

# ---- Run the wrapped command under the held lock ---------------------------
"$@"
