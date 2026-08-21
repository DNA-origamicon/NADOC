"""Pool extra-base positions across reciprocal Holliday-junction crossover sides.

The trajectory probe already expresses every inserted nucleotide in one canonical
helix-pair frame: +x points from the lexicographically lower helix id to the higher,
+y follows their average helical axis, and +z completes the right-handed frame.  This
module uses that common frame to compare positions from otherwise unrelated junctions.

Only reciprocal crossover pairs one base-pair level apart are Holliday-junction sides
for this analysis.  The lower level is ``i``/left and the higher level is
``i+1``/right.  Unpaired crossover inserts are reported but never silently mixed into
either ensemble.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from backend.core.atomistic import BASE_TEMPLATES, _SUGAR, _SUGAR_BONDS
from backend.core.junction_topology import crossover_connectors, reciprocal_pairs
from backend.core.models import Design
from backend.core.occupancy_core import occupancy_clusters

POSITION_KEYS = ("g_ih_c1", "g_ax_c1", "g_pp_c1")


def reciprocal_crossover_sides(design: Design) -> dict[str, dict]:
    """Map crossover ids to the non-overlapping ``i``/``i+1`` HJ pairs they occupy."""
    connectors = crossover_connectors(design)
    candidates = []
    for index_a, index_b in reciprocal_pairs(connectors):
        a, b = connectors[index_a], connectors[index_b]
        if not a.crossover_id or not b.crossover_id:
            continue
        # An immobile two-crossover Holliday junction uses adjacent base-pair levels.
        if abs(a.from_bp - b.from_bp) != 1:
            continue
        candidates.append(
            (
                abs(a.from_bp - b.from_bp),
                min(a.from_bp, b.from_bp),
                str(a.crossover_id),
                str(b.crossover_id),
                index_a,
                index_b,
            )
        )

    used: set[int] = set()
    sides: dict[str, dict] = {}
    for *_, index_a, index_b in sorted(candidates):
        if index_a in used or index_b in used:
            continue
        used.update((index_a, index_b))
        a, b = connectors[index_a], connectors[index_b]
        lower, upper = sorted(
            (a, b), key=lambda c: (c.from_bp, c.to_bp, str(c.crossover_id))
        )
        pair_id = f"{lower.crossover_id}:{upper.crossover_id}"
        helix_pair = sorted(lower.helices)
        for connector, side, label in (
            (lower, "i", "Left crossover · i"),
            (upper, "i+1", "Right crossover · i+1"),
        ):
            sides[str(connector.crossover_id)] = {
                "side": side,
                "label": label,
                "pair_id": pair_id,
                "paired_with": str(
                    upper.crossover_id if connector is lower else lower.crossover_id
                ),
                "bp_level": int(connector.from_bp),
                "helix_pair": helix_pair,
            }
    return sides


def _round_robin(series: list[list[dict]]) -> list[dict]:
    """Interleave sites so a bounded fit cannot be dominated by list ordering."""
    if not series:
        return []
    result = []
    for sample_index in range(max(map(len, series))):
        for records in series:
            if sample_index < len(records):
                result.append(records[sample_index])
    return result


def _rigid_fit(local: np.ndarray, world: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit ``world ~= origin + rotation @ local`` with a proper rotation."""
    local_center, world_center = local.mean(axis=0), world.mean(axis=0)
    u, _singular, vt = np.linalg.svd((local - local_center).T @ (world - world_center))
    handedness = np.sign(np.linalg.det(vt.T @ u.T))
    rotation = vt.T @ np.diag((1.0, 1.0, handedness)) @ u.T
    origin = world_center - rotation @ local_center
    residual = world - (local @ rotation.T + origin)
    rmsd = float(np.sqrt(np.sum(residual**2) / len(local)))
    return origin, rotation, rmsd


