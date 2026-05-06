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
    "charmm36-feb2026_cgenff-5.0",
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
    """Return GROMACS top/ directory containing force field sub-directories.

    Priority:
    1. GMXDATA / GMXLIB environment variable (user override).
    2. Data prefix reported by `gmx --version` (handles conda / custom installs
       whose prefix is not one of the standard system paths).
    3. Well-known system paths (/usr/share/gromacs/top, etc.).
    """
    candidates: list[Path] = []

    # 1. Explicit env override
    # GROMACS convention: GMXDATA = share/gromacs/ (parent of top/),
    #                     GMXLIB  = share/gromacs/top/ (the top/ dir itself)
    gmxlib  = os.environ.get("GMXLIB")
    gmxdata = os.environ.get("GMXDATA")
    if gmxlib:
        candidates.append(Path(gmxlib))
    if gmxdata:
        candidates.append(Path(gmxdata) / "top")

    # 2. Ask the gmx binary itself where its data lives
    try:
        gmx = _find_gmx()
        result = subprocess.run(
            [gmx, "--version"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if line.strip().startswith("Data prefix:"):
                prefix = line.split(":", 1)[1].strip()
                candidates.append(Path(prefix) / "share" / "gromacs" / "top")
                break
    except Exception:
        pass  # fall through to hardcoded paths

    # 3. Common system install paths
    candidates += [
        Path("/usr/share/gromacs/top"),
        Path("/usr/local/share/gromacs/top"),
        Path("/opt/gromacs/share/gromacs/top"),
    ]

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
    # charmm36-feb2026_cgenff-5.0 (from charmm2gmx) uses O1P/O2P and C5M —
    # the old-style naming identical to charmm27, despite being a charmm36 release.
    # Earlier charmm36 variants (jul2022, charmm36m) use OP1/OP2 and C7.
    renames_by_res: dict[str, dict[str, str]] = {}
    if ff == "charmm36-feb2026_cgenff-5.0":
        renames_by_res = _RENAMES_CHARMM27
    elif ff.startswith("charmm36") or ff.startswith("charmm36m"):
        return pdb_text   # OP1/OP2 + C7 matches NADOC directly
    elif ff.startswith("amber"):
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

def _build_gromacs_input_pdb(design: "Design", ff: str, box_margin_nm: float = 2.0, *, use_deformed: bool = True, nuc_pos_override=None) -> str:
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

    if not use_deformed:
        design = design.model_copy(update={"deformations": [], "cluster_transforms": []})
    model = build_atomistic_model(design, nuc_pos_override=nuc_pos_override)
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
; NADOC GROMACS — Energy Minimisation (vacuum + PME electrostatics)
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

; Electrostatics — PME for accurate long-range treatment in vacuum.
; Reaction-field with epsilon-rf=80 caused artificial compaction by damping
; inter-helix repulsion beyond rcoulomb while leaving short-range attractions
; unscreened, drawing Na+ ions into the grooves.  PME correctly handles all
; distances via Ewald summation with no cutoff discontinuity.
coulombtype             = PME
rcoulomb                = 1.2
pme-order               = 4
fourierspacing          = 0.12

; Van der Waals — force-switch for smooth truncation (AMBER OL15 validated)
vdwtype                 = cutoff
vdw-modifier            = force-switch
rvdw-switch             = 1.0
rvdw                    = 1.2

; No constraints in EM: steepest descent follows bonded force gradients,
; so bond lengths minimize naturally.  Crossover terminal atoms (O3'/H5T,
; O5'/O1P) from different GROMACS chains clash at ~0.05 nm; constraining
; h-bonds here causes >1000 LINCS warnings as EM tries to resolve them.
; NVT uses constraints=h-bonds, which is the correct place to enforce them.
constraints             = none

; Output (suppress trajectory during EM)
nstxout                 = 0
nstvout                 = 0
nstenergy               = 500
nstlog                  = 500
"""

_NVT_MDP = """\
; NADOC GROMACS — NVT equilibration with position restraints (vacuum + PME)
; MDP settings validated against AMBER OL15 DNA Holliday junction protocol.
;
; WHY POSITION RESTRAINTS?
; pdb2gmx generates posre_DNA_chain_X.itp for every chain (all heavy atoms,
; spring constant 1000 kJ/mol/nm²).  The topology models each DNA strand as an
; independent molecule — crossover bonds between helices are not included.
; Without restraints helices immediately drift apart under electrostatic
; repulsion, which confounds design validation.
;
; With restraints, the simulation answers: "does this geometry have severe
; steric clashes or force-field inconsistencies?"
;   RMSD < 1 Å after 50 ps  → geometry is physically reasonable
;   Energy diverges          → steric clash or geometry error in the design
;
; For unrestrained dynamics (helices will drift — expected), use nvt_free.mdp.

; Langevin integrator (sd) — more stable than md for charged systems
integrator              = sd
dt                      = 0.002
nsteps                  = 25000

; ── Position restraints ──────────────────────────────────────────────────────
; Activates #ifdef POSRES blocks in posre_DNA_chain_X.itp (all heavy atoms).
; refcoord_scaling = com shifts reference coords with the centre of mass to
; avoid artificial drift artefacts with a non-cubic box.
define                  = -DPOSRES
refcoord_scaling        = com

; Langevin thermostat (built into sd integrator)
; tau-t = 2 ps (γ = 0.5 ps⁻¹) — tighter friction needed in vacuum because
; there is no solvent to dissipate energy; 10 ps is appropriate only with
; explicit water which provides its own damping.
tc-grps                 = System
tau-t                   = 2.0
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

; Electrostatics — PME for accurate long-range treatment in vacuum.
coulombtype             = PME
rcoulomb                = 1.2
pme-order               = 4
fourierspacing          = 0.12

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

; Initial velocities — start from 0 K; annealing ramp heats to 310 K
gen-vel                 = yes
gen-temp                = 0.0
gen-seed                = -1

; Remove centre-of-mass translation
comm-mode               = Linear
nstcomm                 = 100
"""

_NVT_FREE_MDP = """\
; NADOC GROMACS — NVT free dynamics (vacuum + PME)
; No position restraints.  Use after restrained equilibration (nvt.mdp), or
; to observe unrestrained behaviour.
;
; NOTE: Without crossover bonds in the topology, independent DNA helices will
; drift apart over time — this is an expected topology limitation, not a design
; flaw.  Explosive instability (energy divergence, atoms escaping) indicates a
; genuine geometry error.  Slow, gradual drift is normal.
; MDP settings validated against AMBER OL15 DNA Holliday junction protocol.

; Langevin integrator (sd) — more stable than md for charged systems
integrator              = sd
dt                      = 0.002
nsteps                  = 25000

; Langevin thermostat — tau-t = 2 ps for vacuum (no solvent damping)
tc-grps                 = System
tau-t                   = 2.0
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

; Electrostatics — PME for accurate long-range treatment in vacuum.
coulombtype             = PME
rcoulomb                = 1.2
pme-order               = 4
fourierspacing          = 0.12

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

; Continue from NVT checkpoint — system is already at 310 K
gen-vel                 = no
continuation            = yes

; Remove centre-of-mass translation
comm-mode               = Linear
nstcomm                 = 100
"""

# ──────────────────────────────────────────────────────────────────────────────
# §3b  MDP TEMPLATES — EXPLICIT SOLVENT (TIP3P + ions, PME electrostatics)
#
# Based on validated settings from AutoNAMD/gromacs/mdp_templates/ (production
# Holliday junction equilibration protocol, AMBER OL15 / CHARMM36m force fields).
# Protocol: EM → NVT 100 ps (POSRES) → NPT 1 ns (POSRES)
# ──────────────────────────────────────────────────────────────────────────────

# Minimal MDP passed to grompp before genion — no real dynamics.
_IONS_MDP = """\
; Minimal MDP for ion placement — used only by grompp before genion
integrator      = steep
nsteps          = 0
nstlog          = 0
nstenergy       = 0

cutoff-scheme   = Verlet
nstlist         = 10
rlist           = 1.2
rcoulomb        = 1.0
rvdw            = 1.0
coulombtype     = cutoff
pbc             = xyz
"""

_EM_MDP_SOL = """\
; NADOC GROMACS — Energy Minimisation (explicit TIP3P water + ions)
; Based on AutoNAMD validated settings (minimization.mdp).

integrator              = steep
emtol                   = 10.0
emstep                  = 0.01
nsteps                  = 5000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

constraints             = none

nstxout                 = 0
nstvout                 = 0
nstenergy               = 500
nstlog                  = 500
"""

_NVT_MDP_SOL = """\
; NADOC GROMACS — NVT equilibration (explicit TIP3P + ions, position restraints)
; 100 ps heat equilibration with DNA heavy atoms restrained.
; Based on AutoNAMD validated protocol (nvt_equil.mdp).
;
; WHY POSITION RESTRAINTS?
; Each strand is a separate topology molecule — crossover bonds are absent.
; POSRES holds helices in place while water and ions equilibrate around the DNA.
; RMSD < 1 Å after 100 ps confirms no steric clash in the design.

integrator              = sd
dt                      = 0.002
nsteps                  = 50000       ; 100 ps

nstxout-compressed      = 5000        ; save every 10 ps
nstvout                 = 0
nstfout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = no

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4
continuation            = no
gen-vel                 = yes
gen-temp                = 0.0
gen-seed                = -1

define                  = -DPOSRES
refcoord_scaling        = com
comm-mode               = Linear
nstcomm                 = 100

; Ramp 0→310 K to prevent LINCS failures from kinetic shock at t=0.
; annealing-time spans [0, total_sim_ps] = [0, 100] at dt=0.002, nsteps=50000.
annealing               = single
annealing-npoints       = 4
annealing-time          = 0  10  50  100
annealing-temp          = 0  100 310 310
"""

_NPT_MDP_SOL = """\
; NADOC GROMACS — NPT equilibration (explicit TIP3P + ions, position restraints)
; 1 ns box-volume relaxation with DNA restrained.  Continue from NVT checkpoint.
; Based on AutoNAMD validated protocol (npt_equil.mdp).

integrator              = sd
dt                      = 0.002
nsteps                  = 500000      ; 1 ns

nstxout-compressed      = 5000        ; save every 10 ps
nstvout                 = 0
nstfout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = C-rescale
pcoupltype              = isotropic
tau-p                   = 5.0
ref-p                   = 1.0
compressibility         = 4.5e-5

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4
continuation            = yes
gen-vel                 = no

define                  = -DPOSRES
refcoord_scaling        = com
comm-mode               = Linear
nstcomm                 = 100
"""

_NVT_FREE_MDP_SOL = """\
; NADOC GROMACS — NVT free dynamics (explicit TIP3P + ions, no restraints)
; Run after NPT equilibration for unrestrained production-like dynamics.
;
; NOTE: Without crossover bonds in the topology, independent DNA helices will
; drift apart over time — this is an expected topology limitation.
; For production MD, add crossover bonds or use a coarse-grained model.

integrator              = sd
dt                      = 0.002
nsteps                  = 50000       ; 100 ps

nstxout-compressed      = 5000
nstvout                 = 0
nstfout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = no

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4
continuation            = yes
gen-vel                 = no

comm-mode               = Linear
nstcomm                 = 100
"""

# ── Extra-base crossover MDP templates (solvated, staged equilibration) ───────
#
# Designs with extra-T crossover insertions need a more careful equilibration
# sequence.  The inserted residues sit at strained backbone geometry that
# explodes if POSRES is removed abruptly.  The protocol is:
#
#   em_free   (no constraints, no POSRES) — relax strained backbone to FF geometry
#   em_posres (h-bonds + POSRES)          — lock h-bond lengths before dynamics
#   nvt       (annealed 0→310 K, POSRES, dt=0.001) — gentle heating
#   npt       (C-rescale, POSRES 1000 kJ, dt=0.001) — box volume relaxation
#   npt_low   (C-rescale, POSRES  100 kJ, dt=0.001) — partial release
#   npt_release (C-rescale, no POSRES,   dt=0.001) — full release check
#   nvt_free  (production-like, 310 K)

_EM_FREE_MDP_SOL = """\
; NADOC GROMACS — Phase 1 EM: free (no POSRES, no h-bond constraints)
; Lets strained extra-T crossover residues relax to force-field geometry.
; h-bond constraints omitted to avoid LINCS warnings at crossover terminus
; atoms (O3'/H5T, O5'/O1P) that clash during steepest-descent EM.

integrator              = steep
emtol                   = 100.0
emstep                  = 0.005
nsteps                  = 100000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

constraints             = none

nstxout                 = 0
nstvout                 = 0
nstenergy               = 500
nstlog                  = 500
"""

_EM_POSRES_MDP_SOL = """\
; NADOC GROMACS — Phase 2 EM: POSRES + h-bond constraints
; Runs after free EM.  Holds extra-T crossover atoms at relaxed geometry while
; locking h-bond lengths at LINCS targets so NVT has zero correction to apply.

integrator              = steep
emtol                   = 1000.0
emstep                  = 0.01
nsteps                  = 50000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 2
lincs-order             = 4
define                  = -DPOSRES

nstxout                 = 0
nstvout                 = 0
nstenergy               = 500
nstlog                  = 500
"""

_NPT_LOW_MDP_SOL = """\
; NADOC GROMACS — Staged POSRES release step 1: 100 ps at 100 kJ/mol/nm²
; Lets strained extra-T crossover atoms partially relax before full release.

integrator              = sd
dt                      = 0.001
nsteps                  = 100000          ; 100 ps

nstxout-compressed      = 5000
nstvout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = C-rescale
pcoupltype              = isotropic
tau-p                   = 5.0
ref-p                   = 1.0
compressibility         = 4.5e-5

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 2
lincs-order             = 4
continuation            = yes
gen-vel                 = no

define                  = -DPOSRES_LOW
refcoord_scaling        = com
"""

_NPT_RELEASE_MDP_SOL = """\
; NADOC GROMACS — Staged POSRES release step 2: 200 ps with no POSRES
; Final equilibration — confirms strained atoms are stable without restraints.

integrator              = sd
dt                      = 0.001
nsteps                  = 200000          ; 200 ps

nstxout-compressed      = 5000
nstvout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = C-rescale
pcoupltype              = isotropic
tau-p                   = 5.0
ref-p                   = 1.0
compressibility         = 4.5e-5

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 2
lincs-order             = 4
continuation            = yes
gen-vel                 = no
"""


# ══════════════════════════════════════════════════════════════════════════════
# §4  LAUNCH SCRIPT
# ══════════════════════════════════════════════════════════════════════════════

_LAUNCH_SH = r"""#!/usr/bin/env bash
# NADOC GROMACS — Vacuum equilibration with Na+ counterions
# Protocol: EM → benchmark → NVT restrained 0→310 K → NVT free 310 K
# Requires: GROMACS 2021+ on PATH.   Usage: bash launch.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GMX="${GMX:-gmx}"
export GMX_NO_QUOTES=1   # suppress GROMACS random quotes in output
mkdir -p output

# ── Thread selection: default = half of available cores ───────────────────────
NCPU=$(nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 4)
NTHREADS=$(( NCPU / 2 ))
[ "$NTHREADS" -lt 1 ] && NTHREADS=1

# ── GPU detection ─────────────────────────────────────────────────────────────
GPU_FLAGS=""
if nvidia-smi -L &>/dev/null; then
    GPU_FLAGS="-gpu_id 0"
    echo "  GPU detected (NVIDIA) — will use -gpu_id 0 for simulation phases"
elif rocm-smi &>/dev/null; then
    GPU_FLAGS="-gpu_id 0"
    echo "  GPU detected (AMD/ROCm) — will use -gpu_id 0 for simulation phases"
fi

# ── Phase 1: Energy minimisation ─────────────────────────────────────────────
echo ""
echo "=== Phase 1/4: Energy minimisation ==="
"$GMX" grompp -f em.mdp -c conf.gro -p topol.top -o output/em.tpr -maxwarn 2 -quiet
"$GMX" mdrun -v -deffnm output/em -ntmpi 1

# ── Phase 2: Benchmark — select best thread count for NVT stages ─────────────
echo ""
echo "=== Phase 2/4: Thread benchmark (${NCPU} cores detected, default ${NTHREADS}) ==="
BENCH_BEST=0.0
BENCH_STEPS=300
BENCH_TIMEOUT=60   # seconds per test before it is killed as too slow
_BW=22             # bar width (characters)

# Draw a single bar string: _bbar <filled> <width>
_bbar() {
    local f=$1 w=$2 s="" i
    for (( i=0; i<f; i++ )); do s="${s}#"; done
    for (( i=f; i<w; i++ )); do s="${s}-"; done
    printf "%s" "$s"
}

# Overwrite a table row in-place using ANSI cursor movement.
# _bench_row <rows_below> <label> <bar_str> <status_str>
_bench_row() {
    local up=$(( $1 + 1 ))
    printf '\033[%dA' "$up"       # cursor up to this row
    printf '\033[2K\r'             # clear line
    printf "  %-14s  [%s]   %s" "$2" "$3" "$4"
    printf '\033[%dB' "$up"       # cursor back to bottom
    printf '\r'
}

"$GMX" grompp -f nvt.mdp -c output/em.gro -r output/em.gro \
       -p topol.top -o output/bench_base.tpr -maxwarn 2 -quiet 2>/dev/null || true

if [ -f output/bench_base.tpr ]; then
    # Powers-of-2 thread list, append NCPU if not already a power of 2
    _blist=""
    _nt=1
    while [ "$_nt" -le "$NCPU" ]; do
        _blist="$_blist $_nt"
        _nt=$(( _nt * 2 ))
    done
    _blast=$(echo "$_blist" | awk '{print $NF}')
    [ "$_blast" -ne "$NCPU" ] && _blist="$_blist $NCPU"
    _bn=$(echo "$_blist" | wc -w)

    # Print initial table — all rows pending
    echo ""
    for _nt in $_blist; do
        [ "$_nt" -eq 1 ] && _tl="1 thread      " || _tl="${_nt} threads"
        printf "  %-14s  [%s]   pending...\n" "$_tl" "$(_bbar 0 $_BW)"
    done

    # Run each benchmark, animating its row while mdrun runs
    _row=0
    for _nt in $_blist; do
        [ "$_nt" -eq 1 ] && _tl="1 thread      " || _tl="${_nt} threads"
        _below=$(( _bn - _row - 1 ))
        BOUT="output/bench_t${_nt}"

        # -v writes "step N" lines to stderr (separated by \r); capture to .prog
        "$GMX" mdrun -s output/bench_base.tpr -deffnm "$BOUT" \
               -ntmpi 1 -ntomp "$_nt" -nsteps "$BENCH_STEPS" \
               -pin on -v 2>"${BOUT}.prog" &
        _mpid=$!
        _t0=$SECONDS
        _timedout=0

        # Animate bar; kill mdrun if it exceeds the per-test timeout
        while kill -0 "$_mpid" 2>/dev/null; do
            _elapsed=$(( SECONDS - _t0 ))
            if [ "$_elapsed" -ge "$BENCH_TIMEOUT" ]; then
                kill "$_mpid" 2>/dev/null
                wait "$_mpid" 2>/dev/null || true
                _timedout=1
                break
            fi
            _step=$(tr '\r' '\n' < "${BOUT}.prog" 2>/dev/null \
                    | awk '/^step [0-9]/{s=$2} END{print s+0}')
            _step=${_step:-0}
            _f=$(( _step * _BW / BENCH_STEPS ))
            [ "$_f" -gt "$_BW" ] && _f=$_BW
            _bench_row "$_below" "$_tl" "$(_bbar "$_f" "$_BW")" \
                       "$(printf 'running...  %2ds' "$_elapsed")"
            sleep 0.2
        done
        [ "$_timedout" -eq 0 ] && { wait "$_mpid" || true; }

        # Performance: is written to .prog (stderr -v output)
        _perf=$(grep -m1 "^Performance:" "${BOUT}.prog" 2>/dev/null \
                | awk '{print $2}' || true)
        if [ "$_timedout" -eq 1 ]; then
            _bench_row "$_below" "$_tl" "$(_bbar "$_f" "$_BW")" \
                       "$(printf 'timeout     >%ds' "$BENCH_TIMEOUT")"
        elif [ -n "$_perf" ]; then
            _bench_row "$_below" "$_tl" "$(_bbar $_BW $_BW)" \
                       "$(printf '%6.1f ns/day' "$_perf")"
            if awk "BEGIN{exit !($_perf+0 > $BENCH_BEST+0)}"; then
                BENCH_BEST=$_perf
                NTHREADS=$_nt
            fi
        else
            _bench_row "$_below" "$_tl" "$(_bbar 0 $_BW)" "failed"
        fi

        _row=$(( _row + 1 ))
    done
    echo ""

    rm -f output/bench_t*.{gro,edr,cpt,xtc,trr,log,prog} output/bench_base.tpr \
          2>/dev/null || true
fi

if awk "BEGIN{exit !($BENCH_BEST+0 > 0)}"; then
    echo "  → Selected: ${NTHREADS} threads  (${BENCH_BEST} ns/day)"
else
    echo "  → Benchmark skipped — using default: ${NTHREADS} threads (half of ${NCPU})"
fi

# ── Phase 3: NVT equilibration (restrained, 0→310 K annealing ramp) ──────────
echo ""
echo "=== Phase 3/4: NVT equilibration (restrained, 0→310 K) ==="
"$GMX" grompp -f nvt.mdp -c output/em.gro -r output/em.gro \
              -p topol.top -o output/nvt.tpr -maxwarn 2 -quiet
"$GMX" mdrun -v -deffnm output/nvt -ntmpi 1 -ntomp "$NTHREADS" -pin on $GPU_FLAGS

# ── Phase 4: NVT production (unrestrained, 310 K) ────────────────────────────
echo ""
echo "=== Phase 4/4: NVT production (unrestrained, 310 K) ==="
"$GMX" grompp -f nvt_free.mdp -c output/nvt.gro -t output/nvt.cpt \
              -p topol.top -o output/nvt_free.tpr -maxwarn 2 -quiet
"$GMX" mdrun -v -deffnm output/nvt_free -ntmpi 1 -ntomp "$NTHREADS" -pin on $GPU_FLAGS

# ── Post-processing: unwrap trajectory for VMD ───────────────────────────────
echo ""
echo "=== Post-processing: unwrapping trajectory for VMD ==="

# nojump removes periodic jumps so molecules move continuously across frames
echo "0" | "$GMX" trjconv \
    -s output/nvt_free.tpr -f output/nvt_free.xtc \
    -o output/nvt_free_vis.xtc -pbc nojump

# Minimised structure as VMD reference frame
echo "0" | "$GMX" trjconv \
    -s output/em.tpr -f output/em.gro \
    -o output/em_vis.gro -pbc whole

echo ""
echo "Done.  Output files are in output/."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Analysis (see README.txt for details):"
echo ""
echo "  # Energy over time"
echo "  echo Potential | $GMX energy -f output/nvt_free.edr -o output/energy.xvg"
echo ""
echo "  # RMSD from minimised structure"
echo "  echo '0 0' | $GMX rms -s output/em.tpr -f output/nvt_free_vis.xtc -o output/rmsd.xvg"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
vmd -e load_vmd.tcl
"""

_VMD_TCL = """\
# NADOC — VMD visualisation script
# Usage: vmd -e load_vmd.tcl
mol new output/em_vis.gro type gro waitfor all
mol addfile output/nvt_free_vis.xtc type xtc waitfor all

# Licorice representation coloured by chain
mol delrep 0 top
mol representation Licorice 0.3 10 10
mol color Chain
mol selection all
mol addrep top
mol showrep top 0 1

display resetview
animate goto 0
"""


# ─────────────────────────────────────────────────────────────────────────────
# §4b  LAUNCH SCRIPT — EXPLICIT SOLVENT (TIP3P + ions, PME)
#
# Protocol: EM → NVT 100 ps (POSRES) → NPT 1 ns (POSRES)
# Based on AutoNAMD/gromacs/ol15_equil/run_equil.sh validated workflow.
# ─────────────────────────────────────────────────────────────────────────────

_LAUNCH_SH_SOL = r"""\
#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  NADOC GROMACS Launch Script — Explicit Solvent (TIP3P + ions)
#  Protocol: EM → NVT 100 ps (POSRES) → NPT 1 ns (POSRES)
#  Usage:  bash launch.sh [--skip-bench] [--bench-steps N] [--keep-output]
#  Re-running always starts clean (output/ is wiped).  Pass --keep-output to
#  resume a manually interrupted run instead.
#  Tested: Ubuntu 22.04 / 24.04
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Flag parsing ─────────────────────────────────────────────────────────────
SKIP_BENCH=0
BENCH_STEPS=500
KEEP_OUTPUT=0
for _arg in "$@"; do
    case "$_arg" in
        --skip-bench)    SKIP_BENCH=1 ;;
        --bench-steps=*) BENCH_STEPS="${_arg#*=}" ;;
        --keep-output)   KEEP_OUTPUT=1 ;;
    esac
