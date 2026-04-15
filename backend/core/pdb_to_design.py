"""PDB DNA structure → NADOC Design converter.

Parses a PDB file containing DNA, identifies Watson-Crick paired duplexes,
and constructs a NADOC Design with helices, strands, and domains.
Non-DNA atoms (water, ions, protein) are silently removed.

The atomistic model uses the actual PDB atom coordinates (after rigid-body
alignment to the lattice frame) rather than NADOC's template-based positions.

Each imported PDB gets its own ClusterRigidTransform so the user can
translate/rotate it independently when merged with an existing design.
"""

from __future__ import annotations

import math
import uuid
from typing import Callable

import numpy as np

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.constants import BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD, HELIX_RADIUS
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.pdb_import import ATOM_ELEMENT, BASE_BONDS, SUGAR_BONDS

# ── Constants ──────────���─────────────────────────────────────────────────────

_DNA_RESNAME: dict[str, str] = {
    "DA": "A", "DT": "T", "DG": "G", "DC": "C",
    "A": "A", "T": "T", "G": "G", "C": "C", "U": "U",
    "ADE": "A", "THY": "T", "GUA": "G", "CYT": "C", "URA": "U",
}

_WC_COMPLEMENT: set[frozenset[str]] = {
    frozenset({"A", "T"}),
    frozenset({"G", "C"}),
    frozenset({"A", "U"}),
}

_WC_C1_DIST_MIN = 0.90  # nm
_WC_C1_DIST_MAX = 1.20  # nm


