import json
from pathlib import Path
import subprocess

import pytest

from backend.parameterization.photoproduct_fit import (
    audit_parameter_workbook,
    build_parameter_workbook,
)
from backend.parameterization.photoproduct_charmm_export import (
    export_charmm_candidate_assets,
)
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.core.namd_topology import find_psfgen
from backend.core.photoproduct_psf_audit import parse_psf_atoms, parse_psf_index_section


def test_parameter_workbook_is_explicitly_unassigned_and_gate_neutral(tmp_path):
    path = tmp_path / "fit.json"
    workbook = build_parameter_workbook(
        product="TT-CPD", stereochemistry="cis-syn", output_path=path
    )

    assert workbook["release_status"] == "unassigned"
    assert workbook["gate_effect"] == "none"
    assert len(workbook["bonded_terms"]["bonds"]) > 2
    assert len(workbook["bonded_terms"]["impropers_added"]) == 4
    assert workbook["bonded_terms"]["impropers_added"][0][
        "ordered_atoms_candidate"
    ] == ["1:C5", "1:C4", "1:C6", "1:C7"]
    assert all(
        item["ordering_candidate_status"] == "requires_product_specific_review"
        and item["ordered_atoms"] is None
        for item in workbook["bonded_terms"]["impropers_added"]
    )
    assert len(workbook["atoms"]) == 28
    assert all(not item["atom"].endswith(":C1'") for item in workbook["atoms"])
    assert workbook["charge_scope"]["unchanged_boundary_atoms"] == [
        "1:C1'",
        "2:C1'",
    ]
    assert all(atom["final_type"] is None for atom in workbook["atoms"])
    assert json.loads(path.read_text()) == workbook

    report = audit_parameter_workbook(path)
    assert report["status"] == "incomplete"
    assert report["passed"] is False
    assert report["gate_effect"] == "none"
    assert any("final atom type is missing" in error for error in report["errors"])
    assert any("required QM target set is empty" in error for error in report["errors"])


def test_parameter_workbook_never_overwrites_evidence(tmp_path):
    path = tmp_path / "fit.json"
    build_parameter_workbook(
        product="TT-CPD", stereochemistry="cis-syn", output_path=path
    )
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        build_parameter_workbook(
            product="TT-CPD", stereochemistry="cis-syn", output_path=path
        )


def test_parameter_workbook_rejects_mismatched_initial_guess(tmp_path):
    guess = tmp_path / "guess.json"
    guess.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-initial-charge-guess.v1",
                "product_id": "some-other-product",
                "atoms": [],
            }
        )
    )
    with pytest.raises(ValueError, match="does not match"):
        build_parameter_workbook(
            product="TT-CPD",
            stereochemistry="cis-syn",
            output_path=tmp_path / "fit.json",
            initial_charge_guess_path=guess,
        )