done

# ── Clean previous run output ─────────────────────────────────────────────────
# Stale .cpt checkpoint files cause mdrun to *resume* from the last run
# instead of starting fresh, so output/ is wiped before every run.
# Pass --keep-output to skip this (e.g. to resume a manually interrupted run).
if [ -d output ] && [ "$KEEP_OUTPUT" -eq 0 ]; then
    echo "→ Removing previous run output (pass --keep-output to skip)…"
    rm -rf output
fi
mkdir -p output

# ── Helper functions ──────────────────────────────────────────────────────────

_clean_backups() {
    find "$SCRIPT_DIR" -maxdepth 3 -name '#*#' -delete 2>/dev/null || true
}

_check_step() {
    local desc="$1" mlog="$2"
    local glog="${mlog/_mdrun.log/.log}"
    _clean_backups
    for _f in "$mlog" "$glog"; do
        [ -f "$_f" ] || continue
        if grep -qi "back off" "$_f" 2>/dev/null; then
            echo "  NOTE: GROMACS created backup files during $desc (cleaned)."
            break
        fi
    done
    for _f in "$mlog" "$glog"; do
        [ -f "$_f" ] || continue
        if grep -qiE "^Fatal error:|Atoms that may have.*left the box|nan energy|Segmentation fault" \
               "$_f" 2>/dev/null; then
            echo ""
            echo "  ✗ $desc failed — see $mlog"
            echo "  Common fixes:"
            echo "    • NaN / energy divergence  → more EM steps (increase nsteps in em.mdp)"
            echo "    • Non-deformed + loop_skips → re-export with deformed positions instead"
            echo "    • Atoms leaving the box    → larger box margin (re-export with -d 3.0)"
            echo "    • LINCS / constraint crash → reduce dt = 0.001 in nvt.mdp and re-run"
            echo "    • Persistent failure       → fix the design geometry and re-export"
            exit 1
        fi
    done
    local nw=0
    for _f in "$mlog" "$glog"; do
        [ -f "$_f" ] || continue
        local c; c=$(grep -c "LINCS WARNING" "$_f" 2>/dev/null || echo 0)
        nw=$((nw + c))
    done
    if [ "$nw" -gt 0 ]; then
        echo "  WARNING: $nw LINCS warning(s) in $desc — geometry may be strained."
        echo "           If unstable, try reducing dt = 0.001 in nvt.mdp."
    fi
}

