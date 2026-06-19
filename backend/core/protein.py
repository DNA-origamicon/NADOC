"""
Protein import + placement helpers (display layer).

Proteins are imported from PDB, kept in a reusable library (``ProteinAsset``),
and attached to DNA overhangs for visualization.  This module owns the logic;
the Pydantic models (``ProteinAtom``/``ProteinAsset``/``ProteinAttachment``)
live in :mod:`backend.core.models` because ``Design``/``Assembly`` reference
them at class-definition time.

Three-Layer Law: nothing here writes to the topological layer.  Protein atoms
are converted into the existing all-atom :class:`~backend.core.atomistic.Atom`
representation purely so the established renderer/serializer can draw them; they
carry a sentinel ``helix_id``/``strand_id`` (``__protein__{id}``) that never
collides with real DNA helices.

All coordinates are nm internally (PDB Angstroms ÷ 10), matching the rest of the
codebase.
"""

from __future__ import annotations

import numpy as np

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.models import ProteinAsset, ProteinAtom
from backend.core.pdb_to_design import (
    _IONS,
    _WATER,
    _frame_from_axis,
    _norm,
    _rotation_between,
)

# Sentinel helix/strand id prefix for protein atoms in the all-atom pipeline.
PROTEIN_SENTINEL_PREFIX = "__protein__"

# ssDNA contour length per nucleotide (nm, nominal) — used only for the
# display-only handle-spacer offset that pushes the protein past the free tip.
_SS_RISE_NM = 0.63

# Residue names to discard.  Extends the DNA importer's water/ion sets with
# CHARMM solvent/ion names (SOD, CLA, POT, …) and 3-char truncations, since
# protein PDBs are frequently CHARMM-formatted.
_DROP_RESIDUES = _WATER | _IONS | {
    "TIP", "TIP3", "TIP4", "TIP5", "SPCE", "SWM4",
    "SOD", "CLA", "POT", "CAL", "CES", "MG2", "ZN2", "CAL2",
}

# Amino-acid residue names (standard 20 + selenomethionine/-cysteine and common
# CHARMM/protonation variants).  Used to classify a PDB as containing protein.
_AMINO_ACIDS = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "SEC", "PYL", "MSE",                              # Se-Cys, pyrrolysine, Se-Met
    "HSD", "HSE", "HSP", "HID", "HIE", "HIP",         # histidine protonation states
    "CYX", "CYM", "ASH", "GLH", "LYN", "ARN",         # protonation variants
}


def classify_pdb_content(text: str) -> tuple[bool, bool]:
    """Return ``(has_dna, has_protein)`` for a PDB by sniffing residue names.

    Water/ions are ignored.  Used to route a merged "Import PDB" between the DNA
    design importer and the protein library.
    """
    from backend.core.pdb_to_design import _DNA_RESNAME

    has_dna = has_protein = False
    for line in text.splitlines():
        if line[:6].rstrip() not in ("ATOM", "HETATM") or len(line) < 20:
            continue
        res = line[17:21].strip()
        if res in _DROP_RESIDUES:
            continue
        if res in _DNA_RESNAME:
            has_dna = True
        elif res in _AMINO_ACIDS:
            has_protein = True
        if has_dna and has_protein:
            break
    return has_dna, has_protein


def _element_from_atom(name: str, element_col: str) -> str:
    """Resolve an element symbol for a protein atom.

    Prefers the PDB element column (cols 77-78) when present.  Otherwise infers
    from the atom name using only the first alphabetic character — CHARMM-style
    PDBs leave the element column blank, and for standard amino-acid atoms the
    leading character is the element (CA→C, SD→S, ND1→N).  Deliberately does NOT
    treat two-letter atom names as elements (e.g. "CA" is C-alpha carbon, not
    calcium); genuine metals carry an element column in well-formed files and
    monatomic ions are dropped before this is called.
    """
    el = element_col.strip()
    if el:
        return el.capitalize()
    raw = name.strip().lstrip("0123456789")
    return raw[:1].upper() if raw else "C"


