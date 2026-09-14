from __future__ import annotations

import hashlib
import json

import pytest

import backend.parameterization.photoproduct_candidate_assembly as assembly
from backend.parameterization.photoproduct_charmm_export import (
    export_charmm_candidate_assets,
)
from backend.parameterization.photoproduct_fit import (
    audit_parameter_workbook,
    build_parameter_workbook,
)


def _source(path):
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_fourier_multiplicity_accepts_fit_and_workbook_names() -> None:
    assert assembly._fourier_multiplicity({"periodicity": 4}) == 4
    assert assembly._fourier_multiplicity({"multiplicity": 3}) == 3
    with pytest.raises(ValueError, match="positive integer periodicity"):
        assembly._fourier_multiplicity({"periodicity": 0})


def test_transformed_angle_keeps_urey_bradley_pair() -> None:
    record = {}
    assembly._apply_transformed_angle(
        record,
        {
            "k_kcal_mol_rad2": 64.0,
            "theta0_degrees": 98.0,
            "urey_bradley": {
                "k_kcal_mol_angstrom2": 21.5,
                "s0_angstrom": 2.2,
            },
        },
    )

    assert record == {
        "k_kcal_mol_rad2": 64.0,
        "theta0_degrees": 98.0,
        "urey_bradley_k_kcal_mol_a2": 21.5,
        "urey_bradley_s0_angstrom": 2.2,
    }


def test_transformed_angle_rejects_half_or_nonphysical_urey_bradley() -> None:
    with pytest.raises(ValueError, match="nonphysical Urey-Bradley"):
        assembly._apply_transformed_angle(
            {},
            {
                "k_kcal_mol_rad2": 64.0,
                "theta0_degrees": 98.0,
                "urey_bradley": {
                    "k_kcal_mol_angstrom2": 21.5,
                    "s0_angstrom": None,
                },
            },
        )


