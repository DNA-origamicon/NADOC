"""Fit and compare gate-neutral TT-CPD charge/LJ-transfer hypotheses."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.parameterization.photoproduct_qm import parse_xyz

HYPOTHESES_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_nonbonded_fit_hypotheses.json"
)
_COULOMB_KCAL_ANGSTROM_PER_MOL_E2 = 332.063713299
_E_ANGSTROM_TO_DEBYE = 4.80320471257
_AU_DIPOLE_TO_DEBYE = 2.541746473
_WATER_CHARGES = (-0.834, 0.417, 0.417)
_WATER_TYPES = ("OGTIP3", "HGTIP3", "HGTIP3")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_charmm_nonbonded(parameters_path: Path) -> dict[str, dict[str, float]]:
    """Parse atom epsilon and Rmin/2 values from one CHARMM parameter file."""

    active = False
    result: dict[str, dict[str, float]] = {}
    for raw in parameters_path.read_text(errors="replace").splitlines():
        fields = raw.split("!", 1)[0].split()
        if not fields:
            continue
        keyword = fields[0].upper()
        if keyword == "NONBONDED":
            active = True
            continue
        if active and keyword in {"NBFIX", "HBOND", "END"}:
            break
        if active and len(fields) >= 4:
            try:
                ignored = float(fields[1])
                epsilon = float(fields[2])
                rmin_half = float(fields[3])
            except ValueError:
                continue
            if ignored != 0.0 or epsilon > 0 or rmin_half <= 0:
                continue
            result[fields[0]] = {
                "epsilon_kcal_mol": epsilon,
                "rmin_half_angstrom": rmin_half,
            }
            if len(fields) >= 7:
                try:
                    ignored_14 = float(fields[4])
                    epsilon_14 = float(fields[5])
                    rmin_half_14 = float(fields[6])
                except ValueError:
                    pass
                else:
                    if ignored_14 == 0.0 and epsilon_14 <= 0 and rmin_half_14 > 0:
                        result[fields[0]].update(
                            {
                                "epsilon_14_kcal_mol": epsilon_14,
                                "rmin_half_14_angstrom": rmin_half_14,
                            }
                        )
    if not result:
        raise ValueError(f"no CHARMM NONBONDED records parsed from {parameters_path}")
    return result


def _interaction_row(
    model_coordinates: np.ndarray,
    model_lj: list[dict[str, float]],
    water_coordinates: np.ndarray,
    nonbonded: dict[str, dict[str, float]],
) -> tuple[np.ndarray, float]:
    row = np.zeros(len(model_coordinates))
    lj_energy = 0.0
    for index, model_xyz in enumerate(model_coordinates):
        for water_xyz, water_charge, water_type in zip(
            water_coordinates, _WATER_CHARGES, _WATER_TYPES, strict=True
        ):
            distance = float(np.linalg.norm(model_xyz - water_xyz))
            if distance <= 0.0:
                raise ValueError("model-water atom overlap in a charge target")
            row[index] += _COULOMB_KCAL_ANGSTROM_PER_MOL_E2 * water_charge / distance
            water_lj = nonbonded[water_type]
            well = math.sqrt(
                abs(model_lj[index]["epsilon_kcal_mol"])
                * abs(water_lj["epsilon_kcal_mol"])
            )
            rmin = (
                model_lj[index]["rmin_half_angstrom"] + water_lj["rmin_half_angstrom"]
            )
            ratio6 = (rmin / distance) ** 6
            lj_energy += well * (ratio6 * ratio6 - 2.0 * ratio6)
    return row, lj_energy


def _constraint_matrix(
    atom_map: list[str], constraints: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    index = {key: position for position, key in enumerate(atom_map)}
    rows = []
    values = []
    for record in [
        constraints["total_charge"],
        *constraints["neutral_n1_methyl_caps"],
    ]:
        row = np.zeros(len(atom_map))
        for atom in record["atoms"]:
            row[index[atom]] += 1.0
        rows.append(row)
        values.append(float(record["value_e"]))
    for group in constraints["equal_charge_groups"]:
        for atom in group[1:]:
            row = np.zeros(len(atom_map))
            row[index[group[0]]] = 1.0
            row[index[atom]] = -1.0
            rows.append(row)
            values.append(0.0)
    return np.asarray(rows), np.asarray(values)


def _solve_constrained_least_squares(
    design: np.ndarray,
    target: np.ndarray,
    constraints: np.ndarray,
    constraint_values: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    from scipy.linalg import null_space

    particular, *_ = np.linalg.lstsq(constraints, constraint_values, rcond=None)
    if np.max(np.abs(constraints @ particular - constraint_values)) > 1e-10:
        raise ValueError("charge constraints are inconsistent")
    null = null_space(constraints)
    reduced = design @ null
    reduced_target = target - design @ particular
    coefficients, residuals, rank, singular = np.linalg.lstsq(
        reduced, reduced_target, rcond=None
    )
    charges = particular + null @ coefficients
    return charges, {
        "constraint_rank": int(np.linalg.matrix_rank(constraints)),
        "independent_charge_variables": int(null.shape[1]),
        "weighted_design_rank": int(rank),
        "weighted_residual_sum_squares": (
            float(residuals[0])
            if residuals.size
            else float(np.sum((design @ charges - target) ** 2))
        ),
        "smallest_singular_value": float(singular[-1]) if singular.size else None,
    }


def _quadratic_grid_minimum(
    distances: np.ndarray, energies: np.ndarray
) -> tuple[float, float]:
    """Return a local parabolic minimum, or the sampled boundary if unbracketed."""

    index = int(np.argmin(energies))
    if index == 0 or index == len(energies) - 1:
        return float(distances[index]), float(energies[index])
    x = distances[index - 1 : index + 2]
    y = energies[index - 1 : index + 2]
    coefficients = np.polyfit(x, y, 2)
    if coefficients[0] <= 0:
        return float(distances[index]), float(energies[index])
    minimum_x = float(-coefficients[1] / (2.0 * coefficients[0]))
    if not float(x[0]) <= minimum_x <= float(x[-1]):
        return float(distances[index]), float(energies[index])
    return minimum_x, float(np.polyval(coefficients, minimum_x))


def _hypothesis_fit_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Reduce a candidate fit to reviewable diagnostics without selecting it."""

    split_metrics = {}
    for split in ("training", "held_out"):
        records = [item for item in result["water_metrics"] if item["split"] == split]

        def rmse(field: str) -> float | None:
            return (
                math.sqrt(
                    sum(float(item[field]) ** 2 for item in records) / len(records)
                )
                if records
                else None
            )

        split_metrics[split] = {
            "site_count": len(records),
            "energy_rmse_kcal_mol": rmse("energy_error_kcal_mol"),
            "distance_rmse_angstrom": rmse("distance_error_angstrom"),
            "maximum_absolute_energy_error_kcal_mol": (
                max(abs(float(item["energy_error_kcal_mol"])) for item in records)
                if records
                else None
            ),
            "maximum_absolute_distance_error_angstrom": (
                max(abs(float(item["distance_error_angstrom"])) for item in records)
                if records
                else None
            ),
        }
    return {
        "hypothesis_id": result["hypothesis_id"],
        "nonlinear_objective_cost": result["solver"]["nonlinear_refinement"]["cost"],
        "dipole_vector_error_debye": result["dipole_vector_error_debye"],
        "esp_rmse_atomic_unit": (
            (result.get("esp_validation") or {}).get("rmse_atomic_unit")
        ),
        "maximum_charge_change_e": result["maximum_charge_change_e"],
        "water": split_metrics,
    }


