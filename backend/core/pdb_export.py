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

import json
import math
from collections import OrderedDict, defaultdict
from typing import Optional

from backend.core.atomistic import Atom, AtomisticModel, build_atomistic_model
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
# extends these fields using base-36 upper- then lower-case blocks. For example,
# width 5 transitions 99999 → A0000, A0009 → A000A. This exact algorithm is
# understood by ChimeraX, cctbx, OpenMM, VMD, and PyMOL.

_H36_UPPER = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_H36_LOWER = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(value: int, width: int, digits: str) -> str:
    chars = []
    for _ in range(width):
        value, rem = divmod(value, 36)
        chars.append(digits[rem])
    if value:
        raise ValueError("base-36 overflow")
    return "".join(reversed(chars))


def _h36(value: int, width: int) -> str:
    """
    Encode *value* as a right-justified hybrid-36 string of *width* characters.
    *width* must be 4 (residue number) or 5 (atom serial).
    """
    dec_max = 10 ** width                          # 10000 or 100000
    if 0 <= value < dec_max:
        return f"{value:{width}d}"
    value -= dec_max
    block = 26 * 36 ** (width - 1)
    offset = 10 * 36 ** (width - 1)
    if value < block:
        return _base36(value + offset, width, _H36_UPPER)
    value -= block
    if value < block:
        return _base36(value + offset, width, _H36_LOWER)
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


def _nucleotide_uid(atom: Atom) -> str:
    """Stable nucleotide key independent of lossy PDB chain/residue fields."""
    if atom.aux_helix_id:
        return (
            f"strand={atom.strand_id}|helix={atom.helix_id}|bp={atom.bp_index}|"
            f"dir={atom.direction}|seq={atom.seq_num}|aux={atom.aux_helix_id}|"
            f"t={atom.aux_t:.6f}"
        )
    return (
        f"strand={atom.strand_id}|helix={atom.helix_id}|bp={atom.bp_index}|"
        f"dir={atom.direction}|seq={atom.seq_num}"
    )


def _psf_segid(chain_id: str) -> str:
    """Segment ID convention shared by PSF and identity sidecar exports."""
    return ("DNA" + chain_id)[:8]


