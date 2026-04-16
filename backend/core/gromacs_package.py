"""
GROMACS Complete Package Builder
=================================
Assembles a self-contained ZIP that a user can download and immediately
run a GROMACS simulation on a Linux machine.

Two-phase design
----------------
**Export phase (server-side)**: NADOC runs pdb2gmx + editconf to convert the
atomistic PDB into GROMACS topology (topol.top + per-molecule .itp files) and
an initial structure (conf.gro).  The force-field files are bundled from the
GROMACS installation so the package is self-contained.

**Simulation phase (user's machine)**: launch.sh installs GROMACS if absent,
then calls grompp + mdrun for energy minimization, followed by a short NVT
validation run.

Simulation physics
------------------
- Force field : charmm36-jul2022 (preferred) → charmm27 → amber99sb-ildn
                The FF is chosen at export time from whatever is installed.
- Electrostatics: Reaction-Field (epsilon-rf = 80) — approximates solvent
                  screening without requiring an explicit water box.
- Ensemble     : NVT at 310 K, Langevin thermostat
- Minimization : Steepest descent, emtol = 1000 kJ/mol/nm
- Production   : 50 ps at 1 fs/step (50,000 steps)

Limitations (simplest version)
-------------------------------
- No explicit water or counter-ions.  Reaction-field approximates dielectric
  screening; suitable for structural validation and relative comparisons.
- Cross-helix crossover bonds are NOT included in the topology.  Each DNA
  strand is simulated as an independent molecule.  Future version will add
  intermolecular restraints for crossover junctions.

ZIP layout::

    {name}_gromacs/
    ├── launch.sh
    ├── conf.gro              ← initial structure (pdb2gmx + editconf)
    ├── topol.top             ← GROMACS topology (references bundled FF)
    ├── {molecule}.itp        ← per-strand topology includes
    ├── {ff_name}.ff/         ← bundled force-field directory
    ├── em.mdp                ← energy-minimisation parameters
    ├── nvt.mdp               ← NVT production parameters
    ├── scripts/
    │   └── monitor.py
    ├── README.txt
    └── AI_ASSISTANT_PROMPT.txt
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.pdb_export import (
    _cryst1_record,  # type: ignore[attr-defined]
    _h36,            # type: ignore[attr-defined]
    _chain_char,     # type: ignore[attr-defined]
    _pdb_atom_name,  # type: ignore[attr-defined]
)

# ── Force field preference (first found in GROMACS top/ wins) ─────────────────
# Priority: charmm36 variants (if externally installed, match NADOC naming exactly)
# then AMBER variants (which ship with the apt package and have dna.r2b).
# charmm27 is intentionally excluded: it lacks dna.r2b so pdb2gmx applies
# protein termini (NH3+/COO-) to DNA chains, causing a fatal error.
_FF_CANDIDATES = [
    "charmm36-jul2022",
    "charmm36m",
    "charmm36",
    "amber99sb-ildn",
    "amber99sb",
]

# ── Atom-name maps: PDB name → FF name ────────────────────────────────────────
# NADOC exports CHARMM36 naming: OP1/OP2 for phosphate oxygens, C7 for thymine methyl.
#
# charmm27 uses O1P/O2P (same as AMBER) and C5M for thymine methyl.
# charmm36+ uses OP1/OP2 and C7 — matches NADOC directly.
# AMBER FFs use O1P/O2P and C7 (IUPAC).
#
# residue → { nadoc_atom: ff_atom }
_RENAMES_CHARMM27: dict[str, dict[str, str]] = {
    "DA": {"OP1": "O1P", "OP2": "O2P"},
    "DT": {"OP1": "O1P", "OP2": "O2P", "C7": "C5M"},   # C5M = thymine methyl in CHARMM27
    "DG": {"OP1": "O1P", "OP2": "O2P"},
    "DC": {"OP1": "O1P", "OP2": "O2P"},
}
_RENAMES_AMBER: dict[str, dict[str, str]] = {
    # AMBER FFs use O1P/O2P (vs NADOC/CHARMM36 OP1/OP2); C7 is correct for AMBER
    "DA": {"OP1": "O1P", "OP2": "O2P"},
    "DT": {"OP1": "O1P", "OP2": "O2P"},
    "DG": {"OP1": "O1P", "OP2": "O2P"},
    "DC": {"OP1": "O1P", "OP2": "O2P"},
}


# ══════════════════════════════════════════════════════════════════════════════
# §1  GROMACS DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

def _find_gmx() -> str:
    """Return the gmx binary name, or raise RuntimeError."""
    for name in ("gmx", "gmx_mpi", "gmx_d"):
        if shutil.which(name):
            return name
    raise RuntimeError(
        "GROMACS not found in PATH.  Install with:\n"
        "    sudo apt-get install -y gromacs"
    )


def _find_top_dir() -> Path:
    """Return GROMACS top/ directory containing force field sub-directories."""
    candidates: list[Path] = [
        Path("/usr/share/gromacs/top"),
        Path("/usr/local/share/gromacs/top"),
        Path("/opt/gromacs/share/gromacs/top"),
    ]
    gmxdata = os.environ.get("GMXDATA") or os.environ.get("GMXLIB")
    if gmxdata:
        candidates.insert(0, Path(gmxdata))
    for p in candidates:
        if p.is_dir():
            return p
    raise RuntimeError(
        "Cannot locate GROMACS top/ directory.  "
        "Set GMXDATA=/path/to/gromacs/top or install GROMACS."
    )


def _pick_ff(top_dir: Path) -> str:
    """Return the name of the best available force field for DNA."""
    for ff in _FF_CANDIDATES:
        if (top_dir / f"{ff}.ff").is_dir():
            return ff
    available = [p.name for p in top_dir.iterdir() if p.name.endswith(".ff")]
    raise RuntimeError(
        f"No supported force field found in {top_dir}.\n"
        f"Expected one of: {_FF_CANDIDATES}\n"
        f"Available: {available}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# §2  PDB ATOM-NAME ADAPTATION
# ══════════════════════════════════════════════════════════════════════════════

def _rename_atom_in_line(line: str, old: str, new: str) -> str:
    """Replace atom name (cols 12-15) in a PDB ATOM/HETATM line."""
    atom_field = line[12:16]
    if atom_field.strip() != old:
        return line
    elem = line[76:78].strip() if len(line) > 77 else ""
    if len(elem) == 1 and len(new) <= 3:
        new_field = f" {new:<3s}"
    else:
        new_field = f"{new:<4s}"
    return line[:12] + new_field + line[16:]


def adapt_pdb_for_ff(pdb_text: str, ff: str) -> str:
    """
    Rename atom names in a NADOC PDB to match the chosen GROMACS force field.

    NADOC exports CHARMM36 naming (OP1/OP2 for phosphate oxygens, C7 for
    thymine methyl).

    Adjustments per FF:
    - charmm36+: no rename (NADOC naming matches directly)
    - amber*   : OP1→O1P, OP2→O2P  (amber dna.arn also does this, so this is
                 a pre-pass for safety; C7 stays as-is, which is correct for AMBER)

    Note: charmm27 is no longer in _FF_CANDIDATES because it lacks dna.r2b and
    causes pdb2gmx to apply protein termini to DNA chains.
    """
    if ff.startswith("charmm36") or ff.startswith("charmm36m"):
        return pdb_text   # CHARMM36 naming matches NADOC directly

    renames_by_res: dict[str, dict[str, str]] = {}
    if ff.startswith("amber"):
        renames_by_res = _RENAMES_AMBER

    if not renames_by_res:
        return pdb_text

    out: list[str] = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            res = line[17:20].strip()
            for old, new in renames_by_res.get(res, {}).items():
                line = _rename_atom_in_line(line, old, new)
        out.append(line)
    return "\n".join(out) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# §2b  5′-PHOSPHATE STRIPPING
# ══════════════════════════════════════════════════════════════════════════════

# AMBER DNA 5′-terminus entries (DA5, DT5, DG5, DC5) are defined as 5′-OH
# residues without a phosphate group.  The NADOC PDB includes P/OP1/OP2 on
# every residue (CHARMM convention where even the first residue has a
# phosphate).  Strip those three atoms from the first residue of each chain
# so pdb2gmx can match the 5′-terminus RTP entry.
_5P_ATOMS = {"P", "O1P", "O2P", "OP1", "OP2"}   # pre- and post-rename variants


def strip_5prime_phosphate(pdb_text: str) -> str:
    """
    Remove P, O1P, O2P (and OP1/OP2 pre-rename variants) from the first
    residue of each contiguous chain block in a PDB file.

    Required for AMBER FF pdb2gmx: the 5′-terminus RTP entries (DA5 etc.)
    model a 5′-OH and do not include the phosphate group.

    NADOC reuses chain letters (A–Z) when a design has more than 26 strands.
    pdb2gmx treats each contiguous run of a chain letter as a separate chain,
    so every block-start residue — not just the first occurrence of a letter —
    needs its 5′-phosphate stripped.  A new block is detected whenever the
    chain letter changes between consecutive ATOM lines.
    """
    lines = pdb_text.splitlines()

    # First pass: collect (chain, resnum) pairs that are the first residue of
    # each contiguous block.  A block boundary is detected when the chain ID
    # differs from the previous ATOM/HETATM line.
    block_starts: set[tuple[str, str]] = set()
    prev_chain: str | None = None
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            chain  = line[21]
            resnum = line[22:26].strip()
            if chain != prev_chain:          # start of a new contiguous block
                block_starts.add((chain, resnum))
                prev_chain = chain

    # Second pass: drop 5′-phosphate atoms from every block-start residue.
    result: list[str] = []
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            chain     = line[21]
            resnum    = line[22:26].strip()
            atom_name = line[12:16].strip()
            if (chain, resnum) in block_starts and atom_name in _5P_ATOMS:
                continue   # drop this phosphate atom from the 5′ end
        result.append(line)
    return "\n".join(result) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# §2c  GROMACS-SPECIFIC PDB BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_gromacs_input_pdb(design: "Design", ff: str, box_margin_nm: float = 2.0) -> str:
    """
    Generate a PDB for pdb2gmx with residues in correct 5'→3' traversal order.

    pdb2gmx ignores CONECT/LINK records and bonds residues sequentially in
    file order (residue N bonds to residue N+1 as they appear in the file).
    The standard export_pdb() appends extra-base crossover residues at the
    end of each chain, which causes pdb2gmx to:
      - Create a wrong direct O3'→P bond across the crossover (consecutive
        residues in the main strand get bonded even though an extra-base chain
        should connect them).
      - Create wrong bonds between the extra-base residues and whatever
        appears before them in file order.

    This function traverses the backbone O3'→P bond graph to compute the
    correct 5'→3' residue order per chain, then emits ATOM records in that
    order.  Extra-base residues appear immediately after their src residue and
    before their dst residue, so pdb2gmx generates the correct sequential
    bonds: O3'(src)→P(eb1)→…→O3'(ebn)→P(dst).

    The FF atom-name renaming (adapt_pdb_for_ff) and AMBER 5'-phosphate
    stripping (strip_5prime_phosphate) must be applied to the returned text
    by the caller.
    """
    from collections import defaultdict

    model = build_atomistic_model(design)
    atoms = model.atoms
    bonds = model.bonds
    atom_map = {a.serial: a for a in atoms}

    # ── Build O3'→P inter-residue bond map (same-chain bonds only) ─────────
    # These are the backbone links that define the 5'→3' traversal order.
    o3_to_p: dict[int, int] = {}   # O3' serial → P serial of next residue
    p_with_incoming: set[int] = set()  # P serials that have an incoming O3' bond

    for i, j in bonds:
        a, b = atom_map[i], atom_map[j]
        if a.name == "O3'" and b.name == "P" and a.chain_id == b.chain_id:
            o3_to_p[i] = j
            p_with_incoming.add(j)

    # ── Group atoms by chain then by original seq_num ──────────────────────
    chain_res: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    chain_order: list[str] = []
    for a in atoms:
        if a.chain_id not in chain_res:
            chain_order.append(a.chain_id)
        chain_res[a.chain_id][a.seq_num].append(a)

    # ── Per chain: traverse residues in 5'→3' order ────────────────────────
    # Result: list of (new_seq_num, Atom) in output order.
    ordered_output: list[tuple[int, object]] = []
    chain_output: dict[str, list[tuple[int, object]]] = defaultdict(list)

    for chain_id in chain_order:
        res_dict = chain_res[chain_id]

        # 5' terminus: residue whose P atom (if present) has no incoming O3'
        # bond from within the same chain.  The first such residue in seq_num
        # order is the 5' end.
        five_prime_seq: int | None = None
        for seq_num in sorted(res_dict.keys()):
            p_sers = [a.serial for a in res_dict[seq_num] if a.name == "P"]
            if not p_sers or p_sers[0] not in p_with_incoming:
                five_prime_seq = seq_num
                break

        if five_prime_seq is None:
            # Circular strand or degenerate case: fall back to original order.
            traversal = sorted(res_dict.keys())
        else:
            traversal = []
            current: int | None = five_prime_seq
            visited: set[int] = set()
            while current is not None and current not in visited:
                traversal.append(current)
                visited.add(current)
                # Follow O3'(current residue) → P(next residue)
                o3_ser = next(
                    (a.serial for a in res_dict.get(current, []) if a.name == "O3'"),
                    None,
                )
                if o3_ser is None or o3_ser not in o3_to_p:
                    break
                nxt = atom_map[o3_to_p[o3_ser]]
                current = nxt.seq_num if nxt.chain_id == chain_id else None

            # Append any residues not reached (e.g. disconnected extra bases
            # for inter-chain crossovers — these stay at the end).
            for s in sorted(res_dict.keys()):
                if s not in visited:
                    traversal.append(s)

        # Assign new sequential seq_nums (1-based within chain)
        new_seq = 0
        for old_seq in traversal:
            new_seq += 1
            for a in res_dict[old_seq]:
                chain_output[chain_id].append((new_seq, a))

    # ── Emit PDB lines ──────────────────────────────────────────────────────
    lines: list[str] = [
        "REMARK  NADOC all-atom model (Phase AA, heavy atoms only)",
        "REMARK  Residues ordered 5'->3' per chain for pdb2gmx compatibility.",
        "REMARK  Extra-base crossover residues are interleaved at correct position.",
    ]
    lines.append(_cryst1_record(atoms, margin_nm=box_margin_nm))

    ter_serial = len(atoms) + 1
    for chain_id in chain_order:
        for new_seq, a in chain_output[chain_id]:
            serial_str = _h36(a.serial + 1, 5)
            seq_str    = _h36(new_seq, 4)
            name_field = _pdb_atom_name(a.name, a.element)
            resname    = f"{a.residue:>3s}"
            chain_char = _chain_char(chain_id)
            x_ang      = a.x * 10.0
            y_ang      = a.y * 10.0
            z_ang      = a.z * 10.0
            elem_field = f"{a.element:>2s}"
            lines.append(
                f"ATOM  {serial_str} {name_field}{' '}{resname} {chain_char}"
                f"{seq_str}    "
                f"{x_ang:8.3f}{y_ang:8.3f}{z_ang:8.3f}"
                f"  1.00  0.00"
                f"          {elem_field}  "
            )
        if chain_output[chain_id]:
            last_seq, last_a = chain_output[chain_id][-1]
            chain_char = _chain_char(chain_id)
            lines.append(
                f"TER   {_h36(ter_serial, 5)}      "
                f"{last_a.residue:>3s} {chain_char}{_h36(last_seq, 4)}"
            )
            ter_serial += 1

    lines.append("END")
    pdb_text = "\n".join(lines) + "\n"

    # Apply FF-specific atom name renaming and 5'-phosphate stripping.
    pdb_text = adapt_pdb_for_ff(pdb_text, ff)
    if ff.startswith("amber"):
        pdb_text = strip_5prime_phosphate(pdb_text)

    return pdb_text


# ══════════════════════════════════════════════════════════════════════════════
# §3  MDP FILE TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

_EM_MDP = """\
; NADOC GROMACS — Energy Minimisation (vacuum / reaction-field)
; Validated settings adapted from AMBER OL15 DNA equilibration protocol.

