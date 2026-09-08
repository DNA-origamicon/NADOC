"""Iteratively refine a bonded response fit against its QM minimum geometry."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.core.photoproduct_chemistry import signed_tetrahedron_volume
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_openmm_linear_response import (
    cartesian_gradient_hessian,
    mass_weighted_rigid_body_projector,
)
from backend.parameterization.photoproduct_response_fit import (
    _campaign,
    _metrics,
    _weighted_system,
    transform_linear_coefficients_to_charmm,
)


POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_geometry_refinement_policy.json"
)
AUDIT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_geometry_refinement_audit_policy.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def geometry_variable_indices(
    parameters: Sequence[dict[str, Any]], coefficients: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Select equilibrium/torsion variables and tighten harmonic physical bounds."""

    if len(parameters) != len(coefficients):
        raise ValueError("parameter and coefficient counts differ")
    groups: dict[str, dict[str, int]] = {}
    selected = []
    for index, parameter in enumerate(parameters):
        group = str(parameter.get("group_id") or "")
        basis = str(parameter.get("basis") or "")
        if not group or not basis:
            raise ValueError("parameter identity is incomplete")
        if basis in groups.setdefault(group, {}):
            raise ValueError("parameter group repeats a basis function")
        groups[group][basis] = index
        if basis in {"r", "theta"} or parameter.get("category") == "dihedrals":
            selected.append(index)
    if not selected:
        raise ValueError("no geometry-refinement variables were selected")
    indices = np.asarray(selected, dtype=int)
    lower = np.asarray(
        [float(parameters[index]["lower_bound"]) for index in indices], dtype=float
    )
    upper = np.asarray(
        [float(parameters[index]["upper_bound"]) for index in indices], dtype=float
    )
    for position, index in enumerate(indices):
        parameter = parameters[index]
        basis = parameter["basis"]
        if basis not in {"r", "theta"}:
            continue
        quadratic_basis = "r^2" if basis == "r" else "theta^2"
        quadratic_index = groups[parameter["group_id"]].get(quadratic_basis)
        if quadratic_index is None:
            raise ValueError(f"{parameter['group_id']} lacks {quadratic_basis}")
        curvature = float(coefficients[quadratic_index])
        if curvature <= 0.0:
            raise ValueError(f"{parameter['group_id']} has nonpositive curvature")
        if basis == "r":
            lower[position] = max(lower[position], -2.0 * curvature * 3.0)
            upper[position] = min(upper[position], -2.0 * curvature * 0.5)
        else:
            lower[position] = max(lower[position], -2.0 * curvature * math.pi)
            upper[position] = min(upper[position], -2.0e-5 * curvature)
    if (
        not np.all(np.isfinite(lower))
        or not np.all(np.isfinite(upper))
        or np.any(lower >= upper)
        or np.any(coefficients[indices] < lower)
        or np.any(coefficients[indices] > upper)
    ):
        raise ValueError("selected candidate lies outside physical refinement bounds")
    return indices, lower, upper


