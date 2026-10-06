#!/usr/bin/env bash
# Serialize large development checks and isolate their memory from the editor.
# This wraps, and never replaces, test_guard.sh / test-session authorization.
set -euo pipefail
if (( $# == 0 )); then
  echo 'Usage: scripts/validation_guard.sh COMMAND [ARG ...]' >&2
  exit 2
fi
if [[ "${NADOC_VALIDATION_SCOPE:-}" == 1 ]]; then
  exec "$@"
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/.development-artifacts"
exec 9>"$ROOT/.development-artifacts/validation.lock"
flock 9
export NADOC_VALIDATION_SCOPE=1
export PYTEST_XDIST_AUTO_NUM_WORKERS="${PYTEST_XDIST_AUTO_NUM_WORKERS:-4}"
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-1}"
if command -v systemd-run >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  validation_unit="nadoc-validation-$$-$RANDOM.scope"
  # A failing subprocess test must not leave detached children in the desktop.
  trap 'systemctl --user stop "$validation_unit" >/dev/null 2>&1 || true' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  systemd-run --user --scope --quiet --collect --unit="$validation_unit" \
    -p MemoryHigh=6G -p MemoryMax=8G -p MemorySwapMax=512M -- "$@"
  exit $?
fi
echo 'Validation: no user systemd; serialized workers remain capped, memory limit unavailable.' >&2
exec "$@"
