import hashlib
import json

import numpy as np
import pytest
from openmm import (
    Context,
    CustomBondForce,
    CustomExternalForce,
    Platform,
    System,
    VerletIntegrator,
    XmlSerializer,
    unit,
)

from backend.parameterization.photoproduct_openmm_linear_response import (
    HARTREE_PER_BOHR2_TO_KCAL_PER_MOL_ANGSTROM2,
    HARTREE_PER_BOHR_TO_KCAL_PER_MOL_ANGSTROM,
    _svd_identifiability,
    build_openmm_linear_response,
    cartesian_gradient_hessian,
    mass_weighted_rigid_body_projector,
)


def test_hartree_bohr_hessian_conversion_is_positive_and_expected_scale():
    assert 2240.0 < HARTREE_PER_BOHR2_TO_KCAL_PER_MOL_ANGSTROM2 < 2241.0
    assert 1185.0 < HARTREE_PER_BOHR_TO_KCAL_PER_MOL_ANGSTROM < 1186.0


def test_cartesian_hessian_matches_a_harmonic_bond():
    system = System()
    system.addParticle(12.0)
    system.addParticle(12.0)
    force = CustomBondForce("0.5*418.4*(r-0.1)^2")
    force.addBond(0, 1, [])
    system.addForce(force)
    integrator = VerletIntegrator(0.001 * unit.picoseconds)
    context = Context(system, integrator, Platform.getPlatformByName("Reference"))
    xyz = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))

    gradient, hessian, asymmetry = cartesian_gradient_hessian(
        context, xyz, unit, step_angstrom=1.0e-4
    )

    assert np.max(np.abs(gradient)) < 1.0e-10
    assert asymmetry < 1.0e-8
    assert np.isclose(hessian[0, 0], 1.0, atol=1.0e-6)
    assert np.isclose(hessian[0, 3], -1.0, atol=1.0e-6)
    assert np.isclose(hessian[3, 3], 1.0, atol=1.0e-6)
    del context, integrator


def test_identifiability_reports_rank_deficiency_at_declared_threshold():
    matrix = np.asarray(((1.0, 0.0, 1.0), (0.0, 1.0, 1.0)))

    report = _svd_identifiability(matrix)

    assert report["rank_by_relative_threshold"]["relative_1e-08"] == 2
    assert report["full_column_rank_at_relative_1e-8"] is False


def test_mass_weighted_projector_removes_six_rigid_directions():
    xyz = np.asarray(
        ((0.0, 0.0, 0.0), (1.2, 0.0, 0.0), (0.1, 1.0, 0.3), (0.2, 0.4, 1.1))
    )
    masses = np.asarray((12.0, 1.0, 14.0, 16.0))

    projector, rank = mass_weighted_rigid_body_projector(xyz, masses)

    assert rank == 6
    assert np.allclose(projector, projector.T, atol=1.0e-12)
    assert np.allclose(projector @ projector, projector, atol=1.0e-12)
    assert np.isclose(np.trace(projector), xyz.size - 6, atol=1.0e-10)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_off_equilibrium_response_retains_explicit_qm_gradient(tmp_path):
    system = System()
    for _ in range(4):
        system.addParticle(12.0)
    force = CustomExternalForce("scale*(x*x+y*y+z*z)")
    force.addGlobalParameter("scale", 0.0)
    for index in range(4):
        force.addParticle(index, [])
    system.addForce(force)
    system_path = tmp_path / "system.xml"
    system_path.write_text(XmlSerializer.serialize(system))
    parameter_map = tmp_path / "parameters.json"
    parameter_map.write_text(
        json.dumps(
            [
                {
                    "name": "scale",
                    "default": 0.0,
                    "group_id": "bond:test",
                    "category": "bonds",
                }
            ]
        )
        + "\n"
    )
    stable_map = tmp_path / "stable_map.json"
    stable_map.write_text(
        json.dumps([{"stable_atom_key": key} for key in ("A", "B", "C", "D")]) + "\n"
    )
    basis = tmp_path / "basis.json"
    basis.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-openmm-linear-fit-basis.v1",
                "status": "candidate_basis_unfitted_not_releasable",
                "simulation_ready": False,
                "gate_effect": "none",
                "product_id": "fixture-product",
                "model_id": "fixture-model",
                "hypothesis_id": "fixture-hypothesis",
                "parameter_count": 1,
                "outputs": {
                    "linear_fit_system": {
                        "path": str(system_path),
                        "sha256": _sha256(system_path),
                    },
                    "linear_parameter_map": {
                        "path": str(parameter_map),
                        "sha256": _sha256(parameter_map),
                    },
                },
                "sources": {
                    "stable_atom_map": {
                        "path": str(stable_map),
                        "sha256": _sha256(stable_map),
                    }
                },
            }
        )
        + "\n"
    )
    geometry = tmp_path / "conformer.xyz"
    geometry.write_text(
        "4\nnonlinear fixture\n"
        "C 0.0 0.0 0.0\nC 1.0 0.0 0.0\nC 0.2 1.1 0.0\nC 0.1 0.2 1.2\n"
    )
    gradient = tmp_path / "gradient.txt"
    qm_gradient = np.linspace(-0.006, 0.005, 12)
    np.savetxt(gradient, qm_gradient)
    hessian = tmp_path / "hessian.txt"
    np.savetxt(hessian, np.eye(12) * 0.01)
    target = tmp_path / "target.json"
    target.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-hessian-target-bundle.v2",
                "status": "candidate_off_equilibrium_response_evidence",
                "simulation_ready": False,
                "gate_effect": "none",
                "target_kind": "reviewed_off_equilibrium_conformer",
                "product_id": "fixture-product",
                "model_id": "fixture-model",
                "atom_map": ["A", "B", "C", "D"],
                "source_geometry": {
                    "path": str(geometry),
                    "sha256": _sha256(geometry),
                },
                "cartesian_gradient": {
                    "path": str(gradient),
                    "sha256": _sha256(gradient),
                    "units": "hartree/bohr",
                    "dimension": 12,
                },
                "cartesian_hessian": {
                    "path": str(hessian),
                    "sha256": _sha256(hessian),
                    "units": "hartree/bohr^2",
                    "dimension": 12,
                },
            }
        )
        + "\n"
    )
    output = tmp_path / "response"
    manifest = build_openmm_linear_response(
        fit_basis_manifest_path=basis,
        hessian_targets_path=target,
        output_dir=output,
    )
    assert manifest["target"]["kind"] == "reviewed_off_equilibrium_conformer"
    with np.load(output / "linear_response_arrays.npz", allow_pickle=False) as arrays:
        expected = qm_gradient * HARTREE_PER_BOHR_TO_KCAL_PER_MOL_ANGSTROM
        assert np.allclose(arrays["qm_gradient_kcal_mol_angstrom"], expected)
        assert np.allclose(
            arrays["residual_gradient"],
            expected - arrays["base_gradient_kcal_mol_angstrom"],
        )

    broken = json.loads(target.read_text())
    broken.pop("cartesian_gradient")
    broken_path = tmp_path / "broken_target.json"
    broken_path.write_text(json.dumps(broken) + "\n")
    with pytest.raises(ValueError, match="gradient"):
        build_openmm_linear_response(
            fit_basis_manifest_path=basis,
            hessian_targets_path=broken_path,
            output_dir=tmp_path / "broken-response",
        )