; Minimisation
integrator              = steep
emtol                   = 1000.0
emstep                  = 0.01
nsteps                  = 50000

; Neighbour list
cutoff-scheme           = Verlet
pbc                     = xyz
nstlist                 = 20

; Electrostatics — reaction-field (epsilon-rf=80) approximates dielectric
; screening without an explicit water box. For production simulations with
; explicit TIP3P + ions, switch to coulombtype = PME.
coulombtype             = reaction-field
rcoulomb                = 1.2
epsilon-rf              = 80.0

; Van der Waals — force-switch for smooth truncation (AMBER OL15 validated)
vdwtype                 = cutoff
vdw-modifier            = force-switch
rvdw-switch             = 1.0
rvdw                    = 1.2

; Output (suppress trajectory during EM)
nstxout                 = 0
nstvout                 = 0
nstenergy               = 500
nstlog                  = 500
"""

_NVT_MDP = """\
; NADOC GROMACS — NVT validation run (vacuum / reaction-field)
; MDP settings validated against AMBER OL15 DNA Holliday junction protocol.
; Reference: sd integrator + force-switch vdW from production_ol15.mdp.

; Langevin integrator (sd) — more stable than md for charged systems
integrator              = sd
dt                      = 0.002
nsteps                  = 25000

; Langevin thermostat (built into sd integrator)
tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310
ld-seed                 = -1

