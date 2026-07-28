"""
NAMD Complete Package Builder
==============================
Assembles a self-contained ZIP that a complete novice can download and
immediately run a NAMD simulation on a fresh Ubuntu/Linux machine.

ZIP layout::

    {name}_namd_complete/
    ├── launch.sh
    ├── {name}.pdb
    ├── {name}.psf          ← complete PSF (angles/dihedrals/impropers via parmed)
    ├── namd.conf
    ├── forcefield/
    │   ├── top_all36_na.rtf
    │   ├── par_all36_na.prm
    │   └── toppar_water_ions_cufix.str
    ├── scripts/
    │   └── monitor.py
    ├── README.txt
    └── AI_ASSISTANT_PROMPT.txt
"""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from backend.core.namd_helpers import (
    _AI_PROMPT,
    _render_namd_conf,
    complete_psf,
    get_ai_prompt,  # noqa: F401  re-export for backend.api.crud import path
)
from backend.core.pdb_export import (
    export_basepair_map_json,
    export_basepair_map_tsv,
    export_design_maps_json,
    export_dry_implicit_restraints,
    export_identity_json,
    export_identity_tsv,
    export_pdb,
    export_psf,
    export_stacking_map_json,
    export_stacking_map_tsv,
)

_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"

_FF_FILES = [
    "top_all36_na.rtf",
    "par_all36_na.prm",
    "toppar_water_ions_cufix.str",
]

# CHARMM36m protein force field — bundled only when the design carries proteins.
_PROTEIN_FF_FILES = [
    "top_all36_prot.rtf",
    "par_all36m_prot.prm",
]


# ── Pure helpers (PSF completion, AI prompt, NAMD config rendering) ───────────
# Moved verbatim to backend/core/namd_helpers.py (Refactor 10-A).
# Re-imported above for backward-compat with `from backend.core.namd_package import …`.


def build_namd_package(design: Design, *, allow_catenated_seed: bool = False) -> bytes:
    """Return raw ZIP bytes of the complete NAMD simulation package.

    ``allow_catenated_seed`` builds even when a reciprocal crossover pair's backbones
    are topologically linked.  Off by default — see
    :func:`backend.core.junction_topology.gate_seed_topology`.
    """
    _check_ff_files()

    name = (design.metadata.name or "design").replace(" ", "_")
    prefix = f"{name}_namd_complete/"

    model = build_atomistic_model(design, include_proteins=True)
    # Same gate as the MD job pipeline — this ZIP path does not go through md_protocols.
    from backend.core.junction_topology import gate_seed_topology  # noqa: PLC0415
    gate_seed_topology(design, model=model, allow=allow_catenated_seed)
    pdb_text = export_pdb(design, model=model)
    identity_json = export_identity_json(design, model=model)
    identity_tsv = export_identity_tsv(design, model=model)
    design_maps_json = export_design_maps_json(design, model=model)
    basepairs_json = export_basepair_map_json(design, model=model)
    basepairs_tsv = export_basepair_map_tsv(design, model=model)
    stacking_json = export_stacking_map_json(design, model=model)
    stacking_tsv = export_stacking_map_tsv(design, model=model)
    dry_restraints = export_dry_implicit_restraints(design, model=model)

    try:
        psf_text = complete_psf(design, model=model)
    except Exception as exc:
        # Fall back to stub PSF with a warning header if parmed fails
        stub = export_psf(design, model=model)
        psf_text = (
            "! WARNING: parmed PSF completion failed — using stub PSF\n"
            f"! Error: {exc}\n"
            + stub
        )

    from backend.core.protein_enm import build_protein_extrabonds
    extrabonds_text = build_protein_extrabonds(design, model)
    has_protein = bool(extrabonds_text)

    conf_text   = _render_namd_conf(name, has_protein=has_protein)
    readme_text = _README.format(name=name)
    prompt_text = _AI_PROMPT.replace("{name}", name)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + f"{name}.pdb",              pdb_text)
        zf.writestr(prefix + f"{name}.psf",              psf_text)
        zf.writestr(prefix + f"{name}.identity.json",    identity_json)
        zf.writestr(prefix + f"{name}.identity.tsv",     identity_tsv)
        zf.writestr(prefix + f"{name}.design_maps.json", design_maps_json)
        zf.writestr(prefix + f"{name}.basepairs.json",   basepairs_json)
        zf.writestr(prefix + f"{name}.basepairs.tsv",    basepairs_tsv)
        zf.writestr(prefix + f"{name}.stacking.json",    stacking_json)
        zf.writestr(prefix + f"{name}.stacking.tsv",     stacking_tsv)
        for filename, text in dry_restraints.items():
            zf.writestr(prefix + f"restraints/{filename}", text)
        zf.writestr(prefix + "namd.conf",                conf_text)
        zf.writestr(prefix + "README.txt",               readme_text)
        zf.writestr(prefix + "AI_ASSISTANT_PROMPT.txt",  prompt_text)
        if has_protein:
            zf.writestr(prefix + "extrabonds.txt", extrabonds_text)

        ff_files = list(_FF_FILES)
        if has_protein:
            ff_files += _PROTEIN_FF_FILES
        for ff_file in ff_files:
            ff_path = _FF_DIR / ff_file
            zf.writestr(prefix + f"forcefield/{ff_file}", ff_path.read_bytes())

        zf.writestr(prefix + "scripts/monitor.py", _MONITOR_PY)

        # launch.sh needs executable bit — set via ZipInfo external_attr
        info = zipfile.ZipInfo(prefix + "launch.sh")
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (
            stat.S_IFREG
            | stat.S_IRWXU   # rwx for owner
            | stat.S_IRGRP | stat.S_IXGRP
            | stat.S_IROTH | stat.S_IXOTH
        ) << 16
        zf.writestr(info, _LAUNCH_SH.format(name=name))

    buf.seek(0)
    return buf.getvalue()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_ff_files() -> None:
    missing = [f for f in _FF_FILES if not (_FF_DIR / f).exists()]
    if missing:
        raise RuntimeError(
            "Force field files not found in backend/data/forcefield/: "
            + ", ".join(missing)
            + "\nSee backend/data/forcefield/README.md for download instructions."
        )


