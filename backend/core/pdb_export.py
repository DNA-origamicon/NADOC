"""
PDB and PSF export for NAMD simulations — Phase AA.

Exports the heavy-atom all-atom model as:
  - PDB:  ATOM records + CONECT records (all covalent bonds) + LINK records for
          non-standard inter-residue bonds (CPD-ready).
  - PSF:  NAMD-compatible extended-format topology with !NATOM and !NBOND sections,
          CHARMM36 atom types and partial charges.

CPD extensibility
─────────────────
The ``non_std_bonds`` parameter accepts a list of (serial_i, serial_j) pairs
(0-based, matching AtomisticModel.atoms indices) for any non-canonical
inter-residue covalent bonds.  For CPD photoproducts this would be the
C5–C5 and C6–C6 bond pairs between adjacent thymines.

Coordinate convention
─────────────────────
AtomisticModel stores coordinates in nm.  PDB records require Å:
    x_Å = x_nm × 10.0
PSF coordinates are not stored in the PSF file itself; only topology data.

CHARMM36 atom types
───────────────────
Backbone and base atom types / charges / masses are hard-coded from
CHARMM36 top_all36_na.rtf (MacKerell lab, 2012+).  A fallback (element
symbol as type, zero charge, standard atomic mass) is used for any atom
name not in the lookup table — which covers future non-standard residues
until explicit entries are added.
"""

from __future__ import annotations

from typing import Optional

from backend.core.atomistic import AtomisticModel, Atom, build_atomistic_model
from backend.core.models import Design

# ── CHARMM36 atom type / charge / mass lookup ────────────────────────────────
# Source: top_all36_na.rtf (CHARMM36, MacKerell lab)
# Format: atom_name → (charmm_type, partial_charge, mass_amu)
#
# Backbone atoms are residue-independent; base atoms are keyed as
# (residue, atom_name) in _BASE_PARAMS and fall back to _BACKBONE_PARAMS.

_BACKBONE_PARAMS: dict[str, tuple[str, float, float]] = {
    "P":   ("P2",    1.50,  30.974),
    "OP1": ("ON3",  -0.78,  15.999),   # non-bridging phosphate O (CHARMM36: ON3)
    "OP2": ("ON3",  -0.78,  15.999),   # non-bridging phosphate O (CHARMM36: ON3)
    "O5'": ("ON2",  -0.57,  15.999),   # 5' ester O (CHARMM36: ON2)
    "C5'": ("CN8B", -0.08,  12.011),   # deoxyribose 5' C (CHARMM36: CN8B)
    "C4'": ("CN7",   0.16,  12.011),
    "O4'": ("ON6",  -0.50,  15.999),
    "C3'": ("CN7",   0.01,  12.011),
    "O3'": ("ON2",  -0.57,  15.999),
    "C2'": ("CN8",  -0.18,  12.011),
    "C1'": ("CN7B",  0.16,  12.011),
}