echo "═══════════════════════════════════════════════"
echo "  NADOC GROMACS Launcher  —  {name}"
echo "  Solvent: TIP3P + {ion_label}"
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

# ── 3. Energy minimisation ────────────────────────────────────────────────────
echo "→ Step 1/5: Energy minimisation…"
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
    2>&1 | tee output/em_mdrun.log \
|| { _check_step "energy minimisation" output/em_mdrun.log; exit 1; }
_check_step "energy minimisation" output/em_mdrun.log

echo ""

# ── 4. Hardware benchmark (PME, from minimised structure) ─────────────────────
BEST_NTOMP="$NCPU"
BEST_GPU_FLAGS=""
BEST_NS_DAY="0"
BENCH_DIR=""
trap '[ -n "$BENCH_DIR" ] && rm -rf "$BENCH_DIR"' EXIT

_is_gt() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0 > b+0)}'; }

if [ "$SKIP_BENCH" -eq 1 ]; then
    echo "→ Benchmark skipped (--skip-bench).  Using $NCPU threads, CPU-only."
    echo ""
else
    BENCH_DIR="$(mktemp -d)"

    # Benchmark MDP: PME, NVT physics, suppressed output, very short run.
    cat > "$BENCH_DIR/bench.mdp" << MDPEOF
integrator     = sd
dt             = 0.002
nsteps         = $BENCH_STEPS
cutoff-scheme  = Verlet
nstlist        = 20
rlist          = 1.2
rcoulomb       = 1.0
rvdw           = 1.0
vdwtype        = Cut-off
vdw-modifier   = Force-switch
rvdw-switch    = 0.8
pbc            = xyz
coulombtype    = PME
pme-order      = 4
fourierspacing = 0.16
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

        THREAD_COUNTS=()
        _t=2
        while [ "$_t" -lt "$NCPU" ]; do
            THREAD_COUNTS+=("$_t")
            _t=$((_t * 2))
        done
        THREAD_COUNTS+=("$NCPU")

        echo "─── Benchmark results ($BENCH_STEPS steps, PME, from minimised structure) ──────"
        printf "  %-36s  %10s\n" "Configuration" "ns/day"
        printf "  %-36s  %10s\n" "────────────────────────────────────" "──────────"

        for _ntomp in "${THREAD_COUNTS[@]}"; do
            _ns=$(_bench "$_ntomp")
            printf "  %-36s  %10s\n" "CPU × ${_ntomp} threads" "$_ns"
            if [ "$_ns" != "FAIL" ] && _is_gt "$_ns" "$BEST_NS_DAY"; then
                BEST_NS_DAY="$_ns"; BEST_NTOMP="$_ntomp"; BEST_GPU_FLAGS=""
            fi
        done

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
            NVT_ETA=$(awk -v r="$BEST_NS_DAY" 'BEGIN{printf "%.1f", 0.1 / r * 24 * 60}')
            NPT_ETA=$(awk -v r="$BEST_NS_DAY" 'BEGIN{printf "%.1f", 1.0 / r * 24 * 60}')
            _cfg="$BEST_NTOMP threads"
            [ -n "$BEST_GPU_FLAGS" ] && _cfg="$BEST_NTOMP threads  $BEST_GPU_FLAGS"
            echo "  Best config : $_cfg  (${BEST_NS_DAY} ns/day)"
            echo "  NVT ETA     : ~${NVT_ETA} min for 100 ps"
            echo "  NPT ETA     : ~${NPT_ETA} min for 1 ns"
        else
            echo "  Benchmark inconclusive — using $NCPU threads, CPU-only."
        fi
        echo ""
    fi