def export_identity_json(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    """Export durable atom/nucleotide identity metadata for MD pipelines.

    PDB atom serials, chain IDs, and residue numbers are fixed-width fields and
    can wrap or be rewritten by third-party tools.  This JSON sidecar preserves
    NADOC's design identity for every nucleotide and atom so downstream scripts
    can build base-pair maps, restraints, and health checks from intended
    design identity instead of inferred geometry.
    """
    if model is None:
        model = build_atomistic_model(design)

    nucleotide_rows: "OrderedDict[str, dict]" = OrderedDict()
    atom_rows: list[dict] = []
    for atom in model.atoms:
        uid = _nucleotide_uid(atom)
        if uid not in nucleotide_rows:
            nucleotide_rows[uid] = {
                "nucleotide_uid": uid,
                "strand_id": atom.strand_id,
                "helix_id": atom.helix_id,
                "bp_index": atom.bp_index,
                "direction": atom.direction,
                "chain_id": atom.chain_id,
                "seq_num": atom.seq_num,
                "residue": atom.residue,
                "is_modified": atom.is_modified,
                "aux_helix_id": atom.aux_helix_id,
                "aux_t": atom.aux_t,
                "atom_serials": [],
            }
        nucleotide_rows[uid]["atom_serials"].append(atom.serial)
        atom_rows.append({
            "atom_serial": atom.serial,
            "atom_serial_1based": atom.serial + 1,
            "atom_name": atom.name,
            "element": atom.element,
            "residue": atom.residue,
            "nucleotide_uid": uid,
            "strand_id": atom.strand_id,
            "helix_id": atom.helix_id,
            "bp_index": atom.bp_index,
            "direction": atom.direction,
            "chain_id": atom.chain_id,
            "seq_num": atom.seq_num,
            "pdb_chain": _chain_char(atom.chain_id),
            "pdb_resseq": _h36(atom.seq_num, 4),
            "pdb_atom_serial": (atom.serial % 9999) + 1,
            "psf_segid": _psf_segid(atom.chain_id),
            "psf_resid": str(atom.seq_num),
            "aux_helix_id": atom.aux_helix_id,
            "aux_t": atom.aux_t,
        })

    payload = {
        "schema": "nadoc.md_identity.v1",
        "design_name": design.metadata.name,
        "notes": [
            "Use atom_serial_1based to join against PSF/NAMD atom ids.",
            "PDB chain/residue/serial fields are included for convenience but are not unique for large systems.",
            "nucleotide_uid is the stable NADOC identity key for restraint generation and health checks.",
        ],
        "counts": {
            "atoms": len(model.atoms),
            "nucleotides": len(nucleotide_rows),
            "bonds": len(model.bonds),
        },
        "nucleotides": list(nucleotide_rows.values()),
        "atoms": atom_rows,
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def export_identity_tsv(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    """Export a compact atom identity table for shell/analysis workflows."""
    if model is None:
        model = build_atomistic_model(design)
    header = [
        "atom_serial_1based", "atom_serial", "atom_name", "element", "residue",
        "nucleotide_uid", "strand_id", "helix_id", "bp_index", "direction",
        "chain_id", "seq_num", "pdb_chain", "pdb_resseq", "psf_segid",
        "psf_resid", "aux_helix_id", "aux_t",
    ]
    lines = ["\t".join(header)]
    for atom in model.atoms:
        uid = _nucleotide_uid(atom)
        row = [
            str(atom.serial + 1),
            str(atom.serial),
            atom.name,
            atom.element,
            atom.residue,
            uid,
            atom.strand_id,
            atom.helix_id,
            str(atom.bp_index),
            atom.direction,
            atom.chain_id,
            str(atom.seq_num),
            _chain_char(atom.chain_id),
            _h36(atom.seq_num, 4),
            _psf_segid(atom.chain_id),
            str(atom.seq_num),
            atom.aux_helix_id,
            f"{atom.aux_t:.6f}",
        ]
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


# ── Design-aware MD maps and dry/implicit restraints ─────────────────────────

_BACKBONE_NAMES = {
    "P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'",
}

_WC_ATOM_PAIRS: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    ("DA", "DT"): (("N1", "N3"), ("N6", "O4")),
    ("DT", "DA"): (("N3", "N1"), ("O4", "N6")),
    ("DG", "DC"): (("N1", "N3"), ("N2", "O2"), ("O6", "N4")),
    ("DC", "DG"): (("N3", "N1"), ("O2", "N2"), ("N4", "O6")),
}

_GLYCOSIDIC_ATOM_BY_RESIDUE = {
    "DA": "N9",
    "DG": "N9",
    "DC": "N1",
    "DT": "N1",
}


def _coord_ang(atom: Atom) -> tuple[float, float, float]:
    return atom.x * 10.0, atom.y * 10.0, atom.z * 10.0


def _distance_ang(atom_a: Atom, atom_b: Atom) -> float:
    ax, ay, az = _coord_ang(atom_a)
    bx, by, bz = _coord_ang(atom_b)
    dx, dy, dz = ax - bx, ay - by, az - bz
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _nucleotide_table(model: AtomisticModel) -> "OrderedDict[str, dict]":
    """Group atomistic atoms into stable nucleotide records."""
    table: "OrderedDict[str, dict]" = OrderedDict()
    for atom in model.atoms:
        uid = _nucleotide_uid(atom)
        rec = table.get(uid)
        if rec is None:
            rec = {
                "nucleotide_uid": uid,
                "strand_id": atom.strand_id,
                "helix_id": atom.helix_id,
                "bp_index": atom.bp_index,
                "direction": atom.direction,
                "chain_id": atom.chain_id,
                "seq_num": atom.seq_num,
                "residue": atom.residue,
                "is_modified": atom.is_modified,
                "aux_helix_id": atom.aux_helix_id,
                "aux_t": atom.aux_t,
                "atom_serials": [],
                "atom_serials_1based": [],
                "atoms_by_name": {},
            }
            table[uid] = rec
        rec["atom_serials"].append(atom.serial)
        rec["atom_serials_1based"].append(atom.serial + 1)
        rec["atoms_by_name"][atom.name] = atom
    return table


def _public_nucleotide_record(rec: dict) -> dict:
    return {
        "nucleotide_uid": rec["nucleotide_uid"],
        "strand_id": rec["strand_id"],
        "helix_id": rec["helix_id"],
        "bp_index": rec["bp_index"],
        "direction": rec["direction"],
        "chain_id": rec["chain_id"],
        "seq_num": rec["seq_num"],
        "residue": rec["residue"],
        "is_modified": rec["is_modified"],
        "aux_helix_id": rec["aux_helix_id"],
        "aux_t": rec["aux_t"],
        "atom_serials": rec["atom_serials"],
        "atom_serials_1based": rec["atom_serials_1based"],
    }


def _build_basepair_records(model: AtomisticModel) -> list[dict]:
    nucleotides = _nucleotide_table(model)
    by_site: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for rec in nucleotides.values():
        if rec["aux_helix_id"]:
            continue
        by_site[(rec["helix_id"], rec["bp_index"], rec["direction"])].append(rec)

    records: list[dict] = []
    fwd_keys = sorted(
        (key for key in by_site if key[2] == "FORWARD"),
        key=lambda key: (str(key[0]), int(key[1])),
    )
    for helix_id, bp_index, _direction in fwd_keys:
        forward = sorted(by_site[(helix_id, bp_index, "FORWARD")], key=lambda r: r["seq_num"])
        reverse = sorted(by_site.get((helix_id, bp_index, "REVERSE"), []), key=lambda r: r["seq_num"])
        for copy_index, (a, b) in enumerate(zip(forward, reverse)):
            c1_a = a["atoms_by_name"].get("C1'")
            c1_b = b["atoms_by_name"].get("C1'")
            wc_pairs = [
                {
                    "atom_a": atom_a,
                    "atom_b": atom_b,
                    "atom_serial_a": a["atoms_by_name"][atom_a].serial,
                    "atom_serial_b": b["atoms_by_name"][atom_b].serial,
                    "atom_serial_a_1based": a["atoms_by_name"][atom_a].serial + 1,
                    "atom_serial_b_1based": b["atoms_by_name"][atom_b].serial + 1,
                    "distance_angstrom": _distance_ang(
                        a["atoms_by_name"][atom_a],
                        b["atoms_by_name"][atom_b],
                    ),
                    "type": "canonical_wc",
                }
                for atom_a, atom_b in _WC_ATOM_PAIRS.get((a["residue"], b["residue"]), ())
                if atom_a in a["atoms_by_name"] and atom_b in b["atoms_by_name"]
            ]
            anchor_pairs = list(wc_pairs)
            if not anchor_pairs and c1_a is not None and c1_b is not None:
                anchor_pairs.append({
                    "atom_a": "C1'",
                    "atom_b": "C1'",
                    "atom_serial_a": c1_a.serial,
                    "atom_serial_b": c1_b.serial,
                    "atom_serial_a_1based": c1_a.serial + 1,
                    "atom_serial_b_1based": c1_b.serial + 1,
                    "distance_angstrom": _distance_ang(c1_a, c1_b),
                    "type": "noncanonical_c1prime_anchor",
                })
            gly_a_name = _GLYCOSIDIC_ATOM_BY_RESIDUE.get(a["residue"])
            gly_b_name = _GLYCOSIDIC_ATOM_BY_RESIDUE.get(b["residue"])
            gly_a = a["atoms_by_name"].get(gly_a_name) if gly_a_name else None
            gly_b = b["atoms_by_name"].get(gly_b_name) if gly_b_name else None
            if not wc_pairs and gly_a is not None and gly_b is not None:
                anchor_pairs.append({
                    "atom_a": gly_a.name,
                    "atom_b": gly_b.name,
                    "atom_serial_a": gly_a.serial,
                    "atom_serial_b": gly_b.serial,
                    "atom_serial_a_1based": gly_a.serial + 1,
                    "atom_serial_b_1based": gly_b.serial + 1,
                    "distance_angstrom": _distance_ang(gly_a, gly_b),
                    "type": "noncanonical_glycosidic_anchor",
                })
            records.append({
                "pair_id": f"{helix_id}:{bp_index}:{copy_index}",
                "helix_id": helix_id,
                "bp_index": bp_index,
                "copy_index": copy_index,
                "nucleotide_5p_side": _public_nucleotide_record(a),
                "nucleotide_3p_side": _public_nucleotide_record(b),
                "wc_atom_pairs": wc_pairs,
                "basepair_atom_pairs": anchor_pairs,
                "c1prime_distance_angstrom": (
                    _distance_ang(c1_a, c1_b) if c1_a is not None and c1_b is not None else None
                ),
            })
    return records


def _build_stacking_records(model: AtomisticModel) -> list[dict]:
    nucleotides = _nucleotide_table(model)
    by_strand_chain: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for rec in nucleotides.values():
        by_strand_chain[(rec["strand_id"], rec["chain_id"])].append(rec)

    records: list[dict] = []
    for (strand_id, chain_id), recs in sorted(by_strand_chain.items(), key=lambda item: item[0]):
        ordered = sorted(recs, key=lambda rec: rec["seq_num"])
        for a, b in zip(ordered, ordered[1:]):
            records.append({
                "stack_id": f"{strand_id}:{chain_id}:{a['seq_num']}-{b['seq_num']}",
                "strand_id": strand_id,
                "chain_id": chain_id,
                "nucleotide_5p": _public_nucleotide_record(a),
                "nucleotide_3p": _public_nucleotide_record(b),
            })
    return records


def export_design_maps_json(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    """Export intended base-pair and stacking maps from design identity."""
    if model is None:
        model = build_atomistic_model(design)
    basepairs = _build_basepair_records(model)
    stacking = _build_stacking_records(model)
    payload = {
        "schema": "nadoc.md_design_maps.v1",
        "design_name": design.metadata.name,
        "notes": [
            "Base pairs are mapped by intended helix/bp/opposite-direction identity, not inferred from geometry.",
            "Stacking neighbors follow each strand's atomistic 5-prime to 3-prime residue order.",
            "Atom serials are zero-based; *_1based fields join against PSF/NAMD atom ids.",
        ],
        "counts": {
            "atoms": len(model.atoms),
            "basepairs": len(basepairs),
            "stacking_neighbors": len(stacking),
        },
        "basepairs": basepairs,
        "stacking": stacking,
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def export_basepair_map_json(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    if model is None:
        model = build_atomistic_model(design)
    payload = {
        "schema": "nadoc.md_basepair_map.v1",
        "design_name": design.metadata.name,
        "basepairs": _build_basepair_records(model),
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def export_stacking_map_json(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    if model is None:
        model = build_atomistic_model(design)
    payload = {
        "schema": "nadoc.md_stacking_map.v1",
        "design_name": design.metadata.name,
        "stacking": _build_stacking_records(model),
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def export_basepair_map_tsv(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    if model is None:
        model = build_atomistic_model(design)
    header = [
        "pair_id", "helix_id", "bp_index", "copy_index",
        "uid_forward", "residue_forward", "strand_forward", "seq_forward",
        "uid_reverse", "residue_reverse", "strand_reverse", "seq_reverse",
        "wc_atom_pair_count", "c1prime_distance_angstrom",
    ]
    lines = ["\t".join(header)]
    for rec in _build_basepair_records(model):
        fwd = rec["nucleotide_5p_side"]
        rev = rec["nucleotide_3p_side"]
        c1dist = rec["c1prime_distance_angstrom"]
        lines.append("\t".join([
            rec["pair_id"],
            str(rec["helix_id"]),
            str(rec["bp_index"]),
            str(rec["copy_index"]),
            fwd["nucleotide_uid"],
            fwd["residue"],
            fwd["strand_id"],
            str(fwd["seq_num"]),
            rev["nucleotide_uid"],
            rev["residue"],
            rev["strand_id"],
            str(rev["seq_num"]),
            str(len(rec["wc_atom_pairs"])),
            "" if c1dist is None else f"{c1dist:.4f}",
        ]))
    return "\n".join(lines) + "\n"


def export_stacking_map_tsv(
    design: Design,
    model: Optional[AtomisticModel] = None,
) -> str:
    if model is None:
        model = build_atomistic_model(design)
    header = [
        "stack_id", "strand_id", "chain_id",
        "uid_5p", "helix_5p", "bp_5p", "direction_5p", "residue_5p", "seq_5p",
        "uid_3p", "helix_3p", "bp_3p", "direction_3p", "residue_3p", "seq_3p",
    ]
    lines = ["\t".join(header)]
    for rec in _build_stacking_records(model):
        a = rec["nucleotide_5p"]
        b = rec["nucleotide_3p"]
        lines.append("\t".join([
            rec["stack_id"],
            rec["strand_id"],
            rec["chain_id"],
            a["nucleotide_uid"],
            str(a["helix_id"]),
            str(a["bp_index"]),
            a["direction"],
            a["residue"],
            str(a["seq_num"]),
            b["nucleotide_uid"],
            str(b["helix_id"]),
            str(b["bp_index"]),
            b["direction"],
            b["residue"],
            str(b["seq_num"]),
        ]))
    return "\n".join(lines) + "\n"


def _extra_bond_line(atom_i: Atom, atom_j: Atom, distance_ang: float, k: float) -> str:
    return f"bond {atom_i.serial} {atom_j.serial} {distance_ang:.4f} {k:.4f}"


def _base_heavy_atoms(rec: dict) -> list[Atom]:
    atoms = rec["atoms_by_name"].values()
    return [
        atom for atom in atoms
        if atom.element != "H" and atom.name not in _BACKBONE_NAMES
    ]


def _append_unique_extra_bond(
    lines: list[str],
    seen: set[tuple[int, int]],
    covalent: set[tuple[int, int]],
    atom_i: Atom,
    atom_j: Atom,
    distance_ang: float,
    k: float,
) -> None:
    key = tuple(sorted((atom_i.serial, atom_j.serial)))
    if atom_i.serial == atom_j.serial or key in seen or key in covalent:
        return
    seen.add(key)
    lines.append(_extra_bond_line(atom_i, atom_j, distance_ang, k))


def _helix_axis_midpoint(helix) -> tuple[float, float, float]:
    return (
        (helix.axis_start.x + helix.axis_end.x) / 2.0,
        (helix.axis_start.y + helix.axis_end.y) / 2.0,
        (helix.axis_start.z + helix.axis_end.z) / 2.0,
    )


def _helix_midpoint_distance_nm(helix_a, helix_b) -> float:
    ax, ay, az = _helix_axis_midpoint(helix_a)
    bx, by, bz = _helix_axis_midpoint(helix_b)
    dx, dy, dz = ax - bx, ay - by, az - bz
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def export_dry_implicit_restraints(
    design: Design,
    model: Optional[AtomisticModel] = None,
    wc_k: float = 5.0,
    stacking_k: float = 1.0,
    stacking_cutoff_angstrom: float = 4.8,
    interhelix_k: float = 0.5,
    interhelix_distance_angstrom: float = 31.0,
    interhelix_neighbor_cutoff_nm: float = 3.2,
    interhelix_stride_bp: int = 7,
) -> dict[str, str]:
    """Export NAMD extraBonds files for dry or implicit-solvent origami tests.

    These files are design-aware: WC restraints come from intended base-pair
    identity, stacking restraints come from strand order, and dry inter-helix
    restraints come from the design helix layout.  Atom ids are zero-based,
    matching NAMD extraBonds conventions.
    """
    if model is None:
        model = build_atomistic_model(design)

    nucleotides = _nucleotide_table(model)
    basepairs = _build_basepair_records(model)
    stacking = _build_stacking_records(model)
    by_uid = nucleotides
    covalent = {tuple(sorted(pair)) for pair in model.bonds}

    wc_lines: list[str] = [
        "# NAMD extraBonds: intended base-pair restraints",
        "# Canonical A-T/G-C pairs use Watson-Crick heavy atoms; noncanonical pairs use C1' and glycosidic anchors.",
    ]
    wc_seen: set[tuple[int, int]] = set()
    for rec in basepairs:
        a = by_uid[rec["nucleotide_5p_side"]["nucleotide_uid"]]
        b = by_uid[rec["nucleotide_3p_side"]["nucleotide_uid"]]
        for pair in rec["basepair_atom_pairs"]:
            atom_a_name = pair["atom_a"]
            atom_b_name = pair["atom_b"]
            atom_a = a["atoms_by_name"].get(atom_a_name)
            atom_b = b["atoms_by_name"].get(atom_b_name)
            if atom_a is None or atom_b is None:
                continue
            _append_unique_extra_bond(
                wc_lines, wc_seen, covalent, atom_a, atom_b,
                _distance_ang(atom_a, atom_b), wc_k,
            )

    stack_lines: list[str] = [
        "# NAMD extraBonds: adjacent-base stacking contact restraints",
        f"# Contacts are non-covalent base heavy-atom pairs within {stacking_cutoff_angstrom:.2f} A initially.",
    ]
    stack_seen: set[tuple[int, int]] = set()
    for rec in stacking:
        a = by_uid[rec["nucleotide_5p"]["nucleotide_uid"]]
        b = by_uid[rec["nucleotide_3p"]["nucleotide_uid"]]
        for atom_a in _base_heavy_atoms(a):
            for atom_b in _base_heavy_atoms(b):
                dist = _distance_ang(atom_a, atom_b)
                if dist <= stacking_cutoff_angstrom:
                    _append_unique_extra_bond(
                        stack_lines, stack_seen, covalent, atom_a, atom_b, dist, stacking_k,
                    )

    bp_by_helix_bp = {(rec["helix_id"], rec["bp_index"]): rec for rec in basepairs}
    helix_by_id = {helix.id: helix for helix in design.helices}
    helix_pairs: list[tuple[str, str, float]] = []
    helix_ids = sorted(helix_by_id)
    for idx, hid_a in enumerate(helix_ids):
        for hid_b in helix_ids[idx + 1:]:
            dist = _helix_midpoint_distance_nm(helix_by_id[hid_a], helix_by_id[hid_b])
            if dist <= interhelix_neighbor_cutoff_nm:
                helix_pairs.append((hid_a, hid_b, dist))

    inter_lines: list[str] = [
        "# NAMD extraBonds: sparse dry inter-helix spacing restraints",
        f"# Neighbor helices are selected by design-axis midpoint distance <= {interhelix_neighbor_cutoff_nm:.2f} nm.",
        f"# Equilibrium distance is {interhelix_distance_angstrom:.2f} A; stride is {interhelix_stride_bp} bp.",
    ]
    inter_seen: set[tuple[int, int]] = set()
    for hid_a, hid_b, _dist_nm in helix_pairs:
        bp_indices = sorted({
            rec["bp_index"]
            for rec in basepairs
            if rec["helix_id"] in {hid_a, hid_b}
        })
        for bp_index in bp_indices[::max(1, interhelix_stride_bp)]:
            rec_a = bp_by_helix_bp.get((hid_a, bp_index))
            rec_b = bp_by_helix_bp.get((hid_b, bp_index))
            if rec_a is None or rec_b is None:
                continue
            for side in ("nucleotide_5p_side", "nucleotide_3p_side"):
                nuc_a = by_uid[rec_a[side]["nucleotide_uid"]]
                nuc_b = by_uid[rec_b[side]["nucleotide_uid"]]
                atom_a = nuc_a["atoms_by_name"].get("P")
                atom_b = nuc_b["atoms_by_name"].get("P")
                if atom_a is None or atom_b is None:
                    continue
                _append_unique_extra_bond(
                    inter_lines, inter_seen, covalent, atom_a, atom_b,
                    interhelix_distance_angstrom, interhelix_k,
                )

    combined_lines = [
        "# NAMD extraBonds: de-duplicated combined dry/implicit design restraints",
        "# Contains intended base-pair, adjacent stacking, and sparse dry inter-helix restraints.",
    ]
    combined_seen: set[tuple[int, int]] = set()
    for source_lines in (wc_lines, stack_lines, inter_lines):
        for line in source_lines:
            if not line.startswith("bond "):
                continue
            parts = line.split()
            key = tuple(sorted((int(parts[1]), int(parts[2]))))
            if key in combined_seen:
                continue
            combined_seen.add(key)
            combined_lines.append(line)

    summary = {
        "schema": "nadoc.md_restraints_summary.v1",
        "design_name": design.metadata.name,
        "atom_ids": "zero_based_namd_extraBonds",
        "parameters": {
            "wc_k": wc_k,
            "stacking_k": stacking_k,
            "stacking_cutoff_angstrom": stacking_cutoff_angstrom,
            "interhelix_k": interhelix_k,
            "interhelix_distance_angstrom": interhelix_distance_angstrom,
            "interhelix_neighbor_cutoff_nm": interhelix_neighbor_cutoff_nm,
            "interhelix_stride_bp": interhelix_stride_bp,
        },
        "counts": {
            "basepairs": len(basepairs),
            "stacking_neighbors": len(stacking),
            "helix_neighbor_pairs": len(helix_pairs),
            "wc_restraints": len(wc_seen),
            "basepair_restraints": len(wc_seen),
            "stacking_restraints": len(stack_seen),
            "interhelix_restraints": len(inter_seen),
            "combined_restraints": len(combined_seen),
        },
        "notes": [
            "Use one restraint file at a time unless you know duplicate extraBonds are impossible.",
            "The combined file is de-duplicated and is the safest NAMD input.",
            "These restraints preserve intended design contacts for dry/implicit screening and should be reported separately from unrestrained stability metrics.",
        ],
    }

    return {
        "restraints_wc_k5.extrabonds": "\n".join(wc_lines) + "\n",
        "restraints_stack_k1.extrabonds": "\n".join(stack_lines) + "\n",
        "restraints_interhelix_31A_k0p5.extrabonds": "\n".join(inter_lines) + "\n",
        "restraints_dry_implicit_combined.extrabonds": "\n".join(combined_lines) + "\n",
        "restraints_summary.json": json.dumps(summary, indent=2, sort_keys=False) + "\n",
    }


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


def _pdb_atom_record(atom: Atom, *, chain: str | None = None,
                     seq_num: int | None = None) -> str:
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
    # PDB serials are 1-based; AtomisticModel uses 0-based serials.
    # Encode with hybrid-36 (the same scheme used by the CONECT/TER records below
    # and by namd_topology's psfgen PDB writer).  A prior version wrapped serials
    # mod-9999, which made ATOM serials non-unique and — fatally — mismatched the
    # hybrid-36 serials the CONECT records reference, so every design over 9999
    # atoms exported with broken connectivity.  For serials ≤ 99999 hybrid-36 is
    # byte-identical to plain decimal, so the NAMD/psfgen path is unaffected.
    serial_1   = atom.serial + 1
    serial_str = _h36(serial_1, 5)
    seq_str    = _h36(atom.seq_num if seq_num is None else seq_num, 4)
    name_field = _pdb_atom_name(atom.name, atom.element)
    resname    = f"{atom.residue:>3s}"
    chain      = _chain_char(atom.chain_id) if chain is None else chain
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
    atom_a: Atom, atom_b: Atom, dist_ang: float,
    seq_a: int | None = None, seq_b: int | None = None,
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
    # Must use the exact same multi-character→PDB-chain mapping as ATOM records.
    # Taking chain_id[0] aliases AA..AZ back onto A and creates distant LINK bonds.
    c1  = _chain_char(atom_a.chain_id)
    n2  = _pdb_atom_name(atom_b.name, atom_b.element)
    r2  = f"{atom_b.residue:>3s}"
    c2  = _chain_char(atom_b.chain_id)
    return (
        f"LINK        {n1} {r1} {c1}{_h36(atom_a.seq_num if seq_a is None else seq_a, 4)}                "
        f"{n2} {r2} {c2}{_h36(atom_b.seq_num if seq_b is None else seq_b, 4)}                  {dist_ang:5.2f}"
    )


# ── PDB export ────────────────────────────────────────────────────────────────


def export_pdb(
    design: Design,
    non_std_bonds: Optional[list[tuple[int, int]]] = None,
    box_margin_nm: float = 5.0,
    model: Optional[AtomisticModel] = None,
    viewer_terminals: bool = False,
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
    model:
        Pre-built AtomisticModel.  When provided, skips the internal
        build_atomistic_model() call — use this when atom positions have been
        corrected before export (e.g. wrap-bond geometry in periodic cells).

    Returns
    -------
    str
        Full PDB file contents, ready to write to disk.
    """
    import math

    if non_std_bonds is None:
        non_std_bonds = []

    if model is None:
        model = build_atomistic_model(design)
    atoms = model.atoms
    bonds = list(model.bonds)

    # A NADOC strand is one covalent polymer even when its route crosses domains,
    # skips a lattice position, or came from a reconstructed simulation frame.
    # Some of those paths can reach this layer with an incomplete inter-residue
    # bond list.  Viewers then treat otherwise standard nucleotides (for example
    # /X DT 45) as detached residues.  Validate the invariant directly from the
    # lossless internal chain IDs before they are mapped into PDB's one-character
    # namespace, and restore only the canonical consecutive O3' -> P edge.
    dna_residues = {"DA", "DC", "DG", "DT"}
    backbone_atoms: dict[tuple[str, int], dict[str, Atom]] = {}
    for atom in atoms:
        if atom.residue in dna_residues and atom.name in {"O3'", "P"}:
            backbone_atoms.setdefault((atom.chain_id, atom.seq_num), {})[atom.name] = atom
    bond_keys = {tuple(sorted((i, j))) for i, j in bonds}
    repaired_backbone_bonds = 0
    for (chain_id, seq_num), current in backbone_atoms.items():
        nxt = backbone_atoms.get((chain_id, seq_num + 1))
        if nxt is None or "O3'" not in current or "P" not in nxt:
            continue
        edge = tuple(sorted((current["O3'"].serial, nxt["P"].serial)))
        if edge not in bond_keys:
            bonds.append((current["O3'"].serial, nxt["P"].serial))
            bond_keys.add(edge)
            repaired_backbone_bonds += 1

    if viewer_terminals:
        # The simulation template carries P/OP1/OP2 on every residue. At a true
        # 5′ terminus there is no preceding O3′→P bond, leaving an impossible
        # three-coordinate phosphate that viewers protonate incorrectly. For a
        # standalone/viewer PDB, represent the conventional unphosphorylated 5′
        # end instead: O5′ remains and receives its terminal H in AddH tools.
        atom_by_serial_all = {a.serial: a for a in atoms}
        incoming_p: set[int] = set()
        for i, j in bonds:
            a, b = atom_by_serial_all.get(i), atom_by_serial_all.get(j)
            if a is None or b is None:
                continue
            if a.name == "O3'" and b.name == "P" and (a.chain_id, a.seq_num) != (b.chain_id, b.seq_num):
                incoming_p.add(b.serial)
            elif b.name == "O3'" and a.name == "P" and (a.chain_id, a.seq_num) != (b.chain_id, b.seq_num):
                incoming_p.add(a.serial)
        terminal_residues = {
            (a.chain_id, a.seq_num) for a in atoms
            if a.name == "P" and a.seq_num == 1 and a.serial not in incoming_p
        }
        omitted = {
            a.serial for a in atoms
            if (a.chain_id, a.seq_num) in terminal_residues and a.name in {"P", "OP1", "OP2"}
        }
        if omitted:
            atoms = [a for a in atoms if a.serial not in omitted]
            bonds = [(i, j) for i, j in bonds if i not in omitted and j not in omitted]
            non_std_bonds = [(i, j) for i, j in non_std_bonds if i not in omitted and j not in omitted]

    lines: list[str] = [
        "REMARK  NADOC all-atom model (Phase AA, heavy atoms only)",
        "REMARK  Coordinates in Angstroms.  CHARMM36 atom names.",
        "REMARK  Non-standard bonds (if any) listed as LINK records.",
    ]
    if viewer_terminals:
        lines.append("REMARK  Viewer termini: unlinked residue-1 P/OP1/OP2 omitted; O5' is the unphosphorylated 5' end.")
    if repaired_backbone_bonds:
        lines.append(
            f"REMARK  Restored {repaired_backbone_bonds} missing consecutive-strand O3'-P bonds."
        )

    # ── CRYST1 record (periodic boundary cell) ────────────────────────────
    lines.append(_cryst1_record(atoms, margin_nm=box_margin_nm))

    atom_by_serial = {a.serial: a for a in atoms}

    internal_chains = list(dict.fromkeys(a.chain_id for a in atoms))
    use_multi_models = viewer_terminals and len(internal_chains) > len(_CHAIN_CHARS)
    if use_multi_models:
        lines.append(
            f"REMARK  {len(internal_chains)} strands exceed PDB's 62-chain limit; split across "
            f"{math.ceil(len(internal_chains) / len(_CHAIN_CHARS))} MODEL records."
        )

    # PDB chain IDs wrap after 62 strands. If every wrapped strand also restarts
    # at residue 1, ChimeraX merges unrelated residues with identical
    # (chain,resSeq), producing template mismatches and distant missing-structure
    # pseudobonds. Continue numbering within each reused PDB chain character;
    # TER still marks every real strand boundary.
    chain_offsets: dict[str, int] = {}
    internal_offsets: dict[str, int] = {}
    internal_max_seq: dict[str, int] = {}
    for a in atoms:
        internal_max_seq[a.chain_id] = max(internal_max_seq.get(a.chain_id, 0), a.seq_num)
    for a in atoms:
        if a.chain_id in internal_offsets:
            continue
        pdb_chain = _chain_char(a.chain_id)
        internal_offsets[a.chain_id] = chain_offsets.get(pdb_chain, 0)
        chain_offsets[pdb_chain] = internal_offsets[a.chain_id] + internal_max_seq[a.chain_id]

    def _pdb_seq(a: Atom) -> int:
        return a.seq_num if use_multi_models else internal_offsets[a.chain_id] + a.seq_num

    # ── Connectivity ──────────────────────────────────────────────────────
    # CONECT below is the complete topology and addresses atoms by unique serial.
    # Do NOT redundantly emit routine O3′→P backbone LINK records: LINK addresses
    # residues by the limited (name, one-char chain, resSeq) namespace, and ChimeraX
    # can resolve those onto the wrong residue in large origami designs (e.g. the
    # observed false DT 21 O3′ → DT 24 P edge). Reserve LINK for caller-supplied
    # genuinely non-standard chemistry only.
    all_model_bonds = list(bonds)
    for si, sj in non_std_bonds:
        all_model_bonds.append((si, sj))

    for i, j in ([] if use_multi_models else non_std_bonds):
        a = atom_by_serial.get(i)
        b = atom_by_serial.get(j)
        if a is None or b is None:
            continue
        dx = (a.x - b.x) * 10.0
        dy = (a.y - b.y) * 10.0
        dz = (a.z - b.z) * 10.0
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        lines.append(_pdb_link_record(a, b, dist, _pdb_seq(a), _pdb_seq(b)))

    # ── ATOM records grouped by chain; emit TER after each chain ──────────
    from itertools import groupby
    ter_serial = max((a.serial for a in atoms), default=-1) + 2  # first 1-based serial after all atoms

    def _emit_chain_block(block_atoms: list[Atom], block_bonds: list[tuple[int, int]]) -> None:
        nonlocal ter_serial
        if viewer_terminals:
            # Inserted crossover bases and terminal extensions are constructed in
            # post-passes, so raw model order can revisit a chain several times and
            # place residues in an order such as 2..19,22..39,20,21,1,40. ChimeraX
            # uses ATOM/TER order to infer polymer segments even when CONECT is
            # complete, producing false missing-structure pseudobonds (for example
            # O3' 21 -> P 30). Emit each internal strand once in residue order while
            # retaining the original serials used by CONECT.
            chain_order = list(dict.fromkeys(a.chain_id for a in block_atoms))
            grouped = [
                sorted(
                    (a for a in block_atoms if a.chain_id == chain_id),
                    key=lambda a: (a.seq_num, a.serial),
                )
                for chain_id in chain_order
            ]
        else:
            grouped = [list(items) for _, items in groupby(block_atoms, key=lambda a: a.chain_id)]

        for chain_atoms in grouped:
            for atom in chain_atoms:
                lines.append(_pdb_atom_record(
                    atom, chain=_chain_char(atom.chain_id), seq_num=_pdb_seq(atom)))
            last = chain_atoms[-1]
            lines.append(
                f"TER   {_h36(ter_serial, 5)}      "
                f"{last.residue:>3s} {_chain_char(last.chain_id)}{_h36(_pdb_seq(last), 4)}"
            )
            ter_serial += 1
        lines.extend(_pdb_conect_records(block_bonds))

    if use_multi_models:
        for model_idx, start in enumerate(range(0, len(internal_chains), len(_CHAIN_CHARS)), 1):
            chunk = set(internal_chains[start:start + len(_CHAIN_CHARS)])
            block_atoms = [a for a in atoms if a.chain_id in chunk]
            serials = {a.serial for a in block_atoms}
            block_bonds = [(i, j) for i, j in all_model_bonds if i in serials and j in serials]
            lines.append(f"MODEL     {model_idx:4d}")
            _emit_chain_block(block_atoms, block_bonds)
            lines.append("ENDMDL")
    else:
        _emit_chain_block(list(atoms), all_model_bonds)

    lines.append("END")
    return "\n".join(lines) + "\n"


# ── PSF export ────────────────────────────────────────────────────────────────


def export_psf(
    design: Design,
    non_std_bonds: Optional[list[tuple[int, int]]] = None,
    model: Optional[AtomisticModel] = None,
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
    model:
        Pre-built AtomisticModel.  When provided, skips the internal
        build_atomistic_model() call.

    Returns
    -------
    str
        Full PSF file contents, ready to write to disk.
    """
    if non_std_bonds is None:
        non_std_bonds = []

    if model is None:
        model = build_atomistic_model(design)
    atoms = model.atoms
    bonds = list(model.bonds) + [(si, sj) for si, sj in non_std_bonds]

    remarks = [
        " REMARKS NADOC all-atom model (Phase AA)",
        " REMARKS Generated by NADOC pdb_export.py",
        " REMARKS CHARMM36 atom types (heavy atoms only; no hydrogens)",
        " REMARKS Stable nucleotide identity is exported separately in *.identity.json",
    ]
    lines: list[str] = [
        "PSF EXT",
        "",
        f"{len(remarks):8d} !NTITLE",
        *remarks,
        "",
    ]

    # ── !NATOM ────────────────────────────────────────────────────────────
    # Extended PSF NATOM format:
    # %10d %-8s %-8s %-8s %-8s %-6s %14.6g %14.6g %8d
    # serial, segid, resid, resname, atomname, atomtype, charge, mass, imove
    lines.append(f"{len(atoms):>8d} !NATOM")
    for atom in atoms:
        serial_1 = atom.serial + 1
        segid    = _psf_segid(atom.chain_id)
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