# ── Helpers ──────────────���──────────────────────────��────────────────────────


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _frame_from_axis(axis_hat: np.ndarray) -> np.ndarray:
    """Orthonormal frame with z-column = axis_hat.  Returns 3×3 [x, y, z]."""
    z = axis_hat
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(z, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    x = _norm(np.cross(ref, z))
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


# ── PDB text parser (self-contained, no file I/O) ────────────────────���──────

_WATER = {"HOH", "WAT", "H2O", "DOD", "D2O", "TIP3", "TIP4", "SPC"}
_IONS = {
    "NA", "CL", "MG", "ZN", "CA", "K", "MN", "FE", "CU", "CO", "NI",
    "BR", "IOD", "CS", "RB", "LI", "BA", "SR", "CD",
    "NA+", "CL-", "MG2", "K+",
}


class _Atom:
    __slots__ = ("name", "res_name", "chain_id", "res_seq", "pos", "element")

    def __init__(self, name: str, res_name: str, chain_id: str,
                 res_seq: int, pos: np.ndarray, element: str = ""):
        self.name = name
        self.res_name = res_name
        self.chain_id = chain_id
        self.res_seq = res_seq
        self.pos = pos
        self.element = element


class _Residue:
    __slots__ = ("chain_id", "res_seq", "res_name", "atoms")

    def __init__(self, chain_id: str, res_seq: int, res_name: str):
        self.chain_id = chain_id
        self.res_seq = res_seq
        self.res_name = res_name
        self.atoms: dict[str, _Atom] = {}

    def pos(self, atom_name: str) -> np.ndarray:
        return self.atoms[atom_name].pos

    def has(self, atom_name: str) -> bool:
        return atom_name in self.atoms


def _parse_dna_atoms(text: str) -> dict[tuple[str, int], _Residue]:
    """Parse PDB text, keep only DNA residues.  Coordinates in nm."""
    residues: dict[tuple[str, int], _Residue] = {}
    in_model = False

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

        res_name = line[17:20].strip()
        if res_name in _WATER or res_name in _IONS:
            continue
        if res_name not in _DNA_RESNAME:
            continue

        chain_id = line[21]
        res_seq = int(line[22:26])
        key = (chain_id, res_seq)
        atom_name = line[12:16].strip()
        pos = np.array([
            float(line[30:38]) / 10.0,
            float(line[38:46]) / 10.0,
            float(line[46:54]) / 10.0,
        ])
        element = line[76:78].strip() if len(line) >= 78 else ""

        if key not in residues:
            residues[key] = _Residue(chain_id, res_seq, res_name)
        residues[key].atoms[atom_name] = _Atom(
            atom_name, res_name, chain_id, res_seq, pos, element,
        )

    return residues


# ── Watson-Crick pair detection ────��─────────────────────────────────────────


def _detect_wc_pairs(
    dna_residues: dict[tuple[str, int], _Residue],
) -> list[tuple[tuple[str, int], tuple[str, int]]]:
    """Find Watson-Crick base pairs by C1'-C1' distance + complementarity.

    Uses antiparallel chain ordering: when two chains have ambiguous
    pairings (e.g. palindromic sequences), the algorithm enforces that
    chain A ascending resSeq pairs with chain B descending resSeq.
    """
    c1_pos: dict[tuple[str, int], np.ndarray] = {}
    for key, res in dna_residues.items():
        if res.has("C1'"):
            c1_pos[key] = res.pos("C1'")

    chains: dict[str, list[tuple[str, int]]] = {}
    for key in sorted(dna_residues):
        chains.setdefault(key[0], []).append(key)

    chain_ids = sorted(chains)
    pairs: list[tuple[tuple[str, int], tuple[str, int]]] = []
    used: set[tuple[str, int]] = set()

    for i, cid_a in enumerate(chain_ids):
        for cid_b in chain_ids[i + 1:]:
            # Try antiparallel assignment first: A ascending ↔ B descending.
            res_a = sorted(chains[cid_a], key=lambda k: k[1])
            res_b = sorted(chains[cid_b], key=lambda k: k[1], reverse=True)

            anti_pairs: list[tuple[tuple[str, int], tuple[str, int], float]] = []
            for ka, kb in zip(res_a, res_b):
                if ka in used or kb in used:
                    continue
                if ka not in c1_pos or kb not in c1_pos:
                    continue
                base_a = _DNA_RESNAME.get(dna_residues[ka].res_name)
                base_b = _DNA_RESNAME.get(dna_residues[kb].res_name)
                if base_a is None or base_b is None:
                    continue
                if frozenset({base_a, base_b}) not in _WC_COMPLEMENT:
                    continue
                dist = float(np.linalg.norm(c1_pos[ka] - c1_pos[kb]))
                if _WC_C1_DIST_MIN <= dist <= _WC_C1_DIST_MAX:
                    anti_pairs.append((ka, kb, dist))

            # Fall back to greedy nearest-neighbor if antiparallel found
            # fewer than half of the expected pairs.
            expected = min(len(res_a), len(res_b))
            if len(anti_pairs) >= expected * 0.5:
                for ka, kb, _ in anti_pairs:
                    pairs.append((ka, kb))
                    used.add(ka)
                    used.add(kb)
            else:
                # Greedy fallback for unusual topologies.
                for key_a in chains[cid_a]:
                    if key_a in used or key_a not in c1_pos:
                        continue
                    base_a = _DNA_RESNAME.get(dna_residues[key_a].res_name)
                    if base_a is None:
                        continue
                    best_dist = float("inf")
                    best_key: tuple[str, int] | None = None
                    for key_b in chains[cid_b]:
                        if key_b in used or key_b not in c1_pos:
                            continue
                        base_b = _DNA_RESNAME.get(dna_residues[key_b].res_name)
                        if base_b is None:
                            continue
                        if frozenset({base_a, base_b}) not in _WC_COMPLEMENT:
                            continue
                        dist = float(np.linalg.norm(c1_pos[key_a] - c1_pos[key_b]))
                        if _WC_C1_DIST_MIN <= dist <= _WC_C1_DIST_MAX and dist < best_dist:
                            best_dist = dist
                            best_key = key_b
                    if best_key is not None:
                        pairs.append((key_a, best_key))
                        used.add(key_a)
                        used.add(best_key)

    return pairs


# ── Duplex segmentation ──────────────────────────────────���──────────────────


def _segment_duplexes(
    pairs: list[tuple[tuple[str, int], tuple[str, int]]],
) -> list[list[tuple[tuple[str, int], tuple[str, int]]]]:
    """Group WC pairs into consecutive duplex segments on chain A."""
    if not pairs:
        return []
    pairs = sorted(pairs, key=lambda p: (p[0][0], p[0][1]))
    duplexes: list[list[tuple[tuple[str, int], tuple[str, int]]]] = []
    current = [pairs[0]]
    for pair in pairs[1:]:
        prev = current[-1]
        same_chains = pair[0][0] == prev[0][0] and pair[1][0] == prev[1][0]
        consecutive = pair[0][1] == prev[0][1] + 1
        if same_chains and consecutive:
            current.append(pair)
        else:
            duplexes.append(current)
            current = [pair]
    duplexes.append(current)
    return duplexes


# ── Alignment helpers ────────────────────────────────────────────────────────


def _rotation_between(v_from: np.ndarray, v_to: np.ndarray) -> np.ndarray:
    """3x3 rotation matrix mapping unit vector *v_from* to *v_to* (Rodrigues)."""
    v_from, v_to = _norm(v_from), _norm(v_to)
    c = float(np.dot(v_from, v_to))
    if c > 1.0 - 1e-12:
        return np.eye(3)
    if c < -1.0 + 1e-12:
        perp = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(v_from, perp)) > 0.9:
            perp = np.array([0.0, 1.0, 0.0])
        axis = _norm(np.cross(v_from, perp))
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    axis = _norm(np.cross(v_from, v_to))
    s = math.sqrt(1.0 - c * c)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + s * K + (1.0 - c) * (K @ K)