# ── Inline file constants ──────────────────────────────────────────────────────

_LAUNCH_SH = """\
#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  NADOC NAMD Launch Script
#  Usage:  bash launch.sh
#  Tested: Ubuntu 22.04 / 24.04
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

echo "═══════════════════════════════════════════════"
echo "  NADOC NAMD Launcher  —  {name}"
echo "═══════════════════════════════════════════════"
echo ""

# ── 1. Locate or install NAMD ────────────────────────────────────────────────
if [ -n "${{NAMD_CMD:-}}" ] && command -v "$NAMD_CMD" &>/dev/null; then
    echo "→ Using NAMD_CMD override: $NAMD_CMD"
elif command -v namd3 &>/dev/null; then
    NAMD_CMD="namd3"
    echo "→ Found namd3 in PATH"
elif command -v namd2 &>/dev/null; then
    NAMD_CMD="namd2"
    echo "→ Found namd2 in PATH"
else
    echo "→ NAMD not found. Attempting apt install of namd2 (CPU build)…"
    echo "  Note: requires internet + sudo; works on Ubuntu 20.04 / 22.04."
    echo "  On Ubuntu 24.04+, apt namd2 is no longer available — see below."
    if sudo apt-get install -y namd2 2>/dev/null; then
        NAMD_CMD="namd2"
        echo "  namd2 installed via apt."
    else
        echo ""
        echo "  ── NAMD not found and apt install failed ─────────────────────────────"
        echo "  Please download and install NAMD manually:"
        echo "    https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=NAMD"
        echo "  (Free registration required; CPU and GPU builds available.)"
        echo ""
        echo "  After downloading, extract and run:"
        echo "    NAMD_CMD=/path/to/namd2  bash launch.sh"
        echo "  ──────────────────────────────────────────────────────────────────────"
        exit 1
    fi
fi
echo "→ NAMD: $NAMD_CMD"
echo ""

# ── 2. Detect NVIDIA GPU ─────────────────────────────────────────────────────
GPU_INFO=""
if command -v nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true)
fi
if [ -n "$GPU_INFO" ]; then
    echo "  GPU detected: $GPU_INFO"
    echo "  The apt namd2 is CPU-only. For GPU acceleration, download NAMD3 from:"
    echo "  https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=NAMD"
    echo "  Then re-run:  NAMD_CMD=/path/to/namd3  bash launch.sh"
    echo ""
fi

# ── 3. Runtime placement ─────────────────────────────────────────────────────
N_LOGICAL=$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 2)
NCPU="${{NAMD_THREADS:-$(( (N_LOGICAL + 1) / 2 ))}}"
DEVICES="${{NAMD_DEVICES:-}}"
PEMAP="${{NAMD_PEMAP:-}}"
namd_args=("+p$NCPU" "+setcpuaffinity")
if [ -n "$PEMAP" ]; then
    namd_args+=("+pemap" "$PEMAP")
fi
if [ -n "$DEVICES" ]; then
    namd_args+=("+devices" "$DEVICES")
fi
echo "→ Using $NCPU NAMD threads"
if [ -n "$DEVICES" ]; then
    echo "→ CUDA devices: $DEVICES"
fi
echo ""

# ── 4. Run NAMD ──────────────────────────────────────────────────────────────
LOG="namd_run.log"
echo "→ Starting NAMD…  (log: $LOG)"
"$NAMD_CMD" "${{namd_args[@]}}" namd.conf > "$LOG" 2>&1 &
NAMD_PID=$!
echo "  PID: $NAMD_PID"
echo ""

# ── 5. Live progress monitor ─────────────────────────────────────────────────
python3 scripts/monitor.py "$LOG" "$NAMD_PID"

echo ""
echo "Done.  Output files are in output/"
"""


