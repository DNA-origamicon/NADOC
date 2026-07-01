---
name: MrDNA + ARBD installation and compatibility patches
description: Installed locations, compatibility patches applied, and validated workflow for mrdna+ARBD CG pipeline
type: project
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---
## ONE-COMMAND RE-SETUP (2026-06-28)

The mrdna Python install is now fully scripted + idempotent:

```bash
./scripts/setup-mrdna.sh      # clone→patch→editable-install→verify; safe to re-run
```

It clones to `~/mrdna-tool` (PERSISTENT — the old `/tmp/mrdna-tool` got wiped on every
reboot, which was the recurring "mrdna stopped working" cause), applies the NumPy-2.x
patches (7&8 below + trapz/rmsdThreshold), editable-installs into NADOC `.venv` `--no-deps`,
writes the privacy config, verifies `import mrdna`. The script is now the single source of
truth (this knowledge was previously duplicated inline in `backend/api/ws.py` ~L899–928 — TECH
DEBT: ws.py should call the script or a shared helper instead of its own inline clone+sed).
Docs: `docs/mrdna_setup.md` "Quick install (one command)".

**Validated 2026-06-28** (RTX 3080 Ti, 12 GB): full bridge round-trip U6hb.nadoc → 635-bead
SegmentModel → ARBD GPU sim (100k steps) → PDB/PSF/DCD in 21 s. ARBD binary survived at
`/usr/local/bin/arbd`. Only the `/tmp` Python checkout was lost; the script restored it.

**Round-trip benchmark harness** (`scripts/benchmark_mrdna_roundtrip.py`, `just bench-mrdna [--fast]`,
added 2026-06-28): the standing guard against the historical "what became what / bad-start-position
→ explosion" pain. Per design (default: 2hb_xover_val, 6hb_test, sq_multi_domain_test1=SQUARE):
Phase A (no GPU) = forward translation traceability — completeness (1 bead/non-skip nt), injective
bead↔nt map, Kabsch-RMSD fidelity vs NADOC's OWN `geometry.nucleotide_positions` render cloud
(0.000 Å — same formula, frame-basis-independent), radius≈HELIX_RADIUS, no coincident beads
(the LJ=2e37 root cause), bp-symmetry + 3'-chain contiguity. Phase B (short ARBD sim) = back-map
complete/finite/distinct, in-frame inside design extent, FWD/REV separation, and extent-ratio
explosion guard (all 3 designs 1.00×, no blow-up). Non-zero exit on any fail → smoke-gate usable.
NOTE it surfaced a benign over-coverage: sq back-map emits 6048 keys vs 5376 routed nts (extra
in-helix-range positions for unrouted/scaffold-gap columns) — harmless (consumers look up only
needed keys) but exactly the traceability ambiguity to watch; the harness now makes it visible.

The **cadnano** patches (1–3 below) and `numpy==1.26` pin are NOT needed for the NADOC bridge
(builds from lists, no cadnano import); they only matter for the standalone cadnano→mrdna tutorial.

## Installation locations

- **ARBD binary**: `/usr/local/bin/arbd` (installed via `sudo make install`; persists across reboots)
- **ARBD source**: extract `~/Downloads/arbd-may24-beta.tar.gz`; build per `docs/mrdna_setup.md` Step 1
- **mrdna tool**: `~/mrdna-tool` (was `/tmp/mrdna-tool` — DO NOT use /tmp; wiped on reboot). `$MRDNA_TOOL_PATH` overrides.
- **GPU (this machine)**: RTX 3080 Ti, 12 GB. (Memory previously noted RTX 2080 SUPER — the other computer.)

**Why:** ARBD requires a CUDA GPU and must be compiled from source. mrdna is installed editable so we can patch it.

**How to apply:** ARBD once per machine (cmake+make+sudo install, Step 1). Everything else: `./scripts/setup-mrdna.sh`.

---

## Python compatibility patches (all required for Python 3.13 + numpy 1.26)

These patches must be re-applied if cadnano or mrdna are reinstalled.

### 1. cadnano — QFont float pointSize (`pathstyles.py`)
PyQt5 5.15+ requires int for pointSize argument:
```bash
sed -i 's/QFont(THE_FONT, THE_FONT_SIZE\/2,/QFont(THE_FONT, int(THE_FONT_SIZE\/2),/g' \
    $CADNANO_SITE/views/pathview/pathstyles.py
```