fi

MDRUN_FLAGS="-ntmpi 1 -ntomp $BEST_NTOMP"
[ -n "$BEST_GPU_FLAGS" ] && MDRUN_FLAGS="$MDRUN_FLAGS $BEST_GPU_FLAGS"

# ── 5. NVT equilibration — 100 ps, position restraints ───────────────────────
echo "→ Step 2/5: NVT equilibration (position-restrained, 100 ps)…"
$GMX grompp \
    -f nvt.mdp \
    -c output/em.gro \
    -r output/em.gro \
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

python3 scripts/monitor.py "$LOG" "$MDRUN_PID" || true
wait "$MDRUN_PID" || { _check_step "NVT equilibration" "$LOG"; exit 1; }
_check_step "NVT equilibration" "$LOG"

echo ""

# ── 6. NPT equilibration — 1 ns, position restraints ────────────────────────
echo "→ Step 3/5: NPT equilibration (position-restrained, 1 ns)…"
$GMX grompp \
    -f npt.mdp \
    -c output/nvt.gro \
    -r output/em.gro \
    -t output/nvt.cpt \
    -p topol.top \
    -o output/npt.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/npt_grompp.log

LOG="output/npt_mdrun.log"
# shellcheck disable=SC2086
$GMX mdrun \
    -v \
    -deffnm output/npt \
    $MDRUN_FLAGS \
    -x output/npt.xtc \
    2>&1 | tee "$LOG" &
MDRUN_PID=$!

python3 scripts/monitor.py "$LOG" "$MDRUN_PID" || true
wait "$MDRUN_PID" || { _check_step "NPT equilibration" "$LOG"; exit 1; }
_check_step "NPT equilibration" "$LOG"

echo ""

# ── 7. RMSD analysis ─────────────────────────────────────────────────────────
echo "→ Step 4/5: RMSD analysis (backbone vs EM structure)…"
if [ -f output/npt.xtc ]; then
    echo "0 0" | $GMX rms \
        -s output/npt.tpr \
        -f output/npt.xtc \
        -o output/rmsd.xvg \
        -tu ns \
        -nobackup 2>&1 | tee output/rmsd_analysis.log \
    && echo "  RMSD trace → output/rmsd.xvg" \
    || echo "  RMSD analysis skipped (check output/rmsd_analysis.log)"
fi

echo ""

# ── 8. Visualization prep — cluster + centre for VMD ────────────────────────
echo "→ Step 5/5: Preparing VMD-ready files (cluster + centre)…"

if [ -f output/em.gro ]; then
    printf "0\n0\n0\n" | $GMX trjconv \
        -s output/npt.tpr \
        -f output/em.gro \
        -o output/em_vis.gro \
        -center \
        -pbc cluster \
        -nobackup 2>&1 | tee output/vis_prep.log \
    && echo "  Clustered structure  → output/em_vis.gro" \
    || echo "  WARNING: trjconv (structure) failed — see output/vis_prep.log"
fi

if [ -f output/npt.xtc ]; then
    printf "0\n" | $GMX trjconv \
        -s output/npt.tpr \
        -f output/npt.xtc \
        -o output/npt_nojump.xtc \
        -pbc nojump \
        -nobackup 2>&1 | tee -a output/vis_prep.log \
    && printf "0\n0\n0\n" | $GMX trjconv \
        -s output/npt.tpr \
        -f output/npt_nojump.xtc \
        -o output/npt_vis.xtc \
        -center \
        -pbc cluster \
        -nobackup 2>&1 | tee -a output/vis_prep.log \
    && echo "  Clustered trajectory → output/npt_vis.xtc" \
    && rm -f output/npt_nojump.xtc \
    || echo "  WARNING: trjconv (trajectory) failed — see output/vis_prep.log"
fi

cat > output/load_vmd.tcl << 'TCLEOF'
mol new output/em_vis.gro type gro waitfor all
mol addfile output/npt_vis.xtc type xtc waitfor all
TCLEOF
echo "  VMD loader script    → output/load_vmd.tcl"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Done.  Output files are in output/"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Equilibration output:"
echo "    em.gro           — energy-minimised structure"
echo "    nvt.xtc          — NVT trajectory (100 ps, POSRES)"
echo "    npt.xtc          — NPT trajectory (1 ns, POSRES)"
echo "    npt.gro          — final equilibrated structure"
echo "    npt.cpt          — checkpoint (use as input for production)"
echo "    rmsd.xvg         — backbone RMSD vs EM structure (ns)"
echo ""
echo "  Visualization-ready files:"
echo "    em_vis.gro       — structure ready to open in VMD"
echo "    npt_vis.xtc      — trajectory ready to open in VMD"
echo "    load_vmd.tcl     — VMD loader"
echo ""
echo "  Open in VMD:"
echo "    vmd -e output/load_vmd.tcl"
echo ""
echo "  ── Design stability interpretation ─────────────────────────"
echo "  RMSD < 1 Å  → geometry is force-field consistent (design OK)"
echo "  RMSD > 3 Å  → steric clashes or geometry errors in the design"
echo "  Energy diverges → severe clash; redesign or increase EM steps"
echo ""
echo "  ── Continue to production MD (after NPT) ───────────────────"
echo "  Unrestrained free NVT (100 ps):"
echo "    $GMX grompp -f nvt_free.mdp -c output/npt.gro -t output/npt.cpt \\"
echo "                -p topol.top -o output/nvt_free.tpr -maxwarn 20 -nobackup"
echo "    $GMX mdrun -v -deffnm output/nvt_free -ntmpi 1 -ntomp $BEST_NTOMP"
echo ""
echo "  ── Energy check ─────────────────────────────────────────────"
echo '  echo "Potential" | gmx energy -f output/npt.edr -o output/potential.xvg'
echo "  xmgrace output/potential.xvg   (or plot with gnuplot/Python)"
echo ""
"""

# ── Extended launch script for designs with extra-base crossover insertions ──
# Same preamble as _LAUNCH_SH_SOL but uses a 8-step pipeline:
#   1/8  EM free (no constraints, no POSRES)
#   2/8  EM POSRES (h-bonds + POSRES) — locks h-bond lengths before dynamics
#   3/8  NVT 100 ps (0→310 K annealing, dt=0.001, POSRES)
#   4/8  NPT 500 ps (C-rescale, POSRES 1000 kJ, dt=0.001)
#   5/8  NPT 100 ps (C-rescale, POSRES 100 kJ — partial release, dt=0.001)
#   6/8  NPT 200 ps (C-rescale, no POSRES — full release, dt=0.001)
#   7/8  RMSD analysis
#   8/8  VMD-ready files

_LAUNCH_SH_SOL_XOVER = r"""\
#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  NADOC GROMACS Launch Script — Explicit Solvent, Extra-Base Crossovers
#  Protocol: free EM → POSRES EM → NVT → NPT → NPT staged release (2 steps)
#  Usage:  bash launch.sh [--skip-bench] [--bench-steps N] [--keep-output]
#  Tested: Ubuntu 22.04 / 24.04
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Flag parsing ─────────────────────────────────────────────────────────────
SKIP_BENCH=0
BENCH_STEPS=500
KEEP_OUTPUT=0
for _arg in "$@"; do
    case "$_arg" in
        --skip-bench)    SKIP_BENCH=1 ;;
        --bench-steps=*) BENCH_STEPS="${_arg#*=}" ;;
        --keep-output)   KEEP_OUTPUT=1 ;;
    esac
done

if [ -d output ] && [ "$KEEP_OUTPUT" -eq 0 ]; then
    echo "→ Removing previous run output (pass --keep-output to skip)…"
    rm -rf output
fi
mkdir -p output

# ── Helper functions ──────────────────────────────────────────────────────────

_clean_backups() {
    find "$SCRIPT_DIR" -maxdepth 3 -name '#*#' -delete 2>/dev/null || true
}

_check_step() {
    local desc="$1" mlog="$2"
    local glog="${mlog/_mdrun.log/.log}"
    _clean_backups
    for _f in "$mlog" "$glog"; do
        [ -f "$_f" ] || continue
        if grep -qi "back off" "$_f" 2>/dev/null; then
            echo "  NOTE: GROMACS created backup files during $desc (cleaned)."
            break
        fi
    done
    for _f in "$mlog" "$glog"; do
        [ -f "$_f" ] || continue
        if grep -qiE "^Fatal error:|Atoms that may have.*left the box|nan energy|Segmentation fault" \
               "$_f" 2>/dev/null; then
            echo ""
            echo "  ✗ $desc failed — see $mlog"
            echo "  Common fixes:"
            echo "    • NaN / energy divergence  → more EM steps in em_free.mdp or em_posres.mdp"
            echo "    • Atoms leaving the box    → larger box margin (re-export with -d 3.0)"
            echo "    • LINCS / constraint crash → check em_posres converged (Fmax < 1000)"
            echo "    • Persistent NPT failure   → verify posre_low_*.itp spring constants (100)"
            exit 1
        fi
    done
    local nw=0
    for _f in "$mlog" "$glog"; do
        [ -f "$_f" ] || continue
        local c; c=$(grep -c "LINCS WARNING" "$_f" 2>/dev/null || echo 0)
        nw=$((nw + c))
    done
    if [ "$nw" -gt 0 ]; then
        echo "  WARNING: $nw LINCS warning(s) in $desc — geometry may be strained."
        echo "           If unstable, check that em_free converged (Fmax < 100)."
    fi
}

echo "═══════════════════════════════════════════════"
echo "  NADOC GROMACS Launcher  —  {name}"
echo "  Solvent: TIP3P + {ion_label}"
echo "  Protocol: extra-base crossover equilibration"
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

# ── 3. Energy minimisation — phase 1: free (no POSRES, no constraints) ───────
echo "→ Step 1/8: Energy minimisation (phase 1 — free EM)…"
$GMX grompp \
    -f em_free.mdp \
    -c conf.gro \
    -p topol.top \
    -o output/em_free.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/em_free_grompp.log

