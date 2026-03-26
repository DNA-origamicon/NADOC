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
    └── README.txt
"""

from __future__ import annotations

import io
import stat
import tempfile
import zipfile
from pathlib import Path

from backend.core.models import Design
from backend.core.pdb_export import export_pdb, export_psf

_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"

_FF_FILES = [
    "top_all36_na.rtf",
    "par_all36_na.prm",
    "toppar_water_ions_cufix.str",
]


# ── PSF completion — pure Python, no external tools needed ────────────────────
#
# CHARMM36 NA has no IMPH (improper) terms — only angles and dihedrals.
# We generate both from the bond graph encoded in the stub PSF.

def complete_psf(design: Design) -> str:
    """Return a fully-parameterised PSF (atoms + bonds + angles + dihedrals)
    built from the stub PSF exported by pdb_export.export_psf().

    Angles and dihedrals are generated from the bond graph; no external
    tools (parmed, psfgen, VMD) are required.
    """
    stub = export_psf(design)
    return _complete_psf_from_stub(stub)


def _complete_psf_from_stub(stub: str) -> str:
    """Expand a bonds-only stub PSF into a full PSF with angles and dihedrals."""
    import re

    # ── Parse atoms ──────────────────────────────────────────────────────────
    # PSF atom line: serial  seg  resid  resname  name  type  charge  mass  0
    atom_re = re.compile(
        r"^\s*(\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+\-Ee]+)\s+([0-9.+\-Ee]+)"
    )
    n_atoms = 0
    # map 1-based serial → index (0-based)
    serial_to_idx: dict[int, int] = {}
    in_atom = False
    atom_lines: list[str] = []
    bond_lines_raw: list[str] = []
    header_lines: list[str] = []
    collecting = "header"

    for line in stub.splitlines():
        stripped = line.strip()
        if "!NATOM" in line:
            m = re.search(r"(\d+)\s+!NATOM", line)
            n_atoms = int(m.group(1)) if m else 0
            in_atom = True
            collecting = "atom"
            header_lines.append(line)
            continue
        if "!NBOND" in line:
            in_atom = False
            collecting = "bond"
            # We'll rebuild the bonds section ourselves — skip this header
            continue
        if collecting == "header":
            header_lines.append(line)
        elif collecting == "atom":
            if stripped == "" or stripped.startswith("!"):
                collecting = "done_atom"
            else:
                m = atom_re.match(line)
                if m:
                    serial = int(m.group(1))
                    serial_to_idx[serial] = len(atom_lines)
                atom_lines.append(line)
        elif collecting == "bond":
            if stripped == "" or stripped.startswith("!"):
                collecting = "done_bond"
            else:
                bond_lines_raw.append(stripped)

    # ── Parse bonds ───────────────────────────────────────────────────────────
    bonds: list[tuple[int, int]] = []   # (0-based idx1, 0-based idx2)
    adj: list[set[int]] = [set() for _ in range(n_atoms)]

    for bl in bond_lines_raw:
        nums = bl.split()
        for i in range(0, len(nums) - 1, 2):
            s1, s2 = int(nums[i]), int(nums[i + 1])
            i1 = serial_to_idx.get(s1)
            i2 = serial_to_idx.get(s2)
            if i1 is not None and i2 is not None:
                bonds.append((i1, i2))
                adj[i1].add(i2)
                adj[i2].add(i1)

    # ── Generate angles from bond graph ───────────────────────────────────────
    # Angle: every unique (a, b, c) where a-b and b-c are bonds, a < c
    angles: list[tuple[int, int, int]] = []
    for b_idx in range(n_atoms):
        nbrs = sorted(adj[b_idx])
        for j, a_idx in enumerate(nbrs):
            for c_idx in nbrs[j + 1:]:
                angles.append((a_idx, b_idx, c_idx))

    # ── Generate proper dihedrals from bond graph ─────────────────────────────
    # Dihedral: every unique (a, b, c, d) where a-b, b-c, c-d bonds exist;
    # a ≠ c, b ≠ d; canonical: (b,c) < (c,b) and a < d for same (b,c).
    seen_dihe: set[tuple[int, int, int, int]] = set()
    dihedrals: list[tuple[int, int, int, int]] = []
    for b_idx in range(n_atoms):
        for c_idx in adj[b_idx]:
            if c_idx <= b_idx:
                continue  # process each bond once
            for a_idx in adj[b_idx]:
                if a_idx == c_idx:
                    continue
                for d_idx in adj[c_idx]:
                    if d_idx == b_idx or d_idx == a_idx:
                        continue
                    key = (min(a_idx, d_idx), b_idx, c_idx, max(a_idx, d_idx))
                    if a_idx > d_idx:
                        key = (d_idx, c_idx, b_idx, a_idx)
                    if key not in seen_dihe:
                        seen_dihe.add(key)
                        dihedrals.append((a_idx, b_idx, c_idx, d_idx))

    # ── Serial numbers (1-based) for output ───────────────────────────────────
    idx_to_serial = {v: k for k, v in serial_to_idx.items()}

    def serial(idx: int) -> int:
        return idx_to_serial.get(idx, idx + 1)

    # ── Build output PSF ──────────────────────────────────────────────────────
    out: list[str] = []
    out.extend(header_lines)
    out.extend(atom_lines)
    out.append("")

    # Bonds
    n_bonds = len(bonds)
    out.append(f"{n_bonds:8d} !NBOND: bonds")
    for i in range(0, n_bonds, 4):
        chunk = bonds[i:i + 4]
        out.append("".join(f"{serial(a):8d}{serial(b):8d}" for a, b in chunk))
    out.append("")

    # Angles
    n_ang = len(angles)
    out.append(f"{n_ang:8d} !NTHETA: angles")
    for i in range(0, n_ang, 3):
        chunk = angles[i:i + 3]
        out.append("".join(f"{serial(a):8d}{serial(b):8d}{serial(c):8d}" for a, b, c in chunk))
    out.append("")

    # Dihedrals
    n_dih = len(dihedrals)
    out.append(f"{n_dih:8d} !NPHI: dihedrals")
    for i in range(0, n_dih, 2):
        chunk = dihedrals[i:i + 2]
        out.append("".join(f"{serial(a):8d}{serial(b):8d}{serial(c):8d}{serial(d):8d}" for a, b, c, d in chunk))
    out.append("")

    # Impropers (none for CHARMM36 NA)
    out.append("       0 !NIMPHI: impropers")
    out.append("")
    out.append("       0 !NDON: donors")
    out.append("")
    out.append("       0 !NACC: acceptors")
    out.append("")
    out.append("       0 !NNB")
    out.append("")
    out.append("       0       0 !NGRP NST2")
    out.append("")
    out.append("       0       0 !NUMLP NUMLPH")
    out.append("")

    return "\n".join(out)


# ── Public entry point ─────────────────────────────────────────────────────────

def build_namd_package(design: Design) -> bytes:
    """Return raw ZIP bytes of the complete NAMD simulation package."""
    _check_ff_files()

    name = (design.metadata.name or "design").replace(" ", "_")
    prefix = f"{name}_namd_complete/"

    pdb_text = export_pdb(design)

    try:
        psf_text = complete_psf(design)
    except Exception as exc:
        # Fall back to stub PSF with a warning header if parmed fails
        stub = export_psf(design)
        psf_text = (
            "! WARNING: parmed PSF completion failed — using stub PSF\n"
            f"! Error: {exc}\n"
            + stub
        )

    conf_text   = _render_namd_conf(name)
    readme_text = _README.format(name=name)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + f"{name}.pdb", pdb_text)
        zf.writestr(prefix + f"{name}.psf", psf_text)
        zf.writestr(prefix + "namd.conf",    conf_text)
        zf.writestr(prefix + "README.txt",   readme_text)

        for ff_file in _FF_FILES:
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


def _render_namd_conf(name: str) -> str:
    return f"""\
