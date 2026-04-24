# MrDNA + ARBD Setup Guide

This document covers everything needed to get the MrDNA multi-resolution pipeline
running on a CUDA-capable Linux workstation so it can be used as NADOC's CG
pre-relaxation engine.

---

## What you're installing

| Component | Purpose | Source |
|-----------|---------|--------|
| **ARBD** | GPU-accelerated Brownian dynamics engine that runs the CG simulation | `~/Downloads/arbd-may24-beta.tar.gz` or Aksimentiev lab |
| **mrdna** | Python package that converts cadnano JSON → CG bead model → runs ARBD → outputs atomistic PDB | `gitlab.engr.illinois.edu/tbgl/tools/mrdna` |
| **mrdna tutorial** | Example designs (hextube.json, curved-hextube.json) and load-mrdna.tcl VMD script | `gitlab.engr.illinois.edu/tbgl/tutorials/multi-resolution-dna-nanostructures` |

---

## Prerequisites

```bash
# Verify these before starting
nvcc --version        # needs CUDA 11+
nvidia-smi            # GPU must be visible
cmake --version       # needs 3.9+
python3 --version     # needs 3.8+; tested on 3.13
```

The mrdna simulation engine is GPU-only. ARBD will not run without a CUDA-capable GPU.

---

## Step 1 — Build and install ARBD

ARBD is distributed as C++/CUDA source and must be compiled.

```bash
# Extract source (adjust path to wherever you downloaded the tar)
tar -xzf ~/Downloads/arbd-may24-beta.tar.gz -C /tmp/

# Configure — CMake auto-detects your GPU architecture via nvidia-smi
mkdir -p /tmp/arbd/build
cd /tmp/arbd/build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local

# Build (uses all cores)
make -j$(nproc)

# Install to /usr/local/bin/arbd  (requires sudo)
sudo make install

# Verify
arbd --info
# Should print: Found 1 GPU(s) ... NVIDIA GeForce ...
```

**If CMake can't find CUDA headers**, set the env var before cmake:
```bash
export CUDA_INCLUDE_DIRS=$(dirname $(which nvcc))/../include
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local
```

---

## Step 2 — Pin NumPy to 1.x

The cadnano package (a mrdna dependency) is incompatible with NumPy 2.x.
Pin it before installing anything else to avoid pip silently upgrading it later.

```bash
pip install "numpy==1.26.4"
```

> **If pip later upgrades numpy** (e.g. when reinstalling cadnano), always re-run this.
> You can confirm with: `python3 -c "import numpy; print(numpy.__version__)"`

---

## Step 3 — Install mrdna

```bash
# Clone to a stable location (editable install so patches survive)
git clone https://gitlab.engr.illinois.edu/tbgl/tools/mrdna.git /opt/mrdna
cd /opt/mrdna
pip install -e .

# Re-pin numpy (pip may have upgraded it during install)
pip install "numpy==1.26.4"
```

> Use `/opt/mrdna` or another permanent path — **not** `/tmp/` — so patches survive reboots.

---

## Step 4 — Apply compatibility patches

These patches fix incompatibilities between cadnano 2.5, PyQt5 5.15+, NumPy 1.26,
and Python 3.10+. They must be applied once after install (and re-applied if
cadnano is ever reinstalled).

```bash
# Find cadnano's install location
CADNANO=$(python3 -c "import cadnano, os; print(os.path.dirname(cadnano.__file__))")
echo "Patching cadnano at: $CADNANO"

# Patch 1: QFont(str, float, weight) → QFont(str, int, weight)
#   PyQt5 5.15+ requires pointSize to be int, not float
sed -i 's/QFont(THE_FONT, THE_FONT_SIZE\/2,/QFont(THE_FONT, int(THE_FONT_SIZE\/2),/g' \
    "$CADNANO/views/pathview/pathstyles.py"

# Patch 2: numpy.core.umath_tests.inner1d removed in NumPy 1.20+
#   Replaced with equivalent einsum expression
sed -i 's/from numpy.core.umath_tests import inner1d/inner1d = lambda a, b, out=None: __import__("numpy").einsum("ij,ij->i", a, b)/' \
    "$CADNANO/part/nucleicacidpart.py"

# Patch 3: KeyError when creating virtual helices out of order
#   During v2decode, cadnano tries to update a neighbor helix's properties
#   before that neighbor has been created yet. Skip missing neighbors gracefully.
python3 - <<'EOF'
import re
path = __import__("os").path.join(
    __import__("os").path.dirname(__import__("cadnano").__file__),
    "part/createvhelixcmd.py"
)
src = open(path).read()
old = (
    "            for neighbor_id in neighbors:\n"
    "                nneighbors = literal_eval(\n"
    "                    part.getVirtualHelixProperties(neighbor_id, 'neighbors')\n"
    "                )\n"
    "                bisect.insort_left(nneighbors, id_num)\n"
    "                part.vh_properties.loc[neighbor_id, 'neighbors'] = str(list(nneighbors))"
)
new = (
    "            for neighbor_id in neighbors:\n"
    "                try:\n"
    "                    nneighbors = literal_eval(\n"
    "                        part.getVirtualHelixProperties(neighbor_id, 'neighbors')\n"
    "                    )\n"
    "                except KeyError:\n"
    "                    continue  # neighbor not yet created\n"
    "                bisect.insort_left(nneighbors, id_num)\n"
    "                part.vh_properties.loc[neighbor_id, 'neighbors'] = str(list(nneighbors))"
)
if old in src:
    open(path, "w").write(src.replace(old, new))
    print("Patch 3 applied")
elif "except KeyError" in src:
    print("Patch 3 already applied")
else:
    print("WARNING: Patch 3 target not found — check createvhelixcmd.py manually")
EOF
```