; No pressure coupling (NVT)
pcoupl                  = no

; Output
nstlog                  = 500
nstenergy               = 500
nstxout-compressed      = 500
compressed-x-precision  = 1000

; Neighbour list
cutoff-scheme           = Verlet
pbc                     = xyz
nstlist                 = 20

; Electrostatics — reaction-field for vacuum/no-water runs.
; Switch to PME with explicit solvent in the future version.
coulombtype             = reaction-field
rcoulomb                = 1.2
epsilon-rf              = 80.0

; Van der Waals — force-switch (validated for AMBER/CHARMM DNA FFs)
vdwtype                 = cutoff
vdw-modifier            = force-switch
rvdw-switch             = 1.0
rvdw                    = 1.2

; Constraints — h-bonds at 2 fs timestep (standard for DNA)
constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4

; Initial velocities
gen-vel                 = yes
gen-temp                = 310
gen-seed                = -1

; Remove centre-of-mass translation
comm-mode               = Linear
nstcomm                 = 100
"""


# ══════════════════════════════════════════════════════════════════════════════
# §4  LAUNCH SCRIPT
# ══════════════════════════════════════════════════════════════════════════════

_LAUNCH_SH = r"""\
#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  NADOC GROMACS Launch Script
#  Usage:  bash launch.sh [--skip-bench] [--bench-steps N]
#  Tested: Ubuntu 22.04 / 24.04
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