def _aligned_difference(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    first = reference - np.mean(reference, axis=0)
    second = candidate - np.mean(candidate, axis=0)
    left, _singular, right = np.linalg.svd(second.T @ first)
    rotation = left @ right
    if np.linalg.det(rotation) < 0.0:
        left[:, -1] *= -1.0
        rotation = left @ right
    return second @ rotation - first


def _policy(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if (
        payload.get("schema")
        != "nadoc.photoproduct-geometry-refinement-policy.v1"
        or payload.get("status") != "workflow_policy"
        or payload.get("method") != "bounded-geometry-response-curvature-v1"
    ):
        raise ValueError("unsupported geometry-refinement policy")
    return payload


def _audit_policy(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if (
        payload.get("schema")
        != "nadoc.photoproduct-geometry-refinement-audit-policy.v1"
        or payload.get("status") != "workflow_policy"
        or payload.get("method")
        != "strict-remiminization-and-finite-difference-hessian-v1"
    ):
        raise ValueError("unsupported geometry-refinement audit policy")
    return payload


def refine_selected_response_fit_geometry(
    *,
    selected_fit_path: Path,
    output_dir: Path,
    policy_path: Path = POLICY_PATH,
) -> dict[str, Any]:
    """Create a neutral candidate using training geometry/response evidence only."""

    try:
        import openmm
        from openmm import unit
        import scipy
        from scipy.optimize import least_squares
    except ImportError as exc:  # pragma: no cover - pinned fitting environment
        raise RuntimeError("OpenMM and SciPy are required for geometry refinement") from exc
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite geometry refinement: {output_dir}")
    policy = _policy(policy_path)
    selected = json.loads(selected_fit_path.read_text())
    if (
        selected.get("schema")
        != "nadoc.photoproduct-selected-response-fit-candidate.v1"
        or selected.get("simulation_ready") is not False
        or selected.get("gate_effect") != "none"
        or not isinstance(selected.get("parameters"), list)
    ):
        raise ValueError("a neutral selected response-fit candidate is required")
    campaign_path = _checked(
        (selected.get("sources") or {}).get("campaign"), "response campaign"
    )
    specification_path = _checked(
        (selected.get("sources") or {}).get("quantitative_specification"),
        "quantitative response specification",
    )
    campaign, training, validation = _campaign(campaign_path)
    expected_parameters = campaign.pop("_parameters")
    campaign.pop("_parameter_map_path")
    parameters = selected["parameters"]
    identity_fields = ("name", "group_id", "category", "basis", "periodicity")
    if [tuple(item.get(key) for key in identity_fields) for item in parameters] != [
        tuple(item.get(key) for key in identity_fields) for item in expected_parameters
    ]:
        raise ValueError("selected-fit parameter identity differs from its campaign")
    coefficients = np.asarray([item.get("coefficient") for item in parameters], dtype=float)
    scales = np.asarray([item.get("scale") for item in parameters], dtype=float)
    if not np.all(np.isfinite(coefficients)) or not np.all(np.isfinite(scales)):
        raise ValueError("selected coefficients or scales are non-finite")
    indices, lower, upper = geometry_variable_indices(parameters, coefficients)

    minimum = [item for item in training if item.get("reviewed_partition") is None]
    if len(minimum) != 1:
        raise ValueError("training campaign must contain exactly one optimized minimum")
    response_manifest_path = minimum[0]["manifest_path"]
    response = json.loads(response_manifest_path.read_text())
    sources = response.get("sources") or {}
    arrays_path = _checked(
        (response.get("outputs") or {}).get("linear_response_arrays"),
        "minimum response arrays",
    )
    system_path = _checked(sources.get("linear_fit_system"), "linear fit system")
    geometry_path = _checked(sources.get("target_geometry"), "QM minimum geometry")
    atom_map_path = _checked(sources.get("stable_atom_map"), "stable atom map")
    atoms, _comment = parse_xyz(geometry_path.read_text())
    reference = np.asarray([atom[1:] for atom in atoms], dtype=float)
    heavy = np.asarray(
        [index for index, atom in enumerate(atoms) if atom[0].upper() != "H"],
        dtype=int,
    )
    atom_map = json.loads(atom_map_path.read_text())
    stable_keys = [item.get("stable_atom_key") for item in atom_map]
    if (
        len(reference) != len(stable_keys)
        or not len(heavy)
        or len(set(stable_keys)) != len(stable_keys)
    ):
        raise ValueError("QM geometry and stable atom map differ")
    stable_index = {key: index for index, key in enumerate(stable_keys)}

    with np.load(arrays_path, allow_pickle=False) as archive:
        arrays = {name: np.asarray(archive[name]) for name in archive.files}
    projector = arrays["rigid_body_projector"]
    projector_values, projector_vectors = np.linalg.eigh(projector)
    vibrational_basis = projector_vectors[:, projector_values > 0.5]
    if vibrational_basis.shape[1] != reference.size - 6:
        raise ValueError("minimum response lacks a nonlinear vibrational subspace")
    inverse_mass = np.repeat(1.0 / np.sqrt(arrays["masses_amu"]), 3)

    def project_hessian(values: np.ndarray) -> np.ndarray:
        weighted = inverse_mass[:, None] * values * inverse_mass[None, :]
        return vibrational_basis.T @ weighted @ vibrational_basis

    base_hessian = project_hessian(arrays["base_hessian_kcal_mol_angstrom2"])
    parameter_hessians = np.asarray(
        [project_hessian(values) for values in arrays["parameter_hessian_response"]]
    )
    specification = json.loads(specification_path.read_text())
    response_design, response_target = _weighted_system(
        training, specification["objective"]
    )
    ridge_lambda = float(selected["ridge_lambda"])
    objective = policy["objective"]
    optimizer = policy["optimizer"]
    coordinate_scale = float(objective["heavy_atom_cartesian_component_scale_angstrom"])
    curvature_floor = float(objective["projected_curvature_floor"])
    curvature_scales = [
        float(value)
        for value in objective["projected_curvature_violation_scale_schedule"]
    ]
    if (
        coordinate_scale <= 0.0
        or not curvature_scales
        or any(value <= 0.0 for value in curvature_scales)
        or curvature_scales != sorted(curvature_scales, reverse=True)
        or ridge_lambda < 0.0
    ):
        raise ValueError("geometry-refinement objective is invalid")

    system = openmm.XmlSerializer.deserialize(system_path.read_text())
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system,
        integrator,
        openmm.Platform.getPlatformByName(str(optimizer["platform"])),
    )
    parameter_names = [item["name"] for item in parameters]
    if set(context.getParameters()) != set(parameter_names):
        raise ValueError("OpenMM global parameters differ from selected fit")
    evaluations = 0

    def evaluate(
        values: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]:
        nonlocal evaluations
        candidate = coefficients.copy()
        candidate[indices] = values
        for name, value in zip(parameter_names, candidate, strict=True):
            context.setParameter(name, float(value))
        context.setPositions(reference * unit.angstrom)
        openmm.LocalEnergyMinimizer.minimize(
            context,
            float(optimizer["openmm_force_tolerance"]),
            int(optimizer["openmm_maximum_iterations"]),
        )
        state = context.getState(getPositions=True, getForces=True, getEnergy=True)
        positions = np.asarray(
            state.getPositions(asNumpy=True).value_in_unit(unit.angstrom), dtype=float
        )
        forces = np.asarray(
            state.getForces(asNumpy=True).value_in_unit(
                unit.kilocalorie_per_mole / unit.angstrom
            ),
            dtype=float,
        )
        energy = float(state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole))
        hessian = base_hessian + np.tensordot(
            candidate, parameter_hessians, axes=(0, 0)
        )
        eigenvalues = np.linalg.eigvalsh((hessian + hessian.T) / 2.0)
        if any(
            not np.all(np.isfinite(item))
            for item in (positions, forces, eigenvalues)
        ) or not math.isfinite(energy):
            raise ValueError("geometry refinement produced non-finite OpenMM output")
        evaluations += 1
        return candidate, positions, forces, energy, eigenvalues

    initial_candidate, initial_positions, initial_forces, initial_energy, initial_modes = evaluate(
        coefficients[indices]
    )
    initial_difference = _aligned_difference(
        reference[heavy], initial_positions[heavy]
    )
    stage_records = []
    stage_start = coefficients[indices]
    curvature_tolerance = float(
        policy["candidate_checks"]["minimum_projected_curvature_tolerance"]
    )
    geometry_tolerance = float(
        policy["candidate_checks"]["maximum_optimized_heavy_atom_rmsd_angstrom"]
    )
    for curvature_scale in curvature_scales:

        def residual(values: np.ndarray) -> np.ndarray:
            candidate, positions, _forces, _energy, eigenvalues = evaluate(values)
            geometry = _aligned_difference(reference[heavy], positions[heavy])
            curvature_violation = np.minimum(eigenvalues - curvature_floor, 0.0)
            return np.concatenate(
                (
                    geometry.reshape(-1) / coordinate_scale,
                    response_design @ candidate - response_target,
                    math.sqrt(ridge_lambda) * candidate / scales,
                    curvature_violation / curvature_scale,
                )
            )

        fit = least_squares(
            residual,
            stage_start,
            bounds=(lower, upper),
            method=str(optimizer["method"]),
            xtol=float(optimizer["xtol"]),
            ftol=float(optimizer["ftol"]),
            gtol=float(optimizer["gtol"]),
            max_nfev=int(optimizer["maximum_function_evaluations"]),
            diff_step=float(optimizer["finite_difference_relative_step"]),
        )
        stage_candidate, stage_positions, _stage_forces, _stage_energy, stage_modes = evaluate(
            fit.x
        )
        stage_rmsd = float(
            np.sqrt(
                np.mean(
                    np.sum(
                        _aligned_difference(
                            reference[heavy], stage_positions[heavy]
                        )
                        ** 2,
                        axis=1,
                    )
                )
            )
        )
        stage_records.append(
            {
                "curvature_violation_scale": curvature_scale,
                "optimizer_success": bool(fit.success),
                "message": str(fit.message),
                "function_evaluations": int(fit.nfev),
                "cost": float(fit.cost),
                "optimality": float(fit.optimality),
                "heavy_atom_rmsd_angstrom": stage_rmsd,
                "minimum_projected_curvature": float(stage_modes[0]),
            }
        )
        stage_start = fit.x
        if (
            fit.success
            and stage_rmsd <= geometry_tolerance
            and float(stage_modes[0]) >= curvature_tolerance
        ):
            break
    final, positions, forces, energy, eigenvalues = evaluate(fit.x)
    final_difference = _aligned_difference(reference[heavy], positions[heavy])

    def rmsd(difference: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.sum(difference**2, axis=1))))

    coordinate_map = {
        key: positions[index].tolist() for index, key in enumerate(stable_keys)
    }
    centers = []
    seen_groups = set()
    for parameter in parameters:
        if parameter.get("category") != "impropers":
            continue
        group = parameter["group_id"]
        if group in seen_groups:
            continue
        seen_groups.add(group)
        ordered = parameter.get("ordered_atoms_candidate") or []
        expected = parameter.get("expected_signed_volume")
        if len(ordered) != 4 or expected not in {"positive", "negative"}:
            raise ValueError("selected stereochemical improper identity is incomplete")
        if any(key not in stable_index for key in ordered):
            raise ValueError("stereochemical improper atom is absent")
        volume = signed_tetrahedron_volume(coordinate_map, ordered[0], ordered[1:])
        centers.append(
            {
                "group_id": group,
                "ordered_atoms": ordered,
                "expected_sign": expected,
                "signed_volume": volume,
                "passed": volume > 0.0 if expected == "positive" else volume < 0.0,
            }
        )
    parameter_rows = [
        {**parameter, "coefficient": float(value)}
        for parameter, value in zip(parameters, final, strict=True)
    ]
    transform_error = None
    try:
        transform_linear_coefficients_to_charmm(parameter_rows)
    except ValueError as exc:
        transform_error = str(exc)
    checks_policy = policy["candidate_checks"]
    final_rmsd = rmsd(final_difference)
    checks = {
        "optimizer_reported_success": bool(fit.success),
        "physical_charmm_transform": transform_error is None,
        "optimized_heavy_atom_rmsd": {
            "passed": final_rmsd
            <= float(checks_policy["maximum_optimized_heavy_atom_rmsd_angstrom"]),
            "value_angstrom": final_rmsd,
            "maximum_angstrom": checks_policy[
                "maximum_optimized_heavy_atom_rmsd_angstrom"
            ],
        },
        "minimum_projected_curvature": {
            "passed": float(eigenvalues[0])
            >= float(checks_policy["minimum_projected_curvature_tolerance"]),
            "value": float(eigenvalues[0]),
            "tolerance": checks_policy["minimum_projected_curvature_tolerance"],
            "negative_mode_count": int(np.count_nonzero(eigenvalues < -1.0e-6)),
        },
        "stereochemical_signs": {
            "passed": len(centers) == 4 and all(item["passed"] for item in centers),
            "retained_fraction": (
                sum(item["passed"] for item in centers) / len(centers) if centers else 0.0
            ),
            "centers": centers,
        },
    }
    numerical_candidate_passed = all(
        value if isinstance(value, bool) else bool(value["passed"])
        for value in checks.values()
    )
    output_dir.mkdir(parents=True)
    parameter_path = output_dir / "refined_parameters.json"
    coordinate_path = output_dir / "mm_minimum.xyz"
    parameter_path.write_text(json.dumps(parameter_rows, indent=2) + "\n")
    coordinate_path.write_text(
        "\n".join(
            [
                str(len(atoms)),
                "NADOC gate-neutral geometry-refined MM minimum",
                *[
                    f"{atom[0]:2s} {point[0]: .10f} {point[1]: .10f} {point[2]: .10f}"
                    for atom, point in zip(atoms, positions, strict=True)
                ],
                "",
            ]
        )
    )
    report = {
        "schema": "nadoc.photoproduct-geometry-refinement.v1",
        "status": (
            "candidate_passed_geometry_curvature_checks"
            if numerical_candidate_passed
            else "candidate_failed_geometry_curvature_checks"
        ),
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": response["product_id"],
        "model_id": response["model_id"],
        "hypothesis_id": response["hypothesis_id"],
        "optimizer": {
            "implementation": "scipy.optimize.least_squares",
            "scipy_version": scipy.__version__,
            "openmm_version": openmm.version.version,
            "success": bool(fit.success),
            "message": str(fit.message),
            "function_evaluations": int(fit.nfev),
            "actual_model_evaluations": evaluations,
            "cost": float(fit.cost),
            "optimality": float(fit.optimality),
            "active_mask_count": int(np.count_nonzero(fit.active_mask)),
            "curvature_penalty_stages": stage_records,
        },
        "variable_count": len(indices),
        "variable_names": [parameter_names[index] for index in indices],
        "initial": {
            "heavy_atom_rmsd_angstrom": rmsd(initial_difference),
            "minimum_projected_curvature": float(initial_modes[0]),
            "negative_mode_count": int(np.count_nonzero(initial_modes < -1.0e-6)),
            "energy_kcal_mol": initial_energy,
            "maximum_force_kcal_mol_angstrom": float(
                np.max(np.linalg.norm(initial_forces, axis=1))
            ),
        },
        "final": {
            "heavy_atom_rmsd_angstrom": final_rmsd,
            "minimum_projected_curvature": float(eigenvalues[0]),
            "negative_mode_count": int(np.count_nonzero(eigenvalues < -1.0e-6)),
            "energy_kcal_mol": energy,
            "maximum_force_kcal_mol_angstrom": float(
                np.max(np.linalg.norm(forces, axis=1))
            ),
            "scaled_displacement_from_selected_fit": float(
                np.linalg.norm((final - initial_candidate) / scales)
            ),
            "training_response": _metrics(training, final),
            "untouched_validation_response": _metrics(validation, final),
        },
        "checks": checks,
        "physical_transform_error": transform_error,
        "sources": {
            "selected_response_fit": _source(selected_fit_path),
            "campaign": _source(campaign_path),
            "quantitative_specification": _source(specification_path),
            "minimum_response_manifest": _source(response_manifest_path),
            "policy": _source(policy_path),
        },
        "outputs": {
            "refined_parameters": _source(parameter_path),
            "mm_minimum": _source(coordinate_path),
        },
        "release_blockers": [
            "optimizer convergence and sensitivity require independent numerical audit",
            "held-out response changes require a preregistered selection decision",
            "QM/MM relative conformer energies remain to be evaluated",
            "nonbonded, CHARMM export, topology, NAMD, and DNA-context gates remain",
        ],
        "interpretation": (
            "A passing numerical result proves only that this model form can represent a "
            "local MM basin near the QM minimum while retaining training response terms. "
            "It is not a released parameter set or simulation-ready product."
        ),
    }
    report_path = output_dir / "geometry_refinement_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def audit_geometry_refinement(
    *,
    refinement_report_path: Path,
    output_path: Path,
    audit_policy_path: Path = AUDIT_POLICY_PATH,
) -> dict[str, Any]:
    """Re-minimize and finite-difference the actual refined MM system.

    The fit objective estimates curvature from the response Hessian at the QM
    geometry.  This independent audit instead evaluates the complete OpenMM system at
    the stored MM minimum with a tighter minimizer and a fresh Cartesian finite
    difference Hessian.  It remains gate-neutral and cannot release parameters.
    """

    try:
        import openmm
        from openmm import unit
    except ImportError as exc:  # pragma: no cover - pinned fitting environment
        raise RuntimeError("OpenMM is required for geometry-refinement audit") from exc
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite refinement audit: {output_path}")
    refinement = json.loads(refinement_report_path.read_text())
    if (
        refinement.get("schema") != "nadoc.photoproduct-geometry-refinement.v1"
        or refinement.get("status")
        != "candidate_passed_geometry_curvature_checks"
        or refinement.get("simulation_ready") is not False
        or refinement.get("gate_effect") != "none"
    ):
        raise ValueError("audit requires a passing neutral geometry refinement")
    policy_path = _checked((refinement.get("sources") or {}).get("policy"), "policy")
    policy = _policy(policy_path)
    audit_policy = _audit_policy(audit_policy_path)
    response_path = _checked(
        (refinement.get("sources") or {}).get("minimum_response_manifest"),
        "minimum response",
    )
    parameter_path = _checked(
        (refinement.get("outputs") or {}).get("refined_parameters"),
        "refined parameters",
    )
    coordinate_path = _checked(
        (refinement.get("outputs") or {}).get("mm_minimum"), "stored MM minimum"
    )
    response = json.loads(response_path.read_text())
    system_path = _checked(
        (response.get("sources") or {}).get("linear_fit_system"),
        "linear fit system",
    )
    target_path = _checked(
        (response.get("sources") or {}).get("target_geometry"), "QM target geometry"
    )
    atom_map_path = _checked(
        (response.get("sources") or {}).get("stable_atom_map"), "stable atom map"
    )
    parameters = json.loads(parameter_path.read_text())
    transform_linear_coefficients_to_charmm(parameters)
    stored_atoms, _ = parse_xyz(coordinate_path.read_text())
    target_atoms, _ = parse_xyz(target_path.read_text())
    stable_map = json.loads(atom_map_path.read_text())
    stable_keys = [item.get("stable_atom_key") for item in stable_map]
    if (
        len(stored_atoms) != len(target_atoms)
        or len(stored_atoms) != len(stable_keys)
        or len(stable_keys) != len(set(stable_keys))
        or [item[0] for item in stored_atoms] != [item[0] for item in target_atoms]
    ):
        raise ValueError("refinement coordinates and stable atom identity differ")
    stored = np.asarray([item[1:] for item in stored_atoms], dtype=float)
    target = np.asarray([item[1:] for item in target_atoms], dtype=float)
    heavy = np.asarray(
        [index for index, atom in enumerate(stored_atoms) if atom[0].upper() != "H"]
    )

    system = openmm.XmlSerializer.deserialize(system_path.read_text())
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system,
        integrator,
        openmm.Platform.getPlatformByName(str(audit_policy["platform"])),
    )
    names = [item.get("name") for item in parameters]
    if len(names) != len(set(names)) or set(context.getParameters()) != set(names):
        raise ValueError("refined parameter identity differs from OpenMM system")
    for item in parameters:
        context.setParameter(str(item["name"]), float(item["coefficient"]))
    context.setPositions(stored * unit.angstrom)
    openmm.LocalEnergyMinimizer.minimize(
        context,
        float(audit_policy["openmm_force_tolerance"]),
        int(audit_policy["openmm_maximum_iterations"]),
    )
    state = context.getState(getPositions=True, getForces=True, getEnergy=True)
    positions = np.asarray(
        state.getPositions(asNumpy=True).value_in_unit(unit.angstrom), dtype=float
    )
    forces = np.asarray(
        state.getForces(asNumpy=True).value_in_unit(
            unit.kilocalorie_per_mole / unit.angstrom
        ),
        dtype=float,
    )
    energy = float(state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole))
    _gradient, hessian, asymmetry = cartesian_gradient_hessian(
        context,
        positions,
        unit,
        step_angstrom=float(audit_policy["cartesian_finite_difference_step_angstrom"]),
    )
    masses = np.asarray(
        [
            system.getParticleMass(index).value_in_unit(unit.dalton)
            for index in range(system.getNumParticles())
        ],
        dtype=float,
    )
    projector, rigid_rank = mass_weighted_rigid_body_projector(positions, masses)
    projector_values, projector_vectors = np.linalg.eigh(projector)
    vibrational_basis = projector_vectors[:, projector_values > 0.5]
    inverse_mass = np.repeat(1.0 / np.sqrt(masses), 3)
    weighted = inverse_mass[:, None] * hessian * inverse_mass[None, :]
    vibrational_hessian = vibrational_basis.T @ weighted @ vibrational_basis
    eigenvalues = np.linalg.eigvalsh(
        (vibrational_hessian + vibrational_hessian.T) / 2.0
    )
    del context, integrator
    if (
        rigid_rank != 6
        or vibrational_basis.shape[1] != positions.size - 6
        or any(not np.all(np.isfinite(item)) for item in (positions, forces, eigenvalues))
        or not math.isfinite(energy)
    ):
        raise ValueError("independent refinement audit produced invalid numerical data")

    stored_shift = float(np.max(np.linalg.norm(positions - stored, axis=1)))
    heavy_difference = _aligned_difference(target[heavy], positions[heavy])
    heavy_rmsd = float(np.sqrt(np.mean(np.sum(heavy_difference**2, axis=1))))
    maximum_force = float(np.max(np.linalg.norm(forces, axis=1)))
    coordinate_map = {
        key: positions[index].tolist() for index, key in enumerate(stable_keys)
    }
    centers = []
    seen_groups = set()
    for parameter in parameters:
        if parameter.get("category") != "impropers":
            continue
        group = parameter["group_id"]
        if group in seen_groups:
            continue
        seen_groups.add(group)
        ordered = parameter.get("ordered_atoms_candidate") or []
        expected = parameter.get("expected_signed_volume")
        if len(ordered) != 4 or expected not in {"positive", "negative"}:
            raise ValueError("refined stereochemical improper identity is incomplete")
        volume = signed_tetrahedron_volume(coordinate_map, ordered[0], ordered[1:])
        centers.append(
            {
                "group_id": group,
                "expected_sign": expected,
                "signed_volume": volume,
                "passed": volume > 0.0 if expected == "positive" else volume < 0.0,
            }
        )
    checks = {
        "stored_minimum_reproduced": {
            "passed": stored_shift
            <= float(audit_policy["maximum_stored_minimum_displacement_angstrom"]),
            "maximum_displacement_angstrom": stored_shift,
            "maximum_angstrom": audit_policy[
                "maximum_stored_minimum_displacement_angstrom"
            ],
        },
        "force_converged": {
            "passed": maximum_force
            <= float(audit_policy["maximum_force_kcal_mol_angstrom"]),
            "maximum_force_kcal_mol_angstrom": maximum_force,
            "maximum": audit_policy["maximum_force_kcal_mol_angstrom"],
        },
        "finite_difference_symmetry": {
            "passed": asymmetry
            <= float(audit_policy["maximum_raw_hessian_asymmetry"]),
            "maximum_asymmetry": asymmetry,
            "maximum": audit_policy["maximum_raw_hessian_asymmetry"],
        },
        "actual_minimum_curvature": {
            "passed": float(eigenvalues[0])
            >= float(audit_policy["minimum_vibrational_projected_curvature"]),
            "minimum_projected_curvature": float(eigenvalues[0]),
            "minimum": audit_policy["minimum_vibrational_projected_curvature"],
            "negative_mode_count": int(np.count_nonzero(eigenvalues < -1.0e-6)),
        },
        "optimized_heavy_atom_rmsd": {
            "passed": heavy_rmsd
            <= float(
                policy["candidate_checks"][
                    "maximum_optimized_heavy_atom_rmsd_angstrom"
                ]
            ),
            "value_angstrom": heavy_rmsd,
            "maximum_angstrom": policy["candidate_checks"][
                "maximum_optimized_heavy_atom_rmsd_angstrom"
            ],
        },
        "stereochemical_signs": {
            "passed": len(centers) == 4 and all(item["passed"] for item in centers),
            "centers": centers,
        },
    }
    passed = all(bool(item["passed"]) for item in checks.values())
    report = {
        "schema": "nadoc.photoproduct-geometry-refinement-audit.v1",
        "status": "passed_independent_numerical_audit" if passed else "failed",
        "passed": passed,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": refinement["product_id"],
        "model_id": refinement["model_id"],
        "hypothesis_id": refinement["hypothesis_id"],
        "platform": str(audit_policy["platform"]),
        "energy_kcal_mol": energy,
        "finite_difference_step_angstrom": audit_policy[
            "cartesian_finite_difference_step_angstrom"
        ],
        "vibrational_dimension": int(len(eigenvalues)),
        "lowest_projected_curvatures": eigenvalues[:10].tolist(),
        "checks": checks,
        "sources": {
            "refinement": _source(refinement_report_path),
            "refinement_policy": _source(policy_path),
            "audit_policy": _source(audit_policy_path),
            "refined_parameters": _source(parameter_path),
            "stored_mm_minimum": _source(coordinate_path),
            "linear_fit_system": _source(system_path),
            "qm_target_geometry": _source(target_path),
            "stable_atom_map": _source(atom_map_path),
        },
        "interpretation": (
            "Passing independently confirms the refined isolated-model local minimum "
            "and stereochemistry. It does not validate nonbonded terms, CHARMM export, "
            "DNA-context transfer, or NAMD readiness."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_geometry_refined_charmm_transform(
    *, refinement_report_path: Path, audit_path: Path, output_path: Path
) -> dict[str, Any]:
    """Apply the CHARMM algebraic inverse to an independently audited refinement."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite CHARMM transform: {output_path}")
    refinement = json.loads(refinement_report_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (
        refinement.get("schema") != "nadoc.photoproduct-geometry-refinement.v1"
        or refinement.get("status")
        != "candidate_passed_geometry_curvature_checks"
        or audit.get("schema")
        != "nadoc.photoproduct-geometry-refinement-audit.v1"
        or audit.get("status") != "passed_independent_numerical_audit"
        or audit.get("passed") is not True
        or ((audit.get("sources") or {}).get("refinement") or {}).get("sha256")
        != _sha256(refinement_report_path)
        or any(
            refinement.get(key) != audit.get(key)
            for key in ("product_id", "model_id", "hypothesis_id")
        )
    ):
        raise ValueError("a matching independently audited refinement is required")
    parameter_path = _checked(
        (refinement.get("outputs") or {}).get("refined_parameters"),
        "refined parameters",
    )
    if ((audit.get("sources") or {}).get("refined_parameters") or {}).get(
        "sha256"
    ) != _sha256(parameter_path):
        raise ValueError("refinement audit parameter hash differs")
    parameters = json.loads(parameter_path.read_text())
    transformed = transform_linear_coefficients_to_charmm(parameters)
    report = {
        "schema": "nadoc.photoproduct-charmm-bonded-transform-candidate.v1",
        "status": "algebraically_transformed_requires_term_mapping_and_validation",
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": refinement["hypothesis_id"],
        "ridge_lambda": None,
        "bonded_terms": transformed,
        "selection_authority": "automated_geometry_and_independent_numerical_audit",
        "sources": {
            "geometry_refinement_candidate": _source(refinement_report_path),
            "geometry_refinement_audit": _source(audit_path),
            "refined_parameters": _source(parameter_path),
        },
        "release_blockers": [
            "held-out relative-energy and all-form transfer tests remain",
            "charges and Lennard-Jones terms require strict revalidation",
            "final term mapping, topology, DNA contexts, psfgen, and NAMD remain",
        ],
        "interpretation": (
            "This applies only the exact CHARMM algebraic inverse to a gate-neutral "
            "independently audited geometry refinement. It is not a released parameter file."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