$GMX mdrun \
    -v \
    -deffnm output/em_free \
    -ntmpi 1 \
    -ntomp "$NCPU" \
    2>&1 | tee output/em_free_mdrun.log \
|| { _check_step "EM phase 1 (free)" output/em_free_mdrun.log; exit 1; }
_check_step "EM phase 1 (free)" output/em_free_mdrun.log
echo ""

# ── 4. Energy minimisation — phase 2: POSRES + h-bond constraints ────────────
echo "→ Step 2/8: Energy minimisation (phase 2 — POSRES)…"
$GMX grompp \
    -f em_posres.mdp \
    -c output/em_free.gro \
    -r output/em_free.gro \
    -p topol.top \
    -o output/em_posres.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/em_posres_grompp.log

$GMX mdrun \
    -v \
    -deffnm output/em_posres \
    -ntmpi 1 \
    -ntomp "$NCPU" \
    2>&1 | tee output/em_posres_mdrun.log \
|| { _check_step "EM phase 2 (POSRES)" output/em_posres_mdrun.log; exit 1; }
_check_step "EM phase 2 (POSRES)" output/em_posres_mdrun.log
echo ""

# ── 5. Hardware benchmark (PME, from POSRES-minimised structure) ──────────────
BEST_NTOMP="$NCPU"
BEST_GPU_FLAGS=""
BEST_NS_DAY="0"
BENCH_DIR=""
trap '[ -n "$BENCH_DIR" ] && rm -rf "$BENCH_DIR"' EXIT

_is_gt() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0 > b+0)}'; }

if [ "$SKIP_BENCH" -eq 1 ]; then
    echo "→ Benchmark skipped (--skip-bench).  Using $NCPU threads, CPU-only."
    echo ""
else
    BENCH_DIR="$(mktemp -d)"

    cat > "$BENCH_DIR/bench.mdp" << MDPEOF
integrator     = sd
dt             = 0.001
nsteps         = $BENCH_STEPS
cutoff-scheme  = Verlet
nstlist        = 20
rlist          = 1.2
rcoulomb       = 1.0
rvdw           = 1.0
vdwtype        = Cut-off
vdw-modifier   = Force-switch
rvdw-switch    = 0.8
pbc            = xyz
coulombtype    = PME
pme-order      = 4
fourierspacing = 0.16
constraints    = h-bonds
constraint-algorithm = LINCS
lincs-iter     = 2
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
            -c output/em_posres.gro \
            -p topol.top \
            -o "$BENCH_DIR/bench.tpr" \
            -maxwarn 20 \
            -nobackup 2>"$BENCH_DIR/grompp.err"; then
        echo "  Benchmark grompp failed — using $NCPU threads, CPU-only."
        BENCH_OK=0
    fi

    if [ "$BENCH_OK" -eq 1 ]; then
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

        THREAD_COUNTS=()
        _t=2
        while [ "$_t" -lt "$NCPU" ]; do
            THREAD_COUNTS+=("$_t")
            _t=$((_t * 2))
        done
        THREAD_COUNTS+=("$NCPU")

        echo "─── Benchmark results ($BENCH_STEPS steps, PME, from minimised structure) ──────"
        printf "  %-36s  %10s\n" "Configuration" "ns/day"
        printf "  %-36s  %10s\n" "────────────────────────────────────" "──────────"

        for _ntomp in "${THREAD_COUNTS[@]}"; do
            _ns=$(_bench "$_ntomp")
            printf "  %-36s  %10s\n" "CPU × ${_ntomp} threads" "$_ns"
            if [ "$_ns" != "FAIL" ] && _is_gt "$_ns" "$BEST_NS_DAY"; then
                BEST_NS_DAY="$_ns"; BEST_NTOMP="$_ntomp"; BEST_GPU_FLAGS=""
            fi
        done

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
            NVT_ETA=$(awk -v r="$BEST_NS_DAY" 'BEGIN{printf "%.1f", 0.1 / r * 24 * 60}')
            NPT_ETA=$(awk -v r="$BEST_NS_DAY" 'BEGIN{printf "%.1f", (0.5 + 0.1 + 0.2) / r * 24 * 60}')
            _cfg="$BEST_NTOMP threads"
            [ -n "$BEST_GPU_FLAGS" ] && _cfg="$BEST_NTOMP threads  $BEST_GPU_FLAGS"
            echo "  Best config : $_cfg  (${BEST_NS_DAY} ns/day)"
            echo "  NVT ETA     : ~${NVT_ETA} min for 100 ps"
            echo "  NPT ETA     : ~${NPT_ETA} min for 500+100+200 ps staged equilibration"
        else
            echo "  Benchmark inconclusive — using $NCPU threads, CPU-only."
        fi
        echo ""
    fi
fi

MDRUN_FLAGS="-ntmpi 1 -ntomp $BEST_NTOMP"
[ -n "$BEST_GPU_FLAGS" ] && MDRUN_FLAGS="$MDRUN_FLAGS $BEST_GPU_FLAGS"

# ── 6. NVT equilibration — 100 ps, 0→310 K annealing, POSRES ────────────────
echo "→ Step 3/8: NVT equilibration (0→310 K annealed, position-restrained, 100 ps)…"
$GMX grompp \
    -f nvt.mdp \
    -c output/em_posres.gro \
    -r output/em_posres.gro \
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

python3 scripts/monitor.py "$LOG" "$MDRUN_PID" || true
wait "$MDRUN_PID" || { _check_step "NVT equilibration" "$LOG"; exit 1; }
_check_step "NVT equilibration" "$LOG"
echo ""

# ── 7. NPT equilibration — 500 ps, C-rescale, POSRES 1000 kJ/mol/nm² ────────
echo "→ Step 4/8: NPT equilibration (position-restrained 1000 kJ, 500 ps)…"
$GMX grompp \
    -f npt.mdp \
    -c output/nvt.gro \
    -r output/em_posres.gro \
    -t output/nvt.cpt \
    -p topol.top \
    -o output/npt.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/npt_grompp.log

LOG="output/npt_mdrun.log"
# shellcheck disable=SC2086
$GMX mdrun \
    -v \
    -deffnm output/npt \
    $MDRUN_FLAGS \
    -x output/npt.xtc \
    2>&1 | tee "$LOG" &
MDRUN_PID=$!

python3 scripts/monitor.py "$LOG" "$MDRUN_PID" || true
wait "$MDRUN_PID" || { _check_step "NPT equilibration" "$LOG"; exit 1; }
_check_step "NPT equilibration" "$LOG"
echo ""

# ── 8. NPT staged release step 1 — 100 ps, POSRES 100 kJ/mol/nm² ─────────────
echo "→ Step 5/8: NPT staged release (POSRES 100 kJ, 100 ps)…"
$GMX grompp \
    -f npt_low.mdp \
    -c output/npt.gro \
    -r output/em_posres.gro \
    -t output/npt.cpt \
    -p topol.top \
    -o output/npt_low.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/npt_low_grompp.log

LOG="output/npt_low_mdrun.log"
# shellcheck disable=SC2086
$GMX mdrun \
    -v \
    -deffnm output/npt_low \
    $MDRUN_FLAGS \
    -x output/npt_low.xtc \
    2>&1 | tee "$LOG" &
MDRUN_PID=$!

python3 scripts/monitor.py "$LOG" "$MDRUN_PID" || true
wait "$MDRUN_PID" || { _check_step "NPT staged release" "$LOG"; exit 1; }
_check_step "NPT staged release" "$LOG"
echo ""

# ── 9. NPT staged release step 2 — 200 ps, no POSRES ────────────────────────
echo "→ Step 6/8: NPT full release (no POSRES, 200 ps)…"
$GMX grompp \
    -f npt_release.mdp \
    -c output/npt_low.gro \
    -t output/npt_low.cpt \
    -p topol.top \
    -o output/npt_release.tpr \
    -maxwarn 20 \
    -nobackup \
    2>&1 | tee output/npt_release_grompp.log

LOG="output/npt_release_mdrun.log"
# shellcheck disable=SC2086
$GMX mdrun \
    -v \
    -deffnm output/npt_release \
    $MDRUN_FLAGS \
    -x output/npt_release.xtc \
    2>&1 | tee "$LOG" &
MDRUN_PID=$!

python3 scripts/monitor.py "$LOG" "$MDRUN_PID" || true
wait "$MDRUN_PID" || { _check_step "NPT full release" "$LOG"; exit 1; }
_check_step "NPT full release" "$LOG"
echo ""

# ── 10. RMSD analysis ─────────────────────────────────────────────────────────
echo "→ Step 7/8: RMSD analysis (backbone vs POSRES-minimised structure)…"
if [ -f output/npt_release.xtc ]; then
    echo "0 0" | $GMX rms \
        -s output/npt_release.tpr \
        -f output/npt_release.xtc \
        -o output/rmsd.xvg \
        -tu ns \
        -nobackup 2>&1 | tee output/rmsd_analysis.log \
    && echo "  RMSD trace → output/rmsd.xvg" \
    || echo "  RMSD analysis skipped (check output/rmsd_analysis.log)"
fi
echo ""

# ── 11. Visualization prep — cluster + centre for VMD ────────────────────────
echo "→ Step 8/8: Preparing VMD-ready files (cluster + centre)…"

if [ -f output/em_posres.gro ]; then
    printf "0\n0\n0\n" | $GMX trjconv \
        -s output/npt_release.tpr \
        -f output/em_posres.gro \
        -o output/em_vis.gro \
        -center \
        -pbc cluster \
        -nobackup 2>&1 | tee output/vis_prep.log \
    && echo "  Clustered structure  → output/em_vis.gro" \
    || echo "  WARNING: trjconv (structure) failed — see output/vis_prep.log"
fi

if [ -f output/npt_release.xtc ]; then
    printf "0\n" | $GMX trjconv \
        -s output/npt_release.tpr \
        -f output/npt_release.xtc \
        -o output/npt_release_nojump.xtc \
        -pbc nojump \
        -nobackup 2>&1 | tee -a output/vis_prep.log \
    && printf "0\n0\n0\n" | $GMX trjconv \
        -s output/npt_release.tpr \
        -f output/npt_release_nojump.xtc \
        -o output/npt_release_vis.xtc \
        -center \
        -pbc cluster \
        -nobackup 2>&1 | tee -a output/vis_prep.log \
    && echo "  Clustered trajectory → output/npt_release_vis.xtc" \
    && rm -f output/npt_release_nojump.xtc \
    || echo "  WARNING: trjconv (trajectory) failed — see output/vis_prep.log"