def _atomistic_medoid(atoms: dict, base: str | None) -> tuple[dict | None, list | None]:
    """Reconstruct the full heavy-atom nucleotide from measured medoid anchors.

    The metric dump stores exact C1′/C3′/C5′/P and base-centroid coordinates.  A rigid
    fit of NADOC's residue template to those five anchors supplies the otherwise absent
    C2′/C4′/O4′ ribose positions and base-ring atoms.  Exact measured anchor positions
    replace their fitted counterparts in the returned structure.
    """
    residue = {"A": "DA", "T": "DT", "G": "DG", "C": "DC"}.get(
        str(base or "T").upper(), "DT"
    )
    base_defs, base_bonds = BASE_TEMPLATES[residue]
    definitions = list(_SUGAR)
    known_names = {definition[0] for definition in definitions}
    for definition in base_defs:
        if definition[0] not in known_names:
            definitions.append(definition)
            known_names.add(definition[0])
    local_by_name = {
        name: np.asarray((x, y, z), dtype=float) * 10.0
        for name, _element, x, y, z in definitions
    }
    ring_names = ("N1", "C2", "N3", "C4", "C5", "C6")
    local_base_center = np.mean([local_by_name[name] for name in ring_names], axis=0)
    anchors = ("P", "C5'", "C3'", "C1'")
    if not all(name in atoms for name in (*anchors, "base")):
        return None, None
    local = np.asarray([local_by_name[name] for name in anchors] + [local_base_center])
    world = np.asarray([atoms[name] for name in anchors] + [atoms["base"]])
    origin, rotation, fit_rmsd = _rigid_fit(local, world)

    direct = set(anchors)
    atom_rows = []
    for name, element, *_coords in definitions:
        position = origin + rotation @ local_by_name[name]
        if name in direct:
            position = np.asarray(atoms[name], dtype=float)
        atom_rows.append(
            {
                "name": name,
                "element": element,
                "position_A": position.tolist(),
                "coordinate_source": "measured" if name in direct else "rigid_template_fit",
            }
        )
    return (
        {
            "atoms": atom_rows,
            "bonds": [list(bond) for bond in (*_SUGAR_BONDS, *base_bonds)],
            "ribose_ring": ["C1'", "C2'", "C3'", "C4'", "O4'"],
            "fit_rmsd_A": fit_rmsd,
            "coordinate_note": (
                "P/C5'/C3'/C1' are measured; remaining heavy atoms are a rigid "
                "NADOC residue-template fit to those anchors plus the measured base center"
            ),
        },
        rotation.tolist(),
    )


def canonical_medoid(
    sample: dict,
    insert: dict,
    side_info: dict,
    *,
    sample_index: int,
    frame: int | None,
) -> dict:
    """Return one real nucleotide pose in the canonical helix-pair frame.

    ``h*`` coordinates live in the per-hop frame while ``g*`` coordinates live in the
    canonical global junction frame.  Changing hop direction flips hop x and z but not
    the shared helical axis, hence the diagonal ``D`` transform below.
    """
    src_helix = str(insert["src"][0])
    helix_pair = sorted((str(insert["src"][0]), str(insert["dst"][0])))
    sign = 1.0 if src_helix == helix_pair[0] else -1.0
    hop_to_global = np.diag((sign, 1.0, sign))
    c1 = np.asarray([sample[k] for k in POSITION_KEYS], dtype=float)
    length = float(sample.get("L", math.nan))
    h_c1 = np.asarray(
        [sample.get("h1_c1"), sample.get("h2_c1"), sample.get("h3_c1")],
        dtype=float,
    )
    origin = c1 - hop_to_global @ (h_c1 * length)

    atoms = {"C1'": c1.tolist()}
    for atom in ("P", "C3'", "C5'"):
        hop = np.asarray(
            [sample.get(f"h{axis}_{atom}") for axis in (1, 2, 3)], dtype=float
        )
        if np.all(np.isfinite(hop)) and np.isfinite(length):
            atoms[atom] = (origin + hop_to_global @ (hop * length)).tolist()
    base = np.asarray(
        [sample.get("g_ih_base"), sample.get("g_ax_base"), sample.get("g_pp_base")],
        dtype=float,
    )
    if np.all(np.isfinite(base)):
        atoms["base"] = base.tolist()

    atomistic, orientation = _atomistic_medoid(atoms, insert.get("base"))

    return {
        "sample_index": int(sample_index),
        "frame": int(frame) if frame is not None else None,
        "crossover_id": str(insert["crossover_id"]),
        "insert_k": int(insert["k"]),
        "base": insert.get("base"),
        "src": insert.get("src"),
        "dst": insert.get("dst"),
        "side": side_info["side"],
        "bp_level": side_info["bp_level"],
        "helix_pair": helix_pair,
        "interhelix_A": float(sample.get("interhelix", math.nan)),
        "atoms_A": atoms,
        "base_orientation": orientation,
        "atomistic": atomistic,
    }


def _fit_indices(n_records: int, max_fit_samples: int) -> np.ndarray:
    if n_records <= max_fit_samples:
        return np.arange(n_records, dtype=int)
    return np.unique(np.linspace(0, n_records - 1, max_fit_samples, dtype=int))


