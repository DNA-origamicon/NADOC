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
    "OP1": ("O2P",  -0.78,  15.999),
    "OP2": ("O2P",  -0.78,  15.999),
    "O5'": ("ON3",  -0.57,  15.999),
    "C5'": ("CN8",  -0.08,  12.011),
    "C4'": ("CN7",   0.16,  12.011),
    "O4'": ("ON6",  -0.50,  15.999),
    "C3'": ("CN7",   0.01,  12.011),
    "O3'": ("ON2",  -0.57,  15.999),
    "C2'": ("CN8",  -0.18,  12.011),
    "C1'": ("CN7B",  0.16,  12.011),
}

_BASE_PARAMS: dict[tuple[str, str], tuple[str, float, float]] = {
    # ── DA (deoxyadenosine) ──────────────────────────────────────────────────
    ("DA", "N9"):  ("NN2",  -0.13, 14.007),
    ("DA", "C8"):  ("CN4",   0.34, 12.011),
    ("DA", "N7"):  ("NN3",  -0.51, 14.007),
    ("DA", "C5"):  ("CN5",   0.16, 12.011),
    ("DA", "C4"):  ("CN5",   0.29, 12.011),
    ("DA", "N3"):  ("NN3",  -0.60, 14.007),
    ("DA", "C2"):  ("CN4",   0.50, 12.011),
    ("DA", "N1"):  ("NN3",  -0.74, 14.007),
    ("DA", "C6"):  ("CN2",   0.50, 12.011),
    ("DA", "N6"):  ("NN3A", -0.77, 14.007),
    # ── DT (deoxythymidine) ──────────────────────────────────────────────────
    ("DT", "N1"):  ("NN2B", -0.34, 14.007),
    ("DT", "C2"):  ("CN1",   0.55, 12.011),
    ("DT", "O2"):  ("ON1C", -0.45, 15.999),
    ("DT", "N3"):  ("NN3",  -0.46, 14.007),
    ("DT", "C4"):  ("CN1",   0.53, 12.011),
    ("DT", "O4"):  ("ON1",  -0.51, 15.999),
    ("DT", "C5"):  ("CN3",  -0.13, 12.011),
    ("DT", "C6"):  ("CN3",  -0.24, 12.011),
    ("DT", "C7"):  ("CN9",  -0.27, 12.011),   # thymine methyl
    # ── DC (deoxycytidine) ───────────────────────────────────────────────────
    ("DC", "N1"):  ("NN2B", -0.13, 14.007),
    ("DC", "C2"):  ("CN1",   0.52, 12.011),
    ("DC", "O2"):  ("ON1C", -0.49, 15.999),
    ("DC", "N3"):  ("NN3",  -0.58, 14.007),
    ("DC", "C4"):  ("CN2",   0.65, 12.011),
    ("DC", "N4"):  ("NN1",  -0.75, 14.007),
    ("DC", "C5"):  ("CN3",  -0.13, 12.011),
    ("DC", "C6"):  ("CN3",  -0.11, 12.011),
    # ── DG (deoxyguanosine) ──────────────────────────────────────────────────
    ("DG", "N9"):  ("NN2",  -0.02, 14.007),
    ("DG", "C8"):  ("CN4",   0.25, 12.011),
    ("DG", "N7"):  ("NN3",  -0.60, 14.007),
    ("DG", "C5"):  ("CN5",   0.05, 12.011),
    ("DG", "C4"):  ("CN5",   0.29, 12.011),
    ("DG", "N3"):  ("NN3",  -0.74, 14.007),
    ("DG", "C2"):  ("CN2",   0.75, 12.011),
    ("DG", "N2"):  ("NN1",  -0.68, 14.007),
    ("DG", "N1"):  ("NN2B", -0.34, 14.007),
    ("DG", "C6"):  ("CN1",   0.54, 12.011),
    ("DG", "O6"):  ("ON1",  -0.51, 15.999),
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
    serial_1 = atom.serial + 1
    name_field = _pdb_atom_name(atom.name, atom.element)
    resname    = f"{atom.residue:>3s}"
    chain      = atom.chain_id[0] if atom.chain_id else "A"
    x_ang      = atom.x * 10.0
    y_ang      = atom.y * 10.0
    z_ang      = atom.z * 10.0
    elem_field = f"{atom.element:>2s}"

    return (
        f"ATOM  {serial_1:5d} {name_field}{' '}{resname} {chain}"
        f"{atom.seq_num:4d}    "
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
        serial_1 = serial_0 + 1
        # Emit in groups of 4 partners
        for start in range(0, len(partners), 4):
            chunk = partners[start:start + 4]
            partner_str = "".join(f"{p + 1:5d}" for p in chunk)
            lines.append(f"CONECT{serial_1:5d}{partner_str}")
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

    # ── LINK records for backbone inter-residue O3′→P bonds ──────────────
    # Find O3'→P inter-residue bonds: atoms on different residues (seq_num differs)
    # connected by a bond.
    o3_name = "O3'"
    p_name  = "P"
    atom_by_serial = {a.serial: a for a in atoms}

    for i, j in bonds:
        a = atom_by_serial.get(i)
        b = atom_by_serial.get(j)
        if a is None or b is None:
            continue
        # Only emit LINK for cross-residue bonds (different seq_num on same chain
        # or different chains at crossovers)
        if a.chain_id == b.chain_id and abs(a.seq_num - b.seq_num) == 1:
            if (a.name == o3_name and b.name == p_name) or \
               (b.name == o3_name and a.name == p_name):
                dx = (a.x - b.x) * 10.0
                dy = (a.y - b.y) * 10.0
                dz = (a.z - b.z) * 10.0
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                # O3' atom first
                if a.name == o3_name:
                    lines.append(_pdb_link_record(a, b, dist))
                else:
                    lines.append(_pdb_link_record(b, a, dist))

    # Non-standard bonds (CPD, etc.)
    for si, sj in non_std_bonds:
        a = atom_by_serial.get(si)
        b = atom_by_serial.get(sj)
        if a is None or b is None:
            continue
        dx = (a.x - b.x) * 10.0
        dy = (a.y - b.y) * 10.0
        dz = (a.z - b.z) * 10.0
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        lines.append(_pdb_link_record(a, b, dist))

    # ── ATOM records ──────────────────────────────────────────────────────
    for atom in atoms:
        lines.append(_pdb_atom_record(atom))

    lines.append("TER")

    # ── CONECT records ────────────────────────────────────────────────────
    all_bonds = list(bonds)
    for si, sj in non_std_bonds:
        all_bonds.append((si, sj))
    lines.extend(_pdb_conect_records(all_bonds))

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

    lines: list[str] = [
        "PSF EXT",
        "",
        "       1 !NTITLE",
        " REMARKS NADOC all-atom model (Phase AA)",
        " REMARKS Generated by NADOC pdb_export.py",
        " REMARKS CHARMM36 atom types (heavy atoms only; no hydrogens)",
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