def fit_nonbonded_hypotheses(
    *,
    charge_target_bundle_path: Path,
    atom_type_plan_path: Path,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path | None = None,
    output_path: Path,
    hypotheses_path: Path = HYPOTHESES_PATH,
) -> dict[str, Any]:
    """Fit symmetry-constrained charges for each explicit LJ transfer hypothesis."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite nonbonded fit report: {output_path}"
        )
    bundle = json.loads(charge_target_bundle_path.read_text())
    plan = json.loads(atom_type_plan_path.read_text())
    hypotheses = json.loads(hypotheses_path.read_text())
    if (
        bundle.get("schema") != "nadoc.photoproduct-charge-target-bundle.v1"
        or bundle.get("status") != "targets_complete_fit_blocked"
        or plan.get("schema") != "nadoc.photoproduct-atom-type-candidate-plan.v1"
        or hypotheses.get("schema") != "nadoc.photoproduct-nonbonded-fit-hypotheses.v1"
        or hypotheses.get("status") != "candidate_not_reviewed"
        or len(
            {
                bundle.get("product_id"),
                plan.get("product_id"),
                hypotheses.get("product_id"),
            }
        )
        != 1
    ):
        raise ValueError("charge targets, atom types, and hypotheses do not match")
    expected_parameter_hash = plan["source"].get("parameters_sha256")
    actual_parameter_hash = _sha256(cgenff_parameters_path)
    if (
        expected_parameter_hash is not None
        and expected_parameter_hash != actual_parameter_hash
    ):
        raise ValueError("CGenFF parameter hash differs from the atom-type plan")
    # The plan currently hash-links the topology; require the separately pinned parameter hash.
    reference_manifest = json.loads(
        (
            Path(__file__).parents[1]
            / "data/forcefield/photoproduct_reference_forcefields.json"
        ).read_text()
    )
    if (
        actual_parameter_hash
        != reference_manifest["cgenff_reference_library"]["parameters_sha256"]
    ):
        raise ValueError("CGenFF parameters do not match the pinned reference release")
    nonbonded = parse_charmm_nonbonded(cgenff_parameters_path)
    nucleic_parameter_hash = None
    if nucleic_parameters_path is not None:
        nucleic_parameter_hash = _sha256(nucleic_parameters_path)
        expected_nucleic_hash = reference_manifest["base_forcefield"]["parameters"][
            "sha256"
        ]
        if nucleic_parameter_hash != expected_nucleic_hash:
            raise ValueError("nucleic-acid parameters do not match the pinned release")
        nucleic_nonbonded = parse_charmm_nonbonded(nucleic_parameters_path)
        conflicts = {
            key
            for key in set(nonbonded) & set(nucleic_nonbonded)
            if nonbonded[key] != nucleic_nonbonded[key]
        }
        if conflicts:
            raise ValueError(
                "CGenFF and nucleic-acid NONBONDED records conflict: "
                + ", ".join(sorted(conflicts))
            )
        nonbonded.update(nucleic_nonbonded)
    atom_map = bundle["atom_map"]
    type_records = {item["model_atom"]: item for item in plan["atoms"]}
    if set(type_records) != set(atom_map):
        raise ValueError("atom-type plan does not exactly cover the charge atom map")
    initial_by_atom = {
        item["model_atom"]: float(item["initial_charge"])
        for item in bundle["initial_charges"]
    }
    initial = np.asarray([initial_by_atom[key] for key in atom_map])
    water_curves = {
        item["site_id"]: item for item in bundle["targets"]["water_interaction_curves"]
    }
    split = bundle["targets"]["proposed_split"]
    objective = hypotheses["objective"]
    energy_sigma = float(objective["water_energy_sigma_kcal_mol"])
    dipole_sigma = float(objective["dipole_component_sigma_debye"])
    charge_sigma = float(objective["initial_charge_restraint_sigma_e"])
    constraints, constraint_values = _constraint_matrix(atom_map, bundle["constraints"])
    results = []
    for hypothesis in hypotheses["hypotheses"]:
        atom_types = []
        for key in atom_map:
            record = type_records[key]
            local = key.split(":", 1)[1]
            override = (hypothesis.get("atom_type_overrides") or {}).get(local)
            if override is not None:
                atom_types.append(override)
            elif record["decision"] == "review_transfer_candidate":
                exact = [
                    item
                    for item in record["candidates"]
                    if item["environment_match"] == "exact_candidate"
                ]
                if len(exact) != 1:
                    raise ValueError(
                        f"{key}: expected exactly one exact type candidate"
                    )
                atom_types.append(exact[0]["source_type"])
            else:
                try:
                    atom_types.append(hypothesis["unresolved_type_sources"][local])
                except KeyError as exc:
                    raise ValueError(
                        f"{key}: hypothesis has no unresolved type source"
                    ) from exc
        missing_types = sorted(set(atom_types + list(_WATER_TYPES)) - set(nonbonded))
        if missing_types:
            raise ValueError("missing NONBONDED types: " + ", ".join(missing_types))
        model_lj = [nonbonded[atom_type] for atom_type in atom_types]
        training_rows = []
        training_targets = []
        cached_curves: dict[str, list[dict[str, Any]]] = {}
        model_coordinates = None
        for site_id, curve in water_curves.items():
            computed_points = []
            for point in curve["points"]:
                job_dir = Path(point["job_dir"])
                job_path = job_dir / "job_manifest.json"
                job = json.loads(job_path.read_text())
                source_path = Path(job["source_xyz"]["path"])
                water_path = Path(job["water_xyz"]["path"])
                if (
                    _sha256(job_path) != point["job_manifest_sha256"]
                    or _sha256(source_path) != job["source_xyz"]["sha256"]
                    or _sha256(water_path) != job["water_xyz"]["sha256"]
                    or job.get("atom_map") != atom_map
                ):
                    raise ValueError(
                        f"{site_id}: water point evidence is hash-mismatched"
                    )
                source_atoms, _ = parse_xyz(source_path.read_text())
                water_atoms, _ = parse_xyz(water_path.read_text())
                current_model_coordinates = np.asarray(
                    [item[1:] for item in source_atoms]
                )
                if model_coordinates is None:
                    model_coordinates = current_model_coordinates
                elif not np.allclose(
                    model_coordinates, current_model_coordinates, atol=1e-10
                ):
                    raise ValueError(
                        "water curves do not share one fixed model geometry"
                    )
                row, lj = _interaction_row(
                    current_model_coordinates,
                    model_lj,
                    np.asarray([item[1:] for item in water_atoms]),
                    nonbonded,
                )
                computed_points.append({"source": point, "charge_row": row, "lj": lj})
            cached_curves[site_id] = computed_points
            if site_id in split["training_sites"]:
                qm_minimum = curve["points"][curve["minimum_point_index"]]
                target_distance = float(qm_minimum["distance_angstrom"]) + float(
                    objective["water_distance_target_offset_angstrom"]
                )
                fit_point = min(
                    computed_points,
                    key=lambda item: abs(
                        float(item["source"]["distance_angstrom"]) - target_distance
                    ),
                )
                if (
                    abs(
                        float(fit_point["source"]["distance_angstrom"])
                        - target_distance
                    )
                    > 1e-6
                ):
                    raise ValueError(
                        f"{site_id}: curve lacks the offset-distance fit point"
                    )
                training_rows.append(fit_point["charge_row"] / energy_sigma)
                training_targets.append(
                    (float(qm_minimum["scaled_target_kcal_mol"]) - fit_point["lj"])
                    / energy_sigma
                )
        assert model_coordinates is not None
        for axis in range(3):
            training_rows.append(
                model_coordinates[:, axis] * _E_ANGSTROM_TO_DEBYE / dipole_sigma
            )
            training_targets.append(
                float(bundle["targets"]["qm_dipole_au"][axis])
                * _AU_DIPOLE_TO_DEBYE
                * float(objective["qm_dipole_scale"])
                / dipole_sigma
            )
        for index in range(len(atom_map)):
            row = np.zeros(len(atom_map))
            row[index] = 1.0 / charge_sigma
            training_rows.append(row)
            training_targets.append(initial[index] / charge_sigma)
        charges, solver = _solve_constrained_least_squares(
            np.asarray(training_rows),
            np.asarray(training_targets),
            constraints,
            constraint_values,
        )
        from scipy import __version__ as scipy_version
        from scipy.linalg import null_space
        from scipy.optimize import least_squares

        particular, *_ = np.linalg.lstsq(constraints, constraint_values, rcond=None)
        null = null_space(constraints)
        start, *_ = np.linalg.lstsq(null, charges - particular, rcond=None)

        def nonlinear_residual(reduced_charges: np.ndarray) -> np.ndarray:
            current = particular + null @ reduced_charges
            residuals = []
            for training_site in split["training_sites"]:
                curve = water_curves[training_site]
                points = cached_curves[training_site]
                distances = np.asarray(
                    [float(item["source"]["distance_angstrom"]) for item in points]
                )
                energies = np.asarray(
                    [
                        float(item["charge_row"] @ current + item["lj"])
                        for item in points
                    ]
                )
                mm_distance, mm_energy = _quadratic_grid_minimum(distances, energies)
                qm_minimum = curve["points"][curve["minimum_point_index"]]
                target_distance = float(qm_minimum["distance_angstrom"]) + float(
                    objective["water_distance_target_offset_angstrom"]
                )
                residuals.extend(
                    [
                        (mm_energy - float(qm_minimum["scaled_target_kcal_mol"]))
                        / energy_sigma,
                        (mm_distance - target_distance) / 0.2,
                    ]
                )
            current_dipole = current @ model_coordinates * _E_ANGSTROM_TO_DEBYE
            target_dipole = (
                np.asarray(bundle["targets"]["qm_dipole_au"])
                * _AU_DIPOLE_TO_DEBYE
                * float(objective["qm_dipole_scale"])
            )
            residuals.extend(((current_dipole - target_dipole) / dipole_sigma).tolist())
            residuals.extend(((current - initial) / charge_sigma).tolist())
            return np.asarray(residuals)

        nonlinear = least_squares(
            nonlinear_residual,
            start,
            method="trf",
            xtol=1e-12,
            ftol=1e-12,
            gtol=1e-12,
            max_nfev=5000,
        )
        charges = particular + null @ nonlinear.x
        solver["nonlinear_refinement"] = {
            "optimizer": "scipy.optimize.least_squares/trf",
            "scipy_version": scipy_version,
            "success": bool(nonlinear.success),
            "status": int(nonlinear.status),
            "message": str(nonlinear.message),
            "function_evaluations": int(nonlinear.nfev),
            "cost": float(nonlinear.cost),
            "optimality": float(nonlinear.optimality),
            "distance_sigma_angstrom": 0.2,
        }
        curve_metrics = []
        for site_id, points in cached_curves.items():
            curve = water_curves[site_id]
            mm = [float(item["charge_row"] @ charges + item["lj"]) for item in points]
            mm_minimum_index = int(np.argmin(mm))
            interpolated_distance, interpolated_energy = _quadratic_grid_minimum(
                np.asarray(
                    [float(item["source"]["distance_angstrom"]) for item in points]
                ),
                np.asarray(mm),
            )
            qm_minimum = curve["points"][curve["minimum_point_index"]]
            target_distance = float(qm_minimum["distance_angstrom"]) + float(
                objective["water_distance_target_offset_angstrom"]
            )
            curve_metrics.append(
                {
                    "site_id": site_id,
                    "split": "training"
                    if site_id in split["training_sites"]
                    else "held_out",
                    "qm_scaled_minimum_energy_kcal_mol": qm_minimum[
                        "scaled_target_kcal_mol"
                    ],
                    "mm_grid_minimum_energy_kcal_mol": mm[mm_minimum_index],
                    "mm_interpolated_minimum_energy_kcal_mol": interpolated_energy,
                    "energy_error_kcal_mol": interpolated_energy
                    - float(qm_minimum["scaled_target_kcal_mol"]),
                    "target_offset_distance_angstrom": target_distance,
                    "mm_grid_minimum_distance_angstrom": points[mm_minimum_index][
                        "source"
                    ]["distance_angstrom"],
                    "mm_interpolated_minimum_distance_angstrom": interpolated_distance,
                    "distance_error_angstrom": interpolated_distance - target_distance,
                    "mm_curve_kcal_mol": mm,
                }
            )
        dipole = (charges @ model_coordinates * _E_ANGSTROM_TO_DEBYE).tolist()
        qm_dipole_target = (
            np.asarray(bundle["targets"]["qm_dipole_au"])
            * _AU_DIPOLE_TO_DEBYE
            * float(objective["qm_dipole_scale"])
        )
        esp_validation = None
        esp_record = (bundle.get("evidence") or {}).get("esp_audit")
        if esp_record is not None:
            esp_audit_path = Path(esp_record["path"])
            if _sha256(esp_audit_path) != esp_record["sha256"]:
                raise ValueError("ESP audit hash differs from the charge target bundle")
            esp_audit = json.loads(esp_audit_path.read_text())
            grid_path = Path(esp_audit["grid"]["path"])
            potential_path = Path(esp_audit["potentials"]["path"])
            if (
                _sha256(grid_path) != esp_audit["grid"]["sha256"]
                or _sha256(potential_path) != esp_audit["potentials"]["sha256"]
            ):
                raise ValueError("ESP grid or potentials are hash-mismatched")
            grid = np.loadtxt(grid_path, ndmin=2)
            qm_potential = np.loadtxt(potential_path, ndmin=1)
            if qm_potential.ndim > 1:
                qm_potential = qm_potential[:, -1]
            inverse_distances = 0.529177210903 / np.linalg.norm(
                grid[:, None, :] - model_coordinates[None, :, :], axis=2
            )
            mm_potential = inverse_distances @ charges
            difference = mm_potential - qm_potential
            esp_validation = {
                "point_count": int(len(grid)),
                "rmse_atomic_unit": float(np.sqrt(np.mean(difference**2))),
                "mean_error_atomic_unit": float(np.mean(difference)),
                "maximum_absolute_error_atomic_unit": float(np.max(np.abs(difference))),
                "role": "validation_only_until_an_ESP_objective_weight_is_reviewed",
            }
        results.append(
            {
                "hypothesis_id": hypothesis["id"],
                "rationale": hypothesis["rationale"],
                "atom_types": dict(zip(atom_map, atom_types, strict=True)),
                "charges_e": dict(zip(atom_map, charges.tolist(), strict=True)),
                "maximum_constraint_error_e": float(
                    np.max(np.abs(constraints @ charges - constraint_values))
                ),
                "maximum_charge_change_e": float(np.max(np.abs(charges - initial))),
                "mm_dipole_debye": dipole,
                "target_scaled_qm_dipole_debye": qm_dipole_target.tolist(),
                "dipole_vector_error_debye": float(
                    np.linalg.norm(np.asarray(dipole) - qm_dipole_target)
                ),
                "esp_validation": esp_validation,
                "water_metrics": sorted(
                    curve_metrics, key=lambda item: item["site_id"]
                ),
                "solver": solver,
            }
        )
    report = {
        "schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1",
        "status": "candidate_comparison_not_reviewed",
        "gate_effect": "none",
        "product_id": bundle["product_id"],
        "model_id": bundle["model_id"],
        "objective": objective,
        "source_records": {
            "charge_targets": {
                "path": str(charge_target_bundle_path.resolve()),
                "sha256": _sha256(charge_target_bundle_path),
            },
            "atom_type_plan": {
                "path": str(atom_type_plan_path.resolve()),
                "sha256": _sha256(atom_type_plan_path),
            },
            "hypotheses": {
                "path": str(hypotheses_path.resolve()),
                "sha256": _sha256(hypotheses_path),
            },
            "cgenff_parameters": {
                "path": str(cgenff_parameters_path.resolve()),
                "sha256": actual_parameter_hash,
            },
            "nucleic_parameters": (
                {
                    "path": str(nucleic_parameters_path.resolve()),
                    "sha256": nucleic_parameter_hash,
                }
                if nucleic_parameters_path is not None
                else None
            ),
        },
        "results": results,
        "comparison": {
            "selection_status": "deferred_no_hypothesis_selected",
            "reason": (
                "Small model-compound objective differences cannot select a Lennard-Jones "
                "or bonded type hypothesis before bonded refitting, MM-minimum re-evaluation, "
                "and condensed-phase/DNA validation."
            ),
            "summaries": [_hypothesis_fit_summary(result) for result in results],
        },
        "release_blockers": [
            "review hypothesis comparison and charge magnitudes",
            "repeat water/dipole evaluation after bonded optimization at the MM minimum",
            "validate selected Lennard-Jones transfers in condensed phase and DNA contexts",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