def pooled_position_clusters(
    data: dict,
    stable_indices: dict[tuple[str, int], list[int]],
    *,
    max_fit_samples: int = 2500,
    k_max: int = 4,
) -> dict:
    """Cluster stable inserted-base C1′ positions after pooling by HJ side."""
    design_path = Path(data.get("job", "")) / "design.json"
    if not design_path.is_file():
        return {
            "ready": False,
            "reason": f"design snapshot not found: {design_path}",
            "sides": [],
        }
    # Match the extractor's frozen-snapshot load exactly. ``Design.from_json`` also
    # performs editor-era topology migrations that can replace crossover ids, severing
    # the identity link to an archived metric dump.
    design = Design.model_validate_json(design_path.read_text(encoding="utf-8"))
    side_map = reciprocal_crossover_sides(design)

    by_side: dict[str, list[list[dict]]] = {"i": [], "i+1": []}
    unpaired = 0
    for insert in data.get("inserts", []):
        crossover_id = str(insert["crossover_id"])
        side_info = side_map.get(crossover_id)
        if side_info is None:
            unpaired += 1
            continue
        samples = insert["samples"]
        n_frames = len(data.get("paired_fraction", []))
        siblings = [
            candidate
            for candidate in data["inserts"]
            if candidate["crossover_id"] == insert["crossover_id"]
        ]
        if len(samples) != n_frames and len(siblings) > 1:
            samples = samples[int(insert["k"]) :: len(siblings)]
        records = []
        for sample_index in stable_indices.get((crossover_id, int(insert["k"])), []):
            sample = samples[sample_index]
            position = np.asarray([sample.get(key) for key in POSITION_KEYS], dtype=float)
            if not np.all(np.isfinite(position)):
                continue
            records.append(
                {
                    "position_A": position,
                    "sample": sample,
                    "sample_index": sample_index,
                    "insert": insert,
                    "side_info": side_info,
                }
            )
        if records:
            by_side[side_info["side"]].append(records)

    side_results = []
    for side in ("i", "i+1"):
        records = _round_robin(by_side[side])
        if len(records) < 20:
            side_results.append(
                {
                    "side": side,
                    "label": "Left crossover · i" if side == "i" else "Right crossover · i+1",
                    "ready": False,
                    "reason": "insufficient stable paired-junction positions",
                    "n_observations": len(records),
                }
            )
            continue
        chosen = _fit_indices(len(records), max_fit_samples)
        fit_records = [records[int(index)] for index in chosen]
        positions_A = np.asarray([record["position_A"] for record in fit_records])
        # occupancy_core reports point spreads in nm, so supply its expected unit.
        result = occupancy_clusters(positions_A / 10.0, k_max=k_max)
        clusters = []
        for cluster in result.get("clusters", []):
            member_indices = cluster.get("frames", [])
            members_A = positions_A[member_indices]
            record = fit_records[int(cluster["medoid_index"])]
            sample_index = int(record["sample_index"])
            frames = data.get("frames", [])
            clusters.append(
                {
                    "rank": int(cluster["rank"]),
                    "population": float(cluster["population"]),
                    "n_fit_samples": int(cluster["n_frames"]),
                    "n_crossovers": len(
                        {
                            fit_records[index]["insert"]["crossover_id"]
                            for index in member_indices
                        }
                    ),
                    "center_A": np.mean(members_A, axis=0).tolist(),
                    "spread_A": 10.0 * float(cluster["rmsd_spread_nm"]),
                    "distance_to_top_A": 10.0
                    * float(cluster.get("rmsd_to_top_nm", 0.0)),
                    "medoid": canonical_medoid(
                        record["sample"],
                        record["insert"],
                        record["side_info"],
                        sample_index=sample_index,
                        frame=frames[sample_index] if sample_index < len(frames) else None,
                    ),
                }
            )
        pair_ids = {
            records_for_insert[0]["side_info"]["pair_id"]
            for records_for_insert in by_side[side]
        }
        side_results.append(
            {
                "side": side,
                "label": "Left crossover · i" if side == "i" else "Right crossover · i+1",
                "ready": bool(result.get("ready")),
                "reason": result.get("reason"),
                "n_observations": len(records),
                "n_fit_samples": len(fit_records),
                "n_crossovers": len(by_side[side]),
                "n_junctions": len(pair_ids),
                "k": result.get("k"),
                "silhouette": result.get("silhouette"),
                "coordinate_frame": ["interhelix", "helix_axis", "out_of_plane"],
                "clusters": clusters,
            }
        )
    return {
        "ready": any(side.get("ready") for side in side_results),
        "classification": "lower reciprocal bp level = i/left; higher = i+1/right",
        "n_unpaired_inserts": unpaired,
        "max_fit_samples_per_side": int(max_fit_samples),
        "sides": side_results,
    }