# ── Flag parsing ─────────────────────────────────────────────────────────────
SKIP_BENCH=0
BENCH_STEPS=500
for _arg in "$@"; do
    case "$_arg" in
        --skip-bench)    SKIP_BENCH=1 ;;
        --bench-steps=*) BENCH_STEPS="${_arg#*=}" ;;
    esac
done

echo "═══════════════════════════════════════════════"
echo "  NADOC GROMACS Launcher  —  {name}"
echo "═══════════════════════════════════════════════"
echo ""

# ── 1. Locate or install GROMACS ─────────────────────────────────────────────
if command -v gmx &>/dev/null; then
    GMX="gmx"
    echo "→ Found gmx in PATH"
elif command -v gmx_mpi &>/dev/null; then
    GMX="gmx_mpi"
    echo "→ Found gmx_mpi in PATH"
else
    echo "→ GROMACS not found — installing via apt…"
    if sudo apt-get install -y gromacs 2>/dev/null; then
        GMX="gmx"
        echo "  GROMACS installed."
    else
        echo "ERROR: GROMACS not found and apt install failed."
        echo "Install GROMACS manually and re-run this script."
        exit 1
    fi
fi
echo "→ GROMACS: $($GMX --version 2>&1 | grep '^GROMACS version' | head -1)"
echo ""

# ── 2. Hardware detection ─────────────────────────────────────────────────────
echo "─── Hardware ────────────────────────────────────────────────────────────"
NCPU=$(nproc 2>/dev/null || echo 4)
CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs 2>/dev/null || echo "Unknown CPU")
echo "  CPU : $CPU_MODEL ($NCPU logical cores)"

HAS_GPU=0
GPU_FLAGS_PME_CPU="-nb gpu -pme cpu"
GPU_FLAGS_PME_GPU="-nb gpu -pme gpu"

if command -v nvidia-smi &>/dev/null; then
    _GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)
    if [ -n "$_GPU_INFO" ]; then
        HAS_GPU=1
        echo "  GPU : NVIDIA  $_GPU_INFO"
    fi
fi
if [ "$HAS_GPU" -eq 0 ] && command -v rocm-smi &>/dev/null; then
    _GPU_INFO=$(rocm-smi --showproductname 2>/dev/null | grep -i 'card series' | head -1 | cut -d: -f2 | xargs 2>/dev/null || true)
    if [ -n "$_GPU_INFO" ]; then
        HAS_GPU=1
        echo "  GPU : AMD  $_GPU_INFO"
    fi
fi
[ "$HAS_GPU" -eq 0 ] && echo "  GPU : none detected (CPU-only)"
echo ""

# ── 3. Energy minimisation (always CPU, needed before benchmark) ──────────────
echo "→ Step 1/3: Energy minimisation…"
$GMX grompp \
    -f em.mdp \
    -c conf.gro \
    -p topol.top \
    -o output/em.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/em_grompp.log

$GMX mdrun \
    -v \
    -deffnm output/em \
    -ntmpi 1 \
    -ntomp "$NCPU" \
    2>&1 | tee output/em_mdrun.log

echo ""

# ── 4. Hardware benchmark (uses minimised structure — no geometry crashes) ────
# The benchmark runs AFTER EM so the structure is relaxed and SD dynamics are
# stable.  All configs start from output/em.gro.
BEST_NTOMP="$NCPU"
BEST_GPU_FLAGS=""
BEST_NS_DAY="0"
BENCH_DIR=""
trap '[ -n "$BENCH_DIR" ] && rm -rf "$BENCH_DIR"' EXIT

# Floating-point greater-than using awk (avoids bc dependency)
_is_gt() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0 > b+0)}'; }

if [ "$SKIP_BENCH" -eq 1 ]; then
    echo "→ Benchmark skipped (--skip-bench).  Using $NCPU threads, CPU-only."
    echo ""
else
    BENCH_DIR="$(mktemp -d)"

    # Benchmark MDP: NVT physics, all output suppressed, very short run.
    # gen-vel=yes is safe here because em.gro has no velocities.
    cat > "$BENCH_DIR/bench.mdp" << MDPEOF
