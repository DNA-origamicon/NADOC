"""Build force and full-Cartesian-Hessian response matrices for bonded fitting."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.parameterization.photoproduct_qm import parse_xyz

HARTREE_PER_BOHR2_TO_KCAL_PER_MOL_ANGSTROM2 = 627.5094740631 / 0.529177210903**2
HARTREE_PER_BOHR_TO_KCAL_PER_MOL_ANGSTROM = 627.5094740631 / 0.529177210903


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_source(record: dict[str, Any], label: str) -> Path:
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path


def _svd_identifiability(matrix: np.ndarray) -> dict[str, Any]:
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    largest = float(singular_values[0]) if len(singular_values) else 0.0
    thresholds = (1.0e-6, 1.0e-8, 1.0e-10, 1.0e-12)
    ranks = {
        f"relative_{threshold:.0e}": int(
            np.count_nonzero(singular_values > largest * threshold)
        )
        for threshold in thresholds
    }
    return {
        "row_count": int(matrix.shape[0]),
        "column_count": int(matrix.shape[1]),
        "largest_singular_value": largest,
        "smallest_singular_value": float(singular_values[-1]),
        "rank_by_relative_threshold": ranks,
        "full_column_rank_at_relative_1e-8": ranks["relative_1e-08"] == matrix.shape[1],
    }


def mass_weighted_rigid_body_projector(
    xyz_angstrom: np.ndarray, masses_amu: np.ndarray
) -> tuple[np.ndarray, int]:
    """Return the Eckart-space projector that removes translation and rotation."""

    xyz = np.asarray(xyz_angstrom, dtype=float)
    masses = np.asarray(masses_amu, dtype=float)
    if (
        xyz.ndim != 2
        or xyz.shape[1] != 3
        or masses.shape != (len(xyz),)
        or not np.all(np.isfinite(xyz))
        or not np.all(np.isfinite(masses))
        or np.any(masses <= 0.0)
    ):
        raise ValueError("rigid-body projection requires finite coordinates and masses")
    center = np.sum(xyz * masses[:, None], axis=0) / np.sum(masses)
    centered = xyz - center
    sqrt_mass = np.sqrt(masses)
    columns = []
    axes = np.eye(3)
    for axis in axes:
        columns.append((sqrt_mass[:, None] * axis).reshape(-1))
    for axis in axes:
        columns.append((sqrt_mass[:, None] * np.cross(axis, centered)).reshape(-1))
    rigid = np.column_stack(columns)
    left, singular_values, _right = np.linalg.svd(rigid, full_matrices=False)
    tolerance = max(rigid.shape) * np.finfo(float).eps * singular_values[0]
    rank = int(np.count_nonzero(singular_values > tolerance))
    basis = left[:, :rank]
    projector = np.eye(xyz.size) - basis @ basis.T
    return (projector + projector.T) / 2.0, rank


def cartesian_gradient_hessian(
    context: Any,
    xyz_angstrom: np.ndarray,
    unit: Any,
    *,
    step_angstrom: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Numerically differentiate OpenMM forces in deterministic Cartesian order."""

    if step_angstrom <= 0.0:
        raise ValueError("finite-difference step must be positive")
    xyz = np.asarray(xyz_angstrom, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.all(np.isfinite(xyz)):
        raise ValueError("Cartesian coordinates must be a finite N-by-3 array")

    def forces(coordinates: np.ndarray) -> np.ndarray:
        context.setPositions(coordinates * unit.angstrom)
        state = context.getState(getForces=True)
        values = state.getForces(asNumpy=True).value_in_unit(
            unit.kilocalorie_per_mole / unit.angstrom
        )
        return np.asarray(values, dtype=float).reshape(-1)

    center_force = forces(xyz)
    dimension = xyz.size
    hessian = np.empty((dimension, dimension), dtype=float)
    flat = xyz.reshape(-1)
    for coordinate in range(dimension):
        plus = flat.copy()
        minus = flat.copy()
        plus[coordinate] += step_angstrom
        minus[coordinate] -= step_angstrom
        hessian[:, coordinate] = -(
            forces(plus.reshape(xyz.shape)) - forces(minus.reshape(xyz.shape))
        ) / (2.0 * step_angstrom)
    context.setPositions(xyz * unit.angstrom)
    asymmetry = float(np.max(np.abs(hessian - hessian.T)))
    return -center_force, (hessian + hessian.T) / 2.0, asymmetry


def build_openmm_linear_response(
    *,
    fit_basis_manifest_path: Path,
    hessian_targets_path: Path,
    output_dir: Path,
    step_angstrom: float = 1.0e-4,
) -> dict[str, Any]:
    """Construct an unfitted linear response matrix against a coupled QM Hessian."""

    try:
        import openmm
        from openmm import unit
    except ImportError as exc:
        raise RuntimeError(
            "OpenMM is required in the photoproduct QM environment"
        ) from exc
    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite OpenMM response matrix: {output_dir}"
        )
    basis = json.loads(fit_basis_manifest_path.read_text())
    targets = json.loads(hessian_targets_path.read_text())
    if (
        basis.get("schema") != "nadoc.photoproduct-openmm-linear-fit-basis.v1"
        or basis.get("status") != "candidate_basis_unfitted_not_releasable"
        or basis.get("simulation_ready") is not False
        or basis.get("gate_effect") != "none"
    ):
        raise ValueError("input is not an unfitted gate-neutral OpenMM basis")
    target_schema = targets.get("schema")
    minimum_target = (
        target_schema == "nadoc.photoproduct-hessian-target-bundle.v1"
        and targets.get("frequency_evidence_status")
        in {"passed_harmonic_minimum", "passed_candidate_harmonic_minimum"}
        and targets.get("gate_effect") == "none"
    )
    conformer_target = (
        target_schema == "nadoc.photoproduct-hessian-target-bundle.v2"
        and targets.get("status") == "candidate_off_equilibrium_response_evidence"
        and targets.get("simulation_ready") is False
        and targets.get("target_kind") == "reviewed_off_equilibrium_conformer"
        and targets.get("gate_effect") == "none"
    )
    if not (minimum_target or conformer_target):
        raise ValueError(
            "a passed minimum or reviewed off-equilibrium gate-neutral Hessian target is required"
        )
    if any(basis.get(key) != targets.get(key) for key in ("product_id", "model_id")):
        raise ValueError("fit basis and Hessian target identities differ")

    basis_outputs = basis.get("outputs") or {}
    system_path = _checked_source(
        basis_outputs.get("linear_fit_system") or {}, "linear fit system"
    )
    parameter_map_path = _checked_source(
        basis_outputs.get("linear_parameter_map") or {}, "linear parameter map"
    )
    basis_sources = basis.get("sources") or {}
    stable_map_path = _checked_source(
        basis_sources.get("stable_atom_map") or {}, "stable atom map"
    )
    target_hessian_path = _checked_source(
        targets.get("cartesian_hessian") or {}, "QM Cartesian Hessian"
    )
    geometry_path = _checked_source(
        targets.get("source_geometry") or {}, "optimized QM geometry"
    )
    parameters = json.loads(parameter_map_path.read_text())
    if (
        len(parameters) != basis.get("parameter_count")
        or any(record.get("default") != 0.0 for record in parameters)
        or len({record.get("name") for record in parameters}) != len(parameters)
    ):
        raise ValueError("linear parameter map is incomplete, nonzero, or ambiguous")
    stable_map = json.loads(stable_map_path.read_text())
    stable_keys = [record.get("stable_atom_key") for record in stable_map]
    if stable_keys != targets.get("atom_map"):
        raise ValueError("OpenMM and QM stable atom orders differ")
    xyz_atoms, _comment = parse_xyz(geometry_path.read_text())
    xyz = np.asarray([atom[1:] for atom in xyz_atoms], dtype=float)
    if len(xyz) != len(stable_keys):
        raise ValueError("optimized geometry atom count differs from the stable map")
    dimension = 3 * len(stable_keys)
    hessian_record = targets["cartesian_hessian"]
    qm_hessian_raw = np.loadtxt(target_hessian_path, ndmin=2)
    if (
        hessian_record.get("units") != "hartree/bohr^2"
        or hessian_record.get("dimension") != dimension
        or qm_hessian_raw.shape != (dimension, dimension)
        or not np.all(np.isfinite(qm_hessian_raw))
        or not np.allclose(qm_hessian_raw, qm_hessian_raw.T, atol=1e-10)
    ):
        raise ValueError(
            "QM Cartesian Hessian units, shape, symmetry, or values are invalid"
        )
    qm_hessian = qm_hessian_raw * HARTREE_PER_BOHR2_TO_KCAL_PER_MOL_ANGSTROM2
    if conformer_target:
        target_gradient_path = _checked_source(
            targets.get("cartesian_gradient") or {}, "QM Cartesian gradient"
        )
        gradient_record = targets["cartesian_gradient"]
        qm_gradient_raw = np.loadtxt(target_gradient_path, ndmin=1).reshape(-1)
        if (
            gradient_record.get("units") != "hartree/bohr"
            or gradient_record.get("dimension") != dimension
            or qm_gradient_raw.shape != (dimension,)
            or not np.all(np.isfinite(qm_gradient_raw))
        ):
            raise ValueError(
                "QM Cartesian gradient units, shape, or values are invalid"
            )
        qm_gradient = qm_gradient_raw * HARTREE_PER_BOHR_TO_KCAL_PER_MOL_ANGSTROM
    else:
        target_gradient_path = None
        qm_gradient = np.zeros(dimension, dtype=float)

    system = openmm.XmlSerializer.deserialize(system_path.read_text())
    masses = np.asarray(
        [
            system.getParticleMass(index).value_in_unit(unit.dalton)
            for index in range(system.getNumParticles())
        ],
        dtype=float,
    )
    if len(masses) != len(stable_keys):
        raise ValueError("OpenMM particle masses differ from the stable atom map")
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system, integrator, openmm.Platform.getPlatformByName("Reference")
    )
    context.setPositions(xyz * unit.angstrom)
    context_parameters = dict(context.getParameters())
    parameter_names = [record["name"] for record in parameters]
    if set(context_parameters) != set(parameter_names) or any(
        not math.isclose(float(context_parameters[name]), 0.0, abs_tol=0.0)
        for name in parameter_names
    ):
        raise ValueError("OpenMM global parameters differ from the zero-valued map")

    base_gradient, base_hessian, base_asymmetry = cartesian_gradient_hessian(
        context, xyz, unit, step_angstrom=step_angstrom
    )
    _, base_half_step_hessian, half_step_asymmetry = cartesian_gradient_hessian(
        context, xyz, unit, step_angstrom=step_angstrom / 2.0
    )
    base_step_difference = base_hessian - base_half_step_hessian
    parameter_gradient_response = np.empty((len(parameters), dimension), dtype=float)
    parameter_hessian_response = np.empty(
        (len(parameters), dimension, dimension), dtype=float
    )
    maximum_basis_asymmetry = 0.0
    for index, name in enumerate(parameter_names):
        context.setParameter(name, 1.0)
        gradient, hessian, asymmetry = cartesian_gradient_hessian(
            context, xyz, unit, step_angstrom=step_angstrom
        )
        parameter_gradient_response[index] = gradient - base_gradient
        parameter_hessian_response[index] = hessian - base_hessian
        maximum_basis_asymmetry = max(maximum_basis_asymmetry, asymmetry)
        context.setParameter(name, 0.0)
    del context, integrator
    arrays = (
        qm_gradient,
        qm_hessian,
        base_gradient,
        base_hessian,
        parameter_gradient_response,
        parameter_hessian_response,
    )
    if any(not np.all(np.isfinite(array)) for array in arrays):
        raise ValueError("linear response contains non-finite values")

    upper = np.triu_indices(dimension)
    residual_gradient = qm_gradient - base_gradient
    residual_hessian = qm_hessian - base_hessian
    design_gradient = parameter_gradient_response.T
    design_hessian = parameter_hessian_response[:, upper[0], upper[1]].T
    projector, rigid_rank = mass_weighted_rigid_body_projector(xyz, masses)
    if rigid_rank != 6:
        raise ValueError(
            f"expected six rigid-body directions for nonlinear model, found {rigid_rank}"
        )
    inverse_sqrt_mass = np.repeat(1.0 / np.sqrt(masses), 3)

    def project_gradient(values: np.ndarray) -> np.ndarray:
        return projector @ (inverse_sqrt_mass * values)

    def project_hessian(values: np.ndarray) -> np.ndarray:
        mass_weighted = inverse_sqrt_mass[:, None] * values * inverse_sqrt_mass[None, :]
        return projector @ mass_weighted @ projector

    projected_residual_gradient = project_gradient(residual_gradient)
    projected_residual_hessian = project_hessian(residual_hessian)
    projected_parameter_gradient = np.asarray(
        [project_gradient(values) for values in parameter_gradient_response]
    )
    projected_parameter_hessian = np.asarray(
        [project_hessian(values) for values in parameter_hessian_response]
    )
    projected_design_gradient = projected_parameter_gradient.T
    projected_design_hessian = projected_parameter_hessian[:, upper[0], upper[1]].T
    output_dir.mkdir(parents=True)
    arrays_path = output_dir / "linear_response_arrays.npz"
    np.savez_compressed(
        arrays_path,
        qm_gradient_kcal_mol_angstrom=qm_gradient,
        qm_hessian_kcal_mol_angstrom2=qm_hessian,
        base_gradient_kcal_mol_angstrom=base_gradient,
        base_hessian_kcal_mol_angstrom2=base_hessian,
        parameter_gradient_response=parameter_gradient_response,
        parameter_hessian_response=parameter_hessian_response,
        residual_gradient=residual_gradient,
        residual_hessian_upper=residual_hessian[upper],
        design_gradient=design_gradient,
        design_hessian_upper=design_hessian,
        hessian_upper_row=upper[0],
        hessian_upper_column=upper[1],
        masses_amu=masses,
        rigid_body_projector=projector,
        projected_residual_gradient=projected_residual_gradient,
        projected_residual_hessian_upper=projected_residual_hessian[upper],
        projected_design_gradient=projected_design_gradient,
        projected_design_hessian_upper=projected_design_hessian,
    )
    matrix_shape = {
        "gradient": list(design_gradient.shape),
        "hessian_upper_triangle": list(design_hessian.shape),
    }
    identifiability = {
        "gradient_block": _svd_identifiability(design_gradient),
        "hessian_upper_triangle_block": _svd_identifiability(design_hessian),
        "projected_mass_weighted_gradient_block": _svd_identifiability(
            projected_design_gradient
        ),
        "projected_mass_weighted_hessian_upper_triangle_block": _svd_identifiability(
            projected_design_hessian
        ),
        "interpretation": (
            "Single-minimum rank is diagnostic only. Rank deficiency or near-null "
            "directions require regularization and additional stereoisomer/conformer targets."
        ),
    }
    manifest = {
        "schema": "nadoc.photoproduct-openmm-linear-response.v1",
        "status": "candidate_response_unfitted_not_releasable",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": basis["product_id"],
        "model_id": basis["model_id"],
        "hypothesis_id": basis["hypothesis_id"],
        "software": {
            "openmm": openmm.version.version,
            "numpy": np.__version__,
        },
        "atom_count": len(stable_keys),
        "cartesian_dimension": dimension,
        "parameter_count": len(parameters),
        "matrix_shape": matrix_shape,
        "single_minimum_identifiability": identifiability,
        "units": {
            "gradient": "kcal/mol/angstrom",
            "hessian": "kcal/mol/angstrom^2",
            "parameter_coefficients": "see linear parameter map",
        },
        "finite_difference": {
            "platform": "Reference",
            "step_angstrom": step_angstrom,
            "base_raw_maximum_asymmetry_kcal_mol_angstrom2": base_asymmetry,
            "half_step_raw_maximum_asymmetry_kcal_mol_angstrom2": half_step_asymmetry,
            "base_step_halving_max_abs_difference_kcal_mol_angstrom2": float(
                np.max(np.abs(base_step_difference))
            ),
            "base_step_halving_rms_difference_kcal_mol_angstrom2": float(
                np.sqrt(np.mean(base_step_difference**2))
            ),
            "maximum_basis_raw_asymmetry_kcal_mol_angstrom2": maximum_basis_asymmetry,
            "status": "measured_requires_fit_review",
        },
        "target": {
            "kind": (
                "reviewed_off_equilibrium_conformer"
                if conformer_target
                else "audited_harmonic_minimum"
            ),
            "qm_gradient": (
                "explicit audited nonzero Cartesian gradient"
                if conformer_target
                else "zero at the audited optimized geometry"
            ),
            "qm_gradient_conversion_factor": (
                HARTREE_PER_BOHR_TO_KCAL_PER_MOL_ANGSTROM if conformer_target else None
            ),
            "qm_hessian_conversion_factor": (
                HARTREE_PER_BOHR2_TO_KCAL_PER_MOL_ANGSTROM2
            ),
            "coupling": "all unique Cartesian Hessian entries retained",
            "diagonal_projection_used": False,
            "rigid_body_projection": {
                "method": "mass-weighted Eckart translation/rotation projector",
                "rank_removed": rigid_rank,
                "full_coupled_vibrational_matrix_retained": True,
            },
        },
        "outputs": {
            "linear_response_arrays": {
                "path": str(arrays_path.resolve()),
                "sha256": _sha256(arrays_path),
            }
        },
        "sources": {
            "fit_basis_manifest": {
                "path": str(fit_basis_manifest_path.resolve()),
                "sha256": _sha256(fit_basis_manifest_path),
            },
            "hessian_targets": {
                "path": str(hessian_targets_path.resolve()),
                "sha256": _sha256(hessian_targets_path),
            },
            "linear_fit_system": basis_outputs["linear_fit_system"],
            "linear_parameter_map": basis_outputs["linear_parameter_map"],
            "stable_atom_map": basis_sources["stable_atom_map"],
            "qm_hessian": targets["cartesian_hessian"],
            "qm_gradient": (
                targets["cartesian_gradient"] if conformer_target else None
            ),
            "target_geometry": targets["source_geometry"],
        },
        "release_blockers": [
            "the response matrix has not been regularized, fitted, or cross-validated",
            "gradient and Hessian blocks require independently justified relative weights",
            "rigid-body and mode weighting choices require sensitivity analysis",
            "torsion basis selection and physical harmonic transforms remain unreviewed",
        ],
        "warning": (
            "This is an unfitted linear-response dataset, not a force field or simulation input."
        ),
    }
    manifest_path = output_dir / "linear_response_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