_BASE_PARAMS: dict[tuple[str, str], tuple[str, float, float]] = {
    # Atom types and charges taken directly from CHARMM36 top_all36_na.rtf
    # (MacKerell lab, Jul 2022).  DNA residues use the RNA residue definitions
    # with the DEOX patch applied (DEOX removes O2'/H2' and changes C2' type).
    #
    # ── DA (deoxyadenosine) — from RTF: ADE ─────────────────────────────────
    ("DA", "N9"):  ("NN2",  -0.05, 14.007),
    ("DA", "C8"):  ("CN4",   0.34, 12.011),
    ("DA", "N7"):  ("NN4",  -0.71, 14.007),   # NN4, not NN3
    ("DA", "C5"):  ("CN5",   0.28, 12.011),
    ("DA", "C4"):  ("CN5",   0.43, 12.011),
    ("DA", "N3"):  ("NN3A", -0.75, 14.007),   # NN3A, not NN3
    ("DA", "C2"):  ("CN4",   0.50, 12.011),
    ("DA", "N1"):  ("NN3A", -0.74, 14.007),   # NN3A, not NN3
    ("DA", "C6"):  ("CN2",   0.46, 12.011),
    ("DA", "N6"):  ("NN1",  -0.77, 14.007),   # NN1, not NN3A
    # ── DT (deoxythymidine) — from RTF: THY ─────────────────────────────────
    ("DT", "N1"):  ("NN2B", -0.34, 14.007),
    ("DT", "C6"):  ("CN3",   0.17, 12.011),
    ("DT", "C2"):  ("CN1T",  0.51, 12.011),   # CN1T, not CN1
    ("DT", "O2"):  ("ON1",  -0.41, 15.999),   # ON1, not ON1C
    ("DT", "N3"):  ("NN2U", -0.46, 14.007),   # NN2U, not NN3
    ("DT", "C4"):  ("CN1",   0.50, 12.011),
    ("DT", "O4"):  ("ON1",  -0.45, 15.999),
    ("DT", "C5"):  ("CN3T", -0.15, 12.011),   # CN3T, not CN3
    ("DT", "C7"):  ("CN9",  -0.11, 12.011),   # thymine methyl (C5M in RTF)
    # ── DC (deoxycytidine) — from RTF: CYT ──────────────────────────────────
    ("DC", "N1"):  ("NN2",  -0.13, 14.007),   # NN2, not NN2B
    ("DC", "C6"):  ("CN3",   0.05, 12.011),
    ("DC", "C5"):  ("CN3",  -0.13, 12.011),
    ("DC", "C2"):  ("CN1",   0.52, 12.011),
    ("DC", "O2"):  ("ON1C", -0.49, 15.999),
    ("DC", "N3"):  ("NN3",  -0.66, 14.007),
    ("DC", "C4"):  ("CN2",   0.65, 12.011),
    ("DC", "N4"):  ("NN1",  -0.75, 14.007),
    # ── DG (deoxyguanosine) — from RTF: GUA ─────────────────────────────────
    ("DG", "N9"):  ("NN2B", -0.02, 14.007),   # NN2B, not NN2
    ("DG", "C4"):  ("CN5",   0.26, 12.011),
    ("DG", "N3"):  ("NN3G", -0.74, 14.007),   # NN3G, not NN3
    ("DG", "C2"):  ("CN2",   0.75, 12.011),
    ("DG", "N2"):  ("NN1",  -0.68, 14.007),
    ("DG", "N1"):  ("NN2G", -0.34, 14.007),   # NN2G, not NN2B
    ("DG", "C6"):  ("CN1",   0.54, 12.011),
    ("DG", "O6"):  ("ON1",  -0.51, 15.999),
    ("DG", "C5"):  ("CN5G",  0.00, 12.011),   # CN5G, not CN5
    ("DG", "N7"):  ("NN4",  -0.60, 14.007),   # NN4, not NN3
    ("DG", "C8"):  ("CN4",   0.25, 12.011),
}

# Fallback element masses
_ELEMENT_MASS: dict[str, float] = {
    "C": 12.011, "N": 14.007, "O": 15.999,
    "P": 30.974, "S": 32.060, "H":  1.008,
}


def _charmm_params(atom: Atom) -> tuple[str, float, float]:
    """Return (charmm_type, charge, mass) for atom, falling back gracefully."""
    # Backbone lookup first (residue-independent)
    if atom.name in _BACKBONE_PARAMS:
        return _BACKBONE_PARAMS[atom.name]
    # Base lookup (residue-specific)
    key = (atom.residue, atom.name)
    if key in _BASE_PARAMS:
        return _BASE_PARAMS[key]
    # Fallback: element as type, zero charge, standard mass
    el = atom.element if atom.element else "C"
    mass = _ELEMENT_MASS.get(el, 12.011)
    return (el, 0.0, mass)


# ── Bounding-box helpers ──────────────────────────────────────────────────────

