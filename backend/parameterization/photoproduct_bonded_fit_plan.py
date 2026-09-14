"""Build a hash-audited, value-null bonded fitting plan for a photoproduct."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.core.photoproduct_chemistry import (
    chemical_definition_asset,
    load_chemical_definition,
    signed_tetrahedron_volume,
)
from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_terms import enumerate_graph_terms

DIHEDRAL_CONVENTION = "openmm_namd_four_atom_atan2_v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_types(types: list[str]) -> tuple[str, ...]:
    forward = tuple(types)
    reverse = tuple(reversed(types))
    return min(forward, reverse)


def _angle(first: np.ndarray, center: np.ndarray, third: np.ndarray) -> float:
    left = first - center
    right = third - center
    cosine = float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))
    return math.degrees(math.acos(float(np.clip(cosine, -1.0, 1.0))))


def _dihedral(
    first: np.ndarray, second: np.ndarray, third: np.ndarray, fourth: np.ndarray
) -> float:
    # Match the torsion used by NAMD and OpenMM's torsion forces. Negating the
    # first bond is essential; omitting it shifts the result by 180 degrees.
    first_bond = first - second
    middle = third - second
    last_bond = fourth - third
    middle_unit = middle / np.linalg.norm(middle)
    first_plane = first_bond - np.dot(first_bond, middle_unit) * middle_unit
    last_plane = last_bond - np.dot(last_bond, middle_unit) * middle_unit
    x_value = float(np.dot(first_plane, last_plane))
    y_value = float(np.dot(np.cross(middle_unit, first_plane), last_plane))
    return math.degrees(math.atan2(y_value, x_value))


def _coordinate_value(
    category: str, atom_path: list[str], coordinates: dict[str, np.ndarray]
) -> tuple[float, str]:
    points = [coordinates[key] for key in atom_path]
    if category == "bonds":
        return float(np.linalg.norm(points[0] - points[1])), "angstrom"
    if category == "angles":
        return _angle(*points), "degree"
    if category == "dihedrals":
        return _dihedral(*points), "degree"
    raise ValueError(f"unsupported coordinate category: {category}")


def _central_bond_context(
    atom_path: list[str], graph_bonds: list[dict[str, Any]]
) -> dict[str, Any]:
    """Classify whether a proper's central bond can be scanned independently."""

    first, second = atom_path[1:3]
    adjacency: dict[str, set[str]] = {}
    order = None
    for record in graph_bonds:
        left, right = record["atoms"]
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
        if {left, right} == {first, second}:
            order = float(record["order"])
    if order is None:
        raise ValueError("proper central bond is absent from the model graph")
    visited = {first}
    pending = [first]
    while pending:
        current = pending.pop()
        for neighbor in adjacency.get(current, set()):
            if {current, neighbor} == {first, second} or neighbor in visited:
                continue
            if neighbor == second:
                return {
                    "central_bond": [first, second],
                    "central_bond_order": order,
                    "central_bond_in_cycle": True,
                    "target_class": "coupled_ring_response_no_independent_scan",
                }
            visited.add(neighbor)
            pending.append(neighbor)
    if not math.isclose(order, 1.0, abs_tol=1e-8):
        target_class = "conjugated_or_multiple_bond_no_free_rotation_scan"
    else:
        target_class = "relaxed_torsion_scan_candidate"
    return {
        "central_bond": [first, second],
        "central_bond_order": order,
        "central_bond_in_cycle": False,
        "target_class": target_class,
    }