Now patch two places in the mrdna package itself (adjust path if you didn't clone to `/opt/mrdna`):

```bash
MRDNA=/opt/mrdna

# Patch 4: numpy.trapz renamed to numpy.trapezoid in NumPy 2.0
#   (safe to apply even on NumPy 1.x — uses getattr fallback)
sed -i 's/return np\.trapz(/\
    _trapz = getattr(np, "trapezoid", None) or np.trapz\n    return _trapz(/' \
    "$MRDNA/mrdna/model/spring_from_lp.py"
# Simpler sed-safe version:
python3 - <<'EOF'
path = "/opt/mrdna/mrdna/model/spring_from_lp.py"
src = open(path).read()
old = "    return np.trapz( fn(t), t[np.newaxis,:], axis = -1 )"
new = ("    _trapz = getattr(np, 'trapezoid', np.trapz) if hasattr(np, 'trapz') else np.trapezoid\n"
       "    return _trapz( fn(t), t[np.newaxis,:], axis = -1 )")
if old in src:
    open(path, "w").write(src.replace(old, new))
    print("Patch 4 applied")
elif "_trapz" in src:
    print("Patch 4 already applied")
EOF

# Patch 5: rmsdThreshold keyword renamed to rmsd_threshold in mrdna's own API
sed -i 's/rmsdThreshold=1/rmsd_threshold=1/g' "$MRDNA/mrdna/simulate.py"

# Patch 6: git-describe version lookup crashes outside a git repo
python3 - <<'EOF'
path = "/opt/mrdna/mrdna/version.py"
src = open(path).read()
old = "        split_version = call_git_describe(abbrev).split(\"-\")"
new = (
    "        _desc = call_git_describe(abbrev)\n"
    "        if _desc is None:\n"
    "            return release_version\n"
    "        split_version = _desc.split(\"-\")"
)
if old in src:
    open(path, "w").write(src.replace(old, new))
    print("Patch 6 applied")
elif "_desc = call_git_describe" in src:
    print("Patch 6 already applied")
EOF
```

---

## Step 5 — Write the mrdna privacy config

On first import, mrdna blocks on an interactive consent prompt. Pre-answer it:

```bash
python3 -c "
import json, appdirs
from pathlib import Path
conf = Path(appdirs.user_data_dir()) / 'mrdna.conf'
conf.parent.mkdir(parents=True, exist_ok=True)
json.dump({'reporting_allowed': False}, open(conf, 'w'))
print('Written to', conf)
"
```

---

## Step 6 — Verify the full pipeline

```bash
# Clone the tutorial repo (only needed once)
git clone --depth 1 \
    https://gitlab.engr.illinois.edu/tbgl/tutorials/multi-resolution-dna-nanostructures.git \
    /tmp/mrdna-tutorial

# Run the short sanity-check (completes in ~30 s on RTX 2080)
cd /tmp/mrdna-tutorial/step1
mrdna --coarse-steps 1e4 --fine-steps 1e4 --output-period 1e2 -d sim_test hextube.json

# Expected output:
#   3 × "Final Step: NNNNN" lines (one per ARBD stage)
#   sim_test/hextube-{0,1,2,3}.psf/.pdb and output/*.dcd
```

Load in VMD:
```bash
vmd -e load-mrdna.tcl -args sim_test/hextube-
```

---

## GPU performance tips

Before running a long simulation (10M steps):

```bash
# Enable persistence mode — prevents clock ramp-down between kernels
sudo nvidia-smi -pm 1

# Lock to max clocks (RTX 2080 SUPER: 7000 MHz mem, 1815 MHz core)
# Replace values with output of: nvidia-smi -q | grep "Max Clocks" -A3
sudo nvidia-smi --auto-boost-default=0
sudo nvidia-smi -ac 7000,1815

# After the run, reset
sudo nvidia-smi -rac
sudo nvidia-smi -pm 0
```

Typical throughput on RTX 2080 SUPER:
- Coarse model (148 beads): ~0.044 ms/step → 10M steps ≈ 7 min
- Fine model (880 beads): ~0.050 ms/step → 10M steps ≈ 8 min
- Total 3-stage run: ~25 min

---

## Standard run commands

```bash
# Quick sanity check (~30 s)
mrdna --coarse-steps 1e4 --fine-steps 1e4 --output-period 1e2 -d sim_quick design.json

# Medium quality (~2 min, good for curved/insertion designs)
mrdna --coarse-steps 2e5 --fine-steps 1e5 --output-period 1e3 -d sim_med design.json

# Full quality (default, ~25 min on RTX 2080)
mrdna -d sim_full design.json
```

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `QFont ... float` TypeError | PyQt5 pointSize must be int | Patch 1 above |
| `No module named 'numpy.core.umath_tests'` | NumPy ≥1.20 removed inner1d | Patch 2 above |
| `KeyError: 'id_num N not in NucleicAcidPart'` | Neighbor lookup during helix creation | Patch 3 above |
| `np.trapz` AttributeError | NumPy 2.x renamed trapz | Patch 4 above |
| `rmsdThreshold` TypeError | mrdna internal API rename | Patch 5 above |
| `'NoneType' has no attribute 'split'` | git-describe fails outside git repo | Patch 6 above |
| `EOF when reading a line` | mrdna consent prompt in non-interactive shell | Step 5 above |
| `arbd: GPU may timeout` warning | Display GPU has watchdog timer | Expected on workstations; ARBD handles checkpoint/restart automatically |
| numpy upgrades itself during cadnano reinstall | pip dependency resolution | Always re-run `pip install "numpy==1.26.4"` after any cadnano install |
| `AttributeError: module 'numpy' has no attribute 'in1d'` | NumPy 2.0 removed `np.in1d` | Patch 7 below |
| `TypeError: only 0-dimensional arrays can be converted` (seed) | `np.random.default_rng().integers(n,m,1)` returns array in NumPy 2.x | Patch 8 below |

---

## Patches 7 & 8 — NumPy 2.x compatibility when running via a NumPy 2.x environment

These are only needed when the bridge is imported from a Python environment that has NumPy ≥ 2.0 (e.g. the NADOC `.venv`). The miniforge environment with NumPy 1.26 does not need these.

```bash
MRDNA=/tmp/mrdna-tool

# Patch 7: np.in1d removed in NumPy 2.0 → use np.isin
sed -i 's/np\.in1d(/np.isin(/g' \
    "$MRDNA/mrdna/readers/segmentmodel_from_lists.py" \
    "$MRDNA/mrdna/readers/segmentmodel_from_pdb.py"

# Also: np.finfo(np.float) → np.finfo(float)
sed -i 's/np\.finfo(np\.float)/np.finfo(float)/g' \
    "$MRDNA/mrdna/readers/libs/base.py"

# Patch 8: integers(1,99999,1) returns a 1-element array in NumPy 2.x, not a scalar
sed -i 's/integers(1,99999,1)/integers(1,99999)/g' \
    "$MRDNA/mrdna/arbdmodel/submodule/engine.py"
```

---

## Integration with NADOC

The NADOC→mrdna bridge is implemented in `backend/core/mrdna_bridge.py`.
It converts a NADOC `Design` object directly to an mrdna `SegmentModel` without
any cadnano file conversion, using the `model_from_basepair_stack_3prime` API.

```python
from backend.core.models import Design
from backend.core.mrdna_bridge import mrdna_model_from_nadoc

design = Design.from_json(open("my_design.nadoc").read())
model = mrdna_model_from_nadoc(design, max_basepairs_per_bead=5)
model.simulate(output_name="my_design", directory="/tmp/mrdna_out")
```

**Validated**: NADOC U6hb (6-helix bundle, 420 bp, 64 strands) → 29-segment SegmentModel →
ARBD simulation in 3 s on RTX 2080 SUPER → atomistic PDB/PSF output.

Key design features already handled by the bridge:
- **Skip sites** (`loop_skip` with `delta=-1`) — skipped nucleotides excluded from arrays
- **Honeycomb and square lattice geometry** — helix axis positions and phase offsets used directly
- **Overhang / ssDNA domains** — unpaired nucleotides become `SingleStrandedSegment` in mrdna
- **Intrahelical nicks** — same-helix adjacent domain continuations get stacking connections

Features deferred (future work):
- **Loop insertions** (`delta=+1`) — currently emits 1 nt instead of 2; no geometric interpolation yet
- **mrdna atomistic PDB → GROMACS** — mrdna outputs NAMD/CHARMM36 PDB; needs pdb2gmx pipeline