def _box_dimensions(
    atoms: list,
    margin_nm: float = 5.0,
) -> tuple[float, float, float, float, float, float]:
    """
    Return (ax, ay, az, ox, oy, oz) in Å — the orthorhombic periodic cell
    dimensions and origin that enclose all atoms with the given margin.

    Used by both the CRYST1 record and the NAMD .conf template.
    """
    xs = [a.x for a in atoms]
    ys = [a.y for a in atoms]
    zs = [a.z for a in atoms]
    lo_x, hi_x = min(xs), max(xs)
    lo_y, hi_y = min(ys), max(ys)
    lo_z, hi_z = min(zs), max(zs)
    ax = (hi_x - lo_x + 2 * margin_nm) * 10.0   # nm → Å
    ay = (hi_y - lo_y + 2 * margin_nm) * 10.0
    az = (hi_z - lo_z + 2 * margin_nm) * 10.0
    ox = ((lo_x + hi_x) / 2) * 10.0
    oy = ((lo_y + hi_y) / 2) * 10.0
    oz = ((lo_z + hi_z) / 2) * 10.0
    return ax, ay, az, ox, oy, oz


def _cryst1_record(atoms: list, margin_nm: float = 5.0) -> str:
    """Return the PDB CRYST1 record for a cubic cell enclosing all atoms."""
    ax, ay, az, *_ = _box_dimensions(atoms, margin_nm)
    return (
        f"CRYST1{ax:9.3f}{ay:9.3f}{az:9.3f}  90.00  90.00  90.00 P 1           1"
    )


# ── Hybrid-36 encoding ────────────────────────────────────────────────────────
# PDB fixed-width fields overflow at 99,999 (5-char serial) and 9,999 (4-char
# residue number).  The hybrid-36 scheme (used by cctbx, OpenMM, VMD, PyMOL)
# extends these fields using letter prefixes:
#   5-char serial:  0-99999 decimal → A0000-Z9999 (100000-359999) → a0000-z9999
#   4-char seq_num: 0-9999 decimal  → A000-Z999  (10000-35999)   → a000-z999
# This supports up to ~87 million atoms (5-char) / ~83 thousand residues (4-char).

_H36_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _h36(value: int, width: int) -> str:
    """
    Encode *value* as a right-justified hybrid-36 string of *width* characters.
    *width* must be 4 (residue number) or 5 (atom serial).
    """
    dec_max = 10 ** width                          # 10000 or 100000
    if 0 <= value < dec_max:
        return f"{value:{width}d}"
    value -= dec_max
    per_letter = 10 ** (width - 1)                 # 1000 or 10000
    for letter in _H36_DIGITS:
        if value < per_letter:
            return letter + f"{value:0{width - 1}d}"
        value -= per_letter
    raise ValueError(f"hybrid-36 overflow: value out of range for width {width}")


# PDB chain IDs are a single character.  We map strand indices to printable
# single chars: A-Z (0-25), a-z (26-51), 0-9 (52-61), then cycle.
_CHAIN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _chain_char(chain_id: str) -> str:
    """
    Return the single PDB chain character for a (potentially multi-char)
    chain_id produced by the atomistic model.

    The atomistic model assigns "A"-"Z" for strands 0-25, then "AA"-"AZ" for
    26-51, etc.  We map these back to a stable single character using the
    62-char _CHAIN_CHARS alphabet, cycling if there are > 62 strands.
    """
    if not chain_id:
        return "A"
    # Decode the atomistic model's alpha-only encoding to an index
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if len(chain_id) == 1:
        idx = letters.index(chain_id) if chain_id in letters else 0
    else:
        # Multi-char: first char is the "tens" digit (1-based), second is units
        hi = letters.index(chain_id[0]) + 1   # 1-based block number
        lo = letters.index(chain_id[1])
        idx = hi * 26 + lo
    return _CHAIN_CHARS[idx % len(_CHAIN_CHARS)]