def build_bonded_fit_plan(
    *,
    model_manifest_path: Path,
    hessian_targets_path: Path,
    model_coverage_path: Path,
    improper_convention_audit_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Join fitting evidence without assigning any missing CHARMM parameter value."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite bonded fit plan: {output_path}")
    manifest = json.loads(model_manifest_path.read_text())
    targets = json.loads(hessian_targets_path.read_text())
    coverage = json.loads(model_coverage_path.read_text())
    convention = json.loads(improper_convention_audit_path.read_text())
    identity = (manifest.get("product_id"), manifest.get("model_id"))
    if (
        manifest.get("schema") != "nadoc.photoproduct-model-compound.v1"
        or targets.get("schema") != "nadoc.photoproduct-hessian-target-bundle.v1"
        or coverage.get("schema")
        != "nadoc.photoproduct-model-parameter-coverage-audit.v1"
        or (targets.get("product_id"), targets.get("model_id")) != identity
        or (coverage.get("product_id"), coverage.get("model_id")) != identity
    ):
        raise ValueError("model, Hessian targets, and parameter coverage do not match")
    if (
        convention.get("schema")
        != "nadoc.photoproduct-namd-improper-convention-audit.v1"
        or convention.get("status") != "passed_convention_only"
        or convention.get("passed") is not True
        or convention.get("product_parameter_authority") is not False
    ):
        raise ValueError("a passed gate-neutral NAMD improper convention audit is required")
    coverage_manifest = (coverage.get("sources") or {}).get("model_manifest") or {}
    if coverage_manifest.get("sha256") != _sha256(model_manifest_path):
        raise ValueError("coverage is not hash-linked to the model manifest")

    graph_record = (manifest.get("outputs") or {}).get("graph") or {}
    graph_path = Path(str(graph_record.get("path") or ""))
    if not graph_path.is_file() or _sha256(graph_path) != graph_record.get("sha256"):
        raise ValueError("model graph is missing or hash-mismatched")
    graph = json.loads(graph_path.read_text())
    atom_keys = [item.get("key") for item in graph.get("atoms") or []]
    if (
        graph.get("schema") != "nadoc.photoproduct-model-graph.v1"
        or atom_keys != manifest.get("atom_map")
        or atom_keys != targets.get("atom_map")
    ):
        raise ValueError("model graph and Hessian stable atom order differ")
    graph_bonds = graph.get("bonds") or []
    graph_terms = enumerate_graph_terms([record["atoms"] for record in graph_bonds])
    for category in ("bonds", "angles", "dihedrals"):
        coverage_terms = [
            item.get("atoms")
            for item in (coverage.get("categories") or {})
            .get(category, {})
            .get("terms")
            or []
        ]
        if coverage_terms != graph_terms[category]:
            raise ValueError(
                f"parameter coverage does not exactly enumerate model {category}"
            )

    geometry_record = targets.get("source_geometry") or {}
    geometry_path = Path(str(geometry_record.get("path") or ""))
    hessian_record = targets.get("cartesian_hessian") or {}
    hessian_path = Path(str(hessian_record.get("path") or ""))
    if (
        not geometry_path.is_file()
        or _sha256(geometry_path) != geometry_record.get("sha256")
        or not hessian_path.is_file()
        or _sha256(hessian_path) != hessian_record.get("sha256")
    ):
        raise ValueError("Hessian or optimized geometry is missing or hash-mismatched")
    xyz_atoms, _comment = parse_xyz(geometry_path.read_text())
    graph_elements = [item.get("element") for item in graph["atoms"]]
    xyz_elements = [item[0] for item in xyz_atoms]
    if len(xyz_atoms) != len(atom_keys) or xyz_elements != graph_elements:
        raise ValueError("optimized geometry elements do not match the model graph")
    coordinates = {
        key: np.asarray(atom[1:], dtype=float)
        for key, atom in zip(atom_keys, xyz_atoms, strict=True)
    }
    hessian = np.loadtxt(hessian_path, ndmin=2)
    dimension = 3 * len(atom_keys)
    if (
        hessian.shape != (dimension, dimension)
        or hessian_record.get("dimension") != dimension
        or not np.all(np.isfinite(hessian))
        or not np.allclose(hessian, hessian.T, atol=1e-10)
    ):
        raise ValueError("Cartesian Hessian dimensions, values, or symmetry are invalid")

    fit_groups = []
    transfer_candidates = []
    for category in ("bonds", "angles", "dihedrals"):
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for term in (coverage.get("categories") or {}).get(category, {}).get("terms") or []:
            value, unit = _coordinate_value(category, term["atoms"], coordinates)
            occurrence = {
                "atoms": term["atoms"],
                "observed_coordinate": value,
                "coordinate_unit": unit,
            }
            if category == "dihedrals":
                occurrence.update(_central_bond_context(term["atoms"], graph_bonds))
            if term.get("coverage") == "missing":
                grouped.setdefault(_canonical_types(term["types"]), []).append(occurrence)
            else:
                transfer_candidates.append(
                    {
                        "category": category,
                        "atoms": term["atoms"],
                        "types": term["types"],
                        "coverage": term["coverage"],
                        "matches": term["matches"],
                        "observed_coordinate": value,
                        "coordinate_unit": unit,
                        "status": "transfer_candidate_requires_review",
                    }
                )
        for types, occurrences in sorted(grouped.items()):
            variables: dict[str, Any]
            if category == "bonds":
                variables = {"k_kcal_mol_a2": None, "r0_angstrom": None}
            elif category == "angles":
                variables = {
                    "k_kcal_mol_rad2": None,
                    "theta0_degrees": None,
                    "urey_bradley_k_kcal_mol_a2": None,
                    "urey_bradley_s0_angstrom": None,
                }
            else:
                variables = {"fourier_terms": None}
            target_classes = {
                item.get("target_class") for item in occurrences if item.get("target_class")
            }
            if category != "dihedrals":
                additional_target = "coupled_cartesian_hessian_and_mm_minimum"
            elif target_classes == {"coupled_ring_response_no_independent_scan"}:
                additional_target = "coupled_ring_hessians_and_multiple_conformers"
            elif target_classes == {"relaxed_torsion_scan_candidate"}:
                additional_target = "reviewed_relaxed_torsion_scan"
            else:
                additional_target = "mixed_context_multi_conformer_and_scan_review"
            fit_groups.append(
                {
                    "id": f"{category}:{'-'.join(types)}",
                    "category": category,
                    "canonical_types": list(types),
                    "occurrences": occurrences,
                    "variables": variables,
                    "status": "unassigned_fit_required",
                    "additional_target_requirement": additional_target,
                }
            )

    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == targets["product_id"]
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError("Hessian target product is absent from the registry")
    definition = load_chemical_definition(
        registry_entry["product"], registry_entry["stereochemistry"]
    )
    stereochemical_impropers = []
    coordinate_lists = {key: value.tolist() for key, value in coordinates.items()}
    for center in definition["product_stereocenters"]:
        ordered = [center["atom"], *center["signed_volume_reference_atoms"]]
        stereochemical_impropers.append(
            {
                "stereocenter": center["atom"],
                "ordered_atoms_candidate": ordered,
                "expected_signed_volume": center["expected_signed_volume"],
                "observed_signed_volume": signed_tetrahedron_volume(
                    coordinate_lists,
                    center["atom"],
                    center["signed_volume_reference_atoms"],
                ),
                "observed_improper_degrees": _dihedral(
                    *(coordinates[key] for key in ordered)
                ),
                "variables": {
                    "k_kcal_mol_rad2": None,
                    "psi0_degrees": None,
                },
                "status": "ordering_and_parameters_require_product_review",
            }
        )

    report = {
        "schema": "nadoc.photoproduct-bonded-fit-plan.v1",
        "status": "candidate_plan_unassigned_not_releasable",
        "gate_effect": "none",
        "product_id": identity[0],
        "model_id": identity[1],
        "hypothesis_id": coverage["hypothesis_id"],
        "atom_count": len(atom_keys),
        "cartesian_hessian_dimension": dimension,
        "dihedral_convention": DIHEDRAL_CONVENTION,
        "transfer_candidates": transfer_candidates,
        "uncovered_parameter_groups": fit_groups,
        "stereochemical_impropers": stereochemical_impropers,
        "precursor_improper_removal_candidates": [
            [f"{endpoint}:C5", f"{endpoint}:C4", f"{endpoint}:C6", f"{endpoint}:C7"]
            for endpoint in (1, 2)
        ],
        "fit_policy": {
            "objective": "coupled Cartesian forces/Hessian plus MM-minimum geometry",
            "diagonal_projection_allowed": False,
            "all_parameter_values_initially_null": True,
            "torsion_rule": (
                "Do not infer Fourier multiplicities/phases from one minimum; add "
                "relaxed scans or multiple independently audited conformers."
            ),
            "multi_isomer_extension": (
                "Fit shared type signatures jointly across reviewed stereoisomers and "
                "retain each isomer as an explicit train or held-out target."
            ),
        },
        "sources": {
            "model_manifest": {
                "path": str(model_manifest_path.resolve()),
                "sha256": _sha256(model_manifest_path),
            },
            "model_graph": {
                "path": str(graph_path.resolve()),
                "sha256": graph_record["sha256"],
            },
            "hessian_targets": {
                "path": str(hessian_targets_path.resolve()),
                "sha256": _sha256(hessian_targets_path),
            },
            "model_coverage": {
                "path": str(model_coverage_path.resolve()),
                "sha256": _sha256(model_coverage_path),
            },
            "improper_convention_audit": {
                "path": str(improper_convention_audit_path.resolve()),
                "sha256": _sha256(improper_convention_audit_path),
            },
            "chemical_definition": chemical_definition_asset(
                registry_entry["product"], registry_entry["stereochemistry"]
            ),
        },
        "release_blockers": [
            "review every transfer candidate and duplicate CHARMM match",
            "fit every null bond/angle/proper/improper variable against declared targets",
            "supply DNA-boundary targets absent from the N-methyl compound",
            "validate all fitted terms on held-out stereoisomers/conformers and DNA contexts",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