fi

cat > output/load_vmd.tcl << 'TCLEOF'
mol new output/em_vis.gro type gro waitfor all
mol addfile output/npt_release_vis.xtc type xtc waitfor all
TCLEOF
echo "  VMD loader script    → output/load_vmd.tcl"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Done.  Output files are in output/"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Equilibration output:"
echo "    em_free.gro       — free-minimised structure (crossovers relaxed)"
echo "    em_posres.gro     — POSRES-minimised structure (h-bonds locked)"
echo "    nvt.xtc           — NVT trajectory (100 ps, 0→310 K, POSRES)"
echo "    npt.xtc           — NPT trajectory (500 ps, POSRES 1000 kJ)"
echo "    npt_low.xtc       — NPT staged release (100 ps, POSRES 100 kJ)"
echo "    npt_release.xtc   — NPT full release (200 ps, no POSRES)"
echo "    npt_release.gro   — final equilibrated structure (no restraints)"
echo "    npt_release.cpt   — checkpoint (use as input for production)"
echo "    rmsd.xvg          — backbone RMSD vs POSRES-minimised structure (ns)"
echo ""
echo "  Visualization-ready files:"
echo "    em_vis.gro           — structure ready to open in VMD"
echo "    npt_release_vis.xtc  — trajectory ready to open in VMD"
echo "    load_vmd.tcl         — VMD loader"
echo ""
echo "  Open in VMD:"
echo "    vmd -e output/load_vmd.tcl"
echo ""
echo "  ── Design stability interpretation ─────────────────────────"
echo "  RMSD < 1 Å  → geometry is force-field consistent (design OK)"
echo "  RMSD > 3 Å  → steric clashes or geometry errors in the design"
echo "  Energy diverges → severe clash; redesign or increase EM steps"
echo ""
echo "  ── Continue to production MD ────────────────────────────────"
echo "  Unrestrained free dynamics (100 ps):"
echo "    $GMX grompp -f nvt_free.mdp -c output/npt_release.gro \\"
echo "                -t output/npt_release.cpt \\"
echo "                -p topol.top -o output/nvt_free.tpr -maxwarn 20 -nobackup"
echo "    $GMX mdrun -v -deffnm output/nvt_free -ntmpi 1 -ntomp $BEST_NTOMP"
echo ""
echo "  ── Energy check ─────────────────────────────────────────────"
echo '  echo "Potential" | gmx energy -f output/npt_release.edr -o output/potential.xvg'
echo "  xmgrace output/potential.xvg   (or plot with gnuplot/Python)"
echo ""
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

# Regexes that match specific parameters in any MDP string
_STEPS_FROM_MDP  = re.compile(r'nsteps\s*=\s*\d+',   re.IGNORECASE)
_DT_FROM_MDP     = re.compile(r'^dt\s*=\s*[\d.]+',   re.IGNORECASE | re.MULTILINE)

# Maximum steps for the *restrained* NVT stage regardless of user nvt_steps.
# The restrained stage only needs to cover the annealing ramp (~30 ps normal,
# ~20 ps for skip structures) plus a brief hold — 25 000 steps (50 ps at
# dt=0.002, 25 ps at dt=0.001) is sufficient and avoids wasting compute time
# if the user requests a longer production run.
_NVT_RESTRAINED_STEPS = 25_000
_GENVEL_FROM_MDP = re.compile(r'^gen-vel\s*=\s*\S+',  re.IGNORECASE | re.MULTILINE)

# Regex to extract the net system charge from pdb2gmx stdout
# GROMACS 2021+ prints: "Total charge in system -4972.000 e"
_TOTAL_CHARGE_RE = re.compile(r'Total charge in system\s+([-\d.]+)', re.IGNORECASE)

# Single Na+ ion template files for vacuum counterion neutralisation.
# The GRO uses GROMACS column format: resnum(5d) resname(5s) atomname(5s) atomnum(5d) x y z (nm).
# The ITP defines the moleculetype; atom type "Na+" must be present in the FF's ffnonbonded.itp.
_NA_ION_GRO = """\
Na ion
    1
    1NA    NA      1   0.000   0.000   0.000
  1.00000  1.00000  1.00000
"""

_NA_ION_ITP = """\
; Na+ counterion — placed to neutralise DNA backbone charge in vacuum
; Atom type "Na" is defined in ffnonbonded.itp (AMBER99SB-ILDN)
[ moleculetype ]
; Name     nrexcl
NA         1

[ atoms ]
;   nr  type   resnr  residue  atom   cgnr   charge    mass
     1  Na         1  NA       NA        1    1.000  22.9898
"""


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
  bash launch.sh

  The script runs three stages and prints a quick-reference command list
  when finished.  See §Analysis below for details.

FILES
-----
  conf.gro         All-atom initial structure with Na+ counterions (GROMACS, nm)
  topol.top        GROMACS topology (references {ff}.ff/ bundled here)
  na_ion.itp       Na+ counterion moleculetype (included by topol.top)
  *.itp            Per-strand position-restraint includes (pdb2gmx generated)
  {ff}.ff/         Bundled force-field directory
  em.mdp           Energy-minimisation parameters
  nvt.mdp          NVT equilibration — restrained, 0→310 K annealing ramp
  nvt_free.mdp     NVT production — unrestrained, 310 K
  output/          Created by launch.sh; all output files land here

SIMULATION PROTOCOL
-------------------
  1. Energy minimisation (steep, h-bond constraints, emtol 1000 kJ/mol/nm)
  2. NVT equilibration — position restrained, Langevin thermostat ramps
     from 0 K to 310 K over the first 30 ps, then holds at 310 K
  3. NVT production — position restraints removed, 310 K

  Force field   : {ff}
  Electrostatics: Reaction-Field (ε=80) — approximates aqueous dielectric
                  without an explicit water box
  Counterions   : Na+ ions added to neutralise backbone phosphate charge;
                  placed randomly in the simulation box before EM
  Temperature   : 310 K (Langevin / sd integrator, τ=10 ps)
  Timestep      : 2 fs (h-bond constraints via LINCS); 1 fs for skip structures

WHY POSITION RESTRAINTS?
------------------------
  The topology models each DNA strand as an independent molecule — crossover
  bonds between helices are not included.  Without restraints, strands drift
  apart under electrostatic repulsion.

  With restraints (spring k = 1000 kJ/mol/nm² on all heavy atoms) the
  restrained NVT answers: "Does this geometry have steric clashes or
  force-field inconsistencies?"

    RMSD < 1 Å after restrained NVT → geometry is physically reasonable
    Energy diverges                  → steric clash or geometry error

  The unrestrained NVT_free stage allows helices to drift — this is expected
  given the missing crossover bond topology, not a design flaw.

WHY TEMPERATURE ANNEALING?
--------------------------
  Starting NVT from 0 K (gen-vel yes, gen-temp 0) and ramping gradually to
  310 K over 30 ps prevents LINCS failures that can occur when the Langevin
  thermostat imposes a sudden large kinetic energy on a freshly minimised
  structure.  The ramp is embedded directly in nvt.mdp via GROMACS simulated
  annealing parameters — no separate low-temperature stage is needed.

  Skip-site structures (delta = -1 loop_skips, undeformed export) use a
  slower ramp (0→310 K over 20 ps) and a half-size timestep (dt = 0.001 ps)
  for extra stability around the strained backbone bridges.

LIMITATIONS
-----------
  * No explicit water.  Reaction-field with ε=80 approximates bulk screening;
    salt-specific effects and ion-specific interactions are not captured.
  * Cross-helix crossover bonds are absent from the topology.  For the
    undeformed export, bending forces cannot develop (see below).
  * For publication-quality work: AMBER OL15 + TIP3P + MgCl2 + PME
    (future NADOC explicit-solvent mode).

LOOP/SKIP SITES AND UNDEFORMED EXPORT (Dietz mechanism)
--------------------------------------------------------
  Exporting with "Original" helix positions produces straight helices where
  Dietz skip sites (delta = -1) introduce backbone strain at each skipped
  base pair.  NADOC pre-minimises these O3'–P–O5' bridges to canonical bond
  lengths and angles.  EM uses 150 000 steps and h-bond constraints throughout
  (not just at skip sites) to prevent X-H bond divergence in false minima.

  IMPORTANT: without crossover bonds the bending mechanism cannot emerge.
  You can observe local skip-site geometry relaxation and per-helix
  curvature, but not the collective bundle bend.  Use oxDNA or a
  full-crossover topology for that.

ANALYSIS
--------
  The commands below are also echoed by launch.sh on completion.
  Group 0 = System (all atoms including Na+ ions).

  Cluster periodic images for visualisation:
    gmx trjconv -s output/nvt_free.tpr -f output/nvt_free.xtc \\
                -o output/nvt_free_vis.xtc -pbc cluster -b 0

  Energy over time (select Potential or Total-Energy at the prompt):
    gmx energy -f output/nvt_free.edr -o output/energy.xvg

  RMSD from minimised structure (select Backbone at both prompts):
    gmx rms -s output/em.tpr -f output/nvt_free.xtc -o output/rmsd.xvg

  RMSF per residue:
    echo "0" | gmx rmsf -s output/nvt_free.tpr -f output/nvt_free.xtc \\
                         -o output/rmsf.xvg -res

VISUALISATION
-------------
  VMD (free, UIUC):
    vmd output/em.gro output/nvt_free.xtc

CITATIONS
---------
  GROMACS: Abraham et al., SoftwareX 1-2, 19-25 (2015)
  AMBER OL15: Zgarbova et al., J. Chem. Theory Comput. 11, 5723 (2015)
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

def _ion_names_for_ff(ff: str) -> tuple[str, int, str]:
    """
    Return (pname, pq, nname) for MgCl2 appropriate for the given force field.

    CHARMM36 uses 'CLA' for chloride; AMBER uses 'CL'.
    Mg2+ is 'MG' (charge +2) in both.
    """
    if ff.startswith("charmm"):
        return "MG", 2, "CLA"
    else:
        return "MG", 2, "CL"