def _inputs(
    tmp_path,
    monkeypatch,
    *,
    product_id="tt-cpd-cis-syn",
    stereochemistry="cis-syn",
    full_boundary=False,
):
    scaffold_path = tmp_path / "source-scaffold.json"
    scaffold = build_parameter_workbook(
        product="TT-CPD",
        stereochemistry=stereochemistry,
        output_path=scaffold_path,
    )
    type_by_element = {
        "C": "TSTC",
        "H": "TSTH",
        "N": "TSTN",
        "O": "TSTO",
    }
    atom_types = {}
    charges = {}
    for atom in scaffold["atoms"]:
        local = atom["atom"].split(":", 1)[1]
        atom_types[atom["atom"]] = type_by_element[local[0]]
        charges[atom["atom"]] = 0.0
    for endpoint in (1, 2):
        atom_types[f"{endpoint}:CM"] = "TSTC"
        charges[f"{endpoint}:CM"] = 0.0
        for cap_hydrogen in ("HCM1", "HCM2", "HCM3"):
            atom_types[f"{endpoint}:{cap_hydrogen}"] = "TSTH"
        if full_boundary:
            atom_types.update(
                {
                    f"{endpoint}:C1'": "TSTC",
                    f"{endpoint}:O4'": "TSTO",
                    f"{endpoint}:C2'": "TSTC",
                    f"{endpoint}:H1'": "TSTH",
                }
            )

    def model_path(atoms):
        return (
            list(atoms)
            if full_boundary
            else [atom.replace(":C1'", ":CM") for atom in atoms]
        )

    transfers = []
    for category in ("bonds", "angles", "dihedrals"):
        for record in scaffold["bonded_terms"][category]:
            atoms = model_path(record["atoms"])
            types = [atom_types[atom] for atom in atoms]
            values = {
                "bonds": [200.0, 1.5],
                "angles": [50.0, 109.5],
                "dihedrals": [0.2, 2.0, 180.0],
            }[category]
            transfers.append(
                {
                    "category": category,
                    "atoms": atoms,
                    "types": types,
                    "coverage": "exact",
                    "matches": [
                        {
                            "types": types,
                            "values": values,
                            "source": "synthetic pinned CGenFF",
                            "line_number": 1,
                        }
                    ],
                }
            )
    for endpoint in (1, 2):
        boundary_atoms = (
            ("O4'", "C2'", "H1'")
            if full_boundary
            else ("HCM1", "HCM2", "HCM3")
        )
        for cap_hydrogen in boundary_atoms:
            atoms = [
                f"{endpoint}:C6",
                f"{endpoint}:N1",
                f"{endpoint}:C1'" if full_boundary else f"{endpoint}:CM",
                f"{endpoint}:{cap_hydrogen}",
            ]
            transfers.append(
                {
                    "category": "dihedrals",
                    "atoms": atoms,
                    "types": [atom_types[atom] for atom in atoms],
                    "coverage": "exact",
                    "matches": [
                        {
                            "types": [atom_types[atom] for atom in atoms],
                            "values": [0.2, 2.0, 180.0],
                            "source": "synthetic fitted model-boundary torsion",
                            "line_number": 1,
                        }
                    ],
                }
            )

    cgenff_topology = tmp_path / "cgenff.rtf"
    cgenff_parameters = tmp_path / "cgenff.prm"
    cgenff_topology.write_text("* synthetic\n")
    cgenff_parameters.write_text("* synthetic\n")
    hessian = tmp_path / "hessian-targets.json"
    hessian.write_text("{}\n")
    nonbonded = tmp_path / "nonbonded.json"
    nonbonded_payload = {
        "schema": "nadoc.photoproduct-nonbonded-hypothesis-fit.v1",
        "product_id": product_id,
        "results": [
            {
                "hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
                "atom_types": atom_types,
                "charges_e": charges,
                "maximum_constraint_error_e": 0.0,
                "maximum_charge_change_e": 0.1,
                "dipole_vector_error_debye": 1.0,
                "esp_validation": {"rmse_atomic_unit": 0.01},
                "water_metrics": [
                    {
                        "split": "held_out",
                        "energy_error_kcal_mol": 0.2,
                        "distance_error_angstrom": 0.05,
                    }
                ],
            }
        ],
    }
    nonbonded.write_text(json.dumps(nonbonded_payload))
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "sources": {
                    "nonbonded_fit": _source(nonbonded),
                    "cgenff_parameters": _source(cgenff_parameters),
                }
            }
        )
    )
    fit_plan = tmp_path / "fit-plan.json"
    fit_plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-bonded-fit-plan.v1",
                "status": "candidate_plan_unassigned_not_releasable",
                "product_id": product_id,
                "hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
                "transfer_candidates": transfers,
                "uncovered_parameter_groups": [],
                "precursor_improper_removal_candidates": [
                    [
                        f"{endpoint}:C5",
                        f"{endpoint}:C4",
                        f"{endpoint}:C6",
                        f"{endpoint}:C7",
                    ]
                    for endpoint in (1, 2)
                ],
                "sources": {
                    "model_coverage": _source(coverage),
                    "hessian_targets": _source(hessian),
                },
            }
        )
    )
    selected = tmp_path / "selected.json"
    selected.write_text("{}\n")
    transformed_impropers = []
    for record in scaffold["bonded_terms"]["impropers_added"]:
        transformed_impropers.append(
            {
                "group_id": f"improper:{record['stereocenter']}",
                "ordered_atoms_candidate": record["ordered_atoms_candidate"],
                "k_kcal_mol_rad2": 20.0,
                "psi0_degrees": 30.0,
            }
        )
    transform = tmp_path / "transform.json"
    transform.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-charmm-bonded-transform-candidate.v1",
                "status": "algebraically_transformed_requires_term_mapping_and_validation",
                "hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
                "bonded_terms": {
                    "bonds": [],
                    "angles": [],
                    "dihedrals": [],
                    "impropers": transformed_impropers,
                },
                "sources": {"selected_response_fit_candidate": _source(selected)},
            }
        )
    )
    boundary = tmp_path / "boundary.json"
    boundary.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
                "status": "quantitatively_screened_boundary",
                "product_id": product_id,
            }
        )
    )
    monkeypatch.setattr(assembly, "assert_pinned_cgenff_inputs", lambda *_: {})
    monkeypatch.setattr(
        assembly,
        "parse_charmm_masses",
        lambda _path: {
            value: {"mass_amu": 12.0, "element": key}
            for key, value in type_by_element.items()
        },
    )
    monkeypatch.setattr(
        assembly,
        "parse_charmm_nonbonded",
        lambda _path: {
            value: {
                "epsilon_kcal_mol": -0.1,
                "rmin_half_angstrom": 1.5,
            }
            for value in type_by_element.values()
        },
    )
    return {
        "fit_plan_path": fit_plan,
        "nonbonded_fit_path": nonbonded,
        "charmm_transform_path": transform,
        "dna_boundary_model_path": boundary,
        "cgenff_topology_path": cgenff_topology,
        "cgenff_parameters_path": cgenff_parameters,
    }