# ── PDB helpers ───────────────────────────────────────────────────────────────

def _pdb_atom_name(name: str, element: str) -> str:
    """
    Format a 4-character PDB atom name field.

    PDB convention (wwPDB 3.3):
      - 1-char element: col 14 is start of name → " XXX" (space + 3-char name)
      - 2-char element: col 13 is start of name → "XXXX" (4-char name)

    For all DNA atoms (P, C, N, O — single-char elements) this means
    left-padding with one space unless the name is already 4 characters.
    """
    if len(element) == 1 and len(name) <= 3:
        return f" {name:<3s}"
    return f"{name:<4s}"


def _pdb_atom_record(atom: Atom) -> str:
    """
    Format one PDB ATOM record (80-char fixed-width).

    Columns (1-based, inclusive):
      1-6   record name ("ATOM  ")
      7-11  serial (right-justified integer)
      12    blank
      13-16 atom name (4 chars, see _pdb_atom_name)
      17    alt loc (blank)
      18-20 residue name (right-justified, 3 chars)
      21    blank
      22    chain ID (1 char)
      23-26 residue seq number (right-justified integer)
      27    code for insertion of residues (blank)
      28-30 blanks
      31-38 x (Å, 8.3f)
      39-46 y (Å, 8.3f)
      47-54 z (Å, 8.3f)
      55-60 occupancy (6.2f)
      61-66 B-factor (6.2f)
      77-78 element symbol (right-justified, 2 chars)
    """
    # PDB serials are 1-based; AtomisticModel uses 0-based serials
    serial_1   = atom.serial + 1
    serial_str = _h36(serial_1, 5)
    seq_str    = _h36(atom.seq_num, 4)
    name_field = _pdb_atom_name(atom.name, atom.element)
    resname    = f"{atom.residue:>3s}"
    chain      = _chain_char(atom.chain_id)
    x_ang      = atom.x * 10.0
    y_ang      = atom.y * 10.0
    z_ang      = atom.z * 10.0
    elem_field = f"{atom.element:>2s}"

    return (
        f"ATOM  {serial_str} {name_field}{' '}{resname} {chain}"
        f"{seq_str}    "
        f"{x_ang:8.3f}{y_ang:8.3f}{z_ang:8.3f}"
        f"  1.00  0.00"
        f"          {elem_field}  "
    )


def _pdb_conect_records(bonds: list[tuple[int, int]]) -> list[str]:
    """
    Generate CONECT records from 0-based bond pairs.

    PDB CONECT format: up to 4 bonded atoms per record.
    We emit one CONECT per atom listing all its bonded partners, grouping
    in sets of 4.  Only heavy-atom bonds are included (no H–X bonds since
    the model has no hydrogens).
    """
    from collections import defaultdict
    adj: dict[int, list[int]] = defaultdict(list)
    for i, j in bonds:
        adj[i].append(j)
        adj[j].append(i)

    lines = []
    for serial_0 in sorted(adj):
        partners = sorted(adj[serial_0])
        serial_str = _h36(serial_0 + 1, 5)
        # Emit in groups of 4 partners
        for start in range(0, len(partners), 4):
            chunk = partners[start:start + 4]
            partner_str = "".join(_h36(p + 1, 5) for p in chunk)
            lines.append(f"CONECT{serial_str}{partner_str}")
    return lines


