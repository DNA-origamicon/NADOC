from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.base_keys import ParsedBaseKey, ResolvedBase
from backend.core.cpd_product import (
    ProductPlacementError,
    _ordered_product_ring_keys,
    _placement_relationship,
    _product_ring_bond_audit,
    _template_coordinates,
    place_product_template,
    select_product_template_assignment,
)
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.parameterization.photoproduct_templates import (
    build_candidate_coordinate_template,
)


def _template():
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    coordinates = {
        key: list(value)
        for key, value in definition["source_ring_coordinates_angstrom"].items()
    }
    coordinates.update(
        {
            "1:C1'": [1.549, 0.186, -1.824],
            "1:C2": [2.4, -0.5, -2.4],
            "1:O2": [3.3, -0.2, -2.1],
            "1:N3": [2.7, -1.3, -3.3],
            "1:O4": [2.9, -1.8, -5.2],
            "2:C1'": [-1.043, -0.280, -3.599],
            "2:C2": [-1.9, -2.0, -4.1],
            "2:O2": [-2.8, -1.8, -3.8],
            "2:N3": [-1.5, -3.0, -4.8],
            "2:O4": [-0.8, -4.7, -5.8],
        }
    )
    return {
        "schema": "nadoc.photoproduct-coordinate-template.v1",
        "version": "test-1",
        "product_id": "tt-cpd-cis-syn",
        "units": "angstrom",
        "reflection_allowed": False,
        "release_status": "released",
        "coordinates": coordinates,
        "placement_safety": {
            "schema": "nadoc.photoproduct-placement-safety.v1",
            "parameter_asset_sha256": "3" * 64,
            "product_ring_bond_ranges_angstrom": [
                {
                    "atom_1": bond["atom_1"],
                    "atom_2": bond["atom_2"],
                    "minimum_angstrom": 1.0,
                    "maximum_angstrom": 2.0,
                    "authority": "synthetic test parameter bounds",
                }
                for category in ("bonds_added", "bonds_retained")
                for bond in definition["graph_delta"][category]
            ],
        },
        "provenance": {
            "optimized_xyz_sha256": "0" * 64,
            "optimized_model_audit_sha256": "1" * 64,
            "frequency_audit_sha256": "2" * 64,
        },
    }


def _endpoint(
    number, key, strand_id, direction, source_class, coordinates, serial_start
):
    names = ["C1'", "N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"]
    serials = {name: serial_start + offset for offset, name in enumerate(names)}
    positions = {
        name: tuple(value * 0.1 for value in coordinates[f"{number}:{name}"])
        for name in names
    }
    endpoint = ResolvedBase(
        key=key,
        parsed=ParsedBaseKey(
            helix_id=f"h{number}", bp_index=number, direction=direction
        ),
        base="T",
        strand_id=strand_id,
        source_class=source_class,
        owner_id=f"h{number}",
        domain_index=0,
        residue_atom_names=tuple(names),
        atom_serials=serials,
        atom_positions_nm=positions,
    )
    atoms = []
    elements = {
        "C1'": "C",
        "N1": "N",
        "C2": "C",
        "O2": "O",
        "N3": "N",
        "C4": "C",
        "O4": "O",
        "C5": "C",
        "C6": "C",
        "C7": "C",
    }
    for name in names:
        x, y, z = positions[name]
        atoms.append(
            Atom(
                serial=serials[name],
                name=name,
                element=elements[name],
                residue="DT",
                chain_id="A" if strand_id == "same" else str(number),
                seq_num=number,
                x=x,
                y=y,
                z=z,
                strand_id=strand_id,
                helix_id=f"h{number}",
                bp_index=number,
                direction=direction,
            )
        )
    bond_names = [
        ("C1'", "N1"),
        ("N1", "C2"),
        ("C2", "O2"),
        ("C2", "N3"),
        ("N3", "C4"),
        ("C4", "O4"),
        ("C4", "C5"),
        ("C5", "C6"),
        ("C5", "C7"),
        ("C6", "N1"),
    ]
    bonds = [(serials[first], serials[second]) for first, second in bond_names]
    return endpoint, atoms, bonds