def _fix_itp_case(tmpdir: Path) -> None:
    """
    Reconcile ITP filename case with the #include directives in topol.top.

    pdb2gmx behaviour is version-dependent: some versions uppercase the
    molecule-type name (and thus the #include path in topol.top) while writing
    the ITP file itself with the lowercase chain letter from the PDB, or vice
    versa.  On a case-sensitive Linux filesystem this causes a fatal "include
    file not found" error when grompp reads topol.top.

    Strategy: topol.top is authoritative (grompp reads it first).  For every
    #include "*.itp" line, if the file already exists at that exact path it is
    left alone.  Otherwise, a case-insensitive lookup finds the closest match
    and renames it.

    Note: a design with >62 strands reuses PDB chain letters (A-Z, a-z, 0-9
    cycle).  pdb2gmx (case-sensitive) generates distinct ITP files for chain
    'A' and chain 'a'; both are already correctly named.  The case-insensitive
    lookup dict would collapse them to the same key, so checking target.exists()
    first is essential to avoid the function destructively overwriting one file
    with the other.
    """
    topol_path = tmpdir / "topol.top"
    if not topol_path.exists():
        return

    # Case-insensitive map: lowercase name → actual Path
    on_disk: dict[str, Path] = {p.name.lower(): p for p in tmpdir.glob("*.itp")}

    include_re = re.compile(r'(#include\s+")([^"]+\.itp)(")')
    for m in include_re.finditer(topol_path.read_text()):
        fname  = m.group(2)          # name as written in topol.top
        target = tmpdir / fname
        if target.exists():          # already correctly named — leave it alone
            continue
        actual = on_disk.get(fname.lower())
        if actual is not None and actual.name != fname:
            actual.rename(target)
            on_disk[fname.lower()] = target  # update map in case of duplicates