_MONITOR_PY = r'''\
#!/usr/bin/env python3
"""
NADOC NAMD Progress Monitor
Reads the NAMD log file in real time and displays a live progress table.
Uses only Python standard library — no packages to install.

Usage:  python3 monitor.py <log_file> <namd_pid>
"""
import argparse
import os
import re
import sys
import time

_ENERGY_RE = re.compile(
    r'^ENERGY:\s+(\d+)'          # step
    r'(?:\s+[\d.eE+\-]+){10}'    # skip 10 fields (bonds … angle …)
    r'\s+([\d.eE+\-]+)'          # TEMP (field 12)
    r'\s+([\d.eE+\-]+)',         # TOTAL (field 13, 0-indexed)
    re.MULTILINE,
)

_MINIMIZE_RE = re.compile(r'^MINIMIZATION DONE', re.MULTILINE)
_TITLE_SHOWN = False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _header():
    print(f"{'Step':>8}  {'Temp (K)':>10}  {'Total E (kcal/mol)':>22}  {'Phase':<14}")
    print("─" * 62)


def main():
    global _TITLE_SHOWN
    ap = argparse.ArgumentParser()
    ap.add_argument("log_file")
    ap.add_argument("namd_pid", type=int)
    args = ap.parse_args()

    pid          = args.namd_pid
    log_path     = args.log_file
    phase        = "starting"
    last_step    = 0
    total_steps  = None   # parsed from "run" directive when seen
    rows_printed = 0

    # Wait for log file to appear
    waited = 0
    while not os.path.exists(log_path):
        if not _pid_alive(pid):
            print("NAMD exited before writing log — check namd_run.log for errors.")
            sys.exit(1)
        time.sleep(0.5)
        waited += 0.5
        if waited > 30:
            print("Timeout waiting for NAMD log file.")
            sys.exit(1)

    with open(log_path, "r", errors="replace") as fh:
        buf = ""
        while True:
            chunk = fh.read(65536)
            if chunk:
                buf += chunk
                # Parse run total from conf echo
                if total_steps is None:
                    m = re.search(r'^\s*run\s+(\d+)', buf, re.MULTILINE | re.IGNORECASE)
                    if m:
                        total_steps = int(m.group(1))

                if _MINIMIZE_RE.search(buf):
                    phase = "NVT dynamics"

                for m in _ENERGY_RE.finditer(buf):
                    step  = int(m.group(1))
                    temp  = float(m.group(2))
                    total = float(m.group(3))

                    if step <= last_step:
                        continue
                    last_step = step

                    if not _TITLE_SHOWN:
                        _header()
                        _TITLE_SHOWN = True

                    prog = ""
                    if total_steps and total_steps > 0 and phase == "NVT dynamics":
                        pct = min(100, int(100 * step / total_steps))
                        prog = f"{pct:3d} %"

                    print(
                        f"{step:>8}  {temp:>10.1f}  {total:>22.1f}  "
                        f"{phase:<14}  {prog}",
                        flush=True,
                    )
                    rows_printed += 1

                # Clear processed buffer (keep last partial line)
                nl = buf.rfind("\n")
                if nl >= 0:
                    buf = buf[nl + 1:]

            elif not _pid_alive(pid):
                # NAMD exited; drain last bytes
                remainder = fh.read()
                if remainder:
                    for m in _ENERGY_RE.finditer(remainder):
                        step  = int(m.group(1))
                        temp  = float(m.group(2))
                        total = float(m.group(3))
                        if step > last_step:
                            last_step = step
                            print(
                                f"{step:>8}  {temp:>10.1f}  {total:>22.1f}  "
                                f"{phase:<14}",
                                flush=True,
                            )
                break
            else:
                time.sleep(0.25)

    if rows_printed == 0 and not _TITLE_SHOWN:
        print("No ENERGY lines found in log. Check namd_run.log for errors.")
    else:
        print("─" * 62)
        print(f"  Final step: {last_step:,}    Done.")


if __name__ == "__main__":
    main()
'''