def parse_protein_pdb(
    text: str, name: str = "", source_filename: str = "", exclude_dna: bool = False,
) -> ProteinAsset:
    """Parse PDB text into a :class:`ProteinAsset`, keeping protein/HETATM atoms.

    Drops water and monatomic ions always.  When ``exclude_dna`` is True, also
    drops DNA/RNA residues (used when importing a protein-DNA complex and the
    user wants protein only).  Reads the first MODEL only (NMR ensembles).
    Coordinates converted to nm.
    """
    from backend.core.pdb_to_design import _DNA_RESNAME

    atoms: list[ProteinAtom] = []
    in_model = False
    serial = 0
    chain_ids: set[str] = set()
    res_keys: set[tuple[str, int]] = set()

    for line in text.splitlines():
        rec = line[:6].rstrip()
        if rec == "MODEL":
            if in_model:
                break
            in_model = True
            continue
        if rec == "ENDMDL":
            break
        if rec not in ("ATOM", "HETATM"):
            continue
        if len(line) < 54:
            continue

        # Read 4 columns (18-21) so CHARMM 4-char residue names (TIP3, …) are
        # captured; for standard PDBs col 21 is blank and this still yields the
        # 3-char name.  chainID is the separate column 22.
        res_name = line[17:21].strip()
        if res_name in _DROP_RESIDUES:
            continue
        if exclude_dna and res_name in _DNA_RESNAME:
            continue

        atom_name = line[12:16].strip()
        # chainID (col 22); fall back to the CHARMM segid (cols 73-76).
        chain_id = line[21].strip() or (line[72:76].strip() if len(line) >= 76 else "") or "A"
        try:
            res_seq = int(line[22:26])
        except ValueError:
            continue
        try:
            x = float(line[30:38]) / 10.0
            y = float(line[38:46]) / 10.0
            z = float(line[46:54]) / 10.0
        except ValueError:
            continue
        element = _element_from_atom(atom_name, line[76:78] if len(line) >= 78 else "")

        serial += 1
        chain_ids.add(chain_id)
        res_keys.add((chain_id, res_seq))
        atoms.append(ProteinAtom(
            serial=serial,
            name=atom_name,
            element=element,
            res_name=res_name,
            chain_id=chain_id,
            res_seq=res_seq,
            x=round(x, 5),
            y=round(y, 5),
            z=round(z, 5),
        ))

    com = [0.0, 0.0, 0.0]
    if atoms:
        arr = np.array([[a.x, a.y, a.z] for a in atoms], dtype=float)
        com = [float(v) for v in arr.mean(axis=0)]

    # Default conjugation atom: the heavy atom farthest from the centre of mass
    # (a sensible surface point to start from; the user can re-pick later).
    default_conj: int | None = None
    candidates = [a for a in atoms if a.element.upper() != "H"] or atoms
    if candidates:
        c = np.array(com)
        farthest = max(candidates, key=lambda a: float(np.linalg.norm(np.array([a.x, a.y, a.z]) - c)))
        default_conj = farthest.serial

    return ProteinAsset(
        name=name or source_filename or "Protein",
        source_filename=source_filename,
        atoms=atoms,
        bonds=[],
        default_conjugation_atom_serial=default_conj,
        center_of_mass=com,
        metadata={
            "atom_count": len(atoms),
            "residue_count": len(res_keys),
            "chain_ids": sorted(chain_ids),
        },
    )


def protein_asset_meta(asset: ProteinAsset) -> dict:
    """Lightweight library metadata for an asset (no atom list)."""
    return {
        "id": asset.id,
        "name": asset.name,
        "source_filename": asset.source_filename,
        "atom_count": len(asset.atoms),
        "residue_count": asset.metadata.get("residue_count", 0),
        "chain_ids": asset.metadata.get("chain_ids", []),
        "default_conjugation_atom_serial": asset.default_conjugation_atom_serial,
    }


def protein_asset_to_atomistic(
    asset: ProteinAsset,
    pose_matrix: np.ndarray | None = None,
    sentinel_id: str | None = None,
) -> AtomisticModel:
    """Convert a :class:`ProteinAsset` into the all-atom representation.

    ``pose_matrix`` (row-major homogeneous 4×4) transforms asset-local atom
    coordinates into world space; ``None`` leaves them at their PDB coordinates.
    The returned atoms carry a sentinel ``helix_id``/``strand_id`` so they merge
    cleanly with DNA atoms without colliding with real helices.
    """
    sentinel = f"{PROTEIN_SENTINEL_PREFIX}{sentinel_id or asset.id}"
    out: list[Atom] = []
    for i, a in enumerate(asset.atoms):
        x, y, z = a.x, a.y, a.z
        if pose_matrix is not None:
            p = pose_matrix @ np.array([x, y, z, 1.0])
            x, y, z = float(p[0]), float(p[1]), float(p[2])
        out.append(Atom(
            serial=i,
            name=a.name,
            element=a.element,
            residue=a.res_name,
            chain_id=a.chain_id,
            seq_num=a.res_seq,
            x=x, y=y, z=z,
            strand_id=sentinel,
            helix_id=sentinel,
            bp_index=0,
            direction="FORWARD",
        ))
    bonds = [(int(i), int(j)) for i, j in asset.bonds]
    return AtomisticModel(atoms=out, bonds=bonds)