integrator     = sd
dt             = 0.002
nsteps         = $BENCH_STEPS
cutoff-scheme  = Verlet
pbc            = xyz
nstlist        = 20
coulombtype    = reaction-field
rcoulomb       = 1.2
epsilon-rf     = 80.0
vdwtype        = cutoff
vdw-modifier   = force-switch
rvdw-switch    = 1.0
rvdw           = 1.2
constraints    = h-bonds
constraint-algorithm = LINCS
lincs-iter     = 1
lincs-order    = 4
tc-grps        = System
tau-t          = 10.0
ref-t          = 310
gen-vel        = yes
gen-temp       = 310
gen-seed       = -1
nstxout        = 0
nstvout        = 0
nstfout        = 0
nstenergy      = 999999
nstlog         = 999999
MDPEOF

    BENCH_OK=1
    if ! $GMX grompp \
            -f "$BENCH_DIR/bench.mdp" \
            -c output/em.gro \
            -p topol.top \
            -o "$BENCH_DIR/bench.tpr" \
            -maxwarn 20 \
            -nobackup 2>"$BENCH_DIR/grompp.err"; then
        echo "  Benchmark grompp failed — using $NCPU threads, CPU-only."
        BENCH_OK=0
    fi

    if [ "$BENCH_OK" -eq 1 ]; then
        # _bench NTOMP [EXTRA_FLAGS...] — echoes ns/day, or "FAIL"
        # Reads Performance line from the log file (reliable across all GROMACS
        # versions and verbosity levels; stdout output varies).
        _bench() {
            local ntomp="$1"; shift
            local run_dir ns_day
            run_dir="$(mktemp -d "$BENCH_DIR/r_XXXX")"
            $GMX mdrun \
                -s "$BENCH_DIR/bench.tpr" \
                -deffnm "$run_dir/b" \
                -ntmpi 1 \
                -ntomp "$ntomp" \
                "$@" \
                >/dev/null 2>&1 || true
            ns_day=$(awk '/Performance:/{print $2; exit}' "$run_dir/b.log" 2>/dev/null || true)
            rm -rf "$run_dir"
            [ -n "$ns_day" ] && echo "$ns_day" || echo "FAIL"
        }

        # Thread candidates: powers of 2 from 2 up to (but not including) NCPU,
        # then NCPU itself.  E.g. NCPU=16 → [2, 4, 8, 16].
        THREAD_COUNTS=()
        _t=2
        while [ "$_t" -lt "$NCPU" ]; do
            THREAD_COUNTS+=("$_t")
            _t=$((_t * 2))
        done
        THREAD_COUNTS+=("$NCPU")

        echo "─── Benchmark results ($BENCH_STEPS steps from minimised structure) ──────────"
        printf "  %-36s  %10s\n" "Configuration" "ns/day"
        printf "  %-36s  %10s\n" "────────────────────────────────────" "──────────"

        for _ntomp in "${THREAD_COUNTS[@]}"; do
            _ns=$(_bench "$_ntomp")
            printf "  %-36s  %10s\n" "CPU × ${_ntomp} threads" "$_ns"
            if [ "$_ns" != "FAIL" ] && _is_gt "$_ns" "$BEST_NS_DAY"; then
                BEST_NS_DAY="$_ns"; BEST_NTOMP="$_ntomp"; BEST_GPU_FLAGS=""
            fi
        done

        # GPU configs: test with max threads + two PME offload strategies
        if [ "$HAS_GPU" -eq 1 ]; then
            for _gflags in "$GPU_FLAGS_PME_CPU" "$GPU_FLAGS_PME_GPU"; do
                # shellcheck disable=SC2086
                _ns=$(_bench "$NCPU" $_gflags)
                printf "  %-36s  %10s\n" "GPU × $NCPU  $_gflags" "$_ns"
                if [ "$_ns" != "FAIL" ] && _is_gt "$_ns" "$BEST_NS_DAY"; then
                    BEST_NS_DAY="$_ns"; BEST_NTOMP="$NCPU"; BEST_GPU_FLAGS="$_gflags"
                fi
            done
        fi

        echo ""
        if _is_gt "$BEST_NS_DAY" "0"; then
            # NVT: nsteps=25000, dt=0.002 ps → 50 ps = 0.05 ns
            NVT_ETA=$(awk -v r="$BEST_NS_DAY" 'BEGIN{printf "%.1f", 0.05 / r * 24 * 60}')
            _cfg="$BEST_NTOMP threads"
            [ -n "$BEST_GPU_FLAGS" ] && _cfg="$BEST_NTOMP threads  $BEST_GPU_FLAGS"
            echo "  Best config : $_cfg  (${BEST_NS_DAY} ns/day)"
            echo "  NVT ETA     : ~${NVT_ETA} min for 50 ps"
        else
            echo "  Benchmark inconclusive — using $NCPU threads, CPU-only."
        fi
        echo ""
    fi
fi

# Final mdrun flags for NVT (word-split intentionally when expanded unquoted)
MDRUN_FLAGS="-ntmpi 1 -ntomp $BEST_NTOMP"
[ -n "$BEST_GPU_FLAGS" ] && MDRUN_FLAGS="$MDRUN_FLAGS $BEST_GPU_FLAGS"

# ── 5. NVT validation run ────────────────────────────────────────────────────
echo "→ Step 2/3: NVT validation run (50 ps)…"
$GMX grompp \
    -f nvt.mdp \
    -c output/em.gro \
    -p topol.top \
    -o output/nvt.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/nvt_grompp.log

LOG="output/nvt_mdrun.log"
# shellcheck disable=SC2086
$GMX mdrun \
    -v \
    -deffnm output/nvt \
    $MDRUN_FLAGS \
    -x output/nvt.xtc \
    2>&1 | tee "$LOG" &
MDRUN_PID=$!

python3 scripts/monitor.py "$LOG" "$MDRUN_PID"

echo ""

# ── 6. Basic analysis ────────────────────────────────────────────────────────
echo "→ Step 3/3: RMSD analysis…"
if [ -f output/nvt.xtc ]; then
    echo "0 0" | $GMX rms \
        -s output/nvt.tpr \
        -f output/nvt.xtc \
        -o output/rmsd.xvg \
        -tu ns \
        -nobackup 2>&1 | tee output/rmsd_analysis.log \
    && echo "  RMSD trace → output/rmsd.xvg" \
    || echo "  RMSD analysis skipped (check output/rmsd_analysis.log)"
fi