# ── Per-duplex analysis (PDB space) ───���───────────────���─────────────────────

class _DuplexInfo:
    """Intermediate analysis of one duplex in PDB coordinate space."""
    __slots__ = (
        "n_bp", "axis_dir", "centroid", "t_min", "t_max",
        "fwd_keys", "rev_keys", "fwd_c1_0",
    )

    def __init__(self) -> None:
        self.n_bp = 0
        self.axis_dir = np.zeros(3)
        self.centroid = np.zeros(3)
        self.t_min = 0.0
        self.t_max = 0.0
        self.fwd_keys: list[tuple[str, int]] = []
        self.rev_keys: list[tuple[str, int]] = []
        self.fwd_c1_0 = np.zeros(3)


def _analyze_duplex_pdb(
    duplex: list[tuple[tuple[str, int], tuple[str, int]]],
    dna_residues: dict[tuple[str, int], _Residue],
    c1_pos: dict[tuple[str, int], np.ndarray],
) -> _DuplexInfo | None:
    """Analyze a single duplex in PDB space.  Returns None on failure."""
    info = _DuplexInfo()
    info.n_bp = len(duplex)

    midpoints = np.array([
        (c1_pos[pa] + c1_pos[pb]) / 2.0
        for pa, pb in duplex
        if pa in c1_pos and pb in c1_pos
    ])
    if len(midpoints) < 2:
        return None

    info.centroid = midpoints.mean(axis=0)
    _, _, Vt = np.linalg.svd(midpoints - info.centroid, full_matrices=False)
    info.axis_dir = _norm(Vt[0])
    if np.dot(info.axis_dir, midpoints[-1] - midpoints[0]) < 0:
        info.axis_dir = -info.axis_dir

    t_vals = np.array([(mp - info.centroid) @ info.axis_dir for mp in midpoints])
    info.t_min = float(t_vals.min())
    info.t_max = float(t_vals.max())

    first_a = dna_residues[duplex[0][0]]
    last_a = dna_residues[duplex[-1][0]]
    if first_a.has("C1'") and last_a.has("C1'"):
        chain_a_53 = _norm(last_a.pos("C1'") - first_a.pos("C1'"))
    else:
        chain_a_53 = info.axis_dir
    chain_a_is_fwd = np.dot(chain_a_53, info.axis_dir) > 0

    for pa, pb in duplex:
        if chain_a_is_fwd:
            info.fwd_keys.append(pa)
            info.rev_keys.append(pb)
        else:
            info.fwd_keys.append(pb)
            info.rev_keys.append(pa)

    info.fwd_c1_0 = c1_pos[info.fwd_keys[0]]
    return info