# ══════════════════════════════════════════════════════════════════════════════
# §7  MAIN BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_gromacs_package(
    design: "Design",
    *,
    package_name: str | None = None,
    use_deformed: bool = False,
    nvt_steps: int | None = None,
    solvate: bool = False,
    ion_conc_mM: float = 10.0,
    nuc_pos_override=None,  # deprecated; pass a cg-fitted design instead
) -> bytes:
    """
    Build and return the raw ZIP bytes of a self-contained GROMACS package.

    Runs pdb2gmx + editconf (+ optionally solvate + genion) server-side.
    Bundles topology, structure, force-field files, MDP files, launch script,
    and README into a single ZIP.

    Parameters
    ----------
    package_name : override the ZIP directory prefix (default: design name)
    use_deformed : apply active deformation to helix positions (reserved)
    nvt_steps    : override nsteps in nvt.mdp
                   (default: 25 000 vacuum / 50 000 solvated)
    solvate      : if True, add TIP3P water + MgCl2 ions (server-side)
    ion_conc_mM  : MgCl2 concentration in mM (default: 10.0)
    """
    gmx     = _find_gmx()
    top_dir = _find_top_dir()
    ff      = _pick_ff(top_dir)
    ff_dir  = top_dir / f"{ff}.ff"
    name    = (package_name or design.metadata.name or "design").replace(" ", "_")

    # NVT step defaults differ between vacuum and solvated protocols
    _nvt_default = 50000 if solvate else 25000
    _nvt_steps   = nvt_steps if nvt_steps is not None else _nvt_default

    # Non-deformed structures with skip sites (delta ≤ −1 loop_skips) have
    # their backbone bridges adjusted by build_atomistic_model, but the chord
    # interpolation still leaves some deviation from ideal bond geometry.
    # Use more EM steps so steepest descent can fully relax these sites.
    _has_skips = (
        not use_deformed
        and any(
            any(ls.delta <= -1 for ls in h.loop_skips)
            for h in design.helices
        )
    )
    _em_nsteps = 150000 if _has_skips else 50000

    # For non-deformed skip structures, gen-vel=no starts NVT from 0 K.
    # Langevin τ=10 ps needs ~5τ≈50 ps to reach 310 K.
    # The default 25 ps (25,000 steps × dt=0.001) only reaches ~289 K.
    # Double NVT steps to 50,000 (50 ps) so equilibration is nearly complete.
    if _has_skips and nvt_steps is None and not solvate:
        _nvt_steps = 50000

    # Designs with extra-base crossover insertions (xo.extra_bases) require a
    # multi-phase solvated equilibration.  The inserted T residues sit at
    # strained backbone geometry; abrupt POSRES removal causes NaN explosions.
    # The extended pipeline (em_free → em_posres → nvt → npt → npt_low →
    # npt_release) is activated automatically only for solvated runs.
    _has_xover_insertions = (
        solvate
        and any(xo.extra_bases for xo in design.crossovers)
    )

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        # ── 1. Build pdb2gmx-compatible PDB ──────────────────────────────────
        # Extra-base crossover residues are interleaved at their correct 5'→3'
        # position within each chain so pdb2gmx generates the right sequential
        # backbone bonds (standard export_pdb appends them at chain end, which
        # causes pdb2gmx to create wrong direct bonds across the crossover).
        adapted = _build_gromacs_input_pdb(design, ff, box_margin_nm=2.0, use_deformed=use_deformed, nuc_pos_override=nuc_pos_override)
        input_pdb = tmpdir / "input.pdb"
        input_pdb.write_text(adapted)

        # ── 2. pdb2gmx — generate topology + GRO ─────────────────────────────
        # Use TIP3P water model when solvating so the topology includes water
        # parameters; use "none" for vacuum runs.
        water_model = "tip3p" if solvate else "none"
        # CHARMM36 requires -ter to select DNA termini (4=5TER, 6=3TER) rather
        # than the default protein NH3+/COO- termini, which cause a fatal error.
        # Count chain BLOCKS (consecutive runs of same letter) not unique letters:
        # pdb2gmx splits non-sequential reuse of the same chain letter into separate
        # chains, so unique-letter count under-provides inputs and pdb2gmx hangs.
        # Over-providing is safe — extra inputs are ignored.
        _needs_ter = ff.startswith("charmm36-feb2026")
        _pdb_lines = [l for l in adapted.splitlines() if l.startswith(("ATOM", "HETATM"))]
        _n_chains  = 1 + sum(
            1 for a, b in zip(_pdb_lines, _pdb_lines[1:]) if a[21] != b[21]
        ) if _pdb_lines else 1
        _pdb2gmx_cmd = [
            gmx, "pdb2gmx",
            "-f", str(input_pdb),
            "-o", str(tmpdir / "conf_raw.gro"),
            "-p", str(tmpdir / "topol.top"),
            "-ignh",
            "-ff", ff,
            "-water", water_model,
            "-nobackup",
        ]
        if _needs_ter:
            _pdb2gmx_cmd.append("-ter")
        pdb2gmx_result = subprocess.run(
            _pdb2gmx_cmd,
            input=("4\n6\n" * _n_chains) if _needs_ter else None,
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
                "-c",
                "-d", "2.5",
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

        # ── 3b. Add Na+ counterions in vacuum (neutralise backbone charge) ──────
        # Parse the net charge pdb2gmx prints to stderr.  Na+ ions are inserted
        # randomly into the simulation box so the system is charge-neutral before
        # EM; this screens inter-helix electrostatic repulsion without water.
        ion_label = ""
        _n_na = 0  # number of Na+ ions inserted (0 when solvate=True)
        if not solvate:
            _charge_match = _TOTAL_CHARGE_RE.search(pdb2gmx_result.stdout)
            _n_na = 0
            if _charge_match:
                _system_charge = float(_charge_match.group(1))
                _n_na = max(0, int(round(-_system_charge)))

            if _n_na > 0:
                (tmpdir / "na_ion.gro").write_text(_NA_ION_GRO)
                (tmpdir / "na_ion.itp").write_text(_NA_ION_ITP)

                ins_result = subprocess.run(
                    [
                        gmx, "insert-molecules",
                        "-ci",  str(tmpdir / "na_ion.gro"),
                        "-nmol", str(_n_na),
                        "-f",   str(tmpdir / "conf.gro"),
                        "-o",   str(tmpdir / "conf_ions.gro"),
                        "-try", "2000",
                        "-scale", "1.0",
                        "-nobackup",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(tmpdir),
                )
                if ins_result.returncode != 0:
                    raise RuntimeError(
                        f"insert-molecules failed (Na+ counterions):\n"
                        f"{ins_result.stderr[-2000:]}"
                    )
                (tmpdir / "conf_ions.gro").rename(tmpdir / "conf.gro")

                # Patch topol.top: include na_ion.itp before [ system ] and
                # append Na+ count to [ molecules ]
                top_text = (tmpdir / "topol.top").read_text()
                top_text = top_text.replace(
                    "[ system ]",
                    '#include "na_ion.itp"\n\n[ system ]',
                    1,
                )
                # Append NA entry to [ molecules ] section (matches moleculetype name)
                top_text = top_text.rstrip("\n") + f"\nNA         {_n_na}\n"
                (tmpdir / "topol.top").write_text(top_text)

        # ── 3c. Solvate + add ions (only when solvate=True) ──────────────────
        if solvate:
            pname, pq, nname = _ion_names_for_ff(ff)
            conc_M = ion_conc_mM / 1000.0
            ion_label = f"{ion_conc_mM:.0f} mM MgCl2"

            # 3b-i. Add TIP3P water (spc216.gro template — correct geometry for
            #        TIP3P; GROMACS uses residue names from the topology, not
            #        from the template).
            r = subprocess.run(
                [
                    gmx, "solvate",
                    "-cp", str(tmpdir / "conf.gro"),
                    "-cs", "spc216.gro",
                    "-o",  str(tmpdir / "solvated.gro"),
                    "-p",  str(tmpdir / "topol.top"),
                    "-nobackup",
                ],
                capture_output=True, text=True, cwd=str(tmpdir),
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"solvate failed:\n{r.stderr[-2000:]}"
                )

            # 3b-ii. grompp with minimal MDP — just enough to build a .tpr for
            #         genion to read system topology and atom counts from.
            (tmpdir / "ions.mdp").write_text(_IONS_MDP)
            r = subprocess.run(
                [
                    gmx, "grompp",
                    "-f", str(tmpdir / "ions.mdp"),
                    "-c", str(tmpdir / "solvated.gro"),
                    "-p", str(tmpdir / "topol.top"),
                    "-o", str(tmpdir / "ions.tpr"),
                    "-maxwarn", "20",
                    "-nobackup",
                ],
                capture_output=True, text=True, cwd=str(tmpdir),
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"grompp (ions) failed:\n{r.stderr[-2000:]}"
                )

            # 3b-iii. genion — replace SOL molecules with Mg2+ and Cl-.
            #  -neutral  : first neutralise the DNA charge (DNA is negative,
            #              so Mg2+ is added until net charge is zero)
            #  -conc     : then add MgCl2 pairs to reach target concentration
            #  Input "SOL\n" selects the solvent group without user interaction.
            r = subprocess.run(
                [
                    gmx, "genion",
                    "-s",      str(tmpdir / "ions.tpr"),
                    "-o",      str(tmpdir / "conf.gro"),   # overwrites dry conf
                    "-p",      str(tmpdir / "topol.top"),
                    "-pname",  pname,
                    "-pq",     str(pq),
                    "-nname",  nname,
                    "-neutral",
                    "-conc",   str(conc_M),
                    "-nobackup",
                ],
                input="SOL\n",
                capture_output=True, text=True, cwd=str(tmpdir),
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"genion failed:\n{r.stderr[-2000:]}"
                )

        # ── 4. Collect generated files ────────────────────────────────────────
        conf_gro  = (tmpdir / "conf.gro").read_text()
        topol_top = (tmpdir / "topol.top").read_text()
        itp_files = {
            p.name: p.read_bytes()
            for p in tmpdir.glob("*.itp")
            if p.name != "na_ion.itp"  # written explicitly in vacuum branch below
        }

        # ── 4b. Generate low-spring posre files + patch topology (xover only) ─
        # pdb2gmx generates posre_DNA_chain_X.itp with 1000 kJ/mol/nm² spring
        # constants.  For extra-base crossover designs we need a second set at
        # 100 kJ/mol/nm² (POSRES_LOW) for the staged release step, plus matching
        # #ifdef POSRES_LOW include guards in each topol_DNA_chain_X.itp.
        if _has_xover_insertions:
            _posre_line_re = re.compile(
                r'(?m)^(\s*\d+\s+1\s+)1000\s+1000\s+1000\s*$'
            )
            for _itp_name in list(itp_files.keys()):
                if not _itp_name.startswith("posre_"):
                    continue
                _low_name = "posre_low_" + _itp_name[len("posre_"):]
                _low_text = _posre_line_re.sub(
                    r'\g<1>100   100   100',
                    itp_files[_itp_name].decode(),
                )
                itp_files[_low_name] = _low_text.encode()

                # Patch the topol_*.itp that #includes this posre file
                _old_block = (
                    f'#ifdef POSRES\n#include "{_itp_name}"\n#endif'
                )
                _new_block = (
                    f'#ifdef POSRES\n#include "{_itp_name}"\n#endif\n'
                    f'#ifdef POSRES_LOW\n#include "{_low_name}"\n#endif'
                )
                for _tn, _tb in list(itp_files.items()):
                    if _tn.startswith("topol_") and _old_block.encode() in _tb:
                        itp_files[_tn] = _tb.decode().replace(
                            _old_block, _new_block, 1
                        ).encode()
                        break

        # ── 5. Assemble ZIP ───────────────────────────────────────────────────
        prefix = f"{name}_gromacs/"
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Structure and topology
            zf.writestr(prefix + "conf.gro",   conf_gro)
            zf.writestr(prefix + "topol.top",  topol_top)
            for itp_name, itp_bytes in itp_files.items():
                zf.writestr(prefix + itp_name, itp_bytes)

            # MDP files — solvated (PME) or vacuum (reaction-field) templates
            if solvate:
                if _has_xover_insertions:
                    # ── Extended equilibration for extra-base crossover designs ─
                    # Two-phase EM + annealed NVT + staged POSRES release.
                    # dt=0.001 throughout for stability around strained termini.
                    # nsteps doubled vs standard to keep the same simulation time.
                    _LINCS2 = re.compile(r'lincs-iter\s*=\s*\d+', re.IGNORECASE)
                    _nvt_xover = _NVT_MDP_SOL
                    _nvt_xover = _DT_FROM_MDP.sub("dt = 0.001", _nvt_xover)
                    _nvt_xover = _STEPS_FROM_MDP.sub("nsteps = 100000", _nvt_xover, count=1)
                    _nvt_xover = _LINCS2.sub("lincs-iter = 2", _nvt_xover)
                    # Annealing-time must match total NVT sim time (100 ps)
                    _nvt_xover = _nvt_xover.replace(
                        "annealing-time          = 0  10  50  100",
                        "annealing-time          = 0  5   20  100",
                    )
                    _npt_xover = _NPT_MDP_SOL
                    _npt_xover = _DT_FROM_MDP.sub("dt = 0.001", _npt_xover)
                    # 500000 steps × dt=0.001 = 500 ps (fix stale "; 1 ns" comment)
                    _npt_xover = _STEPS_FROM_MDP.sub("nsteps = 500000", _npt_xover, count=1)
                    _npt_xover = _npt_xover.replace(
                        "nsteps = 500000      ; 1 ns", "nsteps = 500000      ; 500 ps"
                    )
                    _npt_xover = _LINCS2.sub("lincs-iter = 2", _npt_xover)
                    zf.writestr(prefix + "em_free.mdp",    _EM_FREE_MDP_SOL)
                    zf.writestr(prefix + "em_posres.mdp",  _EM_POSRES_MDP_SOL)
                    zf.writestr(prefix + "nvt.mdp",        _nvt_xover)
                    zf.writestr(prefix + "npt.mdp",        _npt_xover)
                    zf.writestr(prefix + "npt_low.mdp",    _NPT_LOW_MDP_SOL)
                    zf.writestr(prefix + "npt_release.mdp", _NPT_RELEASE_MDP_SOL)
                    zf.writestr(prefix + "nvt_free.mdp",   _NVT_FREE_MDP_SOL)
                else:
                    em_mdp       = _EM_MDP_SOL
                    nvt_mdp      = _STEPS_FROM_MDP.sub(
                                       f"nsteps = {_nvt_steps}", _NVT_MDP_SOL, count=1)
                    npt_mdp      = _NPT_MDP_SOL
                    nvt_free_mdp = _NVT_FREE_MDP_SOL
                    zf.writestr(prefix + "em.mdp",       em_mdp)
                    zf.writestr(prefix + "nvt.mdp",      nvt_mdp)
                    zf.writestr(prefix + "npt.mdp",      npt_mdp)
                    zf.writestr(prefix + "nvt_free.mdp", nvt_free_mdp)
            else:
                em_mdp = (
                    _STEPS_FROM_MDP.sub(f"nsteps = {_em_nsteps}", _EM_MDP, count=1)
                    if _em_nsteps != 50000 else _EM_MDP
                )
                # dt=0.001 for skip-site structures: extra timestep safety while
                # Langevin heats from 0 K through the strained backbone geometry.
                _dt = 0.001 if _has_skips else 0.002

                # Restrained stage is capped — user nvt_steps only governs production.
                _nvt_restrained_ps = _NVT_RESTRAINED_STEPS * _dt

                nvt_mdp = _STEPS_FROM_MDP.sub(
                              f"nsteps = {_NVT_RESTRAINED_STEPS}", _NVT_MDP, count=1)
                if _has_skips:
                    nvt_mdp = _DT_FROM_MDP.sub("dt = 0.001", nvt_mdp)

                nvt_free_mdp = _STEPS_FROM_MDP.sub(
                                   f"nsteps = {_nvt_steps}", _NVT_FREE_MDP, count=1) \
                               if _nvt_steps != 25000 else _NVT_FREE_MDP
                if _has_skips:
                    nvt_free_mdp = _DT_FROM_MDP.sub("dt = 0.001", nvt_free_mdp)

                # Simulated annealing: ramp temperature from 0→310 K during restrained
                # NVT to avoid kinetic energy shock at step 0.  Skip structures use a
                # slower ramp (half the time points) given their backbone strain.
                if _has_skips:
                    _ann_times = f"0  5  20  {_nvt_restrained_ps:.1f}"
                else:
                    _ann_times = f"0  10  30  {_nvt_restrained_ps:.1f}"
                _annealing_block = (
                    "; Ramp 0\u2192310 K to avoid LINCS failures from kinetic energy shock at t=0\n"
                    "annealing               = single\n"
                    "annealing-npoints       = 4\n"
                    f"annealing-time          = {_ann_times}\n"
                    "annealing-temp          = 0  100 310 310\n"
                )
                nvt_mdp = nvt_mdp.rstrip("\n") + "\n" + _annealing_block

                zf.writestr(prefix + "em.mdp",       em_mdp)
                zf.writestr(prefix + "nvt.mdp",      nvt_mdp)
                zf.writestr(prefix + "nvt_free.mdp", nvt_free_mdp)
                if _n_na > 0:
                    zf.writestr(prefix + "na_ion.itp", _NA_ION_ITP)
                zf.writestr(prefix + "load_vmd.tcl", _VMD_TCL)

            # Bundled force-field directory (entire tree)
            for ff_file in ff_dir.rglob("*"):
                if ff_file.is_file():
                    arcname = prefix + ff + ".ff/" + ff_file.relative_to(ff_dir).as_posix()
                    zf.write(str(ff_file), arcname)

            # launch.sh (executable bit)
            if _has_xover_insertions:
                launch_sh_text = _LAUNCH_SH_SOL_XOVER
            elif solvate:
                launch_sh_text = _LAUNCH_SH_SOL
            else:
                launch_sh_text = _LAUNCH_SH
            launch_sh_text = launch_sh_text.replace("{name}", name)
            if solvate:
                launch_sh_text = launch_sh_text.replace("{ion_label}", ion_label)
            launch_info = zipfile.ZipInfo(prefix + "launch.sh")
            launch_info.compress_type = zipfile.ZIP_DEFLATED
            launch_info.external_attr = (
                stat.S_IFREG | stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP
                | stat.S_IROTH | stat.S_IXOTH
            ) << 16
            zf.writestr(launch_info, launch_sh_text)

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