echo ""
echo "Done.  Output files are in output/"
echo "  em.gro           — energy-minimised structure"
echo "  nvt.xtc          — NVT trajectory"
echo "  nvt.edr          — energy time series"
echo "  rmsd.xvg         — backbone RMSD vs minimised structure"
echo ""
echo "Visualise with VMD:  vmd output/em.gro output/nvt.xtc"
"""


# ══════════════════════════════════════════════════════════════════════════════
# §5  MONITOR SCRIPT (GROMACS log parser)
# ══════════════════════════════════════════════════════════════════════════════

_MONITOR_PY = r'''\
#!/usr/bin/env python3
"""
NADOC GROMACS Progress Monitor
Reads the mdrun log file in real time and shows a live energy table.
Uses only Python standard library.

Usage:  python3 scripts/monitor.py <log_file> <mdrun_pid>
"""
import argparse
import os
import re
import sys
import time

_STEP_RE    = re.compile(r'^\s+Step\s+Time\s*$')
_EPOT_RE    = re.compile(r'Potential Energy\s*=\s*([\-\d.eE+]+)')
_EKIN_RE    = re.compile(r'Kinetic En\.\s*=\s*([\-\d.eE+]+)')
_ETOT_RE    = re.compile(r'Total Energy\s*=\s*([\-\d.eE+]+)')
_TEMP_RE    = re.compile(r'Temperature\s*=\s*([\-\d.eE+]+)')
_STEPS_FROM_MDP = re.compile(r'nsteps\s*=\s*(\d+)', re.IGNORECASE)
_HEADER_SHOWN = False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _print_header():
    global _HEADER_SHOWN
    if not _HEADER_SHOWN:
        print(f"{'Step':>8}  {'Time(ps)':>10}  {'Epot(kJ/mol)':>15}  {'Temp(K)':>9}  {'Etot(kJ/mol)':>15}")
        print("─" * 68)
        _HEADER_SHOWN = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log_file")
    ap.add_argument("mdrun_pid", type=int)
    args = ap.parse_args()

    pid      = args.mdrun_pid
    logpath  = args.log_file

    waited = 0
    while not os.path.exists(logpath):
        if not _pid_alive(pid):
            print("mdrun exited before writing log — check the log file for errors.")
            sys.exit(1)
        time.sleep(0.5)
        waited += 0.5
        if waited > 60:
            print("Timeout waiting for GROMACS log file.")
            sys.exit(1)

    total_steps = None
    last_step   = -1
    buf         = ""

    # Multi-line state machine to extract energy blocks
    in_energies  = False
    step_val     = None
    time_val     = None
    epot, ekin, etot, temp = None, None, None, None

    with open(logpath, "r", errors="replace") as fh:
        while True:
            chunk = fh.read(65536)
            if chunk:
                buf += chunk

                if total_steps is None:
                    m = _STEPS_FROM_MDP.search(buf)
                    if m:
                        total_steps = int(m.group(1))

                for raw_line in buf.splitlines():
                    line = raw_line.strip()

                    # Detect "Step   Time" header
                    if _STEP_RE.match(raw_line):
                        in_energies = False   # reset between frames
                        continue

                    # Step and time values follow the Step/Time header
                    if step_val is None and re.match(r'^\s*(\d+)\s+([\d.]+)\s*$', raw_line):
                        m = re.match(r'^\s*(\d+)\s+([\d.]+)\s*$', raw_line)
                        if m:
                            step_val = int(m.group(1))
                            time_val = float(m.group(2))
                            in_energies = True
                            epot = ekin = etot = temp = None
                        continue

                    if in_energies:
                        m = _EPOT_RE.search(line)
                        if m:
                            epot = float(m.group(1))
                        m = _EKIN_RE.search(line)
                        if m:
                            ekin = float(m.group(1))
                        m = _ETOT_RE.search(line)
                        if m:
                            etot = float(m.group(1))
                        m = _TEMP_RE.search(line)
                        if m:
                            temp = float(m.group(1))

                    # Flush once we have a complete energy block
                    if in_energies and step_val is not None and etot is not None and temp is not None:
                        if step_val > last_step:
                            _print_header()
                            epot_s = f"{epot:15.1f}" if epot is not None else f"{'N/A':>15s}"
                            etot_s = f"{etot:15.1f}"
                            print(f"{step_val:>8d}  {time_val:>10.3f}  {epot_s}  {temp:>9.1f}  {etot_s}")
                            last_step = step_val
                        in_energies  = False
                        step_val = time_val = None
                        epot = ekin = etot = temp = None

                # Keep only the last partial line
                nl = buf.rfind("\n")
                if nl >= 0:
                    buf = buf[nl + 1:]

            elif not _pid_alive(pid):
                break
            else:
                time.sleep(0.3)

    if _HEADER_SHOWN:
        print("─" * 68)
        print("  mdrun finished.")
    else:
        print("No energy output detected.  Check the GROMACS log for errors.")


if __name__ == "__main__":
    main()
'''


# ══════════════════════════════════════════════════════════════════════════════
# §6  README AND AI PROMPT
# ══════════════════════════════════════════════════════════════════════════════

_README = """\
NADOC — GROMACS Simulation Package
====================================
Design: {name}
Force field: {ff}
Generated by: NADOC (Not Another DNA Origami CAD)

QUICK START
-----------
  bash launch.sh               # benchmark then run (recommended)
  bash launch.sh --skip-bench  # skip benchmark, use all CPU cores

The script will:
  1. Install GROMACS via apt if not already present (requires sudo once)
  2. Detect CPU model / core count and any NVIDIA or AMD GPU
  3. Run a short benchmark (500 steps) across thread/GPU configurations
     and select the fastest setup automatically
  4. Energy-minimise the structure
  5. Run a 50 ps NVT validation trajectory
  6. Compute backbone RMSD vs the minimised structure

FILES
-----
  conf.gro         All-atom initial structure (GROMACS format, Å)
  topol.top        GROMACS topology (references {ff}.ff/ bundled here)
  *.itp            Per-strand molecule topology includes
  {ff}.ff/         Bundled force-field directory — no GROMACS installation
                   needed to run grompp; only for mdrun
  em.mdp           Energy-minimisation parameters
  nvt.mdp          NVT production run parameters (50 ps)
  scripts/         monitor.py — real-time progress display (stdlib only)
  output/          Created by launch.sh; contains all output files

