#!/usr/bin/env bash
# Install the mrdna CG engine for NADOC's coarse-relax / multi-resolution pipeline.
#
# mrdna converts a NADOC Design → coarse-grained bead model → runs ARBD on the GPU →
# outputs a relaxed structure (and an atomistic PDB/PSF). NADOC's bridge
# (backend/core/mrdna_bridge.py) imports mrdna from an editable checkout at
# $MRDNA_TOOL_PATH (default ~/mrdna-tool, a PERSISTENT path — never /tmp, which is
# wiped on reboot and was the original "it stopped working" cause).
#
# This installs the mrdna PYTHON package only. The ARBD binary is a separate,
# GPU-only, compiled dependency — see docs/mrdna_setup.md Step 1. This script
# checks for it and warns if missing, but does not build it.
#
# Idempotent: re-clones only if missing, re-applies patches only where needed,
# re-points the editable install every run (cheap). Safe to run repeatedly.
#
# Usage:
#   ./scripts/setup-mrdna.sh
#   MRDNA_TOOL_PATH=/opt/mrdna ./scripts/setup-mrdna.sh   # custom checkout location
set -euo pipefail

REPO_URL="https://gitlab.engr.illinois.edu/tbgl/tools/mrdna"
MRDNA="${MRDNA_TOOL_PATH:-$HOME/mrdna-tool}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NADOC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.local/bin:$PATH"   # make uv visible

info() { printf '\033[1;34m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

echo "==> mrdna setup  (checkout=$MRDNA)"

# 1. Clone (shallow) to the persistent checkout if absent.
if [ ! -d "$MRDNA/mrdna" ]; then
  info "cloning mrdna → $MRDNA"
  git clone --depth=1 "$REPO_URL" "$MRDNA"
else
  ok "reusing existing checkout at $MRDNA"
fi

# 2. NumPy-2.x / API-rename compatibility patches (idempotent — sed patterns no
#    longer match once applied). These keep mrdna importable from NADOC's .venv
#    (NumPy 2.x, Python 3.12). The cadnano patches in docs/mrdna_setup.md are NOT
#    needed here: the NADOC bridge builds a SegmentModel from lists, never via cadnano.
#    This list is the single source of truth (was duplicated inline in api/ws.py).
info "applying compatibility patches"
apply() {  # apply <relative-file> <sed-expr> <description>
  local f="$MRDNA/$1"
  [ -f "$f" ] || { warn "patch target missing, skipping: $1"; return; }
  sed -i "$2" "$f"
}
apply "mrdna/readers/segmentmodel_from_lists.py" 's/np\.in1d(/np.isin(/g'                 "in1d→isin"
apply "mrdna/readers/segmentmodel_from_pdb.py"   's/np\.in1d(/np.isin(/g'                 "in1d→isin"
apply "mrdna/readers/libs/base.py"               's/np\.finfo(np\.float)/np.finfo(float)/g' "finfo(np.float)→finfo(float)"
apply "mrdna/arbdmodel/submodule/engine.py"      's/integers(1,99999,1)/integers(1,99999)/g' "integers scalar"
apply "mrdna/model/spring_from_lp.py"            's/np\.trapz(/np.trapezoid(/g'           "trapz→trapezoid"
apply "mrdna/simulate.py"                        's/rmsdThreshold=1/rmsd_threshold=1/g'   "rmsdThreshold→rmsd_threshold"
ok "patches applied"

# 3. Editable-install into NADOC's venv, WITHOUT deps (mrdna's pinned deps — cadnano,
#    old numpy — would fight NADOC's environment; the bridge only needs the readers +
#    arbdmodel, whose runtime deps (numpy/scipy/MDAnalysis) are already in .venv).
command -v uv >/dev/null 2>&1 || die "uv not found on PATH — run ./setup.sh first."
info "editable-installing mrdna into NADOC .venv (--no-deps)"
( cd "$NADOC_ROOT" && uv pip install -e "$MRDNA" --no-deps -q )
ok "mrdna installed"

# 4. Privacy config — without it, first import blocks on an interactive consent prompt
#    (fatal in headless/websocket runs). XDG_DATA_HOME default == ~/.local/share.
CONF="${XDG_DATA_HOME:-$HOME/.local/share}/mrdna.conf"
if [ ! -f "$CONF" ]; then
  mkdir -p "$(dirname "$CONF")"
  printf '{"reporting_allowed": false}\n' > "$CONF"
  ok "wrote privacy config → $CONF"
else
  ok "privacy config present → $CONF"
fi

# 5. Verify the import resolves from the venv.
info "verifying import"
( cd "$NADOC_ROOT" && uv run python -c "import mrdna; print('mrdna', getattr(mrdna,'__version__','?'), 'from', mrdna.__file__)" ) \
  || die "import mrdna failed — inspect the traceback above."
ok "mrdna importable"

# 6. ARBD binary check (GPU engine; built separately — see docs/mrdna_setup.md Step 1).
if command -v arbd >/dev/null 2>&1 || [ -x /usr/local/bin/arbd ]; then
  ok "ARBD binary found ($(command -v arbd || echo /usr/local/bin/arbd))"
else
  warn "ARBD binary NOT found. mrdna will build models but cannot SIMULATE without it."
  warn "Build it from docs/mrdna_setup.md Step 1 (needs a CUDA GPU)."
fi

echo
ok "mrdna setup complete."
echo "   Checkout:  $MRDNA   (override with \$MRDNA_TOOL_PATH)"
echo "   Used by:   backend/core/mrdna_bridge.py, /ws/mrdna-relax, skip-twist coarse relax"
