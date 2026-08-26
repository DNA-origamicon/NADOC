"""Coarse-grained (ANM) representation of an imported protein for oxDNA.

Pure geometry over a :class:`ProteinAsset`: collapses the all-atom structure to
**one bead per residue** at the Cα (alpha-carbon), and builds an **anisotropic
network model (ANM)** — beads connected by harmonic springs between every pair
within a cutoff. This is the protein side of upstream oxDNA's ``DNANM`` hybrid
model (Procyk/Šulc, Soft Matter 2021): DNA↔protein interaction is excluded-volume
only, so a *stiff* network behaves as a near-rigid body with a real shape
envelope.

No FastAPI, no oxDNA-format I/O, no topology mutation — coordinates are nm.  The
oxDNA-format writers (topology/conf/.par) and unit conversion live in
``backend/physics/oxdna_protein.py``.  World placement reuses the SAME transform
as the renderer (``compose_protein_world_transform``) so the simulated protein
sits exactly where the user sees it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.core.models import ProteinAsset
from backend.core.protein import compose_protein_world_transform

# ── ANM defaults (tunable) ────────────────────────────────────────────────────
# Cutoff for the spring network.  12–18 Å is the standard ANM range; the
# ANM-oxDNA ANMUtils default is 15 Å.
ANM_CUTOFF_NM: float = 1.5
# Uniform spring constant (oxDNA energy units).  The ANM-oxDNA examples fit
# per-spring constants to crystallographic B-factors (~7 for realistic
# fluctuations); for a near-rigid body we use a single *stiff* value.  Tunable.
ANM_SPRING_K_STIFF: float = 50.0

# Residue 3-letter → 1-letter (the 20 canonical + common protonation/selenium
# variants we keep in parse_protein_pdb).  Unknown residues fall back to 'G'
# (glycine — small, neutral) so the topology always has a valid amino-acid code.
AA_3TO1: dict[str, str] = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "SEC": "C",
    "PYL": "K",
    "MSE": "M",
    "HSD": "H",
    "HSE": "H",
    "HSP": "H",
    "HID": "H",
    "HIE": "H",
    "HIP": "H",
    "CYX": "C",
    "CYM": "C",
    "ASH": "D",
    "GLH": "E",
    "LYN": "K",
    "ARN": "R",
}


def aa_one_letter(res_name: str) -> str:
    """1-letter code for a residue name; 'G' fallback for anything unknown."""
    return AA_3TO1.get(res_name.upper(), "G")


@dataclass
class ProteinBead:
    """One coarse-grained protein bead (residue), placed in WORLD nm."""

    index: int  # 0-based order within this attachment's protein
    aa: str  # 1-letter amino-acid code
    chain_id: str
    res_seq: int
    pos_nm: np.ndarray  # world position (nm)
    prev_index: int  # backbone-previous bead in the SAME chain, else -1
    is_conjugation: bool = False  # True for the residue carrying the conj atom


def _residue_groups(asset: ProteinAsset) -> list[tuple[str, int, str, list]]:
    """Residues in PDB order: (chain_id, res_seq, res_name, [atoms]).

    Order = first appearance of each (chain_id, res_seq) in ``asset.atoms``,
    which preserves chain blocks and ascending residue order from the PDB.
    """
    groups: dict[tuple[str, int], list] = {}
    order: list[tuple[str, int]] = []
    names: dict[tuple[str, int], str] = {}
    for a in asset.atoms:
        key = (a.chain_id, a.res_seq)
        if key not in groups:
            groups[key] = []
            order.append(key)
            names[key] = a.res_name
        groups[key].append(a)
    return [(c, s, names[(c, s)], groups[(c, s)]) for (c, s) in order]


def _bead_local_pos(atoms: list) -> np.ndarray:
    """Local (asset-frame) bead position: the Cα if present, else the residue's
    heavy-atom centroid (fallback for residues missing a CA)."""
    ca = next((a for a in atoms if a.name.strip() == "CA"), None)
    if ca is not None:
        return np.array([ca.x, ca.y, ca.z], dtype=float)
    heavy = [a for a in atoms if a.element.upper() != "H"] or atoms
    return np.mean([[a.x, a.y, a.z] for a in heavy], axis=0)


def _conjugation_res_key(asset: ProteinAsset, attachment) -> tuple[str, int] | None:
    """(chain_id, res_seq) of the residue carrying the conjugation atom, or None."""
    serial = (
        getattr(attachment, "conjugation_atom_serial", None) if attachment else None
    )
    if serial is None:
        serial = asset.default_conjugation_atom_serial
    if serial is None:
        return None
    atom = next((a for a in asset.atoms if a.serial == serial), None)
    return (atom.chain_id, atom.res_seq) if atom is not None else None


def protein_beads(
    asset: ProteinAsset,
    attachment=None,
    *,
    tip: np.ndarray | None = None,
    outward: np.ndarray | None = None,
) -> list[ProteinBead]:
    """Per-residue Cα beads for ``asset`` in WORLD nm.

    The world transform is ``compose_protein_world_transform`` (``pose · base``) —
    the exact placement the renderer uses.  With ``attachment=None`` the beads stay
    at the asset's PDB coordinates (preview).  ``tip``/``outward`` are the overhang
    anchor (only used for an overhang-anchored attachment).
    """
    world = (
        compose_protein_world_transform(asset, attachment, tip, outward)
        if attachment is not None
        else np.eye(4)
    )
    conj_key = (
        _conjugation_res_key(asset, attachment) if attachment is not None else None
    )

    beads: list[ProteinBead] = []
    prev_chain: str | None = None
    for i, (chain_id, res_seq, res_name, atoms) in enumerate(_residue_groups(asset)):
        local = _bead_local_pos(atoms)
        w = world @ np.array([local[0], local[1], local[2], 1.0])
        prev_index = (
            i - 1 if (prev_chain is not None and prev_chain == chain_id) else -1
        )
        beads.append(
            ProteinBead(
                index=i,
                aa=aa_one_letter(res_name),
                chain_id=chain_id,
                res_seq=res_seq,
                pos_nm=np.array([w[0], w[1], w[2]], dtype=float),
                prev_index=prev_index,
                is_conjugation=(
                    conj_key is not None and (chain_id, res_seq) == conj_key
                ),
            )
        )
        prev_chain = chain_id
    return beads


def conjugation_bead_index(beads: list[ProteinBead]) -> int | None:
    """Index of the bead carrying the conjugation atom, or None if unset."""
    return next((b.index for b in beads if b.is_conjugation), None)


@dataclass
class AnmSpring:
    """One ANM spring between two beads (indices local to the attachment)."""

    i: int
    j: int  # always j > i
    r0_nm: float  # equilibrium length (nm)


def anm_springs(
    beads: list[ProteinBead],
    cutoff_nm: float = ANM_CUTOFF_NM,
) -> list[AnmSpring]:
    """Every bead pair within ``cutoff_nm`` → a spring at its current separation.

    Returns springs with ``i < j`` (each undirected spring once), sorted by
    ``(i, j)``.  Consecutive-in-chain residues (~0.38 nm apart) are always inside
    the cutoff, so the peptide backbone is covered without a special case.
    """
    n = len(beads)
    if n < 2:
        return []
    pos = np.array([b.pos_nm for b in beads])
    cutoff_sq = cutoff_nm * cutoff_nm
    out: list[AnmSpring] = []
    for i in range(n):
        d = pos[i + 1 :] - pos[i]
        sq = np.einsum("ij,ij->i", d, d)
        for off, s in enumerate(sq):
            if s <= cutoff_sq:
                out.append(AnmSpring(i=i, j=i + 1 + off, r0_nm=float(np.sqrt(s))))
    return out