def _pdb_link_record(
    atom_a: Atom, atom_b: Atom, dist_ang: float
) -> str:
    """
    Generate a LINK record for a covalent bond between two residues
    (backbone O3′→P continuity or non-standard bonds like CPD).

    Columns (1-based):
      1-6   "LINK  "
      13-16 atom name 1
      17    alt loc 1
      18-20 res name 1
      22    chain 1
      23-26 res seq 1
      43-46 atom name 2
      47    alt loc 2
      48-50 res name 2
      52    chain 2
      53-56 res seq 2
      74-78 distance (Å)
    """
    n1  = _pdb_atom_name(atom_a.name, atom_a.element)
    r1  = f"{atom_a.residue:>3s}"
    c1  = atom_a.chain_id[0] if atom_a.chain_id else "A"
    n2  = _pdb_atom_name(atom_b.name, atom_b.element)
    r2  = f"{atom_b.residue:>3s}"
    c2  = atom_b.chain_id[0] if atom_b.chain_id else "A"
    return (
        f"LINK        {n1} {r1} {c1}{atom_a.seq_num:4d}                "
        f"{n2} {r2} {c2}{atom_b.seq_num:4d}                  {dist_ang:5.2f}"
    )


# ── PDB export ────────────────────────────────────────────────────────────────


def export_pdb(
    design: Design,
    non_std_bonds: Optional[list[tuple[int, int]]] = None,
    box_margin_nm: float = 5.0,
) -> str:
    """
    Export the design as a PDB file string.

    Parameters
    ----------
    design:
        Active NADOC design.
    non_std_bonds:
        Optional list of additional covalent bonds as (serial_i, serial_j)
        pairs using 0-based AtomisticModel serial numbers.  Pass CPD bond
        pairs here to include them as LINK records.
    box_margin_nm:
        Extra padding around the atom bounding box when computing the CRYST1
        periodic cell dimensions (default 5.0 nm).

    Returns
    -------
    str
        Full PDB file contents, ready to write to disk.
    """
    import math

    if non_std_bonds is None:
        non_std_bonds = []

    model = build_atomistic_model(design)
    atoms = model.atoms
    bonds = model.bonds

    lines: list[str] = [
        "REMARK  NADOC all-atom model (Phase AA, heavy atoms only)",
        "REMARK  Coordinates in Angstroms.  CHARMM36 atom names.",
        "REMARK  Non-standard bonds (if any) listed as LINK records.",
    ]

    # ── CRYST1 record (periodic boundary cell) ────────────────────────────
    lines.append(_cryst1_record(atoms, margin_nm=box_margin_nm))

    atom_by_serial = {a.serial: a for a in atoms}

    # ── LINK records for inter-residue O3′→P bonds (inc. crossovers) ─────
    # Emit LINK for every bond where the two atoms belong to different
    # residues (different seq_num OR different chain_id).  This covers both
    # intra-chain sequential bonds and crossover bonds.  Intra-residue bonds
    # do NOT get LINK records.
    all_model_bonds = list(bonds)
    for si, sj in non_std_bonds:
        all_model_bonds.append((si, sj))

    for i, j in all_model_bonds:
        a = atom_by_serial.get(i)
        b = atom_by_serial.get(j)
        if a is None or b is None:
            continue
        if a.chain_id != b.chain_id or a.seq_num != b.seq_num:
            dx = (a.x - b.x) * 10.0
            dy = (a.y - b.y) * 10.0
            dz = (a.z - b.z) * 10.0
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if a.name == "O3'" and b.name == "P":
                lines.append(_pdb_link_record(a, b, dist))
            elif b.name == "O3'" and a.name == "P":
                lines.append(_pdb_link_record(b, a, dist))

    # ── ATOM records grouped by chain; emit TER after each chain ──────────
    # Atoms are ordered by serial; group into per-chain runs.
    from itertools import groupby
    ter_serial = len(atoms) + 1   # first serial after all atoms
    for _chain, chain_atoms_iter in groupby(atoms, key=lambda a: a.chain_id):
        chain_atoms = list(chain_atoms_iter)
        for atom in chain_atoms:
            lines.append(_pdb_atom_record(atom))
        last = chain_atoms[-1]
        lines.append(
            f"TER   {_h36(ter_serial, 5)}      "
            f"{last.residue:>3s} {_chain_char(last.chain_id)}{_h36(last.seq_num, 4)}"
        )
        ter_serial += 1

    # ── CONECT records ────────────────────────────────────────────────────
    lines.extend(_pdb_conect_records(all_model_bonds))

    lines.append("END")
    return "\n".join(lines) + "\n"