# ── Shared PDB analysis + alignment ��────────────────────────────────────────


class _PdbAnalysis:
    """Result of parsing + analysing a PDB file."""
    __slots__ = (
        "dna_residues", "duplex_infos", "xform", "warnings",
    )

    def __init__(self) -> None:
        self.dna_residues: dict[tuple[str, int], _Residue] = {}
        self.duplex_infos: list[tuple[int, _DuplexInfo]] = []
        self.xform: Callable[[np.ndarray], np.ndarray] = lambda p: p
        self.warnings: list[str] = []


def _analyze_pdb(content: str) -> _PdbAnalysis:
    """Parse PDB content, detect WC pairs, and analyse duplexes.

    Atom coordinates are preserved exactly as read from the PDB file —
    no rotation or translation is applied.  Helix axis positions and phase
    offsets are derived from the original PDB-space geometry.
    """
    result = _PdbAnalysis()
    warnings = result.warnings

    dna_residues = _parse_dna_atoms(content)
    if not dna_residues:
        raise ValueError("No DNA residues found in PDB file.")
    result.dna_residues = dna_residues

    wc_pairs = _detect_wc_pairs(dna_residues)
    if not wc_pairs:
        raise ValueError(
            "No Watson-Crick base pairs detected.  "
            "Ensure the PDB contains double-stranded DNA."
        )

    unpaired = len(dna_residues) - 2 * len(wc_pairs)
    if unpaired > 0:
        warnings.append(f"{unpaired} unpaired DNA residue(s) skipped.")

    duplexes = _segment_duplexes(wc_pairs)

    c1_pos: dict[tuple[str, int], np.ndarray] = {}
    for key, res in dna_residues.items():
        if res.has("C1'"):
            c1_pos[key] = res.pos("C1'")

    for dup_idx, duplex in enumerate(duplexes):
        if len(duplex) < 2:
            warnings.append(
                f"Skipping single-bp duplex between "
                f"{duplex[0][0][0]}:{duplex[0][0][1]} and "
                f"{duplex[0][1][0]}:{duplex[0][1][1]}."
            )
            continue
        info = _analyze_duplex_pdb(duplex, dna_residues, c1_pos)
        if info is None:
            warnings.append(f"Duplex {dup_idx}: insufficient C1' atoms for axis fit.")
            continue
        result.duplex_infos.append((dup_idx, info))

    if not result.duplex_infos:
        raise ValueError("No valid duplexes found (need >= 2 bp per duplex).")

    # Identity transform — atom positions are not modified.
    result.xform = lambda p: p

    return result


# ── Core converter ───────────────────────────────────────────────────────────