def _completed_test_workbook(path):
    workbook = build_parameter_workbook(
        product="TT-CPD", stereochemistry="cis-syn", output_path=path
    )
    type_by_element = {"C": "TCPC", "H": "TCPH", "N": "TCPN", "O": "TCPO"}
    type_by_atom = {}
    for atom in workbook["atoms"]:
        local_name = atom["atom"].split(":", 1)[1]
        atom_type = type_by_element[local_name[0]]
        type_by_atom[atom["atom"]] = atom_type
        atom.update(
            final_type=atom_type,
            final_charge=0.0,
            charge_fit_source="synthetic unit-test evidence",
            lj_source_or_fit="synthetic unit-test evidence",
        )
    patch = workbook["charmm_patch"]
    patch["patch_name"] = "TCPDCS1"
    patch["improper_removal_review"] = {
        "status": "reviewed",
        "source": "synthetic precursor-topology review",
    }
    masses = {"C": 12.011, "H": 1.008, "N": 14.007, "O": 15.999}
    patch["custom_atom_types"] = [
        {
            "name": atom_type,
            "element": element,
            "mass_amu": masses[element],
            "epsilon_kcal_mol": -0.1,
            "rmin_half_angstrom": 1.5,
            "source": "synthetic unit-test evidence",
        }
        for element, atom_type in type_by_element.items()
    ]

    def types_for(atoms):
        return [type_by_atom.get(atom, "CN7B") for atom in atoms]

    for record in workbook["bonded_terms"]["bonds"]:
        record.update(
            types=types_for(record["atoms"]),
            source="synthetic unit-test fit",
            emit_parameter=True,
            k_kcal_mol_a2=200.0,
            r0_angstrom=1.5,
        )
    for record in workbook["bonded_terms"]["angles"]:
        record.update(
            types=types_for(record["atoms"]),
            source="synthetic unit-test fit",
            emit_parameter=True,
            k_kcal_mol_rad2=50.0,
            theta0_degrees=109.5,
        )
    for record in workbook["bonded_terms"]["dihedrals"]:
        record.update(
            types=types_for(record["atoms"]),
            source="synthetic unit-test fit",
            emit_parameter=True,
            fourier_terms=[
                {"k_kcal_mol": 0.5, "multiplicity": 3, "delta_degrees": 0.0}
            ],
        )
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    center_by_atom = {
        record["atom"]: record for record in definition["product_stereocenters"]
    }
    for record in workbook["bonded_terms"]["impropers_added"]:
        center = center_by_atom[record["stereocenter"]]
        ordered = [center["atom"], *center["signed_volume_reference_atoms"]]
        record.update(
            ordered_atoms=ordered,
            types=types_for(ordered),
            source="synthetic unit-test fit",
            emit_parameter=True,
            k_kcal_mol_rad2=20.0,
            psi0_degrees=35.0,
        )
    workbook["bonded_terms"]["impropers_removed"] = [
        {
            "ordered_atoms": [f"{endpoint}:C5", f"{endpoint}:C4", f"{endpoint}:C6", f"{endpoint}:C7"],
            "source": "synthetic CHARMM36 THY topology review",
        }
        for endpoint in (1, 2)
    ]
    for key in workbook["required_qm_targets"]:
        workbook["required_qm_targets"][key] = ["synthetic unit-test evidence"]
    workbook["fit_metadata"] = {
        key: "synthetic unit-test evidence" for key in workbook["fit_metadata"]
    }
    path.write_text(json.dumps(workbook, indent=2) + "\n")
    return workbook


def test_complete_workbook_renders_gate_neutral_charmm_candidate(tmp_path):
    workbook_path = tmp_path / "workbook.json"
    _completed_test_workbook(workbook_path)
    report = audit_parameter_workbook(workbook_path)
    assert report["passed"] is True

    output_dir = tmp_path / "candidate"
    manifest = export_charmm_candidate_assets(
        workbook_path=workbook_path,
        workbook_audit_path=tmp_path / "workbook_audit.json",
        output_dir=output_dir,
    )
    assert manifest["gate_effect"] == "none"
    assert manifest["status"].startswith("candidate_requires_")
    assert manifest["variant"]["schema"] == "nadoc.photoproduct-parameter-variant.v1"
    assert manifest["variant"]["id"].startswith("tt-cpd-cis-syn-")
    assert manifest["variant"]["parameter_workbook_sha256"]
    topology = (output_dir / "photoproduct.rtf").read_text()
    parameters = (output_dir / "photoproduct.prm").read_text()
    spec = json.loads((output_dir / "topology_audit_spec.json").read_text())
    assert "PRES TCPDCS1" in topology
    assert "BOND 1C5 2C5" in topology
    assert "ATOM 1C5M" in topology
    assert "DELETE IMPR 1C5 1C4 1C6 1C5M" not in topology
    assert "IMPR 1C5 1C4 1C6 1C5M" in topology
    assert "BONDS\n" in parameters
    assert "NONBONDED NBXMOD 5" in parameters
    assert ["1:C5", "2:C5"] in spec["crosslinks"]
    assert any(item["atom"] == "1:C5M" for item in spec["expected_product_atoms"])