SIMULATION DETAILS
------------------
  Force field  : {ff} (MacKerell lab)
  Electrostatics: Reaction-Field (epsilon = 80) — approximates implicit solvent
                  without requiring an explicit water box.  Suitable for
                  structural validation; not a substitute for explicit solvent
                  for thermodynamic calculations.
  Temperature  : 310 K (NVT, V-rescale thermostat)
  Timestep     : 1 fs
  Minimization : Steepest descent, 50 000 steps max (emtol 1000 kJ/mol/nm)
  Production   : 25 000 steps = 50 ps (sd integrator, 2 fs timestep)

LIMITATIONS (simplest version)
--------------------------------
  * No explicit water or counter-ions.
  * Cross-helix crossover bonds are NOT in the topology — each strand is an
    independent molecule.  Helices may drift apart in long simulations.
  * For publication-quality work use AMBER OL15 force field (ff99bsc0 +
    chiOL4 + ezOL1 + bOL1) via AmberTools/tleap with TIP3P water and Mg2+
    ions (~15 mM MgCl2).  This requires the future NADOC "explicit solvent"
    export mode, or manual setup using the AMBER OL15 build protocol.

WHAT TO LOOK FOR
----------------
  Stability     : Total energy should decrease during EM and plateau in NVT.
                  If it diverges, the initial geometry has a severe clash.
  Thermal motion: RMSD < 1 Å indicates stable B-DNA geometry.
                  RMSD > 3 Å suggests structural instability.
  Bending/twist : Load output/nvt.xtc in VMD and measure helix-axis angles.

ANALYSIS WITH GROMACS TOOLS
-----------------------------
  Note: group 0 = System (all atoms).  DNA-only topologies do not have
  protein backbone groups (4, 5 …).  Always use group 0 for DNA.

  RMSD vs minimised structure:
    echo "0 0" | gmx rms -s output/nvt.tpr -f output/nvt.xtc \\
                          -o output/rmsd.xvg -tu ns

  B-factor (RMSF per residue):
    echo "0" | gmx rmsf -s output/nvt.tpr -f output/nvt.xtc \\
                         -o output/rmsf.xvg -res

  List available energy terms then extract one:
    gmx energy -f output/nvt.edr         (prints numbered list, Ctrl-D to quit)
    echo "Potential" | gmx energy -f output/nvt.edr -o output/potential.xvg

VISUALISATION
-------------
  VMD (free, UIUC):
    vmd output/em.gro output/nvt.xtc

CITATIONS
---------
  GROMACS: Abraham et al., SoftwareX 1-2, 19-25 (2015)
  CHARMM36 NA: Hart et al., J. Chem. Theory Comput. 8, 348-362 (2012)
"""

_AI_PROMPT = """\
=============================================================================
NADOC — GROMACS SIMULATION PACKAGE: AI ASSISTANT CONTEXT
=============================================================================

Paste this block into Claude, ChatGPT, or any AI assistant for step-by-step
guidance on running and analysing this simulation without prior MD experience.

DESIGN: {name}
FORCE FIELD: {ff}
SOLVER: GROMACS (reaction-field implicit solvent, no water box)
ENSEMBLE: NVT 310 K, 50 ps

FILES INCLUDED
--------------
  conf.gro       Initial structure (all-atom, GROMACS format)
  topol.top      Topology (bonds, angles, dihedrals, charges)
  *.itp          Per-strand topology includes
  {ff}.ff/       Force-field directory (bundled — no GMXDATA needed)
  em.mdp         Energy-minimisation parameters
  nvt.mdp        NVT run parameters (50 ps at 310 K)
  launch.sh      One-click launcher (installs GROMACS if absent)
  scripts/monitor.py  Real-time progress display (stdlib only)

RUNNING
-------
  bash launch.sh               # auto-benchmark then run
  bash launch.sh --skip-bench  # skip benchmark, use all CPU cores
  bash launch.sh --bench-steps=200  # faster benchmark (fewer steps)

OUTPUT FILES (in output/)
-------------------------
  em.gro          Minimised structure
  nvt.xtc         Trajectory (XTC compressed, every 0.5 ps)
  nvt.edr         Energy time series
  nvt.log         Full mdrun log
  rmsd.xvg        Backbone RMSD vs minimised structure (ns)

WHAT TO CHECK
-------------
  1. Did EM converge?  Look for "Converged to machine precision" or
     "Maximum force below emtol" in output/em_mdrun.log.
  2. Is total energy stable in NVT?  Plot output/nvt.edr with:
       echo "Potential" | gmx energy -f output/nvt.edr -o temp.xvg
     (DNA-only topologies do not have the protein group numbering used
      in most GROMACS tutorials; pass the term name instead of a number)
  3. Is RMSD reasonable?  Plot output/rmsd.xvg — values below 1 Å
     indicate a stable B-DNA structure.

LIMITATIONS TO MENTION IN PUBLICATIONS
---------------------------------------
  - No explicit water; reaction-field electrostatics used.
  - Counter-ions not included; overall system charge is negative.
  - Crossover bonds between helices are NOT in the topology for this
    version — each strand is simulated independently.