def import_pdb(
    content: str,
    cluster_name: str = "PDB Import",
) -> tuple[Design, AtomisticModel, list[str]]:
    """Convert PDB text containing DNA into a NADOC Design.

    Helices are placed at the positions and orientations found in the PDB file.
    Atom coordinates are preserved exactly — no alignment or rotation is applied.

    Returns ``(design, atomistic_model, warnings)``.

    The *atomistic_model* carries the actual PDB atom coordinates so the
    Three.js atomistic renderer shows the original crystallographic geometry.
    """
    analysis = _analyze_pdb(content)
    warnings = list(analysis.warnings)
    dna_residues = analysis.dna_residues
    xform = analysis.xform

    uid = uuid.uuid4().hex[:8]
    helices: list[Helix] = []
    strands: list[Strand] = []
    helix_ids: list[str] = []

    # Per-residue mapping: residue key → (helix_id, strand_id, bp_index, direction)
    res_mapping: dict[tuple[str, int], tuple[str, str, int, str]] = {}

    for dup_idx, info in analysis.duplex_infos:
        n_bp = info.n_bp

        ax_start_pdb = info.centroid + (info.t_min - BDNA_RISE_PER_BP * 0.5) * info.axis_dir
        ax_end_pdb = info.centroid + (info.t_max + BDNA_RISE_PER_BP * 0.5) * info.axis_dir
        ax_start = xform(ax_start_pdb)
        ax_end = xform(ax_end_pdb)

        a_dir = _norm(ax_end - ax_start)
        frame = _frame_from_axis(a_dir)

        fwd_c1 = xform(info.fwd_c1_0)
        bp0_axis = xform(info.centroid + info.t_min * info.axis_dir)
        radial = fwd_c1 - bp0_axis
        radial -= np.dot(radial, a_dir) * a_dir
        radial = _norm(radial)
        phase = math.atan2(
            float(np.dot(radial, frame[:, 1])),
            float(np.dot(radial, frame[:, 0])),
        )

        helix_id = f"pdb_{uid}_h{dup_idx}"
        helix = Helix(
            id=helix_id,
            axis_start=Vec3.from_array(ax_start),
            axis_end=Vec3.from_array(ax_end),
            phase_offset=phase,
            length_bp=n_bp,
            bp_start=0,
            direction=Direction.FORWARD,
            grid_pos=None,
        )
        helices.append(helix)
        helix_ids.append(helix_id)

        fwd_seq = "".join(
            _DNA_RESNAME.get(dna_residues[k].res_name, "N") for k in info.fwd_keys
        )
        rev_seq = "".join(
            _DNA_RESNAME.get(dna_residues[k].res_name, "N")
            for k in reversed(info.rev_keys)
        )

        fwd_strand_id = str(uuid.uuid4())
        rev_strand_id = str(uuid.uuid4())

        fwd_strand = Strand(
            id=fwd_strand_id,
            domains=[Domain(
                helix_id=helix_id,
                start_bp=0,
                end_bp=n_bp - 1,
                direction=Direction.FORWARD,
            )],
            strand_type=StrandType.SCAFFOLD if dup_idx == 0 else StrandType.STAPLE,
            sequence=fwd_seq,
            color="#0066CC",
        )
        rev_strand = Strand(
            id=rev_strand_id,
            domains=[Domain(
                helix_id=helix_id,
                start_bp=n_bp - 1,
                end_bp=0,
                direction=Direction.REVERSE,
            )],
            strand_type=StrandType.STAPLE,
            sequence=rev_seq,
            color="#CC0000",
        )
        strands.append(fwd_strand)
        strands.append(rev_strand)

        # Record per-residue mapping for the atomistic model.
        for bp_i, key in enumerate(info.fwd_keys):
            res_mapping[key] = (helix_id, fwd_strand_id, bp_i, "FORWARD")
        for bp_i, key in enumerate(info.rev_keys):
            res_mapping[key] = (helix_id, rev_strand_id, bp_i, "REVERSE")

    if not helices:
        raise ValueError("No valid duplexes found (need >= 2 bp per duplex).")

    # ── Build cluster + design ───────────────────────────────────────────
    cluster = ClusterRigidTransform(
        name=cluster_name,
        is_default=len(helices) > 0,
        helix_ids=helix_ids,
    )
    design = Design(
        helices=helices,
        strands=strands,
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name=cluster_name),
        cluster_transforms=[cluster],
    )

    # ── Build atomistic model from real PDB positions ────────────────────
    atomistic = _build_pdb_atomistic(dna_residues, res_mapping, xform)

    total_bp = sum(h.length_bp for h in helices)
    warnings.append(f"Imported {len(helices)} duplex(es), {total_bp} total bp.")

    return design, atomistic, warnings


# ── PDB atom → AtomisticModel ────────��───────────────────────────────────────


def _atom_element(atom: _Atom) -> str:
    """Resolve element for an atom (prefer PDB element column, fall back to lookup table)."""
    if atom.element:
        return atom.element
    return ATOM_ELEMENT.get(atom.name, atom.name[0])