def infer_bonds_by_distance(asset: ProteinAsset, cutoff_nm: float = 0.20) -> list[tuple[int, int]]:
    """Infer covalent bonds by inter-atom distance (0-based atom-index pairs).

    Coarse heuristic for ball-and-stick rendering: any two heavy atoms within
    ``cutoff_nm`` are bonded (hydrogens excluded).  Uses a uniform grid so it
    stays roughly O(N) for large proteins.  Not used for vdw rendering.
    """
    heavy = [(i, np.array([a.x, a.y, a.z])) for i, a in enumerate(asset.atoms)
             if a.element.upper() != "H"]
    if len(heavy) < 2:
        return []
    cell = cutoff_nm
    grid: dict[tuple[int, int, int], list[int]] = {}

    def key(p: np.ndarray) -> tuple[int, int, int]:
        return (int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))

    for idx, (_, p) in enumerate(heavy):
        grid.setdefault(key(p), []).append(idx)

    bonds: list[tuple[int, int]] = []
    cutoff_sq = cutoff_nm * cutoff_nm
    for idx, (atom_i, p) in enumerate(heavy):
        kx, ky, kz = key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for jdx in grid.get((kx + dx, ky + dy, kz + dz), ()):
                        if jdx <= idx:
                            continue
                        atom_j, q = heavy[jdx]
                        if float(np.dot(p - q, p - q)) <= cutoff_sq:
                            bonds.append((atom_i, atom_j))
    return bonds


# ── Overhang anchor + protein placement (Phase 2) ─────────────────────────────


def _mat_T(t: np.ndarray) -> np.ndarray:
    M = np.eye(4)
    M[:3, 3] = t
    return M


def _mat_R(r3: np.ndarray) -> np.ndarray:
    M = np.eye(4)
    M[:3, :3] = r3
    return M


def _conjugation_local_pos(asset: ProteinAsset, attachment) -> np.ndarray:
    """Local (asset-frame) position of the conjugation atom, or the centre of
    mass when no valid conjugation atom is set."""
    serial = attachment.conjugation_atom_serial
    if serial is None:
        serial = asset.default_conjugation_atom_serial
    atom = next((a for a in asset.atoms if a.serial == serial), None) if serial is not None else None
    if atom is None:
        return np.asarray(asset.center_of_mass, dtype=float)
    return np.array([atom.x, atom.y, atom.z], dtype=float)


