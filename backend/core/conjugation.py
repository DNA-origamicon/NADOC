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
from scipy.spatial import cKDTree

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


def _sasa_for_indices(
    coords: np.ndarray,
    radii: np.ndarray,
    indices: Iterable[int],
    *,
    n_points: int = 96,
) -> dict[int, float]:
    """Vectorized Shrake–Rupley fractions for selected heavy-atom indices."""
    if len(coords) == 0:
        return {}
    sphere = _SPHERE if n_points == 96 else _sphere_points(n_points)
    tree = cKDTree(coords)
    rmax = float(radii.max())
    out: dict[int, float] = {}
    for raw_index in indices:
        i = int(raw_index)
        ci, ri = coords[i], radii[i]
        near = np.asarray(tree.query_ball_point(ci, ri + rmax), dtype=np.intp)
        near = near[near != i]
        if near.size == 0:
            out[i] = 1.0
            continue
        test = ci + sphere * ri
        # (surface points, nearby atoms, xyz).  Proteins have only a small local
        # neighbour set, so this removes the Python loop over all 96 points
        # without creating an atom-count-sized temporary array.
        delta = test[:, None, :] - coords[near][None, :, :]
        occluded = np.any(
            np.einsum("pni,pni->pn", delta, delta, optimize=True)
            < radii[near][None, :] ** 2,
            axis=1,
        )
        out[i] = float(np.count_nonzero(~occluded)) / len(test)
    return out


def _heavy_geometry(asset: ProteinAsset):
    heavy = [a for a in asset.atoms if a.element.upper() != "H"]
    coords = np.array([[a.x, a.y, a.z] for a in heavy], dtype=float)
    radii = np.array(
        [VDW_RADIUS.get(a.element, DEFAULT_VDW_RADIUS) + PROBE_RADIUS for a in heavy],
        dtype=float,
    )
    return heavy, coords, radii


def atom_sasa(asset: ProteinAsset, *, n_points: int = 96) -> dict[int, float]:
    """Per-atom solvent-accessible *fraction* in ``[0, 1]`` keyed by atom serial.

    Shrake–Rupley: roll a probe sphere over each atom; the accessible fraction is
    the share of test points (placed on the atom's expanded sphere of radius
    ``vdw + probe``) that fall outside every *other* atom's expanded sphere.
    Heavy atoms only (hydrogens are usually absent from these assets and would
    bias the surface).  Deterministic — the point set is fixed.
    """
    heavy, coords, radii = _heavy_geometry(asset)
    if not heavy:
        return {}
    fractions = _sasa_for_indices(
        coords, radii, range(len(heavy)), n_points=n_points
    )
    return {heavy[i].serial: fraction for i, fraction in fractions.items()}


def atom_accessible_fraction(
    asset: ProteinAsset, serial: int, *, n_points: int = 96
) -> float | None:
    """Compute SASA fraction for one atom without auditing the whole protein."""
    heavy, coords, radii = _heavy_geometry(asset)
    target_index = next((i for i, atom in enumerate(heavy) if atom.serial == serial), None)
    if target_index is None:
        return None
    return _sasa_for_indices(
        coords, radii, [target_index], n_points=n_points
    )[target_index]


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
    nterms = _nterm_residues(asset) if "nterm" in chemistries else set()
    heavy, coords, radii = _heavy_geometry(asset)
    heavy_index = {a.serial: i for i, a in enumerate(heavy)}
    eligible = []
    eligible_chemistry: dict[int, str] = {}
    for a in asset.atoms:
        chem = next(
            (
                key
                for key in ("lys", "cys")
                if key in chemistries
                and a.res_name == _CHEMISTRY[key][0]
                and a.name == _CHEMISTRY[key][1]
            ),
            None,
        )
        if chem is None and "nterm" in chemistries:
            if a.name == _NTERM_ATOM and (a.chain_id, a.res_seq) in nterms:
                chem = "nterm"
        if chem is not None and a.serial in heavy_index:
            eligible.append(heavy_index[a.serial])
            eligible_chemistry[a.serial] = chem
    sasa_by_index = _sasa_for_indices(coords, radii, eligible)
    sasa = {heavy[i].serial: value for i, value in sasa_by_index.items()}
    candidates: list[dict] = []

    for a in asset.atoms:
        chem = eligible_chemistry.get(a.serial)
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
