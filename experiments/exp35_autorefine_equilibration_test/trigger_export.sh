#!/usr/bin/env bash
# exp35 end-of-job trigger: block until a mode's result JSON appears (the job ends), then export
# an annotated PNG of the resulting data via export_png.py.  Fires exactly once at job end.
#
#   bash trigger_export.sh residual    # watch the residual-transient job
#   bash trigger_export.sh e2e         # watch the end-to-end autorefine job
#   bash trigger_export.sh proxy
set -u
MODE="${1:-residual}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# design mode watches a per-file result (design_<stem>_result.json); pass the stem as $2.
if [ "$MODE" = "design" ]; then
  RESULT="$HERE/results/design_${2:?pass the .nadoc stem as arg 2}_result.json"
else
  RESULT="$HERE/results/${MODE}_result.json"
fi
export PATH="$HOME/.local/bin:$PATH"

echo "[trigger] watching for $RESULT …"
while [ ! -f "$RESULT" ]; do sleep 30; done
echo "[trigger] $MODE job ended — exporting PNG"
cd "$HERE/../.." || exit 1
uv run python experiments/exp35_autorefine_equilibration_test/export_png.py "$MODE"
echo "[trigger] done. PNGs in $HERE/results/profiles/png/"
ls -la "$HERE/results/profiles/png/" 2>/dev/null