def resolve_overhang_anchor(
    nucs: list[dict], overhang_id: str, attach_end: str = "free_end",
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Resolve ``(tip_pos, outward)`` for an overhang's attach end (world nm).

    ``tip_pos`` is the backbone position of the attach-end nucleotide (the free
    tip by default).  ``outward`` is a unit vector pointing from the opposite
    end toward the attach end — i.e. away from the bundle — derived from the two
    end positions rather than an axis-tangent sign convention.  For a single-nt
    overhang it falls back to the nucleotide's ``axis_tangent`` (sign ambiguous;
    the user adjusts via pose / the Phase-4 gizmo).

    Returns ``(None, None)`` when the overhang has no geometry yet.  ``nucs`` is
    the geometry nucleotide list (``_geometry_for_helices`` output).
    """
    from backend.core.linker_relax import _oh_attach_nuc

    oh_nucs = [n for n in nucs if n.get("overhang_id") == overhang_id]
    attach_nuc = _oh_attach_nuc(oh_nucs, attach_end)
    if attach_nuc is None:
        return None, None
    other_nuc = _oh_attach_nuc(oh_nucs, "root" if attach_end == "free_end" else "free_end")

    def _pos(n: dict | None) -> np.ndarray | None:
        if n is None:
            return None
        p = n.get("backbone_position") or n.get("base_position")
        return np.asarray(p, dtype=float) if p is not None else None

    tip = _pos(attach_nuc)
    if tip is None:
        return None, None
    other = _pos(other_nuc)
    if other is not None and np.linalg.norm(tip - other) > 1e-6:
        outward = _norm(tip - other)
    else:
        at = attach_nuc.get("axis_tangent")
        outward = _norm(np.asarray(at, dtype=float)) if at is not None else np.array([0.0, 0.0, 1.0])
    return tip, outward


def protein_base_world(
    asset: ProteinAsset, attachment,
    tip: np.ndarray | None = None, outward: np.ndarray | None = None,
) -> np.ndarray:
    """Row-major 4×4 *base* placement of the asset (BEFORE the user pose).

    * Free target → identity (atoms stay at their PDB coordinates).
    * Overhang target → places the conjugation atom at the free tip with the
      protein body (centre_of_mass − conj) pointing outward:

          base = T(tip_out) · AnchorRot · R_canon · T(-conj)

      where ``R_canon`` rotates the body vector onto +Z, ``AnchorRot``
      (``_frame_from_axis(outward)``) maps +Z onto the world outward direction,
      and ``tip_out`` adds the optional ssDNA-spacer offset along outward.
    """
    if getattr(attachment.target, "kind", "free") == "free" or tip is None or outward is None:
        return np.eye(4)

    outward = _norm(np.asarray(outward, dtype=float))
    conj = _conjugation_local_pos(asset, attachment)
    com = np.asarray(asset.center_of_mass, dtype=float)

    body = com - conj
    r_canon = (_rotation_between(body, np.array([0.0, 0.0, 1.0]))
               if np.linalg.norm(body) > 1e-6 else np.eye(3))
    anchor_rot = _frame_from_axis(outward)   # 3×3 [x | y | z = outward]

    offset = max(getattr(attachment, "handle_spacer_nt", 0), 0) * _SS_RISE_NM
    tip_out = tip + outward * offset
    return _mat_T(tip_out) @ _mat_R(anchor_rot) @ _mat_R(r_canon) @ _mat_T(-conj)


def compose_protein_world_transform(
    asset: ProteinAsset, attachment,
    tip: np.ndarray | None = None, outward: np.ndarray | None = None,
) -> np.ndarray:
    """Full world transform = ``pose · base`` (row-major 4×4).

    ``pose`` is the user's world-space rigid delta (identity by default), so the
    conjugation atom lands at the tip / atoms sit at PDB coords when unmoved.
    """
    base = protein_base_world(asset, attachment, tip, outward)
    pose = np.asarray(attachment.pose.to_array(), dtype=float)
    return pose @ base


def gizmo_move_to_pose(
    pose_old: np.ndarray, pivot, translation, rotation,
) -> np.ndarray:
    """Left-multiply a world-space gizmo delta into ``pose``.

    Matches the cluster-gizmo convention: ``rotation`` is a quaternion
    [x,y,z,w] about ``pivot`` and ``translation`` is an additional world
    offset, so the world delta is ``D = T(translation)·T(pivot)·R·T(-pivot)``
    and the new pose is ``D · pose_old`` (because world = pose · base, a
    world-space motion composes on the left).
    """
    piv = np.asarray(pivot, dtype=float)
    trans = np.asarray(translation, dtype=float)
    qx, qy, qz, qw = (float(v) for v in rotation)
    # quaternion → 3×3 rotation matrix
    r = np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])
    d = _mat_T(trans) @ _mat_T(piv) @ _mat_R(r) @ _mat_T(-piv)
    return d @ np.asarray(pose_old, dtype=float)


def reverse_complement(seq: str) -> str:
    """Reverse-complement a DNA sequence (display-only handle sequence)."""
    from backend.core.sequences import complement_base
    return "".join(complement_base(b) for b in reversed(seq))


def azide_attach_end(
    nucs: list[dict], overhang_id: str, binder_strand_id: str, azide_end: str = "5p",
) -> str:
    """Which overhang end (``"free_end"`` | ``"root"``) the protein should anchor
    to so its conjugation atom coincides with the binder's azide terminus.

    The binder hybridizes the overhang antiparallel over the same bp range, so
    its 5′/3′ termini are co-located with the overhang's two ends — but *which*
    physical end (free tip vs bundle root) the 5′ (or 3′) terminus sits at depends
    on the overhang's polarity.  Rather than reason about that convention, we
    compare the binder terminus position to both overhang-end positions and pick
    the nearer one (geometric, convention-free).  ``azide_end`` is ``"5p"`` or
    ``"3p"``.  Falls back to ``"free_end"`` when geometry is unavailable.
    """
    want_5p = azide_end == "5p"
    term = None
    for n in nucs:
        if n.get("strand_id") != binder_strand_id:
            continue
        if (want_5p and n.get("is_five_prime")) or (not want_5p and n.get("is_three_prime")):
            term = n
            break
    free_tip, _ = resolve_overhang_anchor(nucs, overhang_id, "free_end")
    root_tip, _ = resolve_overhang_anchor(nucs, overhang_id, "root")
    if term is None or free_tip is None or root_tip is None:
        return "free_end"
    p = term.get("backbone_position") or term.get("base_position")
    if p is None:
        return "free_end"
    p = np.asarray(p, dtype=float)
    d_free = float(np.linalg.norm(p - free_tip))
    d_root = float(np.linalg.norm(p - root_tip))
    return "free_end" if d_free <= d_root else "root"
