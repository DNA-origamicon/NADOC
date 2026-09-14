import hashlib
import json

import pytest

from backend.core.cpd_forcefield import (
    CpdCapabilityError,
    assert_packaged_photoproduct_integrator,
    assert_cpd_simulation_supported,
    cpd_capability,
    inject_packaged_photoproduct_parameters,
)
from backend.core.models import Design, PhotoproductJunction


def _product_design():
    return Design(
        photoproduct_junctions=[
            PhotoproductJunction(base_key_1="h0:1:FORWARD", base_key_2="h0:2:FORWARD")
        ]
    )


def test_manifest_keeps_unvalidated_cpd_chemistry_disabled():
    capability = cpd_capability()
    assert capability["available"] is False
    assert capability["missing_requirements"]


def test_product_design_fails_closed_with_no_two_bond_fallback():
    with pytest.raises(CpdCapabilityError) as caught:
        assert_cpd_simulation_supported(_product_design(), path="test exporter")
    message = str(caught.value)
    assert "no reactant-topology or two-bond/restraint fallback" in message
    assert "gate not passed: qm_reference_data" in message
    assert "required asset not declared: parameters" in message


def test_reactant_design_is_unaffected_by_capability_gate():
    assert_cpd_simulation_supported(Design(), path="test exporter")


def test_coordinate_builder_fails_before_mutating_reactant_model():
    from backend.core.atomistic import AtomisticModel
    from backend.core.cpd_product import (
        build_cpd_product_coordinates,
        unavailable_placement_report,
    )

    model = AtomisticModel(atoms=[], bonds=[])
    report = unavailable_placement_report(["h0:1:FORWARD", "h0:2:FORWARD"], None)
    assert report["capability_manifest_schema"] == "nadoc.cpd-forcefield-manifest.v1"
    assert len(report["capability_manifest_sha256"]) == 64
    assert report["coordinates_modified"] is False
    with pytest.raises(CpdCapabilityError):
        build_cpd_product_coordinates(_product_design(), model)
    assert model.atoms == [] and model.bonds == []


@pytest.mark.parametrize(
    "entrypoint",
    [
        "psfgen",
        "explicit",
        "vacuum",
        "gbis",
        "periodic",
        "legacy_zip",
        "pdb",
        "psf",
        "precondition",
        "openmm",
    ],
)
def test_every_topology_and_package_entrypoint_fails_before_emitting_files(
    entrypoint, tmp_path
):
    design = _product_design()
    from backend.core.atomistic import AtomisticModel
    from backend.core.md_precondition import write_preconditioned_namd_inputs
    from backend.core.namd_gbis import build_namd_gbis_package
    from backend.core.namd_package import build_namd_package
    from backend.core.namd_solvate import build_namd_solvated_package
    from backend.core.namd_topology import build_charmm_psfgen_topology
    from backend.core.namd_vacuum import build_namd_vacuum_package
    from backend.core.openmm_implicit import build_openmm_topology
    from backend.core.pdb_export import export_pdb, export_psf
    from backend.core.periodic_cell import build_periodic_cell_package

    calls = {
        "psfgen": lambda: build_charmm_psfgen_topology(design),
        "explicit": lambda: build_namd_solvated_package(design),
        "vacuum": lambda: build_namd_vacuum_package(design, tmp_path),
        "gbis": lambda: build_namd_gbis_package(design, tmp_path),
        "periodic": lambda: build_periodic_cell_package(design),
        "legacy_zip": lambda: build_namd_package(design),
        "pdb": lambda: export_pdb(design),
        "psf": lambda: export_psf(design),
        "precondition": lambda: write_preconditioned_namd_inputs(
            design, AtomisticModel(atoms=[], bonds=[]), tmp_path, name="cpd", report={}
        ),
        "openmm": lambda: build_openmm_topology(design),
    }
    with pytest.raises(
        CpdCapabilityError,
        match="capability is unavailable|does not implement formed-photoproduct",
    ):
        calls[entrypoint]()
    assert not any(tmp_path.iterdir())


def _write_packaged_product(tmp_path):
    parameter_rel = "photoproducts/tt-cpd-cis-syn/product.prm"
    parameter_path = tmp_path / "forcefield" / parameter_rel
    parameter_path.parent.mkdir(parents=True)
    parameter_path.write_text("BONDS\n")
    digest = hashlib.sha256(parameter_path.read_bytes()).hexdigest()
    manifest = {
        "schema": "nadoc.packaged-photoproduct-forcefield.v1",
        "timestep_fs": 2.0,
        "hmr_4fs_enabled": False,
        "lesions": [{"lesion_id": "lesion-1"}],
        "assets": [
            {
                "kind": "parameters",
                "relative_path": parameter_rel,
                "sha256": digest,
            }
        ],
    }
    (tmp_path / "photoproduct_forcefield_manifest.json").write_text(
        json.dumps(manifest)
    )
    return parameter_path


def test_frozen_package_parameters_are_hash_checked_injected_and_idempotent(tmp_path):
    parameter_path = _write_packaged_product(tmp_path)
    base = "parameters forcefield/par_all36_na.prm\nrun 0\n"
    rendered = inject_packaged_photoproduct_parameters(base, tmp_path)
    assert "forcefield/photoproducts/tt-cpd-cis-syn/product.prm" in rendered
    assert inject_packaged_photoproduct_parameters(rendered, tmp_path) == rendered

    parameter_path.write_text("TAMPERED\n")
    with pytest.raises(CpdCapabilityError, match="hash mismatch"):
        inject_packaged_photoproduct_parameters(base, tmp_path)


def test_frozen_product_package_refuses_hmr_or_more_than_two_fs(tmp_path):
    _write_packaged_product(tmp_path)
    assert_packaged_photoproduct_integrator(
        tmp_path, timestep_fs=2.0, hmr=False, path="test"
    )
    with pytest.raises(CpdCapabilityError, match="at 4 fs"):
        assert_packaged_photoproduct_integrator(
            tmp_path, timestep_fs=4.0, hmr=False, path="test"
        )
    with pytest.raises(CpdCapabilityError, match="HMR=on"):
        assert_packaged_photoproduct_integrator(
            tmp_path, timestep_fs=2.0, hmr=True, path="test"
        )