@pytest.mark.parametrize(
    ("strand_ids", "directions", "source_classes", "expected_relationship"),
    [
        (("same", "same"), ("FORWARD", "FORWARD"), ("ordinary", "ordinary"), "intrastrand"),
        (("left", "right"), ("FORWARD", "REVERSE"), ("crossover-extra", "crossover-extra"), "interstrand"),
    ],
)
def test_nonreflective_template_placement_handles_intra_and_antiparallel_interstrand(
    strand_ids, directions, source_classes, expected_relationship
):
    template = _template()
    first, first_atoms, first_bonds = _endpoint(
        1,
        "h1:1:FORWARD",
        strand_ids[0],
        directions[0],
        source_classes[0],
        template["coordinates"],
        0,
    )
    second, second_atoms, second_bonds = _endpoint(
        2,
        "h2:2:REVERSE",
        strand_ids[1],
        directions[1],
        source_classes[1],
        template["coordinates"],
        10,
    )
    model = AtomisticModel(
        atoms=[*first_atoms, *second_atoms], bonds=[*first_bonds, *second_bonds]
    )
    placed, report = place_product_template(
        atomistic_model=model,
        endpoints=[first, second],
        template=template,
        chemical_definition=load_chemical_definition("TT-CPD", "cis-syn"),
        expected_parameter_sha256="3" * 64,
    )
    assert report["passed"] is True
    assert report["relationship"]["strand_relationship"] == expected_relationship
    assert report["relationship"]["extra_pairing"] == (
        "extra-extra" if source_classes[0] == "crossover-extra" else "native-native"
    )
    assert report["fit"]["rotation_determinant"] == pytest.approx(1.0)
    assert report["chirality_audit"]["passed"] is True
    assert report["product_ring_bond_audit"]["passed"] is True
    assert len(report["product_ring_bond_audit"]["bonds"]) == 4
    assert report["piercing_audit"]["ring_atom_cycle"] == [
        "1:C5",
        "1:C6",
        "2:C6",
        "2:C5",
    ]
    assert report["atom_count_before"] == report["atom_count_after"]
    assert report["bond_graph_unchanged"] is True
    assert all(atom.is_modified for atom in placed.atoms if atom.name != "C1'")
    assert all(not atom.is_modified for atom in model.atoms)


def test_template_reflection_is_never_permitted():
    template = _template()
    template["reflection_allowed"] = True
    with pytest.raises(ProductPlacementError, match="forbid reflection"):
        _template_coordinates(template)


def test_unknown_empty_strand_ids_are_not_misreported_as_same_strand():
    template = _template()
    first, _atoms, _bonds = _endpoint(
        1, "h1:1:FORWARD", "", "FORWARD", "ordinary", template["coordinates"], 0
    )
    second, _atoms, _bonds = _endpoint(
        2, "h2:2:REVERSE", "", "REVERSE", "ordinary", template["coordinates"], 10
    )

    assert _placement_relationship([first, second])["strand_relationship"] == "interstrand"


