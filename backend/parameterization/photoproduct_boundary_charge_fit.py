"""Fit full d(TpT)-CPD charges while preserving the CHARMM36 boundary.

Only the 28 registered product-base atoms are variables. Sugar, phosphate, and
terminal-cap charges/types remain the effective CHARMM36 values recorded by the
boundary nonbonded specification. Candidate selection uses a preregistered finite
hyperparameter grid and evidence withheld from each optimization.
"""

from __future__ import annotations

from itertools import product
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_nonbonded_fit import (
    _AU_DIPOLE_TO_DEBYE,
    _E_ANGSTROM_TO_DEBYE,
    _interaction_row,
    _quadratic_grid_minimum,
    _solve_constrained_least_squares,
    parse_charmm_nonbonded,
)
from backend.parameterization.photoproduct_qm import parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _rmse(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot calculate RMSE for an empty sequence")
    return math.sqrt(sum(float(value) ** 2 for value in values) / len(values))


def _constraints(
    variable_map: list[str], equal_groups: Sequence[Sequence[str]]
) -> tuple[np.ndarray, np.ndarray]:
    index = {key: position for position, key in enumerate(variable_map)}
    rows: list[np.ndarray] = []
    values: list[float] = []
    total = np.ones(len(variable_map))
    rows.append(total)
    values.append(0.0)
    for group in equal_groups:
        if len(group) < 2 or any(key not in index for key in group):
            raise ValueError("charge equality group escapes the variable atom scope")
        for key in group[1:]:
            row = np.zeros(len(variable_map))
            row[index[group[0]]] = 1.0
            row[index[key]] = -1.0
            rows.append(row)
            values.append(0.0)
    return np.asarray(rows), np.asarray(values)


def _load_parameter_types(
    cgenff_parameters_path: Path, nucleic_parameters_path: Path
) -> dict[str, dict[str, float]]:
    cgenff = parse_charmm_nonbonded(cgenff_parameters_path)
    nucleic = parse_charmm_nonbonded(nucleic_parameters_path)
    conflicts = {
        name for name in set(cgenff) & set(nucleic) if cgenff[name] != nucleic[name]
    }
    if conflicts:
        raise ValueError(
            "CGenFF and nucleic-acid NONBONDED records conflict: "
            + ", ".join(sorted(conflicts))
        )
    return cgenff | nucleic


def _validate_esp(
    *,
    audit_path: Path,
    product_id: str,
    model_id: str,
    atom_map: list[str],
    model_xyz_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    audit = json.loads(audit_path.read_text())
    grid_path = _checked(audit.get("grid"), "ESP grid")
    potential_path = _checked(audit.get("potentials"), "ESP potentials")
    job_path = _checked(audit.get("job_manifest"), "ESP job manifest")
    job = json.loads(job_path.read_text())
    dipole = (audit.get("dipole") or {}).get("vector")
    if (
        audit.get("schema") != "nadoc.photoproduct-esp-audit.v1"
        or audit.get("status") != "complete_candidate"
        or audit.get("passed") is not True
        or (audit.get("product_id"), audit.get("model_id"))
        != (product_id, model_id)
        or audit.get("potential_units") != "atomic_unit"
        or job.get("properties") != ["GRID_ESP", "DIPOLE"]
        or job.get("dipole_units") != "atomic_unit_e_bohr"
        or job.get("atom_map") != atom_map
        or job.get("charge") != -1
        or (job.get("source_xyz") or {}).get("sha256") != _sha256(model_xyz_path)
        or not isinstance(dipole, list)
        or len(dipole) != 3
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in dipole)
    ):
        raise ValueError("ESP/dipole evidence is incomplete or has stale identity")
    grid = np.loadtxt(grid_path, ndmin=2)
    potentials = np.loadtxt(potential_path, ndmin=1)
    if potentials.ndim > 1:
        potentials = potentials[:, -1]
    if (
        grid.shape != (int(audit.get("point_count") or 0), 3)
        or potentials.shape != (len(grid),)
        or len(grid) < len(atom_map) * 4
        or not np.all(np.isfinite(grid))
        or not np.all(np.isfinite(potentials))
    ):
        raise ValueError("ESP arrays are malformed or incomplete")
    order = np.lexsort((grid[:, 2], grid[:, 1], grid[:, 0]))
    grid = grid[order]
    potentials = potentials[order]
    held_out = np.arange(len(grid)) % 5 == 0
    if not 0.2 <= float(np.mean(held_out)) <= 0.21:
        raise ValueError("deterministic ESP partition is not approximately 20 percent")
    return grid, potentials, held_out, audit


def _load_water_curves(
    *,
    audit_paths: Sequence[Path],
    product_id: str,
    model_id: str,
    atom_map: list[str],
    model_xyz_path: Path,
    model_coordinates: np.ndarray,
    model_lj: list[dict[str, float]],
    nonbonded: dict[str, dict[str, float]],
    training_suffixes: set[str],
    held_out_suffixes: set[str],
) -> dict[str, dict[str, Any]]:
    curves: dict[str, dict[str, Any]] = {}
    for audit_path in audit_paths:
        audit = json.loads(audit_path.read_text())
        identity = audit.get("identity") or {}
        site_id = str(identity.get("probe_id") or "")
        suffix_matches = [
            suffix
            for suffix in training_suffixes | held_out_suffixes
            if site_id.endswith(suffix)
        ]
        split = (
            "training"
            if len(suffix_matches) == 1 and suffix_matches[0] in training_suffixes
            else "held_out"
        )
        if (
            audit.get("schema")
            != "nadoc.photoproduct-water-interaction-series-audit.v1"
            or audit.get("status") != "complete_candidate"
            or audit.get("passed") is not True
            or (identity.get("product_id"), identity.get("model_id"))
            != (product_id, model_id)
            or not site_id
            or site_id in curves
            or len(suffix_matches) != 1
        ):
            raise ValueError(f"water audit is incomplete, duplicate, or mismatched: {audit_path}")
        points = audit.get("points") or []
        minimum_index = audit.get("minimum_point_index")
        if (
            len(points) < 5
            or not isinstance(minimum_index, int)
            or not 0 < minimum_index < len(points) - 1
        ):
            raise ValueError(f"{site_id}: water curve minimum is not bracketed")
        computed = []
        for point in points:
            job_dir = Path(str(point.get("job_dir") or ""))
            job_path = job_dir / "job_manifest.json"
            if not job_path.is_file() or _sha256(job_path) != point.get(
                "job_manifest_sha256"
            ):
                raise ValueError(f"{site_id}: water job manifest changed")
            job = json.loads(job_path.read_text())
            source = _checked(job.get("source_xyz"), f"{site_id} source XYZ")
            water = _checked(job.get("water_xyz"), f"{site_id} water XYZ")
            source_atoms, _ = parse_xyz(source.read_text())
            water_atoms, _ = parse_xyz(water.read_text())
            current_coordinates = np.asarray([item[1:] for item in source_atoms])
            if (
                job.get("atom_map") != atom_map
                or job.get("charge") != -1
                or _sha256(source) != _sha256(model_xyz_path)
                or current_coordinates.shape != model_coordinates.shape
                or not np.allclose(current_coordinates, model_coordinates, atol=1e-9)
                or len(water_atoms) != 3
                or not point.get("complete")
            ):
                raise ValueError(f"{site_id}: water job has stale model identity")
            charge_row, lj_energy = _interaction_row(
                model_coordinates,
                model_lj,
                np.asarray([item[1:] for item in water_atoms]),
                nonbonded,
            )
            computed.append(
                {
                    "distance_angstrom": float(point["distance_angstrom"]),
                    "qm_target_kcal_mol": float(point["scaled_target_kcal_mol"]),
                    "charge_row": charge_row,
                    "lj_energy_kcal_mol": lj_energy,
                }
            )
        curves[site_id] = {
            "split": split,
            "minimum_index": minimum_index,
            "points": computed,
            "audit": {"path": str(audit_path.resolve()), "sha256": _sha256(audit_path)},
        }
    expected = {
        f"endpoint{endpoint}-{suffix}"
        for endpoint in (1, 2)
        for suffix in training_suffixes | held_out_suffixes
    }
    if set(curves) != expected:
        raise ValueError(
            "water audits do not exactly cover the six full-boundary sites: "
            f"missing={sorted(expected - set(curves))}, extra={sorted(set(curves) - expected)}"
        )
    return curves


def _water_metrics(
    curves: dict[str, dict[str, Any]],
    charges: np.ndarray,
    *,
    distance_offset_angstrom: float,
) -> list[dict[str, Any]]:
    metrics = []
    for site_id, curve in sorted(curves.items()):
        points = curve["points"]
        distances = np.asarray([item["distance_angstrom"] for item in points])
        energies = np.asarray(
            [float(item["charge_row"] @ charges + item["lj_energy_kcal_mol"]) for item in points]
        )
        mm_distance, mm_energy = _quadratic_grid_minimum(distances, energies)
        minimum = points[curve["minimum_index"]]
        target_distance = minimum["distance_angstrom"] + distance_offset_angstrom
        metrics.append(
            {
                "site_id": site_id,
                "split": curve["split"],
                "qm_scaled_minimum_energy_kcal_mol": minimum["qm_target_kcal_mol"],
                "mm_interpolated_minimum_energy_kcal_mol": mm_energy,
                "energy_error_kcal_mol": mm_energy - minimum["qm_target_kcal_mol"],
                "target_offset_distance_angstrom": target_distance,
                "mm_interpolated_minimum_distance_angstrom": mm_distance,
                "distance_error_angstrom": mm_distance - target_distance,
                "mm_curve_kcal_mol": energies.tolist(),
            }
        )
    return metrics


def fit_boundary_charges(
    *,
    specification_path: Path,
    esp_audit_path: Path,
    water_audit_paths: Sequence[Path],
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Fit and select one gate-neutral full-boundary charge candidate."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite boundary charge fit: {output_path}")
    specification = json.loads(specification_path.read_text())
    if (
        specification.get("schema")
        != "nadoc.photoproduct-boundary-nonbonded-specification.v1"
        or specification.get("status") != "fit_specification_complete_not_fitted"
        or specification.get("simulation_ready") is not False
        or specification.get("gate_effect") != "none"
    ):
        raise ValueError("boundary nonbonded specification is not fit-ready")
    sources = specification.get("sources") or {}
    model_path = _checked(sources.get("model_manifest"), "boundary model manifest")
    policy_path = _checked(sources.get("policy"), "boundary nonbonded policy")
    if (
        _sha256(cgenff_parameters_path)
        != (sources.get("cgenff_parameters") or {}).get("sha256")
    ):
        raise ValueError("CGenFF parameters differ from the boundary specification")
    policy = json.loads(policy_path.read_text())
    model = json.loads(model_path.read_text())
    references_path = _checked(
        sources.get("reference_manifest"), "reference force-field manifest"
    )
    references = json.loads(references_path.read_text())
    if (
        policy.get("schema")
        != "nadoc.photoproduct-boundary-nonbonded-policy.v1"
        or policy.get("version") != "1.1.0"
        or _sha256(nucleic_parameters_path)
        != references["base_forcefield"]["parameters"]["sha256"]
    ):
        raise ValueError("charge-fit policy or nucleic parameters differ from the pinned release")
    model_xyz_path = _checked((model.get("outputs") or {}).get("xyz"), "boundary model XYZ")
    atoms, _ = parse_xyz(model_xyz_path.read_text())
    atom_map = list(specification.get("atom_map") or [])
    if (
        len(atom_map) != 63
        or len(atom_map) != len(set(atom_map))
        or len(atoms) != len(atom_map)
        or model.get("atom_map") != atom_map
        or (model.get("product_id"), model.get("model_id"))
        != (specification.get("product_id"), specification.get("model_id"))
    ):
        raise ValueError("boundary model and nonbonded atom identity differ")
    model_coordinates = np.asarray([item[1:] for item in atoms])

    variable_records = list(specification.get("variable_atoms") or [])
    fixed_records = list(specification.get("fixed_atoms") or [])
    variable_map = [item["atom"] for item in variable_records]
    if (
        len(variable_map) != 28
        or len(fixed_records) != 35
        or set(variable_map) | {item["atom"] for item in fixed_records} != set(atom_map)
    ):
        raise ValueError("boundary charge partition is not exactly 28 variable/35 fixed")
    variable_index = [atom_map.index(key) for key in variable_map]
    fixed_by_atom = {item["atom"]: item for item in fixed_records}
    initial_by_atom = {item["atom"]: float(item["initial_charge_e"]) for item in variable_records}
    types_by_atom = {
        **{item["atom"]: item["candidate_type"] for item in variable_records},
        **{item["atom"]: item["atom_type"] for item in fixed_records},
    }
    initial_all = np.asarray(
        [float(fixed_by_atom[key]["charge_e"]) if key in fixed_by_atom else initial_by_atom[key] for key in atom_map]
    )
    initial_variable = initial_all[variable_index]
    fixed_charge = initial_all.copy()
    fixed_charge[variable_index] = 0.0

    nonbonded = _load_parameter_types(cgenff_parameters_path, nucleic_parameters_path)
    missing_types = sorted(set(types_by_atom.values()) - set(nonbonded))
    if missing_types:
        raise ValueError("candidate types lack NONBONDED records: " + ", ".join(missing_types))
    model_lj = [nonbonded[types_by_atom[key]] for key in atom_map]

    grid, qm_potential, held_out_mask, esp_audit = _validate_esp(
        audit_path=esp_audit_path,
        product_id=specification["product_id"],
        model_id=specification["model_id"],
        atom_map=atom_map,
        model_xyz_path=model_xyz_path,
    )
    inverse_distances = 0.529177210903 / np.linalg.norm(
        grid[:, None, :] - model_coordinates[None, :, :], axis=2
    )
    if not np.all(np.isfinite(inverse_distances)):
        raise ValueError("ESP grid intersects a model atom")
    curves = _load_water_curves(
        audit_paths=water_audit_paths,
        product_id=specification["product_id"],
        model_id=specification["model_id"],
        atom_map=atom_map,
        model_xyz_path=model_xyz_path,
        model_coordinates=model_coordinates,
        model_lj=model_lj,
        nonbonded=nonbonded,
        training_suffixes=set(specification["evidence_partition"]["water_training_site_suffixes"]),
        held_out_suffixes=set(specification["evidence_partition"]["water_held_out_site_suffixes"]),
    )
    constraints, constraint_values = _constraints(
        variable_map, specification["charge_audit"]["equal_charge_groups"]
    )
    from scipy.linalg import null_space
    from scipy.optimize import least_squares
    import scipy

    particular, *_ = np.linalg.lstsq(constraints, constraint_values, rcond=None)
    null = null_space(constraints)
    train_esp = ~held_out_mask
    variable_esp = inverse_distances[:, variable_index]
    fixed_esp = inverse_distances @ fixed_charge
    target_variable_esp = qm_potential - fixed_esp
    qm_dipole = (
        np.asarray(esp_audit["dipole"]["vector"])
        * _AU_DIPOLE_TO_DEBYE
        * float(policy["fit_hyperparameter_grid"]["qm_dipole_scale"])
    )
    fixed_dipole = fixed_charge @ model_coordinates * _E_ANGSTROM_TO_DEBYE
    variable_dipole_rows = model_coordinates[variable_index].T * _E_ANGSTROM_TO_DEBYE
    target_variable_dipole = qm_dipole - fixed_dipole

    hyperparameters = policy["fit_hyperparameter_grid"]
    distance_offset = float(hyperparameters["water_distance_target_offset_angstrom"])
    grid_records = []
    combinations = product(
        hyperparameters["esp_sigma_atomic_unit"],
        hyperparameters["water_energy_sigma_kcal_mol"],
        hyperparameters["water_distance_sigma_angstrom"],
        hyperparameters["dipole_component_sigma_debye"],
        hyperparameters["initial_charge_restraint_sigma_e"],
    )
    training_curves = [curve for curve in curves.values() if curve["split"] == "training"]
    for esp_sigma, water_sigma, distance_sigma, dipole_sigma, charge_sigma in combinations:
        candidate_id = (
            f"esp-{esp_sigma:g}_water-{water_sigma:g}_distance-{distance_sigma:g}_"
            f"dipole-{dipole_sigma:g}_charge-{charge_sigma:g}"
        )
        linear_rows = [
            variable_esp[train_esp] / float(esp_sigma) / math.sqrt(int(np.sum(train_esp)))
        ]
        linear_targets = [
            target_variable_esp[train_esp]
            / float(esp_sigma)
            / math.sqrt(int(np.sum(train_esp)))
        ]
        water_rows = []
        water_targets = []
        for curve in training_curves:
            minimum = curve["points"][curve["minimum_index"]]
            target_distance = minimum["distance_angstrom"] + distance_offset
            fit_point = min(
                curve["points"],
                key=lambda item: abs(item["distance_angstrom"] - target_distance),
            )
            row = fit_point["charge_row"]
            water_rows.append(row[variable_index])
            water_targets.append(
                minimum["qm_target_kcal_mol"]
                - fit_point["lj_energy_kcal_mol"]
                - float(row @ fixed_charge)
            )
        linear_rows.append(
            np.asarray(water_rows) / float(water_sigma) / math.sqrt(len(water_rows))
        )
        linear_targets.append(
            np.asarray(water_targets) / float(water_sigma) / math.sqrt(len(water_targets))
        )
        linear_rows.append(variable_dipole_rows / float(dipole_sigma) / math.sqrt(3.0))
        linear_targets.append(target_variable_dipole / float(dipole_sigma) / math.sqrt(3.0))
        linear_rows.append(
            np.eye(len(variable_map)) / float(charge_sigma) / math.sqrt(len(variable_map))
        )
        linear_targets.append(
            initial_variable / float(charge_sigma) / math.sqrt(len(variable_map))
        )
        linear_charge, linear_solver = _solve_constrained_least_squares(
            np.vstack(linear_rows),
            np.concatenate(linear_targets),
            constraints,
            constraint_values,
        )
        reduced_start, *_ = np.linalg.lstsq(null, linear_charge - particular, rcond=None)

        def residual(reduced: np.ndarray) -> np.ndarray:
            variable_charge = particular + null @ reduced
            all_charge = fixed_charge.copy()
            all_charge[variable_index] = variable_charge
            parts = [
                (variable_esp[train_esp] @ variable_charge - target_variable_esp[train_esp])
                / float(esp_sigma)
                / math.sqrt(int(np.sum(train_esp)))
            ]
            energy_residuals = []
            distance_residuals = []
            for curve in training_curves:
                points = curve["points"]
                distances = np.asarray([item["distance_angstrom"] for item in points])
                energies = np.asarray(
                    [float(item["charge_row"] @ all_charge + item["lj_energy_kcal_mol"]) for item in points]
                )
                mm_distance, mm_energy = _quadratic_grid_minimum(distances, energies)
                minimum = points[curve["minimum_index"]]
                energy_residuals.append(
                    (mm_energy - minimum["qm_target_kcal_mol"]) / float(water_sigma)
                )
                distance_residuals.append(
                    (mm_distance - (minimum["distance_angstrom"] + distance_offset))
                    / float(distance_sigma)
                )
            parts.extend(
                [
                    np.asarray(energy_residuals) / math.sqrt(len(energy_residuals)),
                    np.asarray(distance_residuals) / math.sqrt(len(distance_residuals)),
                    (variable_dipole_rows @ variable_charge - target_variable_dipole)
                    / float(dipole_sigma)
                    / math.sqrt(3.0),
                    (variable_charge - initial_variable)
                    / float(charge_sigma)
                    / math.sqrt(len(variable_map)),
                ]
            )
            return np.concatenate(parts)

        nonlinear = least_squares(residual, reduced_start, max_nfev=5000)
        variable_charge = particular + null @ nonlinear.x
        all_charge = fixed_charge.copy()
        all_charge[variable_index] = variable_charge
        mm_potential = inverse_distances @ all_charge
        initial_potential = inverse_distances @ initial_all
        esp_error = mm_potential - qm_potential
        initial_esp_error = initial_potential - qm_potential
        water_metrics = _water_metrics(
            curves,
            all_charge,
            distance_offset_angstrom=distance_offset,
        )
        split_water = [item for item in water_metrics if item["split"] == "held_out"]
        heldout_esp_rmse = _rmse(esp_error[held_out_mask].tolist())
        initial_heldout_esp_rmse = _rmse(initial_esp_error[held_out_mask].tolist())
        heldout_water_energy_rmse = _rmse(
            [item["energy_error_kcal_mol"] for item in split_water]
        )
        heldout_water_distance_rmse = _rmse(
            [item["distance_error_angstrom"] for item in split_water]
        )
        dipole = all_charge @ model_coordinates * _E_ANGSTROM_TO_DEBYE
        validation_score = (
            heldout_esp_rmse / initial_heldout_esp_rmse
            + heldout_water_energy_rmse / float(specification["acceptance"]["water_energy_rmse_kcal_mol"])
            + heldout_water_distance_rmse / float(specification["acceptance"]["water_distance_rmse_angstrom"])
        )
        maximum_change = float(np.max(np.abs(variable_charge - initial_variable)))
        dipole_error = float(np.linalg.norm(dipole - qm_dipole))
        constraint_error = float(np.max(np.abs(constraints @ variable_charge - constraint_values)))
        checks = {
            "nonlinear_solver": bool(nonlinear.success),
            "charge_constraint": constraint_error
            <= float(specification["acceptance"]["charge_sum_tolerance_e"]),
            "charge_change": maximum_change
            <= float(specification["acceptance"]["maximum_charge_change_e"]),
            "dipole": dipole_error
            <= float(specification["acceptance"]["dipole_vector_error_debye"]),
            "held_out_esp_improvement": heldout_esp_rmse < initial_heldout_esp_rmse,
            "held_out_water_energy": heldout_water_energy_rmse
            <= float(specification["acceptance"]["water_energy_rmse_kcal_mol"]),
            "held_out_water_distance": heldout_water_distance_rmse
            <= float(specification["acceptance"]["water_distance_rmse_angstrom"]),
        }
        grid_records.append(
            {
                "candidate_id": candidate_id,
                "hyperparameters": {
                    "esp_sigma_atomic_unit": esp_sigma,
                    "water_energy_sigma_kcal_mol": water_sigma,
                    "water_distance_sigma_angstrom": distance_sigma,
                    "dipole_component_sigma_debye": dipole_sigma,
                    "initial_charge_restraint_sigma_e": charge_sigma,
                },
                "validation_score": validation_score,
                "passed_acceptance": all(checks.values()),
                "acceptance_checks": checks,
                "variable_charges": variable_charge,
                "all_charges": all_charge,
                "water_metrics": water_metrics,
                "esp_error": esp_error,
                "initial_esp_error": initial_esp_error,
                "heldout_esp_rmse": heldout_esp_rmse,
                "initial_heldout_esp_rmse": initial_heldout_esp_rmse,
                "heldout_water_energy_rmse": heldout_water_energy_rmse,
                "heldout_water_distance_rmse": heldout_water_distance_rmse,
                "mm_dipole": dipole,
                "qm_dipole": qm_dipole,
                "dipole_error": dipole_error,
                "maximum_change": maximum_change,
                "constraint_error": constraint_error,
                "solver": {
                    **linear_solver,
                    "scipy_version": scipy.__version__,
                    "nonlinear_success": bool(nonlinear.success),
                    "nonlinear_status": int(nonlinear.status),
                    "nonlinear_message": str(nonlinear.message),
                    "nonlinear_cost": float(nonlinear.cost),
                    "nonlinear_optimality": float(nonlinear.optimality),
                    "nonlinear_function_evaluations": int(nonlinear.nfev),
                },
            }
        )

    selected = min(grid_records, key=lambda item: (item["validation_score"], item["candidate_id"]))
    summaries = [
        {
            "candidate_id": item["candidate_id"],
            "hyperparameters": item["hyperparameters"],
            "validation_score": item["validation_score"],
            "passed_acceptance": item["passed_acceptance"],
            "acceptance_checks": item["acceptance_checks"],
            "held_out_esp_rmse_atomic_unit": item["heldout_esp_rmse"],
            "initial_held_out_esp_rmse_atomic_unit": item["initial_heldout_esp_rmse"],
            "held_out_water_energy_rmse_kcal_mol": item["heldout_water_energy_rmse"],
            "held_out_water_distance_rmse_angstrom": item["heldout_water_distance_rmse"],
            "dipole_vector_error_debye": item["dipole_error"],
            "maximum_charge_change_e": item["maximum_change"],
        }
        for item in sorted(grid_records, key=lambda item: item["candidate_id"])
    ]
    hypothesis = {
        "hypothesis_id": specification["candidate_hypothesis_id"],
        "candidate_id": selected["candidate_id"],
        "atom_types": types_by_atom,
        "charges_e": dict(zip(atom_map, selected["all_charges"].tolist(), strict=True)),
        "maximum_constraint_error_e": selected["constraint_error"],
        "maximum_charge_change_e": selected["maximum_change"],
        "mm_dipole_debye": selected["mm_dipole"].tolist(),
        "target_scaled_qm_dipole_debye": selected["qm_dipole"].tolist(),
        "dipole_vector_error_debye": selected["dipole_error"],
        "esp_validation": {
            "point_count": len(grid),
            "training_point_count": int(np.sum(train_esp)),
            "held_out_point_count": int(np.sum(held_out_mask)),
            "rmse_atomic_unit": selected["heldout_esp_rmse"],
            "training_rmse_atomic_unit": _rmse(selected["esp_error"][train_esp].tolist()),
            "held_out_rmse_atomic_unit": selected["heldout_esp_rmse"],
            "initial_training_rmse_atomic_unit": _rmse(selected["initial_esp_error"][train_esp].tolist()),
            "initial_held_out_rmse_atomic_unit": selected["initial_heldout_esp_rmse"],
            "partition": "lexicographic_coordinate_order_then_index_modulo_5",
        },
        "water_metrics": selected["water_metrics"],
        "solver": selected["solver"],
        "acceptance_checks": selected["acceptance_checks"],
        "passed_acceptance": selected["passed_acceptance"],
    }
    report = {
        "schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1",
        "status": (
            "candidate_selected_passed_preregistered_metrics"
            if selected["passed_acceptance"]
            else "diagnostic_candidate_selected_acceptance_failed"
        ),
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": specification["product_id"],
        "model_id": specification["model_id"],
        "objective": {
            "scope": "28 variable product-base charges plus 35 fixed CHARMM36 boundary charges",
            "qm_dipole_scale": hyperparameters["qm_dipole_scale"],
            "water_distance_target_offset_angstrom": distance_offset,
            "group_normalization": {
                key: value
                for key, value in hyperparameters.items()
                if key.endswith("normalization")
            },
        },
        "results": [hypothesis],
        "comparison": {
            "selection_status": "selected_by_preregistered_held_out_score",
            "selected_candidate_id": selected["candidate_id"],
            "selected_passed_acceptance": selected["passed_acceptance"],
            "selection_rule": policy["selection"],
            "summaries": summaries,
        },
        "source_records": {
            "specification": {"path": str(specification_path.resolve()), "sha256": _sha256(specification_path)},
            "policy": {"path": str(policy_path), "sha256": _sha256(policy_path)},
            "esp_audit": {"path": str(esp_audit_path.resolve()), "sha256": _sha256(esp_audit_path)},
            "water_audits": [
                {"path": str(path.resolve()), "sha256": _sha256(path)} for path in water_audit_paths
            ],
            "cgenff_parameters": {"path": str(cgenff_parameters_path.resolve()), "sha256": _sha256(cgenff_parameters_path)},
            "nucleic_parameters": {"path": str(nucleic_parameters_path.resolve()), "sha256": _sha256(nucleic_parameters_path)},
        },
        "release_blockers": [
            "fit and validate bonded parameters against the full d(TpT) Hessian and independent conformers",
            "pass exact psfgen topology and ordinary-mass 2 fs NAMD smoke audits",
            "pass matched explicit-solvent intrastrand and interstrand DNA validation",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=lambda value: value.tolist()) + "\n")
    return report


def fit_boundary_charge_campaign(
    *,
    fit_input_root: Path,
    esp_campaign_root: Path,
    water_campaign_root: Path,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path,
) -> dict[str, Any]:
    """Fit all eight ordered products after exact ESP/water campaign collection."""

    output_path = fit_input_root / "boundary_charge_fit_campaign.json"
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite boundary charge campaign: {output_path}")
    fit_manifest_path = fit_input_root / "campaign_manifest.json"
    esp_collection_path = esp_campaign_root / "collection_report.json"
    water_collection_path = water_campaign_root / "collection_report.json"
    fit_manifest = json.loads(fit_manifest_path.read_text())
    esp_collection = json.loads(esp_collection_path.read_text())
    water_collection = json.loads(water_collection_path.read_text())
    if (
        fit_manifest.get("schema")
        != "nadoc.photoproduct-boundary-fit-input-campaign.v1"
        or fit_manifest.get("status") != "passed_fit_input_materialization"
        or fit_manifest.get("product_count") != 8
        or esp_collection.get("schema")
        != "nadoc.photoproduct-alpine-boundary-esp-collection.v1"
        or esp_collection.get("status") != "passed_esp_import_and_audits"
        or esp_collection.get("passed_product_count") != 8
        or water_collection.get("schema")
        != "nadoc.photoproduct-alpine-water-collection.v1"
        or water_collection.get("status") != "passed_import_and_curve_audits"
        or water_collection.get("product_count") != 8
    ):
        raise ValueError("all-eight fit inputs, ESP, and water collections must pass")
    fit_ids = {item["product_id"] for item in fit_manifest["products"]}
    esp_by_id = {item["product_id"]: item for item in esp_collection["products"]}
    water_by_id = {item["product_id"]: item for item in water_collection["products"]}
    if (
        len(fit_ids) != 8
        or set(esp_by_id) != fit_ids
        or set(water_by_id) != fit_ids
    ):
        raise ValueError("fit, ESP, and water product identities differ")

    records = []
    for product_id in sorted(fit_ids):
        specification_path = fit_input_root / product_id / "nonbonded_specification.json"
        esp_audit_path = _checked(esp_by_id[product_id].get("esp_audit"), f"{product_id} ESP audit")
        water_records = water_by_id[product_id].get("site_audits") or []
        water_paths = [
            _checked(record, f"{product_id} water audit") for record in water_records
        ]
        if len(water_paths) != 6:
            raise ValueError(f"{product_id}: expected six full-boundary water audits")
        product_output = fit_input_root / product_id / "boundary_charge_fit.json"
        result = fit_boundary_charges(
            specification_path=specification_path,
            esp_audit_path=esp_audit_path,
            water_audit_paths=water_paths,
            cgenff_parameters_path=cgenff_parameters_path,
            nucleic_parameters_path=nucleic_parameters_path,
            output_path=product_output,
        )
        records.append(
            {
                "product_id": product_id,
                "status": result["status"],
                "passed_acceptance": result["comparison"]["selected_passed_acceptance"],
                "selected_candidate_id": result["comparison"]["selected_candidate_id"],
                "fit": {"path": str(product_output.resolve()), "sha256": _sha256(product_output)},
            }
        )
    passed = sum(bool(item["passed_acceptance"]) for item in records)
    report = {
        "schema": "nadoc.photoproduct-boundary-charge-fit-campaign.v1",
        "status": (
            "all_candidates_passed_preregistered_nonbonded_metrics"
            if passed == 8
            else "one_or_more_candidates_failed_nonbonded_metrics"
        ),
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": 8,
        "passed_product_count": passed,
        "products": records,
        "sources": {
            "fit_inputs": {"path": str(fit_manifest_path.resolve()), "sha256": _sha256(fit_manifest_path)},
            "esp_collection": {"path": str(esp_collection_path.resolve()), "sha256": _sha256(esp_collection_path)},
            "water_collection": {"path": str(water_collection_path.resolve()), "sha256": _sha256(water_collection_path)},
            "cgenff_parameters": {"path": str(cgenff_parameters_path.resolve()), "sha256": _sha256(cgenff_parameters_path)},
            "nucleic_parameters": {"path": str(nucleic_parameters_path.resolve()), "sha256": _sha256(nucleic_parameters_path)},
        },
        "interpretation": (
            "Selected full-boundary charge candidates are gate-neutral inputs to bonded "
            "fitting and NAMD validation, not released photoproduct parameters."
        ),
    }
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