def test_corrected_candidate_records_parent_and_policy_lineage(tmp_path):
    workbook_path = tmp_path / "workbook.json"
    _completed_test_workbook(workbook_path)
    audit_path = tmp_path / "workbook_audit.json"
    audit_parameter_workbook(workbook_path)
    parent_dir = tmp_path / "parent"
    export_charmm_candidate_assets(
        workbook_path=workbook_path,
        workbook_audit_path=audit_path,
        output_dir=parent_dir,
        variant_id="cis-syn-baseline-v1",
    )
    policy = tmp_path / "refit_policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-bonded-refit-policy.v1",
                "version": "1.0.0",
                "status": "workflow_policy",
                "product_id": "tt-cpd-cis-syn",
                "variant_family": "cis-syn-ring-refit-v1",
            }
        )
    )

    result = export_charmm_candidate_assets(
        workbook_path=workbook_path,
        workbook_audit_path=audit_path,
        output_dir=tmp_path / "corrected",
        variant_id="cis-syn-ring-refit-v1-a",
        parent_candidate_manifest_path=parent_dir / "candidate_manifest.json",
        correction_policy_path=policy,
    )

    assert result["variant"]["kind"] == "corrected_candidate"
    assert result["variant"]["parent_candidate_manifest"]["variant_id"] == (
        "cis-syn-baseline-v1"
    )
    assert result["variant"]["parent_candidate_manifest"]["sha256"]
    assert result["variant"]["correction_policy"]["version"] == "1.0.0"


def test_charmm_export_rejects_incomplete_or_unlinked_workbook(tmp_path):
    workbook_path = tmp_path / "workbook.json"
    build_parameter_workbook(
        product="TT-CPD", stereochemistry="cis-syn", output_path=workbook_path
    )
    audit_parameter_workbook(workbook_path)
    with pytest.raises(ValueError, match="passed hash-linked"):
        export_charmm_candidate_assets(
            workbook_path=workbook_path,
            workbook_audit_path=tmp_path / "workbook_audit.json",
            output_dir=tmp_path / "candidate",
        )


@pytest.mark.slow
def test_exported_candidate_topology_runs_in_real_psfgen(tmp_path):
    """Syntax integration only; synthetic values are not chemistry validation."""

    workbook_path = tmp_path / "workbook.json"
    _completed_test_workbook(workbook_path)
    audit_parameter_workbook(workbook_path)
    candidate_dir = tmp_path / "candidate"
    export_charmm_candidate_assets(
        workbook_path=workbook_path,
        workbook_audit_path=tmp_path / "workbook_audit.json",
        output_dir=candidate_dir,
    )
    base_topology = Path(__file__).parents[1] / "backend/data/forcefield/top_all36_na.rtf"
    output_prefix = tmp_path / "patched"
    script = tmp_path / "build.tcl"
    script.write_text(
        "\n".join(
            [
                f"topology {base_topology}",
                f"topology {candidate_dir / 'photoproduct.rtf'}",
                "segment D000 {",
                "  first 5TER",
                "  last 3TER",
                "  auto angles dihedrals",
                "  residue 1 THY",
                "  residue 2 THY",
                "}",
                "patch DEO5 D000:1",
                "patch DEOX D000:2",
                "patch TCPDCS1 D000:1 D000:2",
                "regenerate angles dihedrals",
                "guesscoord",
                f"writepsf {output_prefix}.psf",
                f"writepdb {output_prefix}.pdb",
                "exit",
                "",
            ]
        )
    )
    process = subprocess.run(
        [find_psfgen(), str(script)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    psf_text = output_prefix.with_suffix(".psf").read_text()
    atoms = parse_psf_atoms(psf_text)
    atom_index = {(atom.resid, atom.name): atom.index for atom in atoms}
    bonds = {
        frozenset(pair)
        for pair in parse_psf_index_section(psf_text, "!NBOND", 2)
    }
    assert frozenset((atom_index[("1", "C5")], atom_index[("2", "C5")])) in bonds
    assert frozenset((atom_index[("1", "C6")], atom_index[("2", "C6")])) in bonds