def test_product_placement_rejects_missing_or_violated_reviewed_ring_bounds():
    template = _template()
    first, first_atoms, first_bonds = _endpoint(
        1, "h1:1:FORWARD", "same", "FORWARD", "ordinary", template["coordinates"], 0
    )
    second, second_atoms, second_bonds = _endpoint(
        2, "h1:2:FORWARD", "same", "FORWARD", "ordinary", template["coordinates"], 10
    )
    model = AtomisticModel(
        atoms=[*first_atoms, *second_atoms], bonds=[*first_bonds, *second_bonds]
    )
    definition = load_chemical_definition("TT-CPD", "cis-syn")

    missing = json.loads(json.dumps(template))
    missing.pop("placement_safety")
    with pytest.raises(ProductPlacementError, match="placement safety bounds"):
        place_product_template(
            atomistic_model=model,
            endpoints=[first, second],
            template=missing,
            chemical_definition=definition,
            expected_parameter_sha256="3" * 64,
        )

    strained = json.loads(json.dumps(template))
    strained["placement_safety"]["product_ring_bond_ranges_angstrom"][0][
        "maximum_angstrom"
    ] = 1.1
    with pytest.raises(ProductPlacementError) as rejected:
        place_product_template(
            atomistic_model=model,
            endpoints=[first, second],
            template=strained,
            chemical_definition=definition,
            expected_parameter_sha256="3" * 64,
        )
    assert rejected.value.report["product_ring_bond_audit"]["passed"] is False


def test_product_ring_cycle_follows_syn_and_anti_crosslinks():
    syn = load_chemical_definition("TT-CPD", "cis-syn")
    anti = json.loads(json.dumps(syn))
    anti["graph_delta"]["bonds_added"] = [
        {"atom_1": "1:C5", "atom_2": "2:C6", "order": "single"},
        {"atom_1": "1:C6", "atom_2": "2:C5", "order": "single"},
    ]

    assert _ordered_product_ring_keys(syn) == (
        "1:C5",
        "1:C6",
        "2:C6",
        "2:C5",
    )
    assert _ordered_product_ring_keys(anti) == (
        "1:C5",
        "1:C6",
        "2:C5",
        "2:C6",
    )
    template = _template()
    template["placement_safety"]["product_ring_bond_ranges_angstrom"] = [
        {
            "atom_1": bond["atom_1"],
            "atom_2": bond["atom_2"],
            "minimum_angstrom": 0.1,
            "maximum_angstrom": 10.0,
            "authority": "synthetic anti test parameter bounds",
        }
        for category in ("bonds_added", "bonds_retained")
        for bond in anti["graph_delta"][category]
    ]
    coordinates_nm = {
        key: np.asarray(value, dtype=float) * 0.1
        for key, value in template["coordinates"].items()
    }
    audit = _product_ring_bond_audit(
        template=template,
        chemical_definition=anti,
        coordinates=coordinates_nm,
        expected_parameter_sha256="3" * 64,
    )
    assert audit["passed"] is True
    assert {
        frozenset((record["atom_1"], record["atom_2"]))
        for record in audit["bonds"]
    } == {
        frozenset(("1:C5", "2:C6")),
        frozenset(("1:C6", "2:C5")),
        frozenset(("1:C5", "1:C6")),
        frozenset(("2:C5", "2:C6")),
    }


def test_product_ring_cycle_rejects_incomplete_connectivity():
    malformed = load_chemical_definition("TT-CPD", "cis-syn")
    malformed = json.loads(json.dumps(malformed))
    malformed["graph_delta"]["bonds_added"] = malformed["graph_delta"][
        "bonds_added"
    ][:1]
    with pytest.raises(ProductPlacementError, match="four-membered"):
        _ordered_product_ring_keys(malformed)


def test_directional_assignment_evaluates_both_orders_and_selects_without_reflection():
    template = _template()
    first, first_atoms, first_bonds = _endpoint(
        1, "z:endpoint", "same", "FORWARD", "ordinary", template["coordinates"], 0
    )
    second, second_atoms, second_bonds = _endpoint(
        2, "a:endpoint", "same", "FORWARD", "ordinary", template["coordinates"], 10
    )
    model = AtomisticModel(
        atoms=[*first_atoms, *second_atoms], bonds=[*first_bonds, *second_bonds]
    )

    ordered, _placed, report = select_product_template_assignment(
        atomistic_model=model,
        endpoints=[second, first],
        template=template,
        chemical_definition=load_chemical_definition("TT-CPD", "cis-syn"),
        expected_parameter_sha256="3" * 64,
    )

    assert [endpoint.key for endpoint in ordered] == ["z:endpoint", "a:endpoint"]
    selection = report["assignment_selection"]
    assert selection["reflection_allowed"] is False
    assert selection["selected_endpoint_keys"] == ["z:endpoint", "a:endpoint"]
    assert len(selection["candidates"]) == 2