def _build_pdb_atomistic(
    dna_residues: dict[tuple[str, int], _Residue],
    res_mapping: dict[tuple[str, int], tuple[str, str, int, str]],
    xform: Callable[[np.ndarray], np.ndarray],
) -> AtomisticModel:
    """Build an AtomisticModel using real PDB atom positions (after alignment).

    Only residues present in *res_mapping* (i.e. those that belong to a
    detected duplex) are included.  Atoms are transformed by *xform* to
    the aligned coordinate frame.
    """
    atoms: list[Atom] = []
    bonds: list[tuple[int, int]] = []

    # Assign chain letters: group strands in order encountered.
    strand_chain: dict[str, str] = {}
    chain_counter = 0
    for helix_id, strand_id, bp_i, direction in res_mapping.values():
        if strand_id not in strand_chain:
            strand_chain[strand_id] = chr(ord("A") + chain_counter % 26)
            chain_counter += 1

    # Sort residues so that each strand's residues appear in 5'→3' order
    # (the direction backbone O3'→P bonds actually connect).
    # FORWARD: increasing bp_index = 5'→3'.
    # REVERSE: decreasing bp_index = 5'→3' (high bp = 5' end).
    def _sort_key(k: tuple[str, int]) -> tuple[str, int]:
        _, strand_id, bp_index, direction = res_mapping[k]
        return (strand_id, bp_index if direction == "FORWARD" else -bp_index)

    sorted_keys = sorted(res_mapping.keys(), key=_sort_key)

    serial = 0
    seq_counter: dict[str, int] = {}  # per-chain residue numbering
    # Track O3' serial for backbone bonds: strand_id → last O3' serial
    last_o3_serial: dict[str, int] = {}

    for res_key in sorted_keys:
        res = dna_residues[res_key]
        helix_id, strand_id, bp_index, direction = res_mapping[res_key]
        chain_id = strand_chain[strand_id]

        seq_counter.setdefault(chain_id, 0)
        seq_counter[chain_id] += 1
        seq_num = seq_counter[chain_id]

        # Index: atom_name → serial for intra-residue bonds.
        atom_serials: dict[str, int] = {}

        for atom_name, pdb_atom in res.atoms.items():
            p = xform(pdb_atom.pos)
            elem = _atom_element(pdb_atom)
            atoms.append(Atom(
                serial=serial,
                name=atom_name,
                element=elem,
                residue=res.res_name,
                chain_id=chain_id,
                seq_num=seq_num,
                x=float(p[0]),
                y=float(p[1]),
                z=float(p[2]),
                strand_id=strand_id,
                helix_id=helix_id,
                bp_index=bp_index,
                direction=direction,
            ))
            atom_serials[atom_name] = serial
            serial += 1

        # Intra-residue bonds (sugar + base).
        all_bonds = list(SUGAR_BONDS)
        if res.res_name in BASE_BONDS:
            all_bonds.extend(BASE_BONDS[res.res_name])
        for a1, a2 in all_bonds:
            s1 = atom_serials.get(a1)
            s2 = atom_serials.get(a2)
            if s1 is not None and s2 is not None:
                bonds.append((s1, s2))

        # Backbone bond: previous residue's O3' → this residue's P.
        p_serial = atom_serials.get("P")
        if p_serial is not None and strand_id in last_o3_serial:
            bonds.append((last_o3_serial[strand_id], p_serial))

        o3_serial = atom_serials.get("O3'")
        if o3_serial is not None:
            last_o3_serial[strand_id] = o3_serial

    return AtomisticModel(atoms=atoms, bonds=bonds)


# ── Public helpers ────────────────��──────────────────────────────────────────


def merge_pdb_into_design(
    existing: Design,
    content: str,
    cluster_name: str = "PDB Import",
) -> tuple[Design, AtomisticModel, list[str]]:
    """Import a PDB and merge its helices/strands into *existing* as a new cluster.

    Returns ``(merged_design, atomistic_model, warnings)``.
    """
    pdb_design, atomistic, warnings = import_pdb(content, cluster_name=cluster_name)

    merged = existing.copy_with(
        helices=list(existing.helices) + list(pdb_design.helices),
        strands=list(existing.strands) + list(pdb_design.strands),
        cluster_transforms=list(existing.cluster_transforms) + list(pdb_design.cluster_transforms),
    )
    return merged, atomistic, warnings
