"""
Test: import Nanosynth_SqArm_OHon_V7.sc → export GROMACS package

Run from the repo root:
    python test_gromacs_pipeline.py
"""

import json
import sys
import traceback
from pathlib import Path

SC_FILE   = Path(__file__).parent / "Examples" / "Nanosynth_SqArm_OHon_V7.sc"
OUT_ZIP   = Path(__file__).parent / "Nanosynth_SqArm_OHon_V7_gromacs.zip"

def log(msg: str) -> None:
    print(f"[STEP] {msg}", flush=True)

def fail(msg: str, exc: BaseException | None = None) -> None:
    print(f"\n[FAIL] {msg}", file=sys.stderr)
    if exc:
        traceback.print_exc()
    sys.exit(1)


# ── Step 1: Load .sc file ──────────────────────────────────────────────────────
log("Loading .sc file from disk...")
try:
    raw = SC_FILE.read_text(encoding="utf-8")
    data = json.loads(raw)
    log(f"  Parsed OK — grid={data.get('grid')}, "
        f"helices={len(data.get('helices', []))}, "
        f"strands={len(data.get('strands', []))}")
except Exception as exc:
    fail(f"Could not read/parse {SC_FILE}", exc)


# ── Step 2: Import scadnano → NADOC Design ───────────────────────────────────
log("Running import_scadnano()...")
try:
    from backend.core.scadnano import import_scadnano
    design, warnings = import_scadnano(data)
    log(f"  Import OK — {len(design.helices)} helices, {len(design.strands)} strands")
    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")
except Exception as exc:
    fail("import_scadnano() raised an exception", exc)


# ── Step 3: Build GROMACS package ────────────────────────────────────────────
log("Running build_gromacs_package() — this calls pdb2gmx + editconf...")
try:
    from backend.core.gromacs_package import build_gromacs_package
    zip_bytes = build_gromacs_package(design)
    log(f"  build_gromacs_package() OK — ZIP size: {len(zip_bytes):,} bytes")
except Exception as exc:
    fail("build_gromacs_package() raised an exception", exc)


# ── Step 4: Write ZIP to disk and validate contents ──────────────────────────
log(f"Writing ZIP to {OUT_ZIP}...")
try:
    import zipfile, io
    OUT_ZIP.write_bytes(zip_bytes)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    log(f"  ZIP contains {len(names)} files:")
    for n in sorted(names):
        print(f"    {n}")
except Exception as exc:
    fail("Could not write or inspect ZIP", exc)

# ── Step 5: Sanity-check required files exist in ZIP ─────────────────────────
log("Checking required files are present in ZIP...")
required_suffixes = ["conf.gro", "topol.top", "em.mdp", "nvt.mdp", "launch.sh", "README.txt"]
missing = [s for s in required_suffixes if not any(n.endswith(s) for n in names)]
if missing:
    fail(f"ZIP is missing expected files: {missing}")
else:
    log(f"  All required files present: {required_suffixes}")

print("\n[PASS] Full pipeline completed without errors.")