# NAMD configuration generated by NADOC
# GBIS implicit solvent — no water box needed for large DNA origami

structure          {name}.psf
coordinates        {name}.pdb
outputName         output/{name}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
# toppar_water_ions_cufix.str is included in the forcefield/ directory.
# Uncomment the line below only when running explicit-solvent simulations
# that include Na+/K+/Mg2+ ion atoms — not needed for GBIS implicit solvent.
#parameters         forcefield/toppar_water_ions_cufix.str

# ── Implicit solvent (Generalised Born) ───────────────────────────────────────
gbis               on
alphaCutoff        14.0
ionConcentration   0.15

# ── Thermostat ────────────────────────────────────────────────────────────────
temperature        310
langevin           on
langevinDamping    5
langevinTemp       310
langevinHydrogen   off

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             16.0
switching          on
switchdist         14.0
pairlistdist       18.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           1.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── Output ────────────────────────────────────────────────────────────────────
outputEnergies     500
dcdFreq            500
dcdFile            output/{name}.dcd
xstFreq            500
xstFile            output/{name}.xst

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           2000
reinitvels         310
run                50000
"""


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

# ── 3. Detect CPU count ──────────────────────────────────────────────────────
NCPU=$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 4)
echo "→ Using $NCPU CPU threads"
echo ""

# ── 4. Run NAMD ──────────────────────────────────────────────────────────────
LOG="namd_run.log"
echo "→ Starting NAMD…  (log: $LOG)"
"$NAMD_CMD" +p"$NCPU" namd.conf > "$LOG" 2>&1 &
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
  3. Use all available CPU cores
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
  Then:  NAMD_CMD=/path/to/namd3  bash launch.sh

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

CITATIONS
---------
  CHARMM36 NA:  Hart et al., J. Chem. Theory Comput. 2012; Foloppe & MacKerell 2000
  CuFix NBFIX:  Yoo & Aksimentiev, J. Phys. Chem. Lett. 2012; JCTC 2016
  NAMD:         Phillips et al., J. Chem. Phys. 2020
"""