# ── PSF export ────────────────────────────────────────────────────────────────


def export_psf(
    design: Design,
    non_std_bonds: Optional[list[tuple[int, int]]] = None,
) -> str:
    """
    Export the design as a NAMD-compatible PSF topology file string.

    The output uses the PSF extended format (EXT flag) which supports
    atom and residue names longer than 4/8 characters.

    Sections written:
      !NTITLE — file header
      !NATOM  — one line per heavy atom with CHARMM36 type, charge, mass
      !NBOND  — all covalent bonds (intra-residue + O3′→P + non_std_bonds)

    Angles, dihedrals, impropers, and cross-terms are NOT written here.
    Run ``psfgen`` or NAMD's ``guesscoord`` to complete the topology.

    Parameters
    ----------
    design:
        Active NADOC design.
    non_std_bonds:
        Same convention as export_pdb().  These bonds are appended to the
        !NBOND section.

    Returns
    -------
    str
        Full PSF file contents, ready to write to disk.
    """
    if non_std_bonds is None:
        non_std_bonds = []

    model = build_atomistic_model(design)
    atoms = model.atoms
    bonds = list(model.bonds) + [(si, sj) for si, sj in non_std_bonds]

    # Segment ID: "DNA" + chain_id (up to 4 chars for PSF field)
    def _segid(chain: str) -> str:
        return ("DNA" + chain)[:8]

    remarks = [
        " REMARKS NADOC all-atom model (Phase AA)",
        " REMARKS Generated by NADOC pdb_export.py",
        " REMARKS CHARMM36 atom types (heavy atoms only; no hydrogens)",
    ]
    lines: list[str] = [
        "PSF",
        "",
        f"{len(remarks):8d} !NTITLE",
        *remarks,
        "",
    ]

    # ── !NATOM ────────────────────────────────────────────────────────────
    # Extended PSF NATOM format:
    # %10d %-8s %-8s %-8s %-8s %-6s %14.6g %14.6g %8d
    # serial, segid, resid, resname, atomname, atomtype, charge, mass, imove
    lines.append(f"{len(atoms):>10d} !NATOM")
    for atom in atoms:
        serial_1 = atom.serial + 1
        segid    = _segid(atom.chain_id)
        resid    = str(atom.seq_num)
        atype, charge, mass = _charmm_params(atom)
        line = (
            f"{serial_1:>10d} "
            f"{segid:<8s} "
            f"{resid:<8s} "
            f"{atom.residue:<8s} "
            f"{atom.name:<8s} "
            f"{atype:<6s} "
            f"{charge:>14.6f}"
            f"{mass:>14.6f}"
            f"{'0':>9s}"
        )
        lines.append(line)
    lines.append("")

    # ── !NBOND ────────────────────────────────────────────────────────────
    # 4 bond pairs per line (8 integers total), 8 chars wide each.
    lines.append(f"{len(bonds):>10d} !NBOND: bonds")
    bond_ints: list[int] = []
    for i, j in bonds:
        bond_ints.append(i + 1)
        bond_ints.append(j + 1)

    # Pad to multiple of 8
    while len(bond_ints) % 8 != 0:
        bond_ints.append(0)

    for k in range(0, len(bond_ints), 8):
        chunk = bond_ints[k:k + 8]
        # Drop trailing zero-padding on last line
        while chunk and chunk[-1] == 0:
            chunk.pop()
        if chunk:
            lines.append("".join(f"{v:>10d}" for v in chunk))

    lines.append("")

    # ── Empty required sections ───────────────────────────────────────────
    for section in ("!NTHETA: angles", "!NPHI: dihedrals",
                    "!NIMPHI: impropers", "!NCRTERM: cross-terms"):
        lines.append(f"{0:>10d} {section}")
        lines.append("")

    return "\n".join(lines) + "\n"
