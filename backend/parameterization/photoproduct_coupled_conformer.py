"""Review boundary for stereochemistry-preserving off-equilibrium Hessian targets.

Cyclobutane-ring torsions are coupled coordinates and cannot be parameterized by
pretending that a ring bond is freely rotatable.  This module creates a gate-neutral
human-review packet for explicitly supplied conformers, revalidates the reviewed packet,
and generates fixed-geometry Psi4 gradient/Hessian jobs without changing coordinates.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Sequence

import numpy as np

from backend.core.photoproduct_chemistry import signed_tetrahedron_volume
from backend.parameterization.photoproduct_qm import (
    QM_PROTOCOL_PATH,
    generate_psi4_job,
    parse_xyz,
)


PARAMETER_ACCEPTANCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_parameter_acceptance.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _stable_keys(path: Path) -> list[str]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("stable atom map must be a JSON list")
    keys = [
        item.get("stable_atom_key") if isinstance(item, dict) else item
        for item in payload
    ]
    if (
        not keys
        or any(not isinstance(key, str) or not key for key in keys)
        or len(keys) != len(set(keys))
    ):
        raise ValueError("stable atom map must contain unique nonempty keys")
    return keys


def _graph(path: Path, keys: Sequence[str]) -> dict[str, Any]:
    graph = json.loads(path.read_text())
    atoms = graph.get("atoms") or []
    bonds = graph.get("bonds") or []
    if (
        graph.get("schema") != "nadoc.photoproduct-model-graph.v1"
        or graph.get("atom_count") != len(keys)
        or [item.get("key") for item in atoms] != list(keys)
        or [item.get("index") for item in atoms] != list(range(len(keys)))
        or len(bonds) != graph.get("bond_count")
    ):
        raise ValueError("model graph and stable atom map differ")
    key_set = set(keys)
    seen: set[tuple[str, str]] = set()
    for bond in bonds:
        pair = tuple(sorted(bond.get("atoms") or []))
        if len(pair) != 2 or pair[0] not in key_set or pair[1] not in key_set:
            raise ValueError("model graph contains an invalid bond endpoint")
        if pair in seen or float(bond.get("order") or 0.0) <= 0.0:
            raise ValueError("model graph contains a duplicate or invalid bond")
        seen.add(pair)
    adjacency = {key: set() for key in keys}
    for first, second in seen:
        adjacency[first].add(second)
        adjacency[second].add(first)
    visited = set()
    pending = [keys[0]]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency[current] - visited)
    if visited != key_set:
        raise ValueError("model graph must be a single connected molecule")
    return graph


def _stereo_records(
    path: Path, product_id: str, model_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text())
    schema = payload.get("schema")
    if schema == "nadoc.photoproduct-chemical-definition.v1":
        if payload.get("id") != product_id:
            raise ValueError("chemical definition product identity differs")
        records = [
            {
                "atom": item["atom"],
                "reference_atoms": item["signed_volume_reference_atoms"],
                "expected_sign": item["expected_signed_volume"],
            }
            for item in payload.get("product_stereocenters") or []
        ]
    elif schema == "nadoc.tt-cpd-stereo-candidate.v1":
        if (
            payload.get("product_id") != product_id
            or payload.get("model_id") != model_id
            or payload.get("status") != "candidate_not_reviewed"
        ):
            raise ValueError("stereo-candidate identity/status differs")
        records = [
            {
                "atom": item["atom"],
                "reference_atoms": item["reference_atoms"],
                "expected_sign": item["expected_sign"],
            }
            for item in payload.get("model_signed_volume_stereochemistry") or []
        ]
    else:
        raise ValueError("unsupported stereochemistry evidence schema")
    if (
        len(records) != 4
        or len({item["atom"] for item in records}) != 4
        or any(
            item["expected_sign"] not in {"positive", "negative"}
            or len(item["reference_atoms"]) != 3
            for item in records
        )
    ):
        raise ValueError("stereochemistry evidence must define four signed centers")
    return payload, records


def _coordinates(
    path: Path, graph: dict[str, Any], keys: Sequence[str]
) -> tuple[np.ndarray, dict[str, list[float]]]:
    atoms, _comment = parse_xyz(path.read_text())
    expected_elements = [str(item.get("element")) for item in graph["atoms"]]
    if len(atoms) != len(keys) or [item[0] for item in atoms] != expected_elements:
        raise ValueError("conformer XYZ changed atom count, order, or elements")
    xyz = np.asarray([item[1:] for item in atoms], dtype=float)
    if not np.all(np.isfinite(xyz)):
        raise ValueError("conformer XYZ contains non-finite coordinates")
    return xyz, {
        key: [float(value) for value in point]
        for key, point in zip(keys, xyz, strict=True)
    }


def _chirality(
    records: Sequence[dict[str, Any]], coordinates: dict[str, list[float]]
) -> dict[str, Any]:
    centers = []
    for record in records:
        try:
            value = signed_tetrahedron_volume(
                coordinates,
                record["atom"],
                record["reference_atoms"],
            )
        except KeyError as exc:
            raise ValueError(f"stereochemistry atom is absent: {exc.args[0]}") from exc
        expected = record["expected_sign"]
        centers.append(
            {
                "atom": record["atom"],
                "signed_volume": value,
                "expected_sign": expected,
                "passed": value > 0.0 if expected == "positive" else value < 0.0,
            }
        )
    return {"passed": all(item["passed"] for item in centers), "centers": centers}


def _aligned_rmsd(reference: np.ndarray, candidate: np.ndarray) -> float:
    first = reference - np.mean(reference, axis=0)
    second = candidate - np.mean(candidate, axis=0)
    left, _singular, right = np.linalg.svd(second.T @ first)
    rotation = left @ right
    if np.linalg.det(rotation) < 0.0:
        left[:, -1] *= -1.0
        rotation = left @ right
    difference = second @ rotation - first
    return float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))


_COVALENT_RADII = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "P": 1.07,
    "S": 1.05,
}


def _geometry_metrics(
    *,
    graph: dict[str, Any],
    keys: Sequence[str],
    reference: np.ndarray,
    candidate: np.ndarray,
) -> dict[str, Any]:
    index = {key: number for number, key in enumerate(keys)}
    bonded: set[tuple[int, int]] = set()
    bond_ratios = []
    adjacency = {number: set() for number in range(len(keys))}
    for bond in graph["bonds"]:
        first, second = (index[key] for key in bond["atoms"])
        pair = tuple(sorted((first, second)))
        bonded.add(pair)
        adjacency[first].add(second)
        adjacency[second].add(first)
        reference_length = float(np.linalg.norm(reference[first] - reference[second]))
        candidate_length = float(np.linalg.norm(candidate[first] - candidate[second]))
        if reference_length <= 0.0:
            raise ValueError("reference geometry has a zero-length graph bond")
        bond_ratios.append(
            {
                "atoms": list(bond["atoms"]),
                "reference_angstrom": reference_length,
                "candidate_angstrom": candidate_length,
                "ratio": candidate_length / reference_length,
            }
        )
    close_graph_pairs = set(bonded)
    for center, neighbors in adjacency.items():
        for first in neighbors:
            for second in neighbors:
                if first < second:
                    close_graph_pairs.add(tuple(sorted((first, second))))
    closest = None
    for first in range(len(keys)):
        for second in range(first + 1, len(keys)):
            if (first, second) in close_graph_pairs:
                continue
            elements = (
                graph["atoms"][first]["element"],
                graph["atoms"][second]["element"],
            )
            radii = [_COVALENT_RADII.get(str(element)) for element in elements]
            if None in radii:
                raise ValueError(
                    f"no covalent-radius clash rule for elements {elements}"
                )
            distance = float(np.linalg.norm(candidate[first] - candidate[second]))
            ratio = distance / float(sum(radii))
            if closest is None or ratio < closest["covalent_radius_ratio"]:
                closest = {
                    "atoms": [keys[first], keys[second]],
                    "distance_angstrom": distance,
                    "covalent_radius_ratio": ratio,
                }
    rmsd = _aligned_rmsd(reference, candidate)
    minimum_ratio = min(item["ratio"] for item in bond_ratios)
    maximum_ratio = max(item["ratio"] for item in bond_ratios)
    passed = (
        0.75 <= minimum_ratio
        and maximum_ratio <= 1.30
        and closest is not None
        and closest["covalent_radius_ratio"] >= 0.65
        and 0.01 <= rmsd <= 1.50
    )
    return {
        "passed": passed,
        "proper_rotation_aligned_rmsd_angstrom": rmsd,
        "minimum_graph_bond_ratio": minimum_ratio,
        "maximum_graph_bond_ratio": maximum_ratio,
        "closest_nonbonded_pair": closest,
        "graph_bonds": bond_ratios,
        "thresholds": {
            "aligned_rmsd_angstrom": [0.01, 1.50],
            "graph_bond_ratio": [0.75, 1.30],
            "minimum_nonbonded_covalent_radius_ratio": 0.65,
        },
    }


def _validate_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _derived_audit_equal(stored: object, recomputed: object) -> bool:
    """Compare recomputed metrics across pinned environments without hiding changes.

    BLAS/LAPACK implementations can change the final bits of the proper-rotation SVD.
    Audit structure, strings, booleans, and integers remain exact; only finite floating
    values receive a tight tolerance far below any review threshold.
    """

    if isinstance(stored, bool) or isinstance(recomputed, bool):
        return (
            type(stored) is bool and type(recomputed) is bool and stored == recomputed
        )
    if isinstance(stored, float) or isinstance(recomputed, float):
        if not isinstance(stored, (int, float)) or not isinstance(
            recomputed, (int, float)
        ):
            return False
        first, second = float(stored), float(recomputed)
        return (
            math.isfinite(first)
            and math.isfinite(second)
            and math.isclose(first, second, rel_tol=1.0e-12, abs_tol=1.0e-12)
        )
    if isinstance(stored, dict) or isinstance(recomputed, dict):
        return (
            isinstance(stored, dict)
            and isinstance(recomputed, dict)
            and stored.keys() == recomputed.keys()
            and all(
                _derived_audit_equal(stored[key], recomputed[key]) for key in stored
            )
        )
    if isinstance(stored, list) or isinstance(recomputed, list):
        return (
            isinstance(stored, list)
            and isinstance(recomputed, list)
            and len(stored) == len(recomputed)
            and all(
                _derived_audit_equal(first, second)
                for first, second in zip(stored, recomputed, strict=True)
            )
        )
    return type(stored) is type(recomputed) and stored == recomputed


_TOP_TWO_MODE_POLICY = "top-two-modes-both-signs-largest-amplitude-v1"


def _select_candidate_records(
    manifest: dict[str, Any], policy: str
) -> list[dict[str, Any]]:
    if policy != _TOP_TWO_MODE_POLICY:
        raise ValueError(f"unsupported coupled-conformer selection policy: {policy}")
    candidates = manifest.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("coupled-conformer candidate manifest is empty")
    amplitudes = [
        abs(float(item.get("signed_active_rmsd_angstrom"))) for item in candidates
    ]
    largest_amplitude = max(amplitudes)
    selected = [
        item
        for item in candidates
        if item.get("mode_rank_by_active_fraction") in {1, 2}
        and abs(abs(float(item.get("signed_active_rmsd_angstrom"))) - largest_amplitude)
        <= 1.0e-12
    ]
    selected.sort(
        key=lambda item: (
            item["mode_rank_by_active_fraction"],
            float(item["signed_active_rmsd_angstrom"]),
            str(item.get("id") or ""),
        )
    )
    identities = [item.get("id") for item in selected]
    sign_pairs = {
        rank: {
            -1 if float(item["signed_active_rmsd_angstrom"]) < 0 else 1
            for item in selected
            if item["mode_rank_by_active_fraction"] == rank
        }
        for rank in (1, 2)
    }
    if (
        len(selected) != 4
        or len(identities) != len(set(identities))
        or sign_pairs != {1: {-1, 1}, 2: {-1, 1}}
    ):
        raise ValueError(
            "selection policy requires both signs of the two highest-ranked modes"
        )
    return selected


def build_coupled_conformer_review_template(
    *,
    product_id: str,
    model_id: str,
    optimized_audit_path: Path | None,
    reference_geometry_path: Path | None = None,
    model_graph_path: Path,
    stable_atom_map_path: Path,
    stereochemistry_evidence_path: Path,
    candidate_xyz_paths: Sequence[Path],
    output_path: Path,
    rank_screen_path: Path | None = None,
    mode_source_path: Path | None = None,
    candidate_manifest_path: Path | None = None,
    candidate_selection_policy: str | None = None,
) -> dict[str, Any]:
    """Measure supplied conformers and emit a packet that still requires human review."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite conformer review packet: {output_path}"
        )
    candidate_manifest_record = None
    selection_record: dict[str, Any]
    selected_candidate_ids: list[str | None]
    if candidate_manifest_path is not None:
        if candidate_xyz_paths:
            raise ValueError(
                "candidate manifest selection and explicit candidate XYZs are mutually exclusive"
            )
        candidate_manifest = json.loads(candidate_manifest_path.read_text())
        if (
            candidate_manifest.get("schema")
            != "nadoc.photoproduct-coupled-conformer-candidates.v1"
            or candidate_manifest.get("status") != "candidates_not_reviewed"
            or candidate_manifest.get("simulation_ready") is not False
            or candidate_manifest.get("gate_effect") != "none"
            or candidate_manifest.get("product_id") != product_id
            or candidate_manifest.get("model_id") != model_id
        ):
            raise ValueError("candidate manifest is not a matching gate-neutral set")
        policy = candidate_selection_policy or _TOP_TWO_MODE_POLICY
        selected_records = _select_candidate_records(candidate_manifest, policy)
        candidate_xyz_paths = [
            _checked(item.get("geometry"), f"candidate {item.get('id')} geometry")
            for item in selected_records
        ]
        selected_candidate_ids = [str(item["id"]) for item in selected_records]
        candidate_manifest_record = _source(candidate_manifest_path)
        selection_record = {
            "policy": policy,
            "selected_candidate_ids": selected_candidate_ids,
            "scientific_effect": "review_queue_only",
        }
    else:
        if candidate_selection_policy is not None:
            raise ValueError("candidate selection policy requires a candidate manifest")
        selected_candidate_ids = [None] * len(candidate_xyz_paths)
        selection_record = {
            "policy": "explicit-paths",
            "selected_candidate_ids": selected_candidate_ids,
            "scientific_effect": "review_queue_only",
        }
    if len(candidate_xyz_paths) < 2:
        raise ValueError(
            "at least two coupled conformers are required for train/holdout review"
        )
    if (optimized_audit_path is None) == (mode_source_path is None):
        raise ValueError(
            "exactly one optimized-model audit or conformer mode source is required"
        )
    optimized_source = None
    mode_source_record = None
    if optimized_audit_path is not None:
        audit = json.loads(optimized_audit_path.read_text())
        if (
            audit.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
            or audit.get("status")
            not in {
                "passed_identity_and_chirality",
                "passed_candidate_identity_and_chirality",
            }
            or audit.get("gate_effect") != "none"
            or audit.get("product_id") != product_id
            or audit.get("model_id") != model_id
        ):
            raise ValueError(
                "reference optimization audit is not a passed matching model"
            )
        declared_reference = audit.get("optimized_xyz") or {}
        optimized_source = _source(optimized_audit_path)
    else:
        mode_source = json.loads(mode_source_path.read_text())
        if (
            mode_source.get("schema") != "nadoc.photoproduct-conformer-mode-source.v1"
            or mode_source.get("status") != "candidate_mode_source_not_fit_target"
            or mode_source.get("simulation_ready") is not False
            or mode_source.get("gate_effect") != "none"
            or mode_source.get("contains_parameter_targets") is not False
            or mode_source.get("chemical_definition_gate_required_before_fit_targets")
            is not True
            or mode_source.get("product_id") != product_id
            or mode_source.get("model_id") != model_id
            or (mode_source.get("chirality_audit") or {}).get("passed") is not True
        ):
            raise ValueError(
                "conformer mode source is not a matching gate-neutral response"
            )
        declared_reference = mode_source.get("source_geometry") or {}
        mode_source_record = _source(mode_source_path)
    if reference_geometry_path is None:
        reference_path = _checked(declared_reference, "optimized reference geometry")
    else:
        reference_path = reference_geometry_path.resolve()
        if not reference_path.is_file() or _sha256(
            reference_path
        ) != declared_reference.get("sha256"):
            raise ValueError(
                "relocated reference geometry does not match the optimized audit"
            )
    keys = _stable_keys(stable_atom_map_path)
    graph = _graph(model_graph_path, keys)
    if mode_source_path is not None:
        mode_sources = mode_source.get("sources") or {}
        expected_sources = {
            "model_graph": model_graph_path,
            "stable_atom_map": stable_atom_map_path,
            "stereochemistry_evidence": stereochemistry_evidence_path,
        }
        for name, path in expected_sources.items():
            if (mode_sources.get(name) or {}).get("sha256") != _sha256(path):
                raise ValueError(f"conformer mode source changed its {name}")
        if mode_source.get("atom_map") != keys:
            raise ValueError("conformer mode source atom map differs")
    _stereo_payload, stereo = _stereo_records(
        stereochemistry_evidence_path, product_id, model_id
    )
    reference, reference_coordinates = _coordinates(reference_path, graph, keys)
    if not _chirality(stereo, reference_coordinates)["passed"]:
        raise ValueError(
            "reference optimized geometry fails its pinned stereochemistry"
        )
    conformers = []
    hashes = set()
    for number, (path, source_candidate_id) in enumerate(
        zip(candidate_xyz_paths, selected_candidate_ids, strict=True), start=1
    ):
        digest = _sha256(path)
        if digest in hashes or digest == _sha256(reference_path):
            raise ValueError(
                "candidate conformer geometries must be distinct from each other and the minimum"
            )
        hashes.add(digest)
        xyz, coordinates = _coordinates(path, graph, keys)
        chirality = _chirality(stereo, coordinates)
        metrics = _geometry_metrics(
            graph=graph, keys=keys, reference=reference, candidate=xyz
        )
        conformers.append(
            {
                "id": f"conformer-{number:03d}",
                "source_candidate_id": source_candidate_id,
                "partition": None,
                "geometry": _source(path),
                "chirality_audit": chirality,
                "geometry_audit": metrics,
                "review_decision": None,
                "review_notes": None,
            }
        )
    rank_screen = None
    if rank_screen_path is not None:
        rank_screen_payload = json.loads(rank_screen_path.read_text())
        if (
            rank_screen_payload.get("schema")
            != "nadoc.photoproduct-coupled-conformer-rank-screen.v1"
            or rank_screen_payload.get("status")
            != "diagnostic_only_candidates_not_reviewed"
            or rank_screen_payload.get("simulation_ready") is not False
            or rank_screen_payload.get("gate_effect") != "none"
            or rank_screen_payload.get("product_id") != product_id
            or rank_screen_payload.get("model_id") != model_id
        ):
            raise ValueError("rank screen is not a matching gate-neutral diagnostic")
        rank_screen = _source(rank_screen_path)
    report = {
        "schema": "nadoc.photoproduct-coupled-conformer-plan.v1",
        "status": "review_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "model_id": model_id,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_rationale": None,
        "review_requirements": {
            "allowed_partitions": ["training", "validation"],
            "each_geometry_must_be_explicitly_accepted": True,
            "minimum_training_conformers": 1,
            "minimum_validation_conformers": 1,
            "reflection_allowed": False,
            "coordinate_optimization_allowed_before_hessian": False,
        },
        "sources": {
            "optimized_model_audit": optimized_source,
            "conformer_mode_source": mode_source_record,
            "reference_geometry": _source(reference_path),
            "model_graph": _source(model_graph_path),
            "stable_atom_map": _source(stable_atom_map_path),
            "stereochemistry_evidence": _source(stereochemistry_evidence_path),
            "rank_screen": rank_screen,
            "candidate_manifest": candidate_manifest_record,
        },
        "candidate_selection": selection_record,
        "atom_map": keys,
        "conformers": conformers,
        "instructions": (
            "A qualified human must inspect each structure, assign training or validation, "
            "set review_decision to accepted, explain its intended coupled distortion, and "
            "then set status/reviewer/time/rationale. Software metrics are necessary but not "
            "sufficient approval and this packet never advances a force-field gate."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_coupled_conformer_review_index(
    *, plan_paths: Sequence[Path], output_dir: Path
) -> dict[str, Any]:
    """Reopen unreviewed plans and build a compact multi-product review index."""

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite conformer review index: {output_dir}"
        )
    if not plan_paths:
        raise ValueError("at least one conformer review plan is required")
    records = []
    seen_products: set[str] = set()
    for plan_path in plan_paths:
        plan_path = plan_path.resolve()
        plan = json.loads(plan_path.read_text())
        product_id = str(plan.get("product_id") or "")
        model_id = str(plan.get("model_id") or "")
        if (
            plan.get("schema") != "nadoc.photoproduct-coupled-conformer-plan.v1"
            or plan.get("status") != "review_required"
            or plan.get("simulation_ready") is not False
            or plan.get("gate_effect") != "none"
            or not product_id
            or product_id in seen_products
            or not model_id
        ):
            raise ValueError(
                "review index requires unique gate-neutral unreviewed plans"
            )
        seen_products.add(product_id)
        sources = plan.get("sources") or {}
        mode_source_path = _checked(
            sources.get("conformer_mode_source"), "conformer mode source"
        )
        candidate_manifest_path = _checked(
            sources.get("candidate_manifest"), "conformer candidate manifest"
        )
        reference_path = _checked(
            sources.get("reference_geometry"), "reference geometry"
        )
        graph_path = _checked(sources.get("model_graph"), "model graph")
        map_path = _checked(sources.get("stable_atom_map"), "stable atom map")
        stereo_path = _checked(
            sources.get("stereochemistry_evidence"), "stereochemistry evidence"
        )
        mode_source = json.loads(mode_source_path.read_text())
        manifest = json.loads(candidate_manifest_path.read_text())
        selection = plan.get("candidate_selection") or {}
        if (
            mode_source.get("schema") != "nadoc.photoproduct-conformer-mode-source.v1"
            or mode_source.get("status") != "candidate_mode_source_not_fit_target"
            or mode_source.get("contains_parameter_targets") is not False
            or mode_source.get("product_id") != product_id
            or mode_source.get("model_id") != model_id
            or manifest.get("schema")
            != "nadoc.photoproduct-coupled-conformer-candidates.v1"
            or manifest.get("status") != "candidates_not_reviewed"
            or manifest.get("product_id") != product_id
            or manifest.get("model_id") != model_id
            or selection.get("scientific_effect") != "review_queue_only"
        ):
            raise ValueError(f"{product_id}: review source identity/status changed")
        selected = _select_candidate_records(
            manifest, str(selection.get("policy") or "")
        )
        selected_by_id = {str(item["id"]): item for item in selected}
        if selection.get("selected_candidate_ids") != list(selected_by_id):
            raise ValueError(f"{product_id}: deterministic candidate selection changed")
        keys = _stable_keys(map_path)
        if keys != plan.get("atom_map") or keys != mode_source.get("atom_map"):
            raise ValueError(f"{product_id}: stable atom-map identity changed")
        graph = _graph(graph_path, keys)
        _payload, stereo = _stereo_records(stereo_path, product_id, model_id)
        reference, reference_coordinates = _coordinates(reference_path, graph, keys)
        if not _chirality(stereo, reference_coordinates)["passed"]:
            raise ValueError(f"{product_id}: reference minimum fails stereochemistry")
        conformer_records = []
        conformers = plan.get("conformers") or []
        if len(conformers) != len(selected):
            raise ValueError(f"{product_id}: review conformer count changed")
        for item in conformers:
            if (
                item.get("partition") is not None
                or item.get("review_decision") is not None
                or item.get("review_notes") is not None
            ):
                raise ValueError(
                    f"{product_id}: index accepts only pristine unreviewed decisions"
                )
            candidate = selected_by_id.get(str(item.get("source_candidate_id") or ""))
            geometry_path = _checked(item.get("geometry"), f"{product_id} conformer")
            if candidate is None or (candidate.get("geometry") or {}).get(
                "sha256"
            ) != _sha256(geometry_path):
                raise ValueError(f"{product_id}: selected conformer identity changed")
            xyz, coordinates = _coordinates(geometry_path, graph, keys)
            chirality = _chirality(stereo, coordinates)
            geometry = _geometry_metrics(
                graph=graph, keys=keys, reference=reference, candidate=xyz
            )
            if (
                not chirality["passed"]
                or not geometry["passed"]
                or not _derived_audit_equal(item.get("chirality_audit"), chirality)
                or not _derived_audit_equal(item.get("geometry_audit"), geometry)
            ):
                raise ValueError(f"{product_id}: conformer audit changed or failed")
            conformer_records.append(
                {
                    "id": item["id"],
                    "source_candidate_id": candidate["id"],
                    "geometry": _source(geometry_path),
                    "mode_rank": candidate["mode_rank_by_active_fraction"],
                    "mode_index_zero_based": candidate["mode_index_zero_based"],
                    "signed_active_rmsd_angstrom": candidate[
                        "signed_active_rmsd_angstrom"
                    ],
                    "coupled_ring_deformation_score": candidate[
                        "coupled_ring_deformation_score"
                    ],
                    "proper_rotation_aligned_rmsd_angstrom": geometry[
                        "proper_rotation_aligned_rmsd_angstrom"
                    ],
                    "minimum_graph_bond_ratio": geometry["minimum_graph_bond_ratio"],
                    "maximum_graph_bond_ratio": geometry["maximum_graph_bond_ratio"],
                    "closest_nonbonded_pair": geometry["closest_nonbonded_pair"],
                    "chirality_passed": True,
                    "geometry_passed": True,
                }
            )
        records.append(
            {
                "product_id": product_id,
                "model_id": model_id,
                "plan": _source(plan_path),
                "mode_source": _source(mode_source_path),
                "candidate_manifest": _source(candidate_manifest_path),
                "selection": selection,
                "conformers": conformer_records,
            }
        )

    index = {
        "schema": "nadoc.photoproduct-coupled-conformer-review-index.v1",
        "status": "human_review_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_count": len(records),
        "records": records,
        "release_boundary": (
            "This index only presents recomputed, gate-neutral review candidates. "
            "It selects no training/validation partition and authorizes no QM job."
        ),
    }
    lines = [
        "# Coupled-conformer human-review index",
        "",
        "> Every structure below is unreviewed. This index creates no fit target and passes no gate.",
        "",
        "| Product | Candidate | Mode rank/index | Signed active RMSD (Å) | Aligned RMSD (Å) | Bond ratio range | Closest nonbonded (Å) |",
        "|---|---|---|---:|---:|---|---:|",
    ]
    for record in records:
        for conformer in record["conformers"]:
            closest = conformer["closest_nonbonded_pair"]
            lines.append(
                "| "
                + " | ".join(
                    (
                        record["product_id"],
                        conformer["source_candidate_id"],
                        f"{conformer['mode_rank']}/{conformer['mode_index_zero_based']}",
                        f"{conformer['signed_active_rmsd_angstrom']:.3f}",
                        f"{conformer['proper_rotation_aligned_rmsd_angstrom']:.4f}",
                        (
                            f"{conformer['minimum_graph_bond_ratio']:.3f}–"
                            f"{conformer['maximum_graph_bond_ratio']:.3f}"
                        ),
                        f"{closest['distance_angstrom']:.3f}",
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "For each product, inspect the four XYZ files, explicitly accept or reject each,",
            "assign every accepted structure to training or validation, and record rationale.",
            "Fixed-geometry QM remains blocked until the matching chemical definition is released.",
            "",
        ]
    )
    output_dir.mkdir(parents=True)
    markdown_path = output_dir / "coupled_conformer_review_index.md"
    markdown_path.write_text("\n".join(lines))
    index["artifacts"] = {"markdown": _source(markdown_path)}
    json_path = output_dir / "coupled_conformer_review_index.json"
    json_path.write_text(json.dumps(index, indent=2) + "\n")
    return index


def _validated_review_visualization_sources(
    review_index_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Revalidate an unreviewed index and return immutable structure-frame inputs."""

    review_index_path = review_index_path.resolve()
    index = json.loads(review_index_path.read_text())
    records = index.get("records") or []
    if (
        index.get("schema") != "nadoc.photoproduct-coupled-conformer-review-index.v1"
        or index.get("status") != "human_review_required"
        or index.get("simulation_ready") is not False
        or index.get("gate_effect") != "none"
        or index.get("product_count") != len(records)
        or not records
    ):
        raise ValueError(
            "visualization requires a gate-neutral unreviewed review index"
        )
    _checked((index.get("artifacts") or {}).get("markdown"), "review index markdown")

    validated: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    for record in records:
        product_id = str(record.get("product_id") or "")
        model_id = str(record.get("model_id") or "")
        if not product_id or product_id in seen_products or not model_id:
            raise ValueError("visualization index has duplicate or missing identities")
        seen_products.add(product_id)
        plan_path = _checked(record.get("plan"), f"{product_id} review plan")
        plan = json.loads(plan_path.read_text())
        if (
            plan.get("schema") != "nadoc.photoproduct-coupled-conformer-plan.v1"
            or plan.get("status") != "review_required"
            or plan.get("simulation_ready") is not False
            or plan.get("gate_effect") != "none"
            or plan.get("product_id") != product_id
            or plan.get("model_id") != model_id
            or plan.get("candidate_selection") != record.get("selection")
        ):
            raise ValueError(f"{product_id}: review plan identity/status changed")
        sources = plan.get("sources") or {}
        mode_source_path = _checked(
            sources.get("conformer_mode_source"), f"{product_id} conformer mode source"
        )
        candidate_manifest_path = _checked(
            sources.get("candidate_manifest"), f"{product_id} candidate manifest"
        )
        if record.get("mode_source") != _source(mode_source_path) or record.get(
            "candidate_manifest"
        ) != _source(candidate_manifest_path):
            raise ValueError(f"{product_id}: indexed source provenance changed")
        mode_source = json.loads(mode_source_path.read_text())
        if (
            mode_source.get("schema") != "nadoc.photoproduct-conformer-mode-source.v1"
            or mode_source.get("status") != "candidate_mode_source_not_fit_target"
            or mode_source.get("contains_parameter_targets") is not False
            or mode_source.get("gate_effect") != "none"
            or mode_source.get("product_id") != product_id
            or mode_source.get("model_id") != model_id
        ):
            raise ValueError(f"{product_id}: mode-source identity/status changed")
        reference_path = _checked(
            sources.get("reference_geometry"), f"{product_id} reference geometry"
        )
        graph_path = _checked(sources.get("model_graph"), f"{product_id} model graph")
        map_path = _checked(
            sources.get("stable_atom_map"), f"{product_id} stable atom map"
        )
        stereo_path = _checked(
            sources.get("stereochemistry_evidence"),
            f"{product_id} stereochemistry evidence",
        )
        keys = _stable_keys(map_path)
        if keys != plan.get("atom_map"):
            raise ValueError(f"{product_id}: stable atom-map identity changed")
        graph = _graph(graph_path, keys)
        _payload, stereo = _stereo_records(stereo_path, product_id, model_id)
        reference, reference_coordinates = _coordinates(reference_path, graph, keys)
        if not _chirality(stereo, reference_coordinates)["passed"]:
            raise ValueError(f"{product_id}: reference minimum fails stereochemistry")

        manifest = json.loads(candidate_manifest_path.read_text())
        candidate_items = manifest.get("candidates") or []
        if (
            manifest.get("schema")
            != "nadoc.photoproduct-coupled-conformer-candidates.v1"
            or manifest.get("status") != "candidates_not_reviewed"
            or manifest.get("simulation_ready") is not False
            or manifest.get("gate_effect") != "none"
            or manifest.get("product_id") != product_id
            or manifest.get("model_id") != model_id
        ):
            raise ValueError(f"{product_id}: candidate identity/status changed")
        candidates = {str(item.get("id") or ""): item for item in candidate_items}
        plan_conformers = {
            str(item.get("id") or ""): item for item in (plan.get("conformers") or [])
        }
        indexed_conformers = record.get("conformers") or []
        indexed_ids = [str(item.get("id") or "") for item in indexed_conformers]
        if (
            len(candidates) != len(candidate_items)
            or "" in candidates
            or len(plan_conformers) != len(indexed_conformers)
            or "" in plan_conformers
            or len(plan_conformers) != len(plan.get("conformers") or [])
            or len(indexed_ids) != len(set(indexed_ids))
            or set(indexed_ids) != set(plan_conformers)
        ):
            raise ValueError(f"{product_id}: conformer identities/count changed")
        frames = []
        for indexed in indexed_conformers:
            conformer_id = str(indexed.get("id") or "")
            planned = plan_conformers.get(conformer_id)
            if planned is None or any(
                planned.get(field) is not None
                for field in ("partition", "review_decision", "review_notes")
            ):
                raise ValueError(
                    f"{product_id}: visualization accepts pristine review only"
                )
            geometry_path = _checked(
                indexed.get("geometry"), f"{product_id} conformer {conformer_id}"
            )
            if indexed.get("geometry") != planned.get("geometry"):
                raise ValueError(f"{product_id}: indexed conformer provenance changed")
            candidate_id = str(indexed.get("source_candidate_id") or "")
            candidate = candidates.get(candidate_id)
            if (
                not candidate
                or planned.get("source_candidate_id") != candidate_id
                or (candidate.get("geometry") or {}).get("sha256")
                != _sha256(geometry_path)
            ):
                raise ValueError(f"{product_id}: candidate identity changed")
            xyz, coordinates = _coordinates(geometry_path, graph, keys)
            chirality = _chirality(stereo, coordinates)
            geometry = _geometry_metrics(
                graph=graph, keys=keys, reference=reference, candidate=xyz
            )
            expected = {
                "proper_rotation_aligned_rmsd_angstrom": geometry[
                    "proper_rotation_aligned_rmsd_angstrom"
                ],
                "minimum_graph_bond_ratio": geometry["minimum_graph_bond_ratio"],
                "maximum_graph_bond_ratio": geometry["maximum_graph_bond_ratio"],
                "closest_nonbonded_pair": geometry["closest_nonbonded_pair"],
                "chirality_passed": chirality["passed"],
                "geometry_passed": geometry["passed"],
                "mode_rank": candidate["mode_rank_by_active_fraction"],
                "mode_index_zero_based": candidate["mode_index_zero_based"],
                "signed_active_rmsd_angstrom": candidate["signed_active_rmsd_angstrom"],
                "coupled_ring_deformation_score": candidate[
                    "coupled_ring_deformation_score"
                ],
            }
            if (
                not chirality["passed"]
                or not geometry["passed"]
                or not _derived_audit_equal(indexed, {**indexed, **expected})
            ):
                raise ValueError(
                    f"{product_id}: indexed conformer audit changed or failed"
                )
            frames.append(
                {
                    "conformer_id": conformer_id,
                    "candidate_id": candidate_id,
                    "geometry": _source(geometry_path),
                    "coordinates": xyz,
                }
            )
        validated.append(
            {
                "product_id": product_id,
                "model_id": model_id,
                "plan": _source(plan_path),
                "graph": graph,
                "atom_map": keys,
                "frames": frames,
            }
        )
    return index, validated


def _pdb_review_models(record: dict[str, Any]) -> str:
    keys = record["atom_map"]
    graph = record["graph"]
    serial_by_key = {key: index + 1 for index, key in enumerate(keys)}
    lines = [
        "REMARK 250 NADOC HUMAN-REVIEW STRUCTURE MODELS; NOT A TRAJECTORY",
        "REMARK 250 UNREVIEWED, NOT PARAMETERIZED, AND NOT SIMULATION-READY",
    ]
    for model_number, frame in enumerate(record["frames"], start=1):
        lines.append(f"MODEL     {model_number:4d}")
        lines.append(
            f"REMARK 250 CONFORMER {frame['conformer_id']} CANDIDATE {frame['candidate_id']}"
        )
        for serial, (key, atom, point) in enumerate(
            zip(keys, graph["atoms"], frame["coordinates"], strict=True), start=1
        ):
            endpoint, _, local_name = key.partition(":")
            chain = "B" if endpoint == "2" else "A"
            residue_number = 2 if endpoint == "2" else 1
            atom_name = re.sub(r"[^A-Za-z0-9'*-]", "", local_name or key)[:4] or "X"
            element = str(atom["element"]).strip().upper()[:2]
            x, y, z = (float(value) for value in point)
            lines.append(
                f"HETATM{serial:5d} {atom_name:>4s} CPD {chain}{residue_number:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2s}"
            )
        lines.append("ENDMDL")
    adjacency: dict[int, list[int]] = {serial: [] for serial in serial_by_key.values()}
    for bond in graph["bonds"]:
        first, second = (serial_by_key[key] for key in bond["atoms"])
        adjacency[first].append(second)
        adjacency[second].append(first)
    for serial, neighbors in adjacency.items():
        for start in range(0, len(neighbors), 4):
            lines.append(
                f"CONECT{serial:5d}"
                + "".join(
                    f"{other:5d}" for other in sorted(neighbors)[start : start + 4]
                )
            )
    lines.append("END")
    return "\n".join(lines) + "\n"


def build_coupled_conformer_review_visualization(
    *, review_index_path: Path, output_dir: Path
) -> dict[str, Any]:
    """Write hash-linked multi-model PDBs solely for qualified human review."""

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite conformer review visualization: {output_dir}"
        )
    _index, records = _validated_review_visualization_sources(review_index_path)
    names: set[str] = set()
    prepared = []
    for record in records:
        stem = re.sub(r"[^a-z0-9._-]+", "-", record["product_id"].lower()).strip("-.")
        if not stem or stem in names:
            raise ValueError(
                "product IDs do not map to unique safe visualization names"
            )
        names.add(stem)
        prepared.append(
            (record, f"{stem}.review-models.pdb", _pdb_review_models(record))
        )

    output_dir.mkdir(parents=True)
    product_records = []
    for record, filename, content in prepared:
        path = output_dir / filename
        path.write_text(content)
        product_records.append(
            {
                "product_id": record["product_id"],
                "model_id": record["model_id"],
                "source_plan": record["plan"],
                "pdb_models": _source(path),
                "model_count": len(record["frames"]),
                "atom_count_per_model": len(record["atom_map"]),
                "bond_count": len(record["graph"]["bonds"]),
                "atom_serial_map": [
                    {"serial": index + 1, "stable_atom_key": key}
                    for index, key in enumerate(record["atom_map"])
                ],
                "models": [
                    {
                        "model_number": index + 1,
                        "conformer_id": frame["conformer_id"],
                        "candidate_id": frame["candidate_id"],
                        "source_geometry": frame["geometry"],
                    }
                    for index, frame in enumerate(record["frames"])
                ],
            }
        )
    readme = output_dir / "README.md"
    readme.write_text(
        "# TT-CPD coupled-conformer review models\n\n"
        "> These are static, unreviewed structure models—not molecular-dynamics "
        "trajectories, parameter evidence, or Help-viewer assets.\n\n"
        "Open a `*.review-models.pdb` file in VMD, ChimeraX, or PyMOL and step through "
        "its four PDB MODEL records. Inspect stereochemistry, ring pucker, contacts, "
        "and chemical plausibility against the matching source plan. Record decisions "
        "only in that plan; this bundle cannot advance a gate.\n"
    )
    manifest = {
        "schema": "nadoc.photoproduct-coupled-conformer-review-visualization.v1",
        "status": "visualization_only_human_review_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "not_a_trajectory": True,
        "not_release_evidence": True,
        "source_review_index": _source(review_index_path),
        "product_count": len(product_records),
        "model_count": sum(item["model_count"] for item in product_records),
        "products": product_records,
        "artifacts": {"readme": _source(readme)},
        "release_boundary": (
            "This bundle only converts already-audited XYZ candidates into convenient "
            "static PDB MODEL records. It has no time axis or simulation engine, makes "
            "no review decision, creates no parameter target, advances no gate, and "
            "must never be packaged as a NADOC Help trajectory."
        ),
    }
    manifest_path = output_dir / "review_visualization_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def build_coupled_conformer_review_decision_template(
    *, review_index_path: Path, output_path: Path
) -> dict[str, Any]:
    """Create a small immutable-source decision overlay for qualified reviewers."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite conformer review decision template: {output_path}"
        )
    _index, records = _validated_review_visualization_sources(review_index_path)
    template = {
        "schema": "nadoc.photoproduct-coupled-conformer-review-decisions.v1",
        "status": "human_input_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "source_review_index": _source(review_index_path),
        "review_count": len(records),
        "reviews": [
            {
                "product_id": record["product_id"],
                "model_id": record["model_id"],
                "source_plan": record["plan"],
                "reviewed_by": None,
                "reviewed_at": None,
                "review_rationale": None,
                "conformers": [
                    {
                        "id": frame["conformer_id"],
                        "candidate_id": frame["candidate_id"],
                        "source_geometry_sha256": frame["geometry"]["sha256"],
                        "review_decision": None,
                        "partition": None,
                        "review_notes": None,
                    }
                    for frame in record["frames"]
                ],
            }
            for record in records
        ],
        "instructions": (
            "A qualified reviewer must set status to human_review_complete; supply "
            "reviewed_by, a timezone-qualified reviewed_at timestamp, and a substantive "
            "review_rationale for every product; and accept or reject every conformer. "
            "Accepted conformers require a training or validation partition, rejected "
            "conformers require null partition, and every decision requires review_notes."
        ),
        "release_boundary": (
            "This overlay protects the pristine source plans but makes no decision. "
            "Materialization revalidates all source hashes, geometry, chirality, and "
            "partition completeness and still advances no registry gate."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(template, indent=2) + "\n")
    return template


def _validate_reviewed_coupled_conformer_payload(
    plan: dict[str, Any],
) -> dict[str, Any]:
    if (
        plan.get("schema") != "nadoc.photoproduct-coupled-conformer-plan.v1"
        or plan.get("simulation_ready") is not False
        or plan.get("gate_effect") != "none"
    ):
        raise ValueError("coupled-conformer plan identity or gate status is invalid")
    authority = str(plan.get("status") or "")
    automated = authority == "quantitatively_screened"
    if authority == "reviewed":
        if (
            not isinstance(plan.get("reviewed_by"), str)
            or not plan["reviewed_by"].strip()
            or not _validate_timestamp(plan.get("reviewed_at"))
            or not isinstance(plan.get("review_rationale"), str)
            or len(plan["review_rationale"].strip()) < 20
        ):
            raise ValueError(
                "coupled-conformer plan lacks an explicit complete human review"
            )
    elif automated:
        screen = plan.get("quantitative_screening") or {}
        policy_path = _checked(screen.get("policy_source"), "quantitative policy")
        policy = json.loads(policy_path.read_text())
        conformer_policy = (policy.get("automated_qm_input_gates") or {}).get(
            "coupled_conformer"
        ) or {}
        if (
            policy.get("schema") != "nadoc.photoproduct-parameter-acceptance.v2"
            or screen.get("schema")
            != "nadoc.photoproduct-coupled-conformer-quantitative-screen.v1"
            or screen.get("status") != "passed_qm_input_screen"
            or screen.get("policy") != conformer_policy.get("policy")
            or screen.get("partition_policy")
            != conformer_policy.get("partition_policy")
            or screen.get("authorizes") != "fixed_geometry_qm_evidence_generation_only"
            or screen.get("releases_parameters") is not False
        ):
            raise ValueError(
                "automated conformer screen is incomplete or policy-mismatched"
            )
    else:
        raise ValueError(
            "coupled-conformer plan requires human review or a passed quantitative QM-input screen"
        )
    sources = plan.get("sources") or {}
    optimized_record = sources.get("optimized_model_audit")
    mode_source_record = sources.get("conformer_mode_source")
    if (optimized_record is None) == (mode_source_record is None):
        raise ValueError(
            "reviewed plan requires exactly one optimized audit or mode source"
        )
    audit_path = (
        _checked(optimized_record, "optimized-model audit")
        if optimized_record is not None
        else None
    )
    mode_source_path = (
        _checked(mode_source_record, "conformer mode source")
        if mode_source_record is not None
        else None
    )
    reference_path = _checked(sources.get("reference_geometry"), "reference geometry")
    graph_path = _checked(sources.get("model_graph"), "model graph")
    map_path = _checked(sources.get("stable_atom_map"), "stable atom map")
    stereo_path = _checked(
        sources.get("stereochemistry_evidence"), "stereochemistry evidence"
    )
    rank_screen_record = sources.get("rank_screen")
    if rank_screen_record is not None:
        rank_screen_path = _checked(rank_screen_record, "conformer rank screen")
        rank_screen = json.loads(rank_screen_path.read_text())
        if (
            rank_screen.get("schema")
            != "nadoc.photoproduct-coupled-conformer-rank-screen.v1"
            or rank_screen.get("status") != "diagnostic_only_candidates_not_reviewed"
            or rank_screen.get("gate_effect") != "none"
            or rank_screen.get("product_id") != plan.get("product_id")
            or rank_screen.get("model_id") != plan.get("model_id")
        ):
            raise ValueError("reviewed plan rank screen changed identity or status")
    candidate_manifest_record = sources.get("candidate_manifest")
    selection = plan.get("candidate_selection") or {}
    selected_candidate_records: dict[str, dict[str, Any]] = {}
    if candidate_manifest_record is not None:
        candidate_manifest_path = _checked(
            candidate_manifest_record, "coupled-conformer candidate manifest"
        )
        candidate_manifest = json.loads(candidate_manifest_path.read_text())
        if (
            candidate_manifest.get("schema")
            != "nadoc.photoproduct-coupled-conformer-candidates.v1"
            or candidate_manifest.get("status") != "candidates_not_reviewed"
            or candidate_manifest.get("simulation_ready") is not False
            or candidate_manifest.get("gate_effect") != "none"
            or candidate_manifest.get("product_id") != plan.get("product_id")
            or candidate_manifest.get("model_id") != plan.get("model_id")
            or selection.get("scientific_effect") != "review_queue_only"
        ):
            raise ValueError(
                "reviewed plan candidate manifest changed identity or status"
            )
        selected = _select_candidate_records(
            candidate_manifest, str(selection.get("policy") or "")
        )
        selected_ids = [str(item["id"]) for item in selected]
        if selection.get("selected_candidate_ids") != selected_ids:
            raise ValueError("reviewed plan candidate selection changed")
        selected_candidate_records = {str(item["id"]): item for item in selected}
    elif selection and (
        selection.get("policy") != "explicit-paths"
        or selection.get("scientific_effect") != "review_queue_only"
    ):
        raise ValueError("reviewed plan explicit candidate selection changed")
    product_id, model_id = plan.get("product_id"), plan.get("model_id")
    if audit_path is not None:
        audit = json.loads(audit_path.read_text())
        if (
            audit.get("product_id") != product_id
            or audit.get("model_id") != model_id
            or audit.get("status")
            not in {
                "passed_identity_and_chirality",
                "passed_candidate_identity_and_chirality",
            }
            or (audit.get("optimized_xyz") or {}).get("sha256")
            != _sha256(reference_path)
        ):
            raise ValueError("reviewed conformer plan reference optimization changed")
    else:
        mode_source = json.loads(mode_source_path.read_text())
        mode_sources = mode_source.get("sources") or {}
        if (
            mode_source.get("schema") != "nadoc.photoproduct-conformer-mode-source.v1"
            or mode_source.get("status") != "candidate_mode_source_not_fit_target"
            or mode_source.get("simulation_ready") is not False
            or mode_source.get("gate_effect") != "none"
            or mode_source.get("contains_parameter_targets") is not False
            or mode_source.get("chemical_definition_gate_required_before_fit_targets")
            is not True
            or mode_source.get("product_id") != product_id
            or mode_source.get("model_id") != model_id
            or (mode_source.get("source_geometry") or {}).get("sha256")
            != _sha256(reference_path)
            or (mode_sources.get("model_graph") or {}).get("sha256")
            != _sha256(graph_path)
            or (mode_sources.get("stable_atom_map") or {}).get("sha256")
            != _sha256(map_path)
            or (mode_sources.get("stereochemistry_evidence") or {}).get("sha256")
            != _sha256(stereo_path)
        ):
            raise ValueError("reviewed conformer plan mode source changed")
    keys = _stable_keys(map_path)
    if keys != plan.get("atom_map"):
        raise ValueError("reviewed conformer plan atom map changed")
    graph = _graph(graph_path, keys)
    stereo_payload, stereo = _stereo_records(stereo_path, product_id, model_id)
    reference, reference_coordinates = _coordinates(reference_path, graph, keys)
    if not _chirality(stereo, reference_coordinates)["passed"]:
        raise ValueError("reference optimized geometry now fails stereochemistry")
    conformers = plan.get("conformers") or []
    if len(conformers) < 2 or len({item.get("id") for item in conformers}) != len(
        conformers
    ):
        raise ValueError("reviewed conformer plan requires at least two unique targets")
    partitions = []
    checked = []
    geometry_hashes: set[str] = set()
    reference_hash = _sha256(reference_path)
    for item in conformers:
        decision = item.get("review_decision")
        notes = item.get("review_notes")
        if (
            decision not in {"accepted", "rejected"}
            or not isinstance(notes, str)
            or len(notes.strip()) < 12
        ):
            raise ValueError(
                f"conformer {item.get('id')!r} lacks an explicit review decision"
            )
        path = _checked(item.get("geometry"), f"conformer {item['id']} geometry")
        geometry_hash = _sha256(path)
        source_candidate_id = item.get("source_candidate_id")
        if selected_candidate_records:
            source_record = selected_candidate_records.get(str(source_candidate_id))
            if (
                source_record is None
                or (source_record.get("geometry") or {}).get("sha256") != geometry_hash
            ):
                raise ValueError(
                    f"conformer {item['id']} differs from its selected source candidate"
                )
        elif source_candidate_id is not None:
            raise ValueError(
                f"explicit conformer {item['id']} cannot claim a source candidate ID"
            )
        if geometry_hash == reference_hash or geometry_hash in geometry_hashes:
            raise ValueError(
                "reviewed conformer geometries must remain distinct from each other "
                "and the reference minimum"
            )
        geometry_hashes.add(geometry_hash)
        xyz, coordinates = _coordinates(path, graph, keys)
        chirality = _chirality(stereo, coordinates)
        metrics = _geometry_metrics(
            graph=graph, keys=keys, reference=reference, candidate=xyz
        )
        if decision == "rejected":
            if item.get("partition") is not None:
                raise ValueError(
                    f"rejected conformer {item.get('id')!r} cannot enter a fit partition"
                )
            if not _derived_audit_equal(
                item.get("chirality_audit"), chirality
            ) or not _derived_audit_equal(item.get("geometry_audit"), metrics):
                raise ValueError(
                    f"conformer {item['id']} stored audit differs from recomputation"
                )
            continue
        if item.get("partition") not in {"training", "validation"}:
            raise ValueError(
                f"accepted conformer {item.get('id')!r} lacks a fit partition"
            )
        if not chirality["passed"] or not metrics["passed"]:
            raise ValueError(
                f"conformer {item['id']} fails recomputed chirality/geometry checks"
            )
        if not _derived_audit_equal(
            item.get("chirality_audit"), chirality
        ) or not _derived_audit_equal(item.get("geometry_audit"), metrics):
            raise ValueError(
                f"conformer {item['id']} stored audit differs from recomputation"
            )
        if automated:
            source_record = selected_candidate_records.get(str(source_candidate_id))
            if source_record is None:
                raise ValueError(
                    "automated screen requires mode-backed conformer candidates"
                )
            rank = int(source_record.get("mode_rank_by_active_fraction") or 0)
            displacement = float(
                source_record.get("signed_active_rmsd_angstrom") or 0.0
            )
            expected_partition = (
                "training"
                if (rank % 2 == 1 and displacement < 0.0)
                or (rank % 2 == 0 and displacement > 0.0)
                else "validation"
            )
            if (
                rank not in {1, 2}
                or displacement == 0.0
                or item.get("partition") != expected_partition
            ):
                raise ValueError(
                    f"conformer {item['id']} violates the automated partition policy"
                )
            thresholds = conformer_policy
            rmsd_rule = thresholds["proper_rotation_aligned_rmsd_angstrom"]
            bond_rule = thresholds["graph_bond_length_ratio_to_qm_minimum"]
            clash_rule = thresholds["minimum_nonbonded_covalent_radius_ratio"]
            if not (
                float(rmsd_rule["minimum"])
                <= metrics["proper_rotation_aligned_rmsd_angstrom"]
                <= float(rmsd_rule["maximum"])
                and float(bond_rule["minimum"]) <= metrics["minimum_graph_bond_ratio"]
                and metrics["maximum_graph_bond_ratio"] <= float(bond_rule["maximum"])
                and metrics["closest_nonbonded_pair"]["covalent_radius_ratio"]
                >= float(clash_rule["minimum"])
            ):
                raise ValueError(
                    f"conformer {item['id']} fails the quantitative QM-input thresholds"
                )
        partitions.append(item["partition"])
        checked.append({**item, "geometry_path": str(path)})
    if set(partitions) != {"training", "validation"}:
        raise ValueError(
            "reviewed plan must reserve at least one independent validation conformer"
        )
    return {
        "plan": plan,
        "conformers": checked,
        "atom_map": keys,
        "stereochemistry_evidence": stereo_payload,
        "stereochemistry_records": stereo,
    }


def validate_reviewed_coupled_conformer_plan(plan_path: Path) -> dict[str, Any]:
    """Recompute every geometry check for human or policy-screened QM inputs."""

    return _validate_reviewed_coupled_conformer_payload(
        json.loads(plan_path.read_text())
    )


def materialize_quantitatively_screened_coupled_conformer_plan(
    *,
    plan_path: Path,
    output_path: Path,
    policy_path: Path = PARAMETER_ACCEPTANCE_PATH,
) -> dict[str, Any]:
    """Replace the visual bottleneck with a hash-pinned, preregistered input screen.

    Passing this screen authorizes expensive fixed-geometry QM evidence generation only.
    It deliberately has no registry effect and cannot release force-field parameters.
    """

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite quantitative screen: {output_path}"
        )
    source = json.loads(plan_path.read_text())
    policy = json.loads(policy_path.read_text())
    conformer_policy = (policy.get("automated_qm_input_gates") or {}).get(
        "coupled_conformer"
    ) or {}
    if (
        source.get("schema") != "nadoc.photoproduct-coupled-conformer-plan.v1"
        or source.get("status") != "review_required"
        or source.get("simulation_ready") is not False
        or source.get("gate_effect") != "none"
        or source.get("reviewed_by") is not None
        or source.get("reviewed_at") is not None
        or source.get("review_rationale") is not None
    ):
        raise ValueError(
            "quantitative screening requires a pristine review-required plan"
        )
    if (
        policy.get("schema") != "nadoc.photoproduct-parameter-acceptance.v2"
        or conformer_policy.get("policy") != "proper-rotation-coupled-response-v1"
        or conformer_policy.get("partition_policy") != "alternating-mode-sign-v1"
    ):
        raise ValueError("unsupported or malformed quantitative acceptance policy")
    candidate_path = _checked(
        (source.get("sources") or {}).get("candidate_manifest"),
        "coupled-conformer candidate manifest",
    )
    candidate_manifest = json.loads(candidate_path.read_text())
    selected = _select_candidate_records(
        candidate_manifest,
        str((source.get("candidate_selection") or {}).get("policy") or ""),
    )
    by_id = {str(item["id"]): item for item in selected}
    screened = deepcopy(source)
    screened["status"] = "quantitatively_screened"
    screened["reviewed_by"] = None
    screened["reviewed_at"] = None
    screened["review_rationale"] = None
    screened["quantitative_screening"] = {
        "schema": "nadoc.photoproduct-coupled-conformer-quantitative-screen.v1",
        "status": "passed_qm_input_screen",
        "policy": conformer_policy["policy"],
        "partition_policy": conformer_policy["partition_policy"],
        "policy_source": _source(policy_path),
        "source_plan": _source(plan_path),
        "authorizes": "fixed_geometry_qm_evidence_generation_only",
        "releases_parameters": False,
    }
    for conformer in screened.get("conformers") or []:
        candidate = by_id.get(str(conformer.get("source_candidate_id") or ""))
        if candidate is None:
            raise ValueError(
                "pristine plan differs from its selected candidate manifest"
            )
        rank = int(candidate.get("mode_rank_by_active_fraction") or 0)
        displacement = float(candidate.get("signed_active_rmsd_angstrom") or 0.0)
        conformer["partition"] = (
            "training"
            if (rank % 2 == 1 and displacement < 0.0)
            or (rank % 2 == 0 and displacement > 0.0)
            else "validation"
        )
        conformer["review_decision"] = "accepted"
        conformer["review_notes"] = (
            "Accepted by the hash-pinned quantitative QM-input policy; identity, "
            "proper-rotation geometry, signed stereocenters, bond ratios, and internal "
            "overlap screen are recomputed when this plan is consumed."
        )
    _validate_reviewed_coupled_conformer_payload(screened)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(screened, indent=2) + "\n")
    return screened


def materialize_visual_coupled_conformer_review(
    *,
    review_index_path: Path,
    visual_decisions_path: Path,
    output_dir: Path,
    product_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Translate complete current UI decisions into audited reviewed plans."""

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite visual conformer-review output: {output_dir}"
        )
    review_index_path = review_index_path.resolve()
    visual_decisions_path = visual_decisions_path.resolve()
    _index, all_records = _validated_review_visualization_sources(review_index_path)
    available_ids = {record["product_id"] for record in all_records}
    requested_ids = set(product_ids) if product_ids else available_ids
    if not requested_ids or not requested_ids <= available_ids:
        raise ValueError(
            f"requested conformer-review products are unavailable: {sorted(requested_ids - available_ids)}"
        )
    records = [
        record for record in all_records if record["product_id"] in requested_ids
    ]
    visual = json.loads(visual_decisions_path.read_text())
    if (
        visual.get("schema") != "nadoc.photoproduct-visual-review-decisions.v1"
        or visual.get("simulation_ready") is not False
        or visual.get("gate_effect") != "none"
        or visual.get("source_conformer_index") != _source(review_index_path)
    ):
        raise ValueError(
            "visual decisions do not match the current conformer-review index"
        )
    raw = [
        item
        for item in visual.get("decisions") or []
        if isinstance(item, dict)
        and item.get("stage") == "coupled_conformer"
        and item.get("product_id") in requested_ids
    ]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw:
        key = (str(item.get("product_id") or ""), str(item.get("conformer_id") or ""))
        if "" in key or key in by_key:
            raise ValueError(
                "visual conformer decisions contain duplicate/missing identities"
            )
        by_key[key] = item
    expected = {
        (record["product_id"], frame["conformer_id"])
        for record in records
        for frame in record["frames"]
    }
    if set(by_key) != expected:
        raise ValueError(
            "visual decisions must cover every indexed conformer exactly once"
        )

    reviews = []
    for record in records:
        product_id = record["product_id"]
        product_decisions = [
            by_key[(product_id, frame["conformer_id"])] for frame in record["frames"]
        ]
        if any(item.get("decision") == "revise" for item in product_decisions):
            raise ValueError(
                f"{product_id}: revision-requested conformers remain unresolved"
            )
        if any(
            item.get("decision") not in {"approve", "reject"}
            for item in product_decisions
        ):
            raise ValueError(
                f"{product_id}: every conformer requires approve or reject"
            )
        reviewers = {
            str(item.get("reviewer") or "").strip() for item in product_decisions
        }
        if len(reviewers) != 1 or "" in reviewers:
            raise ValueError(
                f"{product_id}: one identified reviewer must sign all conformers"
            )
        timestamps = [
            str(item.get("reviewed_at") or "").strip() for item in product_decisions
        ]
        if not all(_validate_timestamp(value) for value in timestamps):
            raise ValueError(f"{product_id}: review timestamps must include timezones")
        notes = [str(item.get("notes") or "").strip() for item in product_decisions]
        if any(len(note) < 12 for note in notes):
            raise ValueError(
                f"{product_id}: every conformer needs a substantive rationale"
            )
        conformers = []
        for frame, decision, note in zip(
            record["frames"], product_decisions, notes, strict=True
        ):
            if decision.get("source_geometry_sha256") != frame["geometry"]["sha256"]:
                raise ValueError(
                    f"{product_id}/{frame['conformer_id']}: visual decision is stale"
                )
            approved = decision["decision"] == "approve"
            partition = decision.get("partition")
            if approved and partition not in {"training", "validation"}:
                raise ValueError(
                    f"{product_id}/{frame['conformer_id']}: approval needs a partition"
                )
            if not approved and partition is not None:
                raise ValueError(
                    f"{product_id}/{frame['conformer_id']}: rejection cannot be partitioned"
                )
            conformers.append(
                {
                    "id": frame["conformer_id"],
                    "candidate_id": frame["candidate_id"],
                    "source_geometry_sha256": frame["geometry"]["sha256"],
                    "review_decision": "accepted" if approved else "rejected",
                    "partition": partition if approved else None,
                    "review_notes": note,
                }
            )
        accepted_partitions = {
            item["partition"]
            for item in conformers
            if item["review_decision"] == "accepted"
        }
        if accepted_partitions != {"training", "validation"}:
            raise ValueError(
                f"{product_id}: approvals must include training and validation"
            )
        reviews.append(
            {
                "product_id": product_id,
                "model_id": record["model_id"],
                "source_plan": record["plan"],
                "reviewed_by": next(iter(reviewers)),
                "reviewed_at": max(timestamps),
                "review_rationale": (
                    "Per-conformer visual rationales: "
                    + " | ".join(
                        f"{item['id']}: {item['review_notes']}" for item in conformers
                    )
                ),
                "conformers": conformers,
            }
        )

    output_dir.mkdir(parents=True)
    overlay_path = output_dir / "coupled_conformer_visual_decisions.json"
    overlay = {
        "schema": "nadoc.photoproduct-coupled-conformer-review-decisions.v1",
        "status": "human_review_complete",
        "simulation_ready": False,
        "gate_effect": "none",
        "source_review_index": _source(review_index_path),
        "source_visual_decisions": _source(visual_decisions_path),
        "scope_product_ids": [record["product_id"] for record in records],
        "review_count": len(reviews),
        "reviews": reviews,
        "release_boundary": (
            "This overlay records visual structure decisions only and cannot release "
            "chemical definitions, QM targets, parameters, or simulations."
        ),
    }
    overlay_path.write_text(json.dumps(overlay, indent=2) + "\n")
    reviewed_dir = output_dir / "reviewed_plans"
    reviewed = apply_coupled_conformer_review_decisions(
        decisions_path=overlay_path, output_dir=reviewed_dir
    )
    receipt = {
        "schema": "nadoc.photoproduct-visual-conformer-review-materialization.v1",
        "status": "passed_human_review_structure",
        "passed": True,
        "simulation_ready": False,
        "gate_effect": "none",
        "source_visual_decisions": _source(visual_decisions_path),
        "decision_overlay": _source(overlay_path),
        "reviewed_plans_manifest": _source(
            reviewed_dir / "reviewed_plans_manifest.json"
        ),
        "product_count": reviewed["product_count"],
    }
    receipt_path = output_dir / "materialization_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def apply_coupled_conformer_review_decisions(
    *, decisions_path: Path, output_dir: Path
) -> dict[str, Any]:
    """Materialize reviewed plans without modifying the pristine generated plans."""

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite materialized conformer reviews: {output_dir}"
        )
    decisions = json.loads(decisions_path.read_text())
    reviews = decisions.get("reviews") or []
    if (
        decisions.get("schema")
        != "nadoc.photoproduct-coupled-conformer-review-decisions.v1"
        or decisions.get("status") != "human_review_complete"
        or decisions.get("simulation_ready") is not False
        or decisions.get("gate_effect") != "none"
        or decisions.get("review_count") != len(reviews)
        or not reviews
    ):
        raise ValueError(
            "decision overlay lacks an explicit complete gate-neutral human review"
        )
    review_index_path = _checked(
        decisions.get("source_review_index"), "decision overlay review index"
    )
    _index, source_records = _validated_review_visualization_sources(review_index_path)
    scope = decisions.get("scope_product_ids")
    if scope is not None:
        if (
            not isinstance(scope, list)
            or not scope
            or len(scope) != len(set(scope))
            or not all(isinstance(item, str) and item for item in scope)
        ):
            raise ValueError("decision overlay product scope is malformed")
        available = {record["product_id"] for record in source_records}
        if not set(scope) <= available:
            raise ValueError("decision overlay product scope is not indexed")
        source_records = [
            record for record in source_records if record["product_id"] in set(scope)
        ]
    review_by_product = {
        str(review.get("product_id") or ""): review for review in reviews
    }
    if (
        len(review_by_product) != len(reviews)
        or "" in review_by_product
        or set(review_by_product) != {record["product_id"] for record in source_records}
    ):
        raise ValueError(
            "decision overlay must cover each indexed product exactly once"
        )

    prepared: list[tuple[str, dict[str, Any]]] = []
    names: set[str] = set()
    for source in source_records:
        product_id = source["product_id"]
        review = review_by_product[product_id]
        if (
            review.get("model_id") != source["model_id"]
            or review.get("source_plan") != source["plan"]
        ):
            raise ValueError(f"{product_id}: review overlay source identity changed")
        decision_items = review.get("conformers") or []
        decisions_by_id = {str(item.get("id") or ""): item for item in decision_items}
        frames_by_id = {frame["conformer_id"]: frame for frame in source["frames"]}
        if (
            len(decisions_by_id) != len(decision_items)
            or "" in decisions_by_id
            or set(decisions_by_id) != set(frames_by_id)
        ):
            raise ValueError(
                f"{product_id}: review overlay must cover each conformer exactly once"
            )
        source_plan_path = _checked(source["plan"], f"{product_id} source review plan")
        reviewed_plan = deepcopy(json.loads(source_plan_path.read_text()))
        reviewed_plan["status"] = "reviewed"
        reviewed_plan["reviewed_by"] = review.get("reviewed_by")
        reviewed_plan["reviewed_at"] = review.get("reviewed_at")
        reviewed_plan["review_rationale"] = review.get("review_rationale")
        for conformer in reviewed_plan.get("conformers") or []:
            decision = decisions_by_id[conformer["id"]]
            frame = frames_by_id[conformer["id"]]
            if (
                decision.get("candidate_id") != frame["candidate_id"]
                or decision.get("source_geometry_sha256") != frame["geometry"]["sha256"]
            ):
                raise ValueError(
                    f"{product_id}/{conformer['id']}: review source geometry changed"
                )
            conformer["review_decision"] = decision.get("review_decision")
            conformer["partition"] = decision.get("partition")
            conformer["review_notes"] = decision.get("review_notes")
        _validate_reviewed_coupled_conformer_payload(reviewed_plan)
        stem = re.sub(r"[^a-z0-9._-]+", "-", product_id.lower()).strip("-.")
        if not stem or stem in names:
            raise ValueError("product IDs do not map to unique safe review filenames")
        names.add(stem)
        prepared.append((stem, reviewed_plan))

    output_dir.mkdir(parents=True)
    outputs = []
    for stem, reviewed_plan in prepared:
        plan_path = output_dir / f"{stem}.reviewed.json"
        plan_path.write_text(json.dumps(reviewed_plan, indent=2) + "\n")
        audit_path = output_dir / f"{stem}.review-audit.json"
        audit = audit_reviewed_coupled_conformer_plan(
            plan_path=plan_path, output_path=audit_path
        )
        outputs.append(
            {
                "product_id": reviewed_plan["product_id"],
                "reviewed_plan": _source(plan_path),
                "review_audit": _source(audit_path),
                "counts": audit["counts"],
            }
        )
    manifest = {
        "schema": "nadoc.photoproduct-coupled-conformer-reviewed-plans.v1",
        "status": "passed_human_review_structure",
        "simulation_ready": False,
        "gate_effect": "none",
        "authorizes_qm": False,
        "source_decisions": _source(decisions_path),
        "source_review_index": _source(review_index_path),
        "product_count": len(outputs),
        "products": outputs,
        "release_boundary": (
            "These plans passed structural ingestion of human-supplied decisions only. "
            "They do not release chemical definitions or parameters and do not mutate "
            "the registry. Fixed-geometry QM independently revalidates a selected plan "
            "and requires the matching released chemical definition."
        ),
    }
    manifest_path = output_dir / "reviewed_plans_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def audit_reviewed_coupled_conformer_plan(
    *, plan_path: Path, output_path: Path
) -> dict[str, Any]:
    """Write a deterministic receipt for a human or quantitative conformer screen.

    This receipt advances no registry gate and is not accepted in place of the source
    plan. Fixed-geometry job generation deliberately reopens and revalidates that plan.
    """

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite coupled-conformer review audit: {output_path}"
        )
    reviewed = validate_reviewed_coupled_conformer_plan(plan_path)
    plan = reviewed["plan"]
    accepted = []
    rejected = []
    for item in plan["conformers"]:
        record = {
            "id": item["id"],
            "source_candidate_id": item.get("source_candidate_id"),
            "geometry": item["geometry"],
            "review_notes": item["review_notes"],
        }
        if item["review_decision"] == "accepted":
            accepted.append({**record, "partition": item["partition"]})
        else:
            rejected.append(record)
    partition_counts = {
        name: sum(item["partition"] == name for item in accepted)
        for name in ("training", "validation")
    }
    automated = plan["status"] == "quantitatively_screened"
    authority = (
        {"kind": "automated_quantitative_policy", **plan["quantitative_screening"]}
        if automated
        else {
            "kind": "human_review",
            "reviewed_by": plan["reviewed_by"],
            "reviewed_at": plan["reviewed_at"],
            "review_rationale": plan["review_rationale"],
        }
    )
    audit = {
        "schema": "nadoc.photoproduct-coupled-conformer-review-audit.v1",
        "status": (
            "passed_quantitative_qm_input_screen"
            if automated
            else "passed_human_review_structure"
        ),
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": plan["product_id"],
        "model_id": plan["model_id"],
        "source_plan": _source(plan_path),
        "decision_authority": authority,
        "counts": {
            "total": len(plan["conformers"]),
            "accepted": len(accepted),
            "rejected": len(rejected),
            **partition_counts,
        },
        "accepted_conformers": accepted,
        "rejected_conformers": rejected,
        "release_boundary": (
            "This audit confirms a complete hash-linked conformer-input decision only. "
            "It creates no QM result, parameter target, force-field asset, or registry "
            "gate pass; fixed-geometry job generation revalidates the source plan."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit, indent=2) + "\n")
    return audit


def _require_released_stereochemistry_before_qm(
    reviewed: dict[str, Any],
) -> None:
    payload = reviewed["stereochemistry_evidence"]
    if payload.get("schema") == "nadoc.photoproduct-chemical-definition.v1":
        return
    if payload.get("schema") != "nadoc.tt-cpd-stereo-candidate.v1":
        raise ValueError(
            "reviewed conformer plan has unsupported stereochemistry evidence"
        )

    from backend.core.photoproduct_chemistry import load_chemical_definition
    from backend.core.photoproduct_registry import photoproduct_registry

    product_id = reviewed["plan"]["product_id"]
    entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == product_id
        ),
        None,
    )
    if entry is None or entry["gates"]["chemical_definition"]["status"] != "passed":
        raise ValueError(
            "fixed-geometry QM requires the product chemical_definition gate to pass"
        )
    definition = load_chemical_definition(entry["product"], entry["stereochemistry"])
    released_records = [
        {
            "atom": item["atom"],
            "reference_atoms": item["signed_volume_reference_atoms"],
            "expected_sign": item["expected_signed_volume"],
        }
        for item in definition.get("product_stereocenters") or []
    ]
    if released_records != reviewed["stereochemistry_records"]:
        raise ValueError(
            "released chemical definition differs from reviewed candidate stereochemistry"
        )


def generate_fixed_geometry_hessian_job(
    *,
    plan_path: Path,
    conformer_id: str,
    output_dir: Path,
    charge: int,
    multiplicity: int = 1,
    memory_gib: int = 8,
    threads: int = 8,
    protocol_path: Path = QM_PROTOCOL_PATH,
) -> dict[str, Any]:
    """Generate a no-optimization gradient/Hessian job from one reviewed conformer."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite fixed-geometry job: {output_dir}")
    reviewed = validate_reviewed_coupled_conformer_plan(plan_path)
    _require_released_stereochemistry_before_qm(reviewed)
    matches = [item for item in reviewed["conformers"] if item["id"] == conformer_id]
    if len(matches) != 1:
        raise ValueError(f"reviewed plan has no unique conformer {conformer_id!r}")
    target = matches[0]
    plan = reviewed["plan"]
    manifest = generate_psi4_job(
        product_id=plan["product_id"],
        model_id=plan["model_id"],
        xyz_path=Path(target["geometry_path"]),
        output_dir=output_dir,
        job_kind="fixed_geometry_hessian",
        charge=charge,
        multiplicity=multiplicity,
        atom_map=reviewed["atom_map"],
        memory_gib=memory_gib,
        threads=threads,
        protocol_path=protocol_path,
        coupled_conformer_plan_path=plan_path,
        conformer_id=conformer_id,
    )
    return manifest


def audit_fixed_geometry_hessian_result(job_dir: Path) -> dict[str, Any]:
    """Hash-audit a completed fixed-geometry gradient and full Cartesian Hessian."""

    job_path = job_dir / "job_manifest.json"
    run_path = job_dir / "run_manifest.json"
    output_path = job_dir / "output.dat"
    gradient_path = job_dir / "gradient_hartree_per_bohr.txt"
    hessian_path = job_dir / "hessian_hartree_per_bohr2.txt"
    required = (job_path, run_path, output_path, gradient_path, hessian_path)
    if not all(path.is_file() for path in required):
        raise ValueError(
            "fixed-geometry job, run, gradient, Hessian, and raw output are required"
        )
    job = json.loads(job_path.read_text())
    run = json.loads(run_path.read_text())
    reconciliation_path = job_dir / "run_reconciliation.json"
    effective_path = reconciliation_path if reconciliation_path.is_file() else run_path
    effective = (
        json.loads(reconciliation_path.read_text())
        if reconciliation_path.is_file()
        else run
    )
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "fixed_geometry_hessian"
        or job.get("status") != "generated_not_run"
        or job.get("gate_effect") != "none"
        or effective.get("status") != "completed_unreviewed"
        or effective.get("job_manifest_sha256") != _sha256(job_path)
    ):
        raise ValueError(
            "fixed-geometry job and completion record are not a matching pair"
        )
    plan_path = _checked(job.get("coupled_conformer_plan"), "coupled-conformer plan")
    reviewed = validate_reviewed_coupled_conformer_plan(plan_path)
    target = next(
        (
            item
            for item in reviewed["conformers"]
            if item["id"] == (job.get("conformer") or {}).get("id")
        ),
        None,
    )
    source_path = _checked(job.get("source_xyz"), "fixed-geometry source")
    if (
        target is None
        or target["geometry"]["sha256"] != _sha256(source_path)
        or job.get("atom_map") != reviewed["atom_map"]
        or (job.get("conformer") or {}).get("partition") != target["partition"]
    ):
        raise ValueError("fixed-geometry job differs from its reviewed conformer")
    output_records = effective.get("outputs") or {}
    for path in (output_path, gradient_path, hessian_path):
        if (output_records.get(path.name) or {}).get("sha256") != _sha256(path):
            raise ValueError(f"completed fixed-geometry {path.name} is hash-mismatched")
    center_energy = (effective.get("parsed") or {}).get("final_energy_hartree")
    if (
        isinstance(center_energy, bool)
        or not isinstance(center_energy, (int, float))
        or not math.isfinite(float(center_energy))
    ):
        raise ValueError("fixed-geometry run lacks a finite center electronic energy")
    dimension = 3 * int(job.get("atom_count") or 0)
    gradient = np.loadtxt(gradient_path, ndmin=1).reshape(-1)
    hessian = np.loadtxt(hessian_path, ndmin=2)
    if (
        dimension <= 0
        or gradient.shape != (dimension,)
        or hessian.shape != (dimension, dimension)
        or not np.all(np.isfinite(gradient))
        or not np.all(np.isfinite(hessian))
    ):
        raise ValueError("fixed-geometry gradient or Hessian has invalid shape/values")
    symmetry_error = float(np.max(np.abs(hessian - hessian.T)))
    if symmetry_error > 1.0e-8:
        raise ValueError("fixed-geometry Cartesian Hessian exceeds symmetry tolerance")
    report = {
        "schema": "nadoc.photoproduct-fixed-geometry-hessian-audit.v1",
        "status": "passed_candidate_response_evidence",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "conformer_id": target["id"],
        "partition": target["partition"],
        "atom_count": job["atom_count"],
        "atom_map": job["atom_map"],
        "source_geometry": _source(source_path),
        "electronic_energy": {
            "value": float(center_energy),
            "units": "hartree",
            "geometry_sha256": _sha256(source_path),
        },
        "cartesian_gradient": {
            **_source(gradient_path),
            "units": "hartree/bohr",
            "dimension": dimension,
        },
        "cartesian_hessian": {
            **_source(hessian_path),
            "units": "hartree/bohr^2",
            "dimension": dimension,
            "maximum_symmetry_error": symmetry_error,
        },
        "qm_job": _source(job_path),
        "effective_run_record": _source(effective_path),
        "coupled_conformer_plan": _source(plan_path),
        "interpretation": (
            "This is a reviewed-coordinate, gate-neutral QM force/Hessian target. It is "
            "not a harmonic minimum, a parameter fit, or a simulation-ready force field."
        ),
    }
    report_path = job_dir / "fixed_geometry_hessian_audit.json"
    if report_path.exists():
        raise FileExistsError(
            f"refusing to overwrite fixed-geometry audit: {report_path}"
        )
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_fixed_geometry_hessian_target_bundle(
    *, job_dir: Path, output_path: Path
) -> dict[str, Any]:
    """Expose audited nonstationary QM derivatives to the linear-response builder."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite fixed-geometry target: {output_path}"
        )
    job_path = job_dir / "job_manifest.json"
    audit_path = job_dir / "fixed_geometry_hessian_audit.json"
    if not job_path.is_file() or not audit_path.is_file():
        raise ValueError("fixed-geometry job and passed derivative audit are required")
    job = json.loads(job_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (
        audit.get("schema") != "nadoc.photoproduct-fixed-geometry-hessian-audit.v1"
        or audit.get("status") != "passed_candidate_response_evidence"
        or audit.get("gate_effect") != "none"
        or audit.get("product_id") != job.get("product_id")
        or audit.get("model_id") != job.get("model_id")
        or (audit.get("qm_job") or {}).get("sha256") != _sha256(job_path)
    ):
        raise ValueError(
            "fixed-geometry job and derivative audit are not a passed matching pair"
        )
    report = {
        "schema": "nadoc.photoproduct-hessian-target-bundle.v2",
        "status": "candidate_off_equilibrium_response_evidence",
        "simulation_ready": False,
        "gate_effect": "none",
        "target_kind": "reviewed_off_equilibrium_conformer",
        "product_id": audit["product_id"],
        "model_id": audit["model_id"],
        "conformer_id": audit["conformer_id"],
        "partition": audit["partition"],
        "atom_count": audit["atom_count"],
        "atom_map": audit["atom_map"],
        "source_geometry": audit["source_geometry"],
        "electronic_energy": audit["electronic_energy"],
        "cartesian_gradient": audit["cartesian_gradient"],
        "cartesian_hessian": audit["cartesian_hessian"],
        "fixed_geometry_hessian_audit": _source(audit_path),
        "coupled_conformer_plan": audit["coupled_conformer_plan"],
        "fit_policy": (
            "Retain the nonzero QM gradient and all coupled Cartesian Hessian entries. "
            "Never reinterpret this off-equilibrium structure as a harmonic minimum."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