def test_quantitative_candidate_assembly_is_complete_but_not_released(
    tmp_path, monkeypatch
):
    inputs = _inputs(tmp_path, monkeypatch)
    output = tmp_path / "candidate-workbook.json"
    workbook = assembly.assemble_quantitative_parameter_workbook(
        **inputs, output_path=output
    )
    audit = audit_parameter_workbook(output)

    assert audit["passed"] is True
    assert workbook["release_status"] == "quantitative_smoke_candidate_not_released"
    assert workbook["quantitative_candidate_assembly"]["simulation_ready"] is False
    assert len(workbook["bonded_terms"]["impropers_added"]) == 4
    endpoint_2 = [
        item
        for item in workbook["bonded_terms"]["impropers_added"]
        if item["stereocenter"].startswith("2:")
    ]
    assert all(item["psi0_degrees"] == 30.0 for item in endpoint_2)
    assert all(
        item["ordered_atoms"] == item["ordered_atoms_candidate"] for item in endpoint_2
    )
    assert all(
        "identity_with_bonded_type_aliases" in item["source"] for item in endpoint_2
    )
    by_atom = {item["atom"]: item for item in workbook["atoms"]}
    assert by_atom["2:C5"]["final_type"] == "CPD5B"
    assert by_atom["2:C6"]["final_type"] == "CPD6B"
    boundary_term = next(
        item for item in workbook["bonded_terms"]["angles"] if "1:C1'" in item["atoms"]
    )
    assert "model_boundary_transfer" in boundary_term["source"]
    sugar_boundary_terms = [
        item
        for item in workbook["bonded_terms"]["dihedrals"]
        if any(atom.endswith((":O4'", ":C2'", ":H1'")) for atom in item["atoms"])
    ]
    assert len(sugar_boundary_terms) == 6
    assert all("model_boundary_transfer" in item["source"] for item in sugar_boundary_terms)


def test_quantitative_candidate_assembly_rejects_failed_heldout_metric(
    tmp_path, monkeypatch
):
    inputs = _inputs(tmp_path, monkeypatch)
    payload = json.loads(inputs["nonbonded_fit_path"].read_text())
    payload["results"][0]["water_metrics"][0]["energy_error_kcal_mol"] = 0.6
    inputs["nonbonded_fit_path"].write_text(json.dumps(payload))
    coverage_path = tmp_path / "coverage.json"
    coverage = json.loads(coverage_path.read_text())
    coverage["sources"]["nonbonded_fit"] = _source(inputs["nonbonded_fit_path"])
    coverage_path.write_text(json.dumps(coverage))
    fit_plan = json.loads(inputs["fit_plan_path"].read_text())
    fit_plan["sources"]["model_coverage"] = _source(coverage_path)
    inputs["fit_plan_path"].write_text(json.dumps(fit_plan))

    with pytest.raises(ValueError, match="held_out_water_energy"):
        assembly.assemble_quantitative_parameter_workbook(
            **inputs, output_path=tmp_path / "rejected.json"
        )