_README = """\
NADOC — NAMD Simulation Package
================================
Design: {name}
Generated by: NADOC (Not Another DNA Origami CAD)

QUICK START
-----------
  bash launch.sh

That's it. The script will:
  1. Install namd2 (CPU build, via apt — requires sudo once)
  2. Detect any NVIDIA GPU and print NAMD3 instructions if found
  3. Use a local-MD-style thread default (half logical CPUs) with CPU affinity
  4. Run NAMD and show a live progress table

If namd2 is already installed, no internet connection is needed.

FILES
-----
  {name}.pdb       All-atom PDB (heavy atoms, CHARMM36 naming, lerp-relaxed crossovers)
  {name}.psf       Complete CHARMM PSF (atoms, bonds, angles, dihedrals, impropers)
  namd.conf        Pre-configured NAMD input (GBIS implicit solvent, 310 K NVT)
  forcefield/      CHARMM36 NA force field (MacKerell lab) + CuFix NBFIX (Aksimentiev lab)
  scripts/         monitor.py — real-time progress display (stdlib only)
  output/          Created by launch.sh; DCD trajectory + XST cell history written here

SIMULATION DETAILS
------------------
  Force field  :  CHARMM36 nucleic acids (MacKerell lab, Jul 2022)
  NBFIX        :  CuFix corrections for ions (Aksimentiev lab, UIUC)
  Solvent      :  GBIS implicit solvent (ionConcentration 0.15 M)
                  For large DNA origami, explicit solvent would require tens of millions
                  of water atoms — impractical on a workstation. GBIS is physically
                  meaningful for structure validation and force-balance assessment.
  Minimization :  2000 steps conjugate gradient
  Production   :  50,000 steps NVT (50 ps at 1 fs/step) at 310 K
  Hydrogen     :  guesscoord on — NAMD builds missing H positions automatically

GPU ACCELERATION
----------------
  apt namd2 is CPU-only. For GPU runs download NAMD3 from:
    https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=NAMD
  Then:  NAMD_CMD=/path/to/namd3 NAMD_DEVICES=0 bash launch.sh

LAUNCH TUNING
-------------
  launch.sh mirrors NADOC's local NAMD runner controls:
    NAMD_THREADS=6          Override the default half-logical thread count
    NAMD_DEVICES=0          Add "+devices 0" for CUDA NAMD3
    NAMD_PEMAP=0-11         Optional explicit CPU affinity map

EXTENDING THE SIMULATION
------------------------
  Longer run:
    Edit namd.conf — change "run 50000" to e.g. "run 5000000" (5 ns).

  Restart from checkpoint:
    Add to namd.conf:
      binCoordinates   output/{name}.restart.coor
      binVelocities    output/{name}.restart.vel
      extendedSystem   output/{name}.restart.xsc
    And comment out:  minimize 2000 / reinitvels 310 / guesscoord on

  Explicit solvent (small sub-systems only):
    Remove the GBIS block and add a water box using solvate in VMD/HTMD/OpenMM.

VISUALISATION
-------------
  Load in VMD:  vmd {name}.pdb {name}.psf
  Or DCD:       vmd {name}.pdb {name}.psf -dcd output/{name}.dcd

AI ASSISTANT
------------
  This package includes AI_ASSISTANT_PROMPT.txt — a ready-to-paste context
  prompt for VS Code Copilot Chat, Claude, ChatGPT, or any LLM. Paste it to
  get step-by-step guidance on setup, running, and analysing this simulation
  without needing prior MD experience.

CITATIONS
---------
  CHARMM36 NA:  Hart et al., J. Chem. Theory Comput. 2012; Foloppe & MacKerell 2000
  CuFix NBFIX:  Yoo & Aksimentiev, J. Phys. Chem. Lett. 2012; JCTC 2016
  NAMD:         Phillips et al., J. Chem. Phys. 2020
"""