### 2. cadnano — inner1d removed from numpy (`nucleicacidpart.py`)
`numpy.core.umath_tests.inner1d` was removed; replace with einsum:
```bash
sed -i 's/from numpy.core.umath_tests import inner1d/inner1d = lambda a, b, out=None: __import__("numpy").einsum("ij,ij->i", a, b)/' \
    $CADNANO_SITE/part/nucleicacidpart.py
```

### 3. cadnano — neighbor KeyError during helix creation (`createvhelixcmd.py`)
When helices are created in order, earlier helices try to update later helices' neighbor lists before they exist. Patch to skip:
```python
# In createvhelixcmd.py around line 88, wrap the neighbor lookup in try/except KeyError: continue
```

### 4. mrdna — numpy.trapz removed (`spring_from_lp.py`)
`np.trapz` was renamed to `np.trapezoid` in numpy 2.0. Already patched in `/tmp/mrdna-tool`.

### 5. mrdna — rmsdThreshold → rmsd_threshold (`simulate.py`)
API rename in mrdna's own code. Already patched in `/tmp/mrdna-tool`.

### 6. numpy version
Must use numpy 1.26.x (not 2.x) for cadnano compatibility:
```bash
pip install "numpy==1.26.4"
```
Note: pip may upgrade numpy if you reinstall cadnano — always pin it back.

---

## mrdna privacy config
Written to `~/.local/share/mrdna.conf`:
```json
{"reporting_allowed": false}
```
Without this file, mrdna blocks on an interactive consent prompt.

---

## Validated tutorial run

```bash
cd /tmp/mrdna-tutorial/step1
mrdna --coarse-steps 1e4 --fine-steps 1e4 --output-period 1e2 -d sim1 hextube.json
```

Output in `sim1/`:
- `hextube-0.psf` / `hextube-0.pdb` — low-res CG (5 bp/bead) initial structure
- `hextube-1.psf/pdb`, `hextube-2.psf/pdb` — high-res CG (2 bp/bead + orientation)
- `hextube-3.psf/pdb/namd` — atomistic model for NAMD/ENRG-MD
- `output/hextube-N.dcd` — trajectory files

Load into VMD:
```bash
vmd -e /tmp/mrdna-tutorial/step1/load-mrdna.tcl -args sim1
```

3 ARBD stages ran in ~2 sec total on RTX 2080 SUPER.

---

## Patches 7 & 8 — NumPy 2.x compat (for NADOC venv with NumPy 2.4)

Required when calling the bridge from Python ≥ NumPy 2.0. Applied to `/tmp/mrdna-tool`.

```bash
MRDNA=/tmp/mrdna-tool
# np.in1d removed in NumPy 2.0
sed -i 's/np\.in1d(/np.isin(/g' \
    "$MRDNA/mrdna/readers/segmentmodel_from_lists.py" \
    "$MRDNA/mrdna/readers/segmentmodel_from_pdb.py"
# np.finfo(np.float) → np.finfo(float)
sed -i 's/np\.finfo(np\.float)/np.finfo(float)/g' \
    "$MRDNA/mrdna/readers/libs/base.py"
# integers(n,m,1) returns array not scalar in NumPy 2.x
sed -i 's/integers(1,99999,1)/integers(1,99999)/g' \
    "$MRDNA/mrdna/arbdmodel/submodule/engine.py"
```

---

## Re-apply all patches (one script)

```bash
CADNANO_SITE=$(python3 -c "import cadnano; import os; print(os.path.dirname(cadnano.__file__))")
sed -i 's/QFont(THE_FONT, THE_FONT_SIZE\/2,/QFont(THE_FONT, int(THE_FONT_SIZE\/2),/g' \
    $CADNANO_SITE/views/pathview/pathstyles.py
sed -i 's/from numpy.core.umath_tests import inner1d/inner1d = lambda a, b, out=None: __import__("numpy").einsum("ij,ij->i", a, b)/' \
    $CADNANO_SITE/part/nucleicacidpart.py
# createvhelixcmd.py patch must be applied manually (see above)
pip install "numpy==1.26.4"
# NumPy 2.x compat (for NADOC venv):
MRDNA=/tmp/mrdna-tool
sed -i 's/np\.in1d(/np.isin(/g' "$MRDNA/mrdna/readers/segmentmodel_from_lists.py" "$MRDNA/mrdna/readers/segmentmodel_from_pdb.py"
sed -i 's/np\.finfo(np\.float)/np.finfo(float)/g' "$MRDNA/mrdna/readers/libs/base.py"
sed -i 's/integers(1,99999,1)/integers(1,99999)/g' "$MRDNA/mrdna/arbdmodel/submodule/engine.py"
```