@pytest.mark.parametrize(
    ("product_id", "stereochemistry", "patch_name"),
    [
        ("tt-cpd-cis-syn", "cis-syn", "TCPDCS1"),
        ("tt-cpd-cis-syn-ii", "cis-syn-II", "TCPDCS2"),
        ("tt-cpd-trans-syn-i", "trans-syn-I", "TCPDTS1"),
        ("tt-cpd-trans-syn-ii", "trans-syn-II", "TCPDTS2"),
        ("tt-cpd-cis-anti-i", "cis-anti-I", "TCPDCA1"),
        ("tt-cpd-cis-anti-ii", "cis-anti-II", "TCPDCA2"),
        ("tt-cpd-trans-anti-i", "trans-anti-I", "TCPDTA1"),
        ("tt-cpd-trans-anti-ii", "trans-anti-II", "TCPDTA2"),
    ],
)
def test_family_policy_assembles_and_exports_each_ordered_product(
    tmp_path, monkeypatch, product_id, stereochemistry, patch_name
):
    inputs = _inputs(
        tmp_path,
        monkeypatch,
        product_id=product_id,
        stereochemistry=stereochemistry,
    )
    output = tmp_path / "candidate-workbook.json"
    policy = (
        assembly.CANDIDATE_ASSEMBLY_POLICY_PATH.parent
        / "photoproduct_candidate_assembly_policy_v2.json"
    )
    workbook = assembly.assemble_quantitative_parameter_workbook(
        **inputs,
        output_path=output,
        policy_path=policy,
    )

    audit = audit_parameter_workbook(output)
    assert audit["passed"] is True
    assert workbook["product_id"] == product_id
    assert workbook["stereochemistry"] == stereochemistry
    assert workbook["charmm_patch"]["patch_name"] == patch_name
    assert workbook["quantitative_candidate_assembly"]["resolved_scope"] == {
        "product_id": product_id,
        "nonbonded_hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
        "patch_name": patch_name,
    }
    expected_crosslinks = (
        {
            frozenset(("1:C5", "2:C6")),
            frozenset(("1:C6", "2:C5")),
        }
        if "anti" in stereochemistry
        else {
            frozenset(("1:C5", "2:C5")),
            frozenset(("1:C6", "2:C6")),
        }
    )
    assert {
        frozenset(bond["atoms"])
        for bond in workbook["bonded_terms"]["bonds"]
        if bond["atoms"][0].split(":", 1)[0]
        != bond["atoms"][1].split(":", 1)[0]
    } == expected_crosslinks
    exported = export_charmm_candidate_assets(
        workbook_path=output,
        workbook_audit_path=output.with_name("candidate-workbook_audit.json"),
        output_dir=tmp_path / "charmm",
    )
    assert exported["product_id"] == product_id
    assert exported["patch_name"] == patch_name
    audit_spec = json.loads(
        (tmp_path / "charmm/topology_audit_spec.json").read_text()
    )
    assert {frozenset(bond) for bond in audit_spec["crosslinks"]} == expected_crosslinks


def test_full_boundary_policy_maps_glycosidic_terms_without_methyl_substitution(
    tmp_path, monkeypatch
):
    inputs = _inputs(
        tmp_path,
        monkeypatch,
        product_id="tt-cpd-trans-anti-i",
        stereochemistry="trans-anti-I",
        full_boundary=True,
    )
    output = tmp_path / "candidate-workbook.json"
    policy = (
        assembly.CANDIDATE_ASSEMBLY_POLICY_PATH.parent
        / "photoproduct_candidate_assembly_policy_v3.json"
    )

    workbook = assembly.assemble_quantitative_parameter_workbook(
        **inputs,
        output_path=output,
        policy_path=policy,
    )

    assert audit_parameter_workbook(output)["passed"] is True
    transfer = workbook["quantitative_candidate_assembly"][
        "model_boundary_transfer"
    ]
    assert transfer["policy"] == "full-dtpdt-direct-boundary-v1"
    assert transfer["stable_atom_substitutions"] == {}
    sugar_terms = [
        item
        for item in workbook["bonded_terms"]["dihedrals"]
        if any(atom.endswith((":O4'", ":C2'", ":H1'")) for atom in item["atoms"])
    ]
    assert len(sugar_terms) == 6
    assert all(item["atoms"] == item["model_atoms"] for item in sugar_terms)
