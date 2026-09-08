"""Cheap OpenMM rank screen for coupled-conformer candidates before QM spending."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_openmm_linear_response import (
    cartesian_gradient_hessian,
    mass_weighted_rigid_body_projector,
)
from backend.parameterization.photoproduct_qm import parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _rank(matrix: np.ndarray, relative_threshold: float) -> int:
    singular = np.linalg.svd(matrix, compute_uv=False)
    largest = float(singular[0]) if len(singular) else 0.0
    return int(np.count_nonzero(singular > largest * relative_threshold))


def _normalize(matrix: np.ndarray, label: str) -> tuple[np.ndarray, float]:
    singular = np.linalg.svd(matrix, compute_uv=False)
    largest = float(singular[0]) if len(singular) else 0.0
    if largest <= 0.0:
        raise ValueError(f"{label} response block is identically zero")
    return matrix / largest, largest


def screen_coupled_conformer_fit_rank(
    *,
    fit_basis_manifest_path: Path,
    baseline_response_manifest_path: Path,
    candidate_manifest_path: Path,
    output_dir: Path,
    candidate_ids: Sequence[str] | None = None,
    step_angstrom: float = 1.0e-4,
    relative_threshold: float = 1.0e-8,
) -> dict[str, Any]:
    """Greedily diagnose candidate rank gains without computing or fitting QM data."""

    try:
        import openmm
        from openmm import unit
    except ImportError as exc:
        raise RuntimeError("OpenMM is required for conformer rank screening") from exc
    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite conformer rank screen: {output_dir}"
        )
    if step_angstrom <= 0.0 or not 0.0 < relative_threshold < 1.0:
        raise ValueError("finite-difference step/relative threshold is invalid")
    basis = json.loads(fit_basis_manifest_path.read_text())
    candidates = json.loads(candidate_manifest_path.read_text())
    baseline = json.loads(baseline_response_manifest_path.read_text())
    if (
        basis.get("schema") != "nadoc.photoproduct-openmm-linear-fit-basis.v1"
        or basis.get("status") != "candidate_basis_unfitted_not_releasable"
        or basis.get("simulation_ready") is not False
        or basis.get("gate_effect") != "none"
    ):
        raise ValueError("rank screen requires a gate-neutral unfitted OpenMM basis")
    if (
        candidates.get("schema") != "nadoc.photoproduct-coupled-conformer-candidates.v1"
        or candidates.get("status") != "candidates_not_reviewed"
        or candidates.get("simulation_ready") is not False
        or candidates.get("gate_effect") != "none"
    ):
        raise ValueError("rank screen requires gate-neutral unreviewed candidates")
    if (
        baseline.get("schema") != "nadoc.photoproduct-openmm-linear-response.v1"
        or baseline.get("status") != "candidate_response_unfitted_not_releasable"
        or baseline.get("simulation_ready") is not False
        or baseline.get("gate_effect") != "none"
    ):
        raise ValueError(
            "rank screen requires a gate-neutral minimum response baseline"
        )
    identity = ("product_id", "model_id", "hypothesis_id")
    if any(basis.get(key) != baseline.get(key) for key in identity) or any(
        basis.get(key) != candidates.get(key) for key in ("product_id", "model_id")
    ):
        raise ValueError("basis, baseline, and candidate identities differ")
    basis_outputs = basis.get("outputs") or {}
    basis_sources = basis.get("sources") or {}
    system_path = _checked(basis_outputs.get("linear_fit_system"), "linear fit system")
    parameter_map_path = _checked(
        basis_outputs.get("linear_parameter_map"), "linear parameter map"
    )
    stable_map_path = _checked(basis_sources.get("stable_atom_map"), "stable atom map")
    if (
        (baseline.get("sources") or {}).get("linear_parameter_map", {}).get("sha256")
        != _sha256(parameter_map_path)
        or (baseline.get("sources") or {}).get("stable_atom_map", {}).get("sha256")
        != _sha256(stable_map_path)
        or (candidates.get("sources") or {}).get("stable_atom_map", {}).get("sha256")
        != _sha256(stable_map_path)
    ):
        raise ValueError(
            "basis, baseline, and candidates do not share exact atom/parameter maps"
        )
    parameters = json.loads(parameter_map_path.read_text())
    stable_map = json.loads(stable_map_path.read_text())
    keys = [item.get("stable_atom_key") for item in stable_map]
    parameter_names = [item.get("name") for item in parameters]
    if (
        len(parameters) != basis.get("parameter_count")
        or len(keys) != len(set(keys))
        or any(not key for key in keys)
        or len(parameter_names) != len(set(parameter_names))
        or any(not name for name in parameter_names)
    ):
        raise ValueError("basis atom or parameter identity is malformed")
    baseline_arrays_path = _checked(
        (baseline.get("outputs") or {}).get("linear_response_arrays"),
        "baseline response arrays",
    )
    with np.load(baseline_arrays_path, allow_pickle=False) as archive:
        baseline_gradient = np.asarray(
            archive["projected_design_gradient"], dtype=float
        )
        baseline_hessian = np.asarray(
            archive["projected_design_hessian_upper"], dtype=float
        )
    if baseline_gradient.shape[1] != len(parameters) or baseline_hessian.shape[
        1
    ] != len(parameters):
        raise ValueError("baseline response parameter dimension differs")
    selected_records = candidates.get("candidates") or []
    available = {item.get("id"): item for item in selected_records}
    requested = list(candidate_ids) if candidate_ids is not None else list(available)
    if (
        not requested
        or len(requested) != len(set(requested))
        or any(identifier not in available for identifier in requested)
    ):
        raise ValueError(
            "candidate IDs must be a nonempty unique subset of the manifest"
        )
    system = openmm.XmlSerializer.deserialize(system_path.read_text())
    if system.getNumParticles() != len(keys):
        raise ValueError("OpenMM particles and stable atom map differ")
    masses = np.asarray(
        [
            system.getParticleMass(index).value_in_unit(unit.dalton)
            for index in range(system.getNumParticles())
        ]
    )
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system, integrator, openmm.Platform.getPlatformByName("Reference")
    )
    context_parameters = dict(context.getParameters())
    if set(context_parameters) != set(parameter_names) or any(
        not math.isclose(float(context_parameters[name]), 0.0, abs_tol=0.0)
        for name in parameter_names
    ):
        raise ValueError("OpenMM global parameters differ from the zero-valued map")
    dimension = 3 * len(keys)
    upper = np.triu_indices(dimension)
    inverse_sqrt_mass = np.repeat(1.0 / np.sqrt(masses), 3)
    gradient_blocks = []
    hessian_blocks = []
    screen_records = []
    maximum_asymmetry = 0.0
    for identifier in requested:
        record = available[identifier]
        geometry_path = _checked(record.get("geometry"), f"candidate {identifier}")
        atoms, _comment = parse_xyz(geometry_path.read_text())
        xyz = np.asarray([item[1:] for item in atoms], dtype=float)
        if len(xyz) != len(keys):
            raise ValueError(f"candidate {identifier} atom count differs")
        base_gradient, base_hessian, asymmetry = cartesian_gradient_hessian(
            context, xyz, unit, step_angstrom=step_angstrom
        )
        maximum_asymmetry = max(maximum_asymmetry, asymmetry)
        gradient_response = np.empty((len(parameters), dimension))
        hessian_response = np.empty((len(parameters), dimension, dimension))
        for index, name in enumerate(parameter_names):
            context.setParameter(name, 1.0)
            gradient, hessian, asymmetry = cartesian_gradient_hessian(
                context, xyz, unit, step_angstrom=step_angstrom
            )
            gradient_response[index] = gradient - base_gradient
            hessian_response[index] = hessian - base_hessian
            maximum_asymmetry = max(maximum_asymmetry, asymmetry)
            context.setParameter(name, 0.0)
        projector, rigid_rank = mass_weighted_rigid_body_projector(xyz, masses)
        if rigid_rank != 6:
            raise ValueError(f"candidate {identifier} is not a nonlinear geometry")
        projected_gradient = np.asarray(
            [projector @ (inverse_sqrt_mass * values) for values in gradient_response]
        ).T
        projected_hessian = np.asarray(
            [
                (
                    projector
                    @ (inverse_sqrt_mass[:, None] * values * inverse_sqrt_mass[None, :])
                    @ projector
                )[upper]
                for values in hessian_response
            ]
        ).T
        normalized_gradient, gradient_scale = _normalize(
            projected_gradient, f"candidate {identifier} gradient"
        )
        normalized_hessian, hessian_scale = _normalize(
            projected_hessian, f"candidate {identifier} Hessian"
        )
        gradient_blocks.append(projected_gradient)
        hessian_blocks.append(projected_hessian)
        screen_records.append(
            {
                "candidate_id": identifier,
                "geometry": record["geometry"],
                "gradient_divisor": gradient_scale,
                "hessian_divisor": hessian_scale,
                "normalized_gradient": normalized_gradient,
                "normalized_hessian": normalized_hessian,
            }
        )
    del context, integrator
    baseline_gradient_normalized, baseline_gradient_scale = _normalize(
        baseline_gradient, "baseline gradient"
    )
    baseline_hessian_normalized, baseline_hessian_scale = _normalize(
        baseline_hessian, "baseline Hessian"
    )
    stack = [baseline_gradient_normalized, baseline_hessian_normalized]
    current_rank = _rank(np.vstack(stack), relative_threshold)
    baseline_rank = current_rank
    remaining = list(screen_records)
    progression = []
    while remaining:
        trials = []
        for record in remaining:
            matrix = np.vstack(
                (*stack, record["normalized_gradient"], record["normalized_hessian"])
            )
            rank = _rank(matrix, relative_threshold)
            trials.append((rank, record["candidate_id"], record))
        rank, _identifier, winner = max(trials, key=lambda item: (item[0], item[1]))
        gain = rank - current_rank
        if gain <= 0:
            break
        stack.extend((winner["normalized_gradient"], winner["normalized_hessian"]))
        progression.append(
            {
                "candidate_id": winner["candidate_id"],
                "rank_before": current_rank,
                "rank_after": rank,
                "rank_gain": gain,
            }
        )
        current_rank = rank
        remaining.remove(winner)
    output_dir.mkdir(parents=True)
    arrays_path = output_dir / "conformer_rank_screen_arrays.npz"
    np.savez_compressed(
        arrays_path,
        candidate_ids=np.asarray(requested),
        projected_design_gradient=np.asarray(gradient_blocks),
        projected_design_hessian_upper=np.asarray(hessian_blocks),
    )
    report_records = [
        {
            key: value
            for key, value in record.items()
            if key not in {"normalized_gradient", "normalized_hessian"}
        }
        for record in screen_records
    ]
    report = {
        "schema": "nadoc.photoproduct-coupled-conformer-rank-screen.v1",
        "status": "diagnostic_only_candidates_not_reviewed",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": basis["product_id"],
        "model_id": basis["model_id"],
        "hypothesis_id": basis["hypothesis_id"],
        "parameter_count": len(parameters),
        "candidate_count": len(requested),
        "baseline_rank": baseline_rank,
        "greedy_final_rank": current_rank,
        "greedy_rank_gain": current_rank - baseline_rank,
        "greedy_rank_progression": progression,
        "candidates": report_records,
        "unselected_candidate_ids": sorted(
            set(requested) - {item["candidate_id"] for item in progression}
        ),
        "normalization": {
            "baseline_gradient_divisor": baseline_gradient_scale,
            "baseline_hessian_divisor": baseline_hessian_scale,
            "policy": (
                "Each geometry's projected gradient and Hessian design blocks are divided "
                "by their own largest singular values before diagnostic stacking."
            ),
        },
        "finite_difference": {
            "platform": "Reference",
            "step_angstrom": step_angstrom,
            "maximum_raw_hessian_asymmetry": maximum_asymmetry,
        },
        "sources": {
            "fit_basis_manifest": {
                "path": str(fit_basis_manifest_path.resolve()),
                "sha256": _sha256(fit_basis_manifest_path),
            },
            "baseline_response_manifest": {
                "path": str(baseline_response_manifest_path.resolve()),
                "sha256": _sha256(baseline_response_manifest_path),
            },
            "candidate_manifest": {
                "path": str(candidate_manifest_path.resolve()),
                "sha256": _sha256(candidate_manifest_path),
            },
            "linear_parameter_map": basis_outputs["linear_parameter_map"],
            "stable_atom_map": basis_sources["stable_atom_map"],
        },
        "outputs": {
            "design_arrays": {
                "path": str(arrays_path.resolve()),
                "sha256": _sha256(arrays_path),
            }
        },
        "interpretation": (
            "Rank gain can prioritize expensive QM targets but cannot approve a conformer, "
            "select a validation set, choose fit weights, or advance any scientific gate."
        ),
    }
    manifest_path = output_dir / "conformer_rank_screen.json"
    manifest_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def compare_periodicity_rank_screens(
    *, screen_manifest_paths: Sequence[Path], output_path: Path
) -> dict[str, Any]:
    """Collate a complexity ladder without selecting a physical torsion model."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite periodicity comparison: {output_path}"
        )
    if len(screen_manifest_paths) < 2:
        raise ValueError("at least two periodicity rank screens are required")
    records = []
    identity = None
    seen_periodicities = set()
    for path in screen_manifest_paths:
        screen = json.loads(path.read_text())
        if (
            screen.get("schema")
            != "nadoc.photoproduct-coupled-conformer-rank-screen.v1"
            or screen.get("status") != "diagnostic_only_candidates_not_reviewed"
            or screen.get("simulation_ready") is not False
            or screen.get("gate_effect") != "none"
        ):
            raise ValueError(f"{path}: invalid gate-neutral rank screen")
        current_identity = tuple(
            screen.get(key) for key in ("product_id", "model_id", "hypothesis_id")
        )
        if identity is None:
            identity = current_identity
        elif current_identity != identity:
            raise ValueError(
                "periodicity rank screens have different chemical identities"
            )
        basis_path = _checked(
            (screen.get("sources") or {}).get("fit_basis_manifest"),
            f"{path} fit basis",
        )
        basis = json.loads(basis_path.read_text())
        periodicities = tuple(basis.get("torsion_periodicities_to_test") or [])
        if (
            basis.get("schema") != "nadoc.photoproduct-openmm-linear-fit-basis.v1"
            or basis.get("parameter_count") != screen.get("parameter_count")
            or not periodicities
            or periodicities in seen_periodicities
        ):
            raise ValueError(
                "rank screen has a malformed or duplicate periodicity basis"
            )
        seen_periodicities.add(periodicities)
        records.append(
            {
                "periodicities": list(periodicities),
                "parameter_count": screen["parameter_count"],
                "minimum_rank": screen["baseline_rank"],
                "screened_rank": screen["greedy_final_rank"],
                "screened_nullity": screen["parameter_count"]
                - screen["greedy_final_rank"],
                "candidate_count": screen["candidate_count"],
                "rank_gain_candidates": screen["greedy_rank_progression"],
                "rank_screen": {
                    "path": str(path.resolve()),
                    "sha256": _sha256(path),
                },
                "fit_basis": {
                    "path": str(basis_path),
                    "sha256": _sha256(basis_path),
                },
            }
        )
    records.sort(key=lambda item: (len(item["periodicities"]), item["periodicities"]))
    report = {
        "schema": "nadoc.photoproduct-periodicity-rank-comparison.v1",
        "status": "human_model_selection_and_qm_validation_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": identity[0],
        "model_id": identity[1],
        "hypothesis_id": identity[2],
        "hypotheses": records,
        "selection": None,
        "selection_requirements": [
            "fit each candidate basis with declared regularization and physical bounds",
            "compare force, Hessian, relative-energy, and geometry errors on held-out conformers",
            "prefer the least complex basis whose held-out errors satisfy reviewed tolerances",
            "record an independent human decision; matrix rank alone cannot select periodicities",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
