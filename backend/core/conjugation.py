"""Protein–ssDNA conjugation site analysis (display / planning layer only).

Finds the residues on an imported protein that are viable attachment points for
an **azide-modified oligonucleotide**.  Chemistry: azide-oligos do not react with
native side chains; the standard route is two-step copper-free click (SPAAC) — a
strained cyclooctyne (DBCO/BCN) is installed on the protein, then the azide-oligo
clicks onto it.  The cyclooctyne is installed at:

* lysine ε-amines      (NHS-ester chemistry)   → functional atom ``NZ``
* cysteine thiols       (maleimide chemistry)   → functional atom ``SG``
* the N-terminal α-amine                        → backbone ``N`` of the first residue

So the candidate sites are the *surface-accessible* Lys / Cys / N-termini.  We
score solvent accessibility with a compact, deterministic Shrake–Rupley
rolling-probe and keep only residues whose functional atom is exposed.

Pure geometry over a :class:`ProteinAsset`; no FastAPI, no topology mutation.
Coordinates are the asset's own local/PDB frame (nm), matching the
``?asset_id=`` atomistic preview render.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from typing import Iterable

import numpy as np

from backend.core.atomistic import DEFAULT_VDW_RADIUS, VDW_RADIUS
from backend.core.models import ProteinAsset
from backend.core.protein import protein_asset_fingerprint

# Solvent probe radius (water), nm.  1.4 Å.
PROBE_RADIUS: float = 0.14

# Chemistry → (residue name, functional atom name, human label).
_CHEMISTRY = {
    "lys": ("LYS", "NZ", "ε-amine"),
    "cys": ("CYS", "SG", "thiol"),
    # N-terminus is handled specially (first residue of each chain, backbone N).
}
_NTERM_ATOM = "N"


def _sphere_points(n: int = 96) -> np.ndarray:
    """``n`` roughly-even points on the unit sphere (deterministic Fibonacci spiral)."""
    pts = np.empty((n, 3), dtype=float)
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        z = 1.0 - (2.0 * i + 1.0) / n
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = golden * i
        pts[i] = (r * math.cos(theta), r * math.sin(theta), z)
    return pts


# Cache the deterministic point set so repeated calls don't rebuild it.
_SPHERE = _sphere_points(96)
_CANDIDATE_CACHE_MAX = 16
_candidate_cache: OrderedDict[str, tuple[dict, ...]] = OrderedDict()
_candidate_cache_lock = threading.Lock()


def atom_sasa(asset: ProteinAsset, *, n_points: int = 96) -> dict[int, float]:
    """Per-atom solvent-accessible *fraction* in ``[0, 1]`` keyed by atom serial.

    Shrake–Rupley: roll a probe sphere over each atom; the accessible fraction is
    the share of test points (placed on the atom's expanded sphere of radius
    ``vdw + probe``) that fall outside every *other* atom's expanded sphere.
    Heavy atoms only (hydrogens are usually absent from these assets and would
    bias the surface).  Deterministic — the point set is fixed.
    """
    heavy = [a for a in asset.atoms if a.element.upper() != "H"]
    if not heavy:
        return {}

    coords = np.array([[a.x, a.y, a.z] for a in heavy], dtype=float)
    radii = np.array(
        [VDW_RADIUS.get(a.element, DEFAULT_VDW_RADIUS) + PROBE_RADIUS for a in heavy],
        dtype=float,
    )
    serials = [a.serial for a in heavy]
    sphere = _SPHERE if n_points == 96 else _sphere_points(n_points)

    # Neighbour radius: two atoms can only occlude each other if their expanded
    # spheres overlap, i.e. within (r_i + r_j).  Use the max radius as a bound.
    rmax = float(radii.max())

    out: dict[int, float] = {}
    for i in range(len(heavy)):
        ci, ri = coords[i], radii[i]
        # Candidate occluders: atoms whose centre is within ri + rj of this atom.
        d = np.linalg.norm(coords - ci, axis=1)
        near = np.where((d > 0) & (d < (ri + rmax)))[0]
        if near.size == 0:
            out[serials[i]] = 1.0
            continue
        near_c = coords[near]
        near_r2 = radii[near] ** 2
        test = ci + sphere * ri  # (n_points, 3)
        accessible = 0
        for p in test:
            diff = near_c - p
            sq = np.einsum("ij,ij->i", diff, diff)
            if not np.any(sq < near_r2):
                accessible += 1
        out[serials[i]] = accessible / len(test)
    return out


def atom_accessible_fraction(
    asset: ProteinAsset, serial: int, *, n_points: int = 96
) -> float | None:
    """Compute SASA fraction for one atom without auditing the whole protein."""
    heavy = [a for a in asset.atoms if a.element.upper() != "H"]
    target_index = next((i for i, atom in enumerate(heavy) if atom.serial == serial), None)
    if target_index is None:
        return None
    coords = np.array([[a.x, a.y, a.z] for a in heavy], dtype=float)
    radii = np.array(
        [VDW_RADIUS.get(a.element, DEFAULT_VDW_RADIUS) + PROBE_RADIUS for a in heavy],
        dtype=float,
    )
    ci, ri = coords[target_index], radii[target_index]
    d = np.linalg.norm(coords - ci, axis=1)
    near = np.where((d > 0) & (d < (ri + float(radii.max()))))[0]
    if near.size == 0:
        return 1.0
    sphere = _SPHERE if n_points == 96 else _sphere_points(n_points)
    test = ci + sphere * ri
    near_c = coords[near]
    near_r2 = radii[near] ** 2
    accessible = sum(
        not np.any(np.einsum("ij,ij->i", near_c - point, near_c - point) < near_r2)
        for point in test
    )
    return accessible / len(test)


def _nterm_residues(asset: ProteinAsset) -> set[tuple[str, int]]:
    """(chain_id, res_seq) of the first residue in each chain (lowest res_seq)."""
    first: dict[str, int] = {}
    for a in asset.atoms:
        cur = first.get(a.chain_id)
        if cur is None or a.res_seq < cur:
            first[a.chain_id] = a.res_seq
    return {(c, s) for c, s in first.items()}


def conjugation_candidate_for_serial(
    asset: ProteinAsset, serial: int, *, min_accessible: float = 0.1
) -> dict | None:
    """Validate and score one selected conjugation atom in O(atom-count) work."""
    atom = next((a for a in asset.atoms if a.serial == serial), None)
    if atom is None:
        return None
    chemistry = None
    for key in ("lys", "cys"):
        res_name, atom_name, _ = _CHEMISTRY[key]
        if atom.res_name == res_name and atom.name == atom_name:
            chemistry = key
            break
    if chemistry is None and atom.name == _NTERM_ATOM:
        if (atom.chain_id, atom.res_seq) in _nterm_residues(asset):
            chemistry = "nterm"
    if chemistry is None:
        return None
    accessible = atom_accessible_fraction(asset, serial)
    if accessible is None or accessible < min_accessible:
        return None
    return {
        "res_name": atom.res_name,
        "chain_id": atom.chain_id,
        "res_seq": atom.res_seq,
        "chemistry": chemistry,
        "functional_atom_serial": atom.serial,
        "x": atom.x,
        "y": atom.y,
        "z": atom.z,
        "accessible": round(accessible, 4),
    }


def find_conjugation_candidates(
    asset: ProteinAsset,
    *,
    chemistries: Iterable[str] = ("lys", "cys", "nterm"),
    min_accessible: float = 0.1,
) -> list[dict]:
    """Surface-accessible azide-oligo conjugation sites on ``asset``.

    Returns one dict per accepted site::

        {res_name, chain_id, res_seq, chemistry, functional_atom_serial,
         x, y, z, accessible}

    where ``chemistry`` ∈ {"lys", "cys", "nterm"} and (x, y, z) is the functional
    atom's position in the asset's local frame (nm).  Only sites whose functional
    atom has an accessible fraction ≥ ``min_accessible`` are returned.
    """
    chemistries = set(chemistries)
    sasa = atom_sasa(asset)
    nterms = _nterm_residues(asset) if "nterm" in chemistries else set()
    candidates: list[dict] = []

    for a in asset.atoms:
        chem: str | None = None
        # Side-chain chemistries take priority; the N-terminus is a backbone atom.
        for key in ("lys", "cys"):
            if key not in chemistries:
                continue
            res_name, atom_name, _ = _CHEMISTRY[key]
            if a.res_name == res_name and a.name == atom_name:
                chem = key
                break
        if chem is None and "nterm" in chemistries:
            if a.name == _NTERM_ATOM and (a.chain_id, a.res_seq) in nterms:
                chem = "nterm"
        if chem is None:
            continue

        acc = sasa.get(a.serial, 1.0)
        if acc < min_accessible:
            continue
        candidates.append(
            {
                "res_name": a.res_name,
                "chain_id": a.chain_id,
                "res_seq": a.res_seq,
                "chemistry": chem,
                "functional_atom_serial": a.serial,
                "x": a.x,
                "y": a.y,
                "z": a.z,
                "accessible": round(acc, 4),
            }
        )
    # Highest-confidence surface sites first; stable biochemical/identity ties
    # make reopening the manager deterministic across runs and machines.
    candidates.sort(
        key=lambda item: (
            -float(item["accessible"]),
            item["chemistry"],
            item["chain_id"],
            int(item["res_seq"]),
            int(item["functional_atom_serial"]),
        )
    )
    return candidates


def find_conjugation_candidates_cached(asset: ProteinAsset) -> tuple[list[dict], bool]:
    """Return default candidate analysis plus whether it came from the bounded cache."""
    fingerprint = asset.metadata.get("structure_fingerprint") or protein_asset_fingerprint(asset)
    with _candidate_cache_lock:
        cached = _candidate_cache.get(fingerprint)
        if cached is not None:
            _candidate_cache.move_to_end(fingerprint)
            return [dict(item) for item in cached], True
    candidates = find_conjugation_candidates(asset)
    frozen = tuple(dict(item) for item in candidates)
    with _candidate_cache_lock:
        _candidate_cache[fingerprint] = frozen
        _candidate_cache.move_to_end(fingerprint)
        while len(_candidate_cache) > _CANDIDATE_CACHE_MAX:
            _candidate_cache.popitem(last=False)
    return [dict(item) for item in frozen], False


def clear_conjugation_candidate_cache() -> None:
    """Clear the bounded analysis cache (session teardown/tests)."""
    with _candidate_cache_lock:
        _candidate_cache.clear()
