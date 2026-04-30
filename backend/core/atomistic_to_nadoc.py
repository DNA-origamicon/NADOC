"""
Mapping from GROMACS atomistic frames to NADOC bead/slab representations.

Build the chain map once from the design's AtomisticModel, then call one of the
extract_* functions for each frame.  All positions are in nm.

Typical usage
-------------
    model    = build_atomistic_model(design)
    chain_map = build_chain_map(model)

    # From the NADOC input PDB (chain letters preserved):
    pdb_text = Path("input_nadoc.pdb").read_text()
    beads    = extract_from_pdb(pdb_text, chain_map)

    # From a GROMACS GRO/XTC (no chain letters — index-based):
    p_order  = build_p_gro_order(pdb_text, chain_map)
    beads    = extract_from_gro(Path("em.gro"), p_order)

    # Compare to original design:
    stats    = compare_to_design(beads, design)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from backend.core.atomistic import AtomisticModel
    from backend.core.models import Design

# (chain_letter, seq_num_in_chain) → (helix_id, bp_index, direction_str)
ChainMap = dict[tuple[str, int], tuple[str, int, str]]

# Ordered list of (helix_id, bp_index, direction) for GRO index mapping
PAtomOrder = list[tuple[str, int, str]]

_GRO_DNA_RESNAMES = frozenset({
    "DA", "DT", "DC", "DG",
    "DA3", "DA5", "DT3", "DT5", "DC3", "DC5", "DG3", "DG5",
})


@dataclass(frozen=True)
class BeadPosition:
    """P-atom backbone position mapped to a NADOC nucleotide."""
    helix_id: str
    bp_index: int
    direction: str  # "FORWARD" | "REVERSE"
    pos: np.ndarray  # nm, shape (3,)


@dataclass
class ComparisonResult:
    n_matched: int
    global_rmsd_nm: float
    per_helix_rmsd_nm: dict[str, float]   # helix_id → RMSD
    max_deviation_nm: float
    n_missing: int                         # keys in beads but not in reference


# ── Chain map ─────────────────────────────────────────────────────────────────


def build_chain_map(model: "AtomisticModel") -> ChainMap:
    """
    Build (chain_letter, seq_num) → (helix_id, bp_index, direction) from P atoms.

    chain_letter and seq_num match the PDB written by NADOC's atomistic model —
    the same file that pdb2gmx consumes.  5'-terminal P atoms are included here;
    they are filtered by build_p_gro_order when reading GROMACS output.
    """
    chain_map: ChainMap = {}
    for atom in model.atoms:
        if atom.name == "P":
            key = (atom.chain_id, atom.seq_num)
            chain_map[key] = (atom.helix_id, atom.bp_index, atom.direction)
    return chain_map


# ── PDB extraction (chain letters preserved) ──────────────────────────────────


def extract_from_pdb(pdb_text: str, chain_map: ChainMap) -> list[BeadPosition]:
    """
    Extract P-atom positions from PDB text and map to NADOC bead positions.

    Positions are converted from Å (PDB) to nm.  Only atoms whose
    (chain_id, seq_num) appear in chain_map are returned; solvent and ions
    are ignored automatically because they have no P atoms in the map.
    """
    beads: list[BeadPosition] = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54:
            continue
        if line[12:16].strip() != "P":
            continue
        chain_id = line[21]
        seq_num  = int(line[22:26])
        entry    = chain_map.get((chain_id, seq_num))
        if entry is None:
            continue
        helix_id, bp_index, direction = entry
        pos = np.array([
            float(line[30:38]) / 10.0,
            float(line[38:46]) / 10.0,
            float(line[46:54]) / 10.0,
        ])
        beads.append(BeadPosition(helix_id, bp_index, direction, pos))
    return beads


# ── GRO / XTC extraction (index-based, no chain letters) ─────────────────────


def build_p_gro_order(pdb_text: str, chain_map: ChainMap) -> PAtomOrder:
    """
    Build the ordered (helix_id, bp_index, direction) list matching GROMACS DNA P atoms.

    pdb2gmx strips the 5'-terminal P from the first residue of every chain block.
    This function walks the NADOC input PDB in file order, skips those terminals,
    and returns a list whose index i corresponds to the i-th DNA P atom in any
    downstream GROMACS file (GRO, XTC, TRR).

    Parameters
    ----------
    pdb_text   : text of the NADOC input PDB (input_nadoc.pdb)
    chain_map  : from build_chain_map()
    """
    # Detect first residue of each contiguous chain block (one P stripped each).
    block_starts: set[tuple[str, int]] = set()
    prev_chain: str | None = None
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            chain  = line[21]
            resnum = int(line[22:26])
            if chain != prev_chain:
                block_starts.add((chain, resnum))
                prev_chain = chain

    # Walk P atoms in PDB file order, skip 5'-terminal entries.
    order: PAtomOrder = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 26:
            continue
        if line[12:16].strip() != "P":
            continue
        chain_id = line[21]
        seq_num  = int(line[22:26])
        if (chain_id, seq_num) in block_starts:
            continue  # 5'-terminal P stripped by pdb2gmx
        entry = chain_map.get((chain_id, seq_num))
        if entry is not None:
            order.append(entry)
    return order


def extract_from_gro(
    gro_path: Path,
    p_order: PAtomOrder,
    frame: int = 0,
) -> list[BeadPosition]:
    """
    Extract P-atom positions from a GROMACS GRO file and map to NADOC beads.

    GRO files carry no chain information, so mapping is purely by index order:
    the i-th DNA P atom in the GRO corresponds to p_order[i].

    For multi-frame trajectories (XTC/TRR) use extract_from_xtc().
    """
    try:
        import MDAnalysis as mda
        u = mda.Universe(str(gro_path))
        return _extract_universe(u, frame, p_order)
    except ImportError:
        pass

    # Pure-Python fallback for single-frame GRO files.
    p_pos = _parse_gro_p_positions(gro_path)
    return _map_positions(p_pos, p_order)


def extract_from_xtc(
    topology_gro: Path,
    xtc_path: Path,
    p_order: PAtomOrder,
    frame: int = 0,
) -> list[BeadPosition]:
    """
    Extract P-atom positions from an XTC trajectory frame.

    Requires MDAnalysis.  topology_gro is a single-frame GRO (e.g. em.gro)
    used to define the atom topology.
    """
    import MDAnalysis as mda
    u = mda.Universe(str(topology_gro), str(xtc_path))
    return _extract_universe(u, frame, p_order)


_P_BACKBONE_MAX_NM: float = 1.0  # maximum realistic intra-strand P-P distance (nm)


def _unwrap_min_image(positions: np.ndarray, box_nm: np.ndarray) -> np.ndarray:
    """
    Sequential minimum-image unwrapping along the p_order sequence.

    GROMACS wraps all atoms into the primary unit cell, splitting strands that
    cross a periodic boundary.  Consecutive backbone P atoms are ~0.6 nm apart
    (always < half a box length for any reasonable DNA nanostructure box), so
    applying the nearest-image convention between adjacent entries in p_order
    makes each strand whole without needing explicit bond data.

    Strand boundaries (where consecutive p_order entries belong to different
    chains) are detected by the minimum-image distance: if the nearest-image
    distance after correction still exceeds _P_BACKBONE_MAX_NM, the pair is
    treated as a strand boundary and no shift is applied.  This prevents a
    wrongly-placed strand from displacing all subsequent atoms.
    """
    out = positions.copy()
    for i in range(1, len(out)):
        delta = out[i] - out[i - 1]
        for d in range(3):
            if box_nm[d] > 0:
                delta[d] -= np.round(delta[d] / box_nm[d]) * box_nm[d]
        # Only apply the shift for genuine backbone bonds (intra-strand).
        if np.linalg.norm(delta) <= _P_BACKBONE_MAX_NM:
            out[i] = out[i - 1] + delta
    return out


def _extract_universe(
    u: "mda.Universe",
    frame: int,
    p_order: PAtomOrder,
) -> list[BeadPosition]:
    import MDAnalysis as mda  # noqa: F401
    u.trajectory[frame]
    dna_p = u.select_atoms(
        "name P and resname " + " ".join(_GRO_DNA_RESNAMES)
    )
    if len(dna_p) != len(p_order):
        raise ValueError(
            f"Frame {frame}: {len(dna_p)} DNA P atoms in trajectory "
            f"but p_order has {len(p_order)} entries. "
            "Re-build p_order with the correct input PDB."
        )
    positions_nm = dna_p.positions / 10.0  # Å → nm

    # Apply minimum-image sequential unwrap so no P atom is split across a
    # periodic boundary.  Requires box dimensions from the trajectory frame.
    dims = u.dimensions
    if dims is not None and dims[0] > 0:
        box_nm = dims[:3] / 10.0
        positions_nm = _unwrap_min_image(positions_nm, box_nm)

    return [
        BeadPosition(hid, bpi, d, positions_nm[i])
        for i, (hid, bpi, d) in enumerate(p_order)
    ]


def _parse_gro_p_positions(gro_path: Path) -> list[np.ndarray]:
    """Parse DNA P-atom positions (nm) from a single-frame GRO file."""
    positions: list[np.ndarray] = []
    lines = Path(gro_path).read_text().splitlines()
    for line in lines[2:]:  # skip title + atom-count lines
        if len(line) < 44:
            break  # reached box-vector line
        res_name  = line[5:10].strip()
        atom_name = line[10:15].strip()
        if atom_name == "P" and res_name in _GRO_DNA_RESNAMES:
            try:
                x = float(line[20:28])
                y = float(line[28:36])
                z = float(line[36:44])
                positions.append(np.array([x, y, z]))
            except ValueError:
                continue
    return positions


def _map_positions(
    p_positions: list[np.ndarray],
    p_order: PAtomOrder,
) -> list[BeadPosition]:
    if len(p_positions) != len(p_order):
        raise ValueError(
            f"{len(p_positions)} DNA P atoms found but p_order has {len(p_order)} entries."
        )
    return [
        BeadPosition(hid, bpi, d, pos)
        for (hid, bpi, d), pos in zip(p_order, p_positions)
    ]


# ── Comparison to reference ───────────────────────────────────────────────────


def compare_to_design(
    beads: list[BeadPosition],
    design: "Design",
    *,
    use_geometry_layer: bool = False,
    align_translation: bool = False,
) -> ComparisonResult:
    """
    Compare extracted P-atom positions to reference positions.

    use_geometry_layer=False (default):
        Reference = AtomisticModel P-atom positions (_ATOMISTIC_P_RADIUS ≈ 0.886 nm).
        Expected near-zero RMSD for input_nadoc.pdb; small RMSD for post-EM GRO.

    use_geometry_layer=True:
        Reference = nucleotide_positions() backbone (HELIX_RADIUS = 1.0 nm).
        Will show ~1.1 Å systematic radial offset because P atoms sit at 0.886 nm,
        not 1.0 nm.  Useful for understanding the coordinate-system offset.

    align_translation=True:
        Remove the centroid offset before computing RMSD.  Required when comparing
        GROMACS frames (box coordinate system) to NADOC world coordinates — GROMACS
        translates the structure into the periodic box, introducing a constant shift
        of ~6–7 nm with no rotation.
    """
    ref_map = _build_reference_map(design, use_geometry_layer)
    return _compute_comparison(beads, ref_map, align_translation=align_translation)


def centroid_offset(
    beads: list[BeadPosition],
    design: "Design",
    *,
    use_geometry_layer: bool = False,
) -> np.ndarray:
    """
    Compute the translation T = ref_centroid - bead_centroid.

    Apply as: bead.pos + T  to bring GROMACS-frame positions into NADOC world frame.
    GROMACS does not rotate the structure relative to the input PDB (only translation
    via editconf -c), so a pure centroid alignment is sufficient for visualisation.
    """
    ref_map = _build_reference_map(design, use_geometry_layer)
    bead_pts, ref_pts = [], []
    for bead in beads:
        key = (bead.helix_id, bead.bp_index, bead.direction)
        if key in ref_map:
            bead_pts.append(bead.pos)
            ref_pts.append(ref_map[key])
    if not bead_pts:
        return np.zeros(3)
    return np.mean(ref_pts, axis=0) - np.mean(bead_pts, axis=0)


def _build_reference_map(
    design: "Design",
    use_geometry_layer: bool,
) -> dict[tuple[str, int, str], np.ndarray]:
    if use_geometry_layer:
        from backend.core.geometry import nucleotide_positions
        ref: dict[tuple[str, int, str], np.ndarray] = {}
        for helix in design.helices:
            for nuc in nucleotide_positions(helix):
                key = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
                ref[key] = nuc.position
        return ref
    else:
        from backend.core.atomistic import build_atomistic_model
        model = build_atomistic_model(design)
        ref = {}
        for atom in model.atoms:
            if atom.name == "P":
                key = (atom.helix_id, atom.bp_index, atom.direction)
                ref[key] = np.array([atom.x, atom.y, atom.z])
        return ref


def _compute_comparison(
    beads: list[BeadPosition],
    ref_map: dict[tuple[str, int, str], np.ndarray],
    align_translation: bool = False,
) -> ComparisonResult:
    per_helix_devs: dict[str, list[float]] = {}
    all_devs: list[float] = []
    n_missing = 0

    # Compute centroid translation if requested (GROMACS box → NADOC world frame).
    translation = np.zeros(3)
    if align_translation:
        bead_pts, ref_pts = [], []
        for bead in beads:
            key = (bead.helix_id, bead.bp_index, bead.direction)
            if key in ref_map:
                bead_pts.append(bead.pos)
                ref_pts.append(ref_map[key])
        if bead_pts:
            translation = np.mean(ref_pts, axis=0) - np.mean(bead_pts, axis=0)

    for bead in beads:
        key = (bead.helix_id, bead.bp_index, bead.direction)
        ref_pos = ref_map.get(key)
        if ref_pos is None:
            n_missing += 1
            continue
        dev = float(np.linalg.norm(bead.pos + translation - ref_pos))
        all_devs.append(dev)
        per_helix_devs.setdefault(bead.helix_id, []).append(dev)

    per_helix_rmsd = {
        hid: float(np.sqrt(np.mean(np.array(devs) ** 2)))
        for hid, devs in per_helix_devs.items()
    }
    global_rmsd = float(np.sqrt(np.mean(np.array(all_devs) ** 2))) if all_devs else 0.0
    max_dev     = float(max(all_devs)) if all_devs else 0.0

    return ComparisonResult(
        n_matched        = len(all_devs),
        global_rmsd_nm   = global_rmsd,
        per_helix_rmsd_nm = per_helix_rmsd,
        max_deviation_nm = max_dev,
        n_missing        = n_missing,
    )