=============================================================================
END OF CONTEXT
=============================================================================
"""


# ══════════════════════════════════════════════════════════════════════════════
# §6b  POST-pdb2gmx FIXUP
# ══════════════════════════════════════════════════════════════════════════════

def _fix_itp_case(tmpdir: Path) -> None:
    """
    Reconcile ITP filename case with the #include directives in topol.top.

    pdb2gmx behaviour is version-dependent: some versions uppercase the
    molecule-type name (and thus the #include path in topol.top) while writing
    the ITP file itself with the lowercase chain letter from the PDB, or vice
    versa.  On a case-sensitive Linux filesystem this causes a fatal "include
    file not found" error when grompp reads topol.top.

    Strategy: topol.top is authoritative (grompp reads it first).  For every
    #include "*.itp" line, find the matching file on disk with a
    case-insensitive lookup and rename it to exactly match the include path.
    """
    topol_path = tmpdir / "topol.top"
    if not topol_path.exists():
        return

    # Case-insensitive map: lowercase name → actual Path
    on_disk: dict[str, Path] = {p.name.lower(): p for p in tmpdir.glob("*.itp")}

    include_re = re.compile(r'(#include\s+")([^"]+\.itp)(")')
    for m in include_re.finditer(topol_path.read_text()):
        fname  = m.group(2)          # name as written in topol.top
        actual = on_disk.get(fname.lower())
        if actual is not None and actual.name != fname:
            target = tmpdir / fname
            actual.rename(target)
            on_disk[fname.lower()] = target  # update map in case of duplicates


# ══════════════════════════════════════════════════════════════════════════════
# §7  MAIN BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_gromacs_package(design: Design) -> bytes:
    """
    Build and return the raw ZIP bytes of a self-contained GROMACS package.

    Runs pdb2gmx + editconf server-side (requires GROMACS in PATH).
    Bundles the resulting topology, structure, force-field files, MDP files,
    launch script, and README into a single ZIP.
    """
    gmx     = _find_gmx()
    top_dir = _find_top_dir()
    ff      = _pick_ff(top_dir)
    ff_dir  = top_dir / f"{ff}.ff"
    name    = (design.metadata.name or "design").replace(" ", "_")

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        # ── 1. Build pdb2gmx-compatible PDB ──────────────────────────────────
        # Extra-base crossover residues are interleaved at their correct 5'→3'
        # position within each chain so pdb2gmx generates the right sequential
        # backbone bonds (standard export_pdb appends them at chain end, which
        # causes pdb2gmx to create wrong direct bonds across the crossover).
        adapted = _build_gromacs_input_pdb(design, ff, box_margin_nm=2.0)
        input_pdb = tmpdir / "input.pdb"
        input_pdb.write_text(adapted)

        # ── 2. pdb2gmx — generate topology + GRO ─────────────────────────────
        pdb2gmx_result = subprocess.run(
            [
                gmx, "pdb2gmx",
                "-f", str(input_pdb),
                "-o", str(tmpdir / "conf_raw.gro"),
                "-p", str(tmpdir / "topol.top"),
                "-ignh",           # add H; ignore any H in PDB
                "-ff", ff,
                "-water", "none",  # vacuum — no explicit water
                "-nobackup",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmpdir),
        )
        if pdb2gmx_result.returncode != 0:
            raise RuntimeError(
                f"pdb2gmx failed (ff={ff}):\n"
                f"--- stdout ---\n{pdb2gmx_result.stdout[-3000:]}\n"
                f"--- stderr ---\n{pdb2gmx_result.stderr[-3000:]}"
            )

        # ── 2b. Reconcile ITP filename case with topol.top #include paths ─────
        _fix_itp_case(tmpdir)

        # ── 3. editconf — set up simulation box (2 nm margin) ────────────────
        editconf_result = subprocess.run(
            [
                gmx, "editconf",
                "-f", str(tmpdir / "conf_raw.gro"),
                "-o", str(tmpdir / "conf.gro"),
                "-c",           # centre molecule
                "-d", "2.0",    # 2 nm margin to box edge
                "-bt", "triclinic",
                "-nobackup",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmpdir),
        )
        if editconf_result.returncode != 0:
            raise RuntimeError(
                f"editconf failed:\n{editconf_result.stderr[-2000:]}"
            )

        # ── 4. Collect generated files ────────────────────────────────────────
        conf_gro  = (tmpdir / "conf.gro").read_text()
        topol_top = (tmpdir / "topol.top").read_text()
        itp_files = {p.name: p.read_bytes() for p in tmpdir.glob("*.itp")}

        # ── 5. Assemble ZIP ───────────────────────────────────────────────────
        prefix = f"{name}_gromacs/"
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Structure and topology
            zf.writestr(prefix + "conf.gro",   conf_gro)
            zf.writestr(prefix + "topol.top",  topol_top)
            for itp_name, itp_bytes in itp_files.items():
                zf.writestr(prefix + itp_name, itp_bytes)

            # MDP files
            zf.writestr(prefix + "em.mdp",  _EM_MDP)
            zf.writestr(prefix + "nvt.mdp", _NVT_MDP)

            # Bundled force-field directory (entire tree)
            for ff_file in ff_dir.rglob("*"):
                if ff_file.is_file():
                    arcname = prefix + ff + ".ff/" + ff_file.relative_to(ff_dir).as_posix()
                    zf.write(str(ff_file), arcname)

            # launch.sh (executable bit)
            launch_info = zipfile.ZipInfo(prefix + "launch.sh")
            launch_info.compress_type = zipfile.ZIP_DEFLATED
            launch_info.external_attr = (
                stat.S_IFREG | stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP
                | stat.S_IROTH | stat.S_IXOTH
            ) << 16
            zf.writestr(launch_info, _LAUNCH_SH.replace("{name}", name))

            # Scripts and docs
            zf.writestr(prefix + "scripts/monitor.py",       _MONITOR_PY)
            zf.writestr(prefix + "README.txt",
                        _README.format(name=name, ff=ff))
            zf.writestr(prefix + "AI_ASSISTANT_PROMPT.txt",
                        _AI_PROMPT.format(name=name, ff=ff))

        buf.seek(0)
        return buf.getvalue()


# ── Convenience: run all pdb2gmx steps and return summary dict ────────────────

def probe_gromacs() -> dict:
    """
    Return a dict with GROMACS discovery info.  Useful for health-check endpoints.
    """
    try:
        gmx     = _find_gmx()
        top_dir = _find_top_dir()
        ff      = _pick_ff(top_dir)
        ver     = subprocess.run(
            [gmx, "--version"], capture_output=True, text=True
        ).stdout.splitlines()
        version = next((l for l in ver if "GROMACS version" in l), "unknown")
        return {"available": True, "binary": gmx, "ff": ff,
                "top_dir": str(top_dir), "version": version}
    except RuntimeError as e:
        return {"available": False, "error": str(e)}