def test_qm_audits_build_only_a_nonreleased_coordinate_candidate(tmp_path):
    template = _template()
    ordered_keys = [
        "1:CM",
        "1:N1",
        "1:C2",
        "1:O2",
        "1:N3",
        "1:C4",
        "1:O4",
        "1:C5",
        "1:C6",
        "1:C7",
        "1:H6",
        "2:CM",
        "2:N1",
        "2:C2",
        "2:O2",
        "2:N3",
        "2:C4",
        "2:O4",
        "2:C5",
        "2:C6",
        "2:C7",
        "2:H6",
    ]
    key_to_template = {
        key: key.replace(":CM", ":C1'") for key in ordered_keys
    }
    geometry_dir = tmp_path / "geometry"
    frequency_dir = tmp_path / "frequency"
    geometry_dir.mkdir()
    frequency_dir.mkdir()
    xyz_lines = [str(len(ordered_keys)), "audited synthetic model"]
    elements = {"N1": "N", "N3": "N", "O2": "O", "O4": "O", "H6": "H"}
    for key in ordered_keys:
        coordinate = template["coordinates"][key_to_template[key]]
        atom_name = key.split(":", 1)[1]
        element = elements.get(atom_name, "C")
        xyz_lines.append(f"{element} {coordinate[0]} {coordinate[1]} {coordinate[2]}")
    optimized_path = geometry_dir / "optimized.xyz"
    optimized_path.write_text("\n".join(xyz_lines) + "\n")
    optimized_hash = hashlib.sha256(optimized_path.read_bytes()).hexdigest()
    geometry_job = {
        "job_kind": "geometry_optimization",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "atom_map": ordered_keys,
        "protocol_version": "test",
    }
    (geometry_dir / "job_manifest.json").write_text(json.dumps(geometry_job))
    geometry_audit = {
        "schema": "nadoc.photoproduct-optimized-model-audit.v1",
        "status": "passed_identity_and_chirality",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "optimized_xyz": {"sha256": optimized_hash},
    }
    geometry_audit_path = geometry_dir / "optimized_model_audit.json"
    geometry_audit_path.write_text(json.dumps(geometry_audit))
    geometry_audit_hash = hashlib.sha256(geometry_audit_path.read_bytes()).hexdigest()
    frequency_job = {
        "job_kind": "frequency",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "protocol_version": "test",
        "source_xyz": {"sha256": optimized_hash},
        "parent_manifest": {"sha256": geometry_audit_hash},
    }
    (frequency_dir / "job_manifest.json").write_text(json.dumps(frequency_job))
    frequency_audit = {
        "schema": "nadoc.photoproduct-frequency-audit.v1",
        "status": "passed_harmonic_minimum",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "expected_mode_count": 60,
        "parsed_mode_count": 60,
        "imaginary_mode_count": 0,
        "lowest_frequency_cm_inverse": 25.0,
        "parent_optimized_model_audit": {"sha256": geometry_audit_hash},
    }
    (frequency_dir / "frequency_audit.json").write_text(json.dumps(frequency_audit))
    output = tmp_path / "candidate.json"
    candidate = build_candidate_coordinate_template(
        geometry_job_dir=geometry_dir,
        frequency_job_dir=frequency_dir,
        output_path=output,
        version="0.1.0-candidate",
    )
    assert candidate["release_status"] == "candidate_unreviewed"
    assert candidate["gate_effect"] == "none"
    assert "1:C1'" in candidate["coordinates"]
    with pytest.raises(ProductPlacementError, match="release review"):
        _template_coordinates(candidate)
