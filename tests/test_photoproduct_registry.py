import hashlib
import json

import pytest

from backend.core.photoproduct_registry import (
    PhotoproductRegistryError,
    attach_photoproduct_asset,
    photoproduct_capabilities,
    photoproduct_capability,
    photoproduct_help_trajectory,
    photoproduct_registry,
    record_photoproduct_gate_review,
    record_photoproduct_metric_gate,
    registered_stereochemistries,
    request_photoproduct,
)
from backend.core.photoproduct_toolchain import photoproduct_toolchain_status
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
    load_patch_charge_scope,
)


EXPECTED_TT_CPD_FORMS = (
    "cis-syn",
    "cis-syn-II",
    "trans-syn-I",
    "trans-syn-II",
    "cis-anti-I",
    "cis-anti-II",
    "trans-anti-I",
    "trans-anti-II",
)


def test_registry_contains_eight_ordered_dna_tt_cpd_stereoisomers():
    registry = photoproduct_registry()
    assert registered_stereochemistries("TT-CPD") == EXPECTED_TT_CPD_FORMS
    assert len({item["id"] for item in registry["products"]}) == 8
    assert registry["catalog_basis"]["hydrolyzed_aglycone_isomer_count"] == 6
    for item in registry["products"]:
        assert item["graph_delta"]["atoms_added"] == 0
        assert item["graph_delta"]["atoms_removed"] == 0
        assert item["graph_delta"]["formal_charge_change"] == 0
        expected = (
            ["1:C5--2:C5", "1:C6--2:C6"]
            if item["structural_class"]["double_bond_orientation"] == "syn"
            else ["1:C5--2:C6", "1:C6--2:C5"]
        )
        assert item["graph_delta"]["bonds_added"] == expected


def test_every_ordered_tt_cpd_has_the_same_atom_conserving_patch_charge_boundary():
    registry = photoproduct_registry()
    expected_patched = None
    for entry in registry["products"]:
        scope = load_patch_charge_scope("TT-CPD", entry["stereochemistry"])
        assert scope["product_id"] == entry["id"]
        assert scope["chemical_definition_sha256"] == entry["assets"][
            "chemical_definition"
        ]["sha256"]
        assert scope["expected_pair_charge"] == 0
        assert scope["unchanged_boundary_atoms"] == ["1:C1'", "2:C1'"]
        if expected_patched is None:
            expected_patched = scope["atoms_with_charges_replaced"]
        assert scope["atoms_with_charges_replaced"] == expected_patched
    assert len(expected_patched) == 28


def test_registry_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(
        '{"schema":"nadoc.photoproduct-registry.v1",'
        '"workflow_gates":[],"workflow_gates":[],"products":[]}'
    )
    with pytest.raises(PhotoproductRegistryError, match="duplicate JSON key"):
        photoproduct_registry(path)


def test_readiness_is_derived_and_every_form_starts_fail_closed():
    catalog = photoproduct_capabilities()
    assert catalog["all_simulation_ready"] is False
    assert len(catalog["products"]) == 8
    for item in catalog["products"]:
        assert item["simulation_ready"] is False
        assert item["next_gate"] is not None
        assert item["blockers"]
    cis_syn = photoproduct_capability("TT-CPD", "cis-syn")
    assert cis_syn["gate_status"]["chemical_definition"] == "passed"
    assert cis_syn["next_gate"] == "qm_reference_data"
    assert cis_syn["asset_audit"]["passed"] is True
    assert "patch_charge_scope" in cis_syn["asset_audit"]["declared"]
    assert "required asset not declared: qm_reference_report" in cis_syn["blockers"]
    assert "required asset not declared: parameters" in cis_syn["blockers"]
    assert "required asset not declared: license" in cis_syn["blockers"]


def test_readiness_requires_loadable_parameter_asset_separate_from_fit_report(tmp_path):
    registry = photoproduct_registry()
    entry = registry["products"][0]
    for gate in registry["workflow_gates"]:
        entry["gates"][gate] = {"status": "passed", "evidence": ["reviewed"]}
    parameters = tmp_path / "product.prm"
    parameters.write_text("* reviewed test parameter stream\n")
    parameter_hash = hashlib.sha256(parameters.read_bytes()).hexdigest()
    required_without_parameters = {
        "chemical_definition",
        "qm_reference_report",
        "parameter_fit_report",
        "topology",
        "coordinate_template",
        "topology_audit_spec",
        "namd_smoke_report",
        "validation_report",
        "release_review",
        "patch_charge_scope",
        "license",
    }
    for kind in required_without_parameters:
        asset = tmp_path / f"{kind}.dat"
        if kind == "coordinate_template":
            asset.write_text(
                json.dumps(
                    {
                        "schema": "nadoc.photoproduct-coordinate-template.v1",
                        "product_id": entry["id"],
                        "product": entry["product"],
                        "stereochemistry": entry["stereochemistry"],
                        "release_status": "released",
                        "reflection_allowed": False,
                        "placement_safety": {
                            "schema": "nadoc.photoproduct-placement-safety.v1",
                            "parameter_asset_sha256": parameter_hash,
                        },
                    }
                )
            )
        else:
            asset.write_text(f"{kind}\n")
        entry["assets"][kind] = {
            "path": asset.name,
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        }
        if kind == "topology":
            entry["assets"][kind]["patch_name"] = "TCPD"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))

    capability = photoproduct_capability("TT-CPD", "cis-syn", path=path)
    assert capability["simulation_ready"] is False
    assert "required asset not declared: parameters" in capability["blockers"]

    entry["assets"]["parameters"] = {
        "path": parameters.name,
        "sha256": parameter_hash,
    }
    path.write_text(json.dumps(registry))
    assert photoproduct_capability("TT-CPD", "cis-syn", path=path)[
        "simulation_ready"
    ] is True

    template_path = tmp_path / "coordinate_template.dat"
    template = json.loads(template_path.read_text())
    template["placement_safety"]["parameter_asset_sha256"] = "0" * 64
    template_path.write_text(json.dumps(template))
    entry["assets"]["coordinate_template"]["sha256"] = hashlib.sha256(
        template_path.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(registry))
    mismatched = photoproduct_capability("TT-CPD", "cis-syn", path=path)
    assert mismatched["simulation_ready"] is False
    assert "coordinate_template" in mismatched["asset_audit"]["invalid_metadata"]


def test_cis_syn_definition_encodes_and_audits_absolute_ring_stereochemistry():
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    assert [item["ccd_configuration"] for item in definition["product_stereocenters"]] == [
        "R", "R", "S", "S",
    ]
    coordinates = definition["source_ring_coordinates_angstrom"]
    report = audit_product_chirality(definition, coordinates)
    assert report["passed"] is True
    reflected = {name: [-xyz[0], xyz[1], xyz[2]] for name, xyz in coordinates.items()}
    reflected_report = audit_product_chirality(definition, reflected)
    assert reflected_report["passed"] is False
    assert not any(item["passed"] for item in reflected_report["centers"])
    charge_model = definition["model_compounds"]["charge_model"]
    assert charge_model["charge"] == 0
    assert len(charge_model["endpoint_caps"]) == 2
    assert definition["model_compounds"]["dna_boundary_model"]["status"] == (
        "definition-pending"
    )


def test_registry_rejects_missing_gate_instead_of_weakening_release(tmp_path):
    registry = photoproduct_registry()
    registry["products"][0]["gates"].pop("namd_smoke")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    with pytest.raises(PhotoproductRegistryError, match="gate set"):
        photoproduct_registry(path)


def test_toolchain_does_not_mistake_gnome_orca_for_quantum_orca():
    status = photoproduct_toolchain_status()
    orca = status["quantum"]["orca"]
    if orca["path"] == "/usr/bin/orca":
        assert orca["available"] is False
        assert "screen reader" in orca["reason"]
    assert status["simulation"]["namd"]
    assert status["simulation"]["psfgen"]
    distributed = status["quantum"]["distributed_hessian"]
    if distributed["available"]:
        assert distributed["qcengine"]["version"] == "0.51.0"
        assert distributed["qcelemental"]["version"] == "0.51.0"
        assert distributed["numpy"]["version"] == "2.5.2"
    fixed = status["quantum"]["distributed_fixed_geometry_response"]
    assert fixed["available"] is distributed["available"]
    assert fixed["requires_reviewed_coupled_conformer"] is True
    assert fixed["preserves_center_gradient"] is True
    assert fixed["preserves_center_electronic_energy"] is True
    assert fixed["performs_frequency_analysis"] is False
    review = status["definition_review_workflow"]
    assert review["minimum_backed_candidate"]["allows_reflection"] is False
    assert review["completed_review_ingestion"]["requires_all_human_decisions"] is True
    assert review["completed_review_ingestion"]["mutates_registry"] is False
    conformers = status["conformer_review_workflow"]
    assert conformers["mode_source"]["contains_parameter_targets"] is False
    assert conformers["mode_source"]["allows_reflection"] is False
    assert conformers["multi_product_review_index"]["authorizes_qm"] is False
    assert conformers["completed_review_audit"]["mutates_registry"] is False
    assert conformers["fixed_geometry_qm"][
        "requires_released_chemical_definition"
    ] is True
    archive = status["resources"]["archive_scratch"]
    if archive["available"]:
        assert archive["mounted"] is True


def test_future_photoproduct_request_starts_with_every_gate_pending(tmp_path):
    registry = photoproduct_registry()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    entry = request_photoproduct(
        product_id="tt-six-four",
        product="TT-6-4PP",
        stereochemistry="configured",
        label="TT (6-4) photoproduct",
        requested_contexts=["adjacent-intrastrand"],
        path=path,
    )
    assert set(entry["gates"]) == set(registry["workflow_gates"])
    assert {record["status"] for record in entry["gates"].values()} == {"pending"}
    assert photoproduct_capability("TT-6-4PP", "configured", path=path)[
        "simulation_ready"
    ] is False
    with pytest.raises(ValueError, match="already exists"):
        request_photoproduct(
            product_id="tt-six-four",
            product="TT-6-4PP",
            stereochemistry="configured",
            label="duplicate",
            path=path,
        )


def test_asset_attachment_and_gate_review_are_hashed_and_ordered(tmp_path):
    registry = photoproduct_registry()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    request_photoproduct(
        product_id="future-lesion",
        product="future",
        stereochemistry="defined",
        label="Future lesion",
        path=path,
    )
    evidence = tmp_path / "future-lesion-definition-review.json"
    evidence.write_text('{"review":"passed"}\n')
    asset = tmp_path / "future-lesion-definition.json"
    asset.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-chemical-definition.v1",
                "id": "future-lesion",
                "product": "future",
                "stereochemistry": "defined",
                "ordered_endpoints": [
                    {
                        "index": endpoint,
                        "ccd_atom_aliases": {"N1": "N1", "C5": "C5", "C6": "C6"},
                    }
                    for endpoint in (1, 2)
                ],
                "graph_delta": {
                    "atoms_added": [],
                    "atoms_removed": [],
                    "formal_charge_change": 0,
                    "bonds_added": [
                        {"atom_1": "1:C5", "atom_2": "2:C5", "order": "single"}
                    ],
                    "bonds_retained": [
                        {
                            "atom_1": "1:C5",
                            "atom_2": "1:C6",
                            "precursor_order": "double",
                            "product_order": "single",
                        }
                    ],
                },
                "source_ring_coordinates_angstrom": {
                    "1:C5": [0.0, 0.0, 0.0],
                    "1:C6": [1.0, 0.0, 0.0],
                    "2:C5": [0.0, 1.0, 0.0],
                    "2:C6": [0.0, 0.0, 1.0],
                },
                "product_stereocenters": [
                    {
                        "atom": "1:C5",
                        "signed_volume_reference_atoms": ["1:C6", "2:C5", "2:C6"],
                        "expected_signed_volume": "positive",
                    }
                ],
                "source_assets": [
                    {
                        "id": "reviewed-source",
                        "url": "https://example.invalid/reviewed-source",
                        "filename": "reviewed-source.dat",
                        "license": "test-only",
                        "sha256": "1" * 64,
                    }
                ],
            }
        )
        + "\n"
    )

    with pytest.raises(ValueError, match="predecessor gates"):
        record_photoproduct_gate_review(
            product_id="future-lesion",
            gate="qm_reference_data",
            status="passed",
            reviewer="test reviewer",
            rationale="test only",
            evidence_path=evidence,
            path=path,
        )
    attached = attach_photoproduct_asset(
        product_id="future-lesion",
        kind="chemical_definition",
        asset_path=asset,
        path=path,
    )
    assert attached["sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
    mismatched = photoproduct_registry(path)
    future = next(item for item in mismatched["products"] if item["id"] == "future-lesion")
    future["graph_delta"] = {
        "atoms_added": 0,
        "atoms_removed": 0,
        "formal_charge_change": 0,
        "bonds_added": ["1:C6--2:C6"],
        "bonds_retained": ["1:C5--1:C6"],
    }
    path.write_text(json.dumps(mismatched))
    with pytest.raises(ValueError, match="does not match the registry graph"):
        record_photoproduct_gate_review(
            product_id="future-lesion",
            gate="chemical_definition",
            status="passed",
            reviewer="test reviewer",
            rationale="must reject a graph identity mismatch",
            evidence_path=evidence,
            path=path,
        )
    future["graph_delta"] = {}
    path.write_text(json.dumps(mismatched))
    review = record_photoproduct_gate_review(
        product_id="future-lesion",
        gate="chemical_definition",
        status="passed",
        reviewer="test reviewer",
        rationale="identity reviewed",
        evidence_path=evidence,
        path=path,
    )
    assert review["status"] == "passed"
    assert review["evidence"][0]["sha256"] == hashlib.sha256(
        evidence.read_bytes()
    ).hexdigest()
    reviewed_entry = next(
        item for item in photoproduct_registry(path)["products"]
        if item["id"] == "future-lesion"
    )
    assert reviewed_entry["graph_delta"]["bonds_added"] == ["1:C5--2:C5"]

    qm_report = tmp_path / "qm-report.json"
    qm_report.write_text('{"schema":"test-only-qm-report"}\n')
    attach_photoproduct_asset(
        product_id="future-lesion",
        kind="qm_reference_report",
        asset_path=qm_report,
        path=path,
    )
    with pytest.raises(ValueError, match="cannot pass qm_reference_data by human review"):
        record_photoproduct_gate_review(
            product_id="future-lesion",
            gate="qm_reference_data",
            status="passed",
            reviewer="test reviewer",
            rationale="looks good is not quantitative evidence",
            evidence_path=evidence,
            path=path,
        )

    blocked = record_photoproduct_gate_review(
        product_id="future-lesion",
        gate="qm_reference_data",
        status="blocked",
        reviewer="test reviewer",
        rationale="a reviewer may still record a diagnosed blocker",
        evidence_path=evidence,
        path=path,
    )
    assert blocked["status"] == "blocked"


def test_gate_review_rejects_changed_or_malformed_chemical_definition(tmp_path):
    registry = photoproduct_registry()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    request_photoproduct(
        product_id="future-lesion",
        product="future",
        stereochemistry="defined",
        label="Future lesion",
        path=path,
    )
    asset = tmp_path / "definition.json"
    asset.write_text('{"schema":"candidate"}\n')
    attach_photoproduct_asset(
        product_id="future-lesion",
        kind="chemical_definition",
        asset_path=asset,
        path=path,
    )
    evidence = tmp_path / "review.json"
    evidence.write_text('{"review":"passed"}\n')
    with pytest.raises(ValueError, match="chemical-definition schema"):
        record_photoproduct_gate_review(
            product_id="future-lesion",
            gate="chemical_definition",
            status="passed",
            reviewer="test reviewer",
            rationale="must reject malformed chemistry",
            evidence_path=evidence,
            path=path,
        )

    asset.write_text('{"schema":"changed-after-attachment"}\n')
    with pytest.raises(ValueError, match="hash-mismatched"):
        record_photoproduct_gate_review(
            product_id="future-lesion",
            gate="chemical_definition",
            status="passed",
            reviewer="test reviewer",
            rationale="must reject changed bytes",
            evidence_path=evidence,
            path=path,
        )


def test_metric_gate_requires_complete_hash_linked_automated_evidence(tmp_path):
    registry = photoproduct_registry()
    entry = registry["products"][0]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))

    policy = tmp_path / "acceptance.json"
    policy.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-parameter-acceptance.v2",
                "decision_rule": "all preregistered checks pass",
            }
        )
        + "\n"
    )
    source = tmp_path / "qm_reference_report.json"
    source.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-qm-reference-release-audit.v1",
                "passed": True,
                "errors": [],
            }
        )
        + "\n"
    )
    asset = attach_photoproduct_asset(
        product_id=entry["id"],
        kind="qm_reference_report",
        asset_path=source,
        path=path,
    )
    required_checks = [
        "stable_atom_identity_bijective",
        "atom_count_and_charge_conserved",
        "product_graph_exact",
        "stereochemistry_retained",
        "optimized_minimum_has_no_imaginary_modes",
        "qm_provenance_and_hashes_complete",
    ]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    envelope = {
        "schema": "nadoc.photoproduct-metric-gate-evidence.v1",
        "product_id": entry["id"],
        "product": entry["product"],
        "stereochemistry": entry["stereochemistry"],
        "gate": "qm_reference_data",
        "decision": "passed",
        "errors": [],
        "generated_at": "2026-09-06T12:00:00Z",
        "producer": {
            "name": "test-release-auditor",
            "version": "1",
            "command": "test only",
        },
        "acceptance_policy": {
            "path": policy.name,
            "sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
        },
        "required_asset": {
            "kind": "qm_reference_report",
            "path": asset["path"],
            "sha256": asset["sha256"],
        },
        "source_files": [
            {
                "id": "qm-release-audit",
                "path": source.name,
                "sha256": source_hash,
                "schema": "nadoc.photoproduct-qm-reference-release-audit.v1",
            }
        ],
        "checks": [
            {
                "id": check_id,
                "passed": True,
                "automated": True,
                "source_sha256": source_hash,
            }
            for check_id in required_checks
        ],
    }
    evidence = tmp_path / "qm_metric_gate.json"
    incomplete = {**envelope, "checks": envelope["checks"][:-1]}
    evidence.write_text(json.dumps(incomplete) + "\n")
    with pytest.raises(ValueError, match="missing required checks"):
        record_photoproduct_metric_gate(
            product_id=entry["id"],
            gate="qm_reference_data",
            evidence_path=evidence,
            acceptance_policy_path=policy,
            path=path,
        )

    evidence.write_text(json.dumps(envelope) + "\n")
    result = record_photoproduct_metric_gate(
        product_id=entry["id"],
        gate="qm_reference_data",
        evidence_path=evidence,
        acceptance_policy_path=policy,
        path=path,
    )
    assert result["status"] == "passed"
    assert result["evidence"][0]["decision_kind"] == "automated-metrics"
    assert result["evidence"][0]["source_sha256"] == [source_hash]

    source.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-qm-reference-release-audit.v1",
                "passed": False,
                "errors": ["imaginary mode"],
            }
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="asset is unusable"):
        record_photoproduct_metric_gate(
            product_id=entry["id"],
            gate="qm_reference_data",
            evidence_path=evidence,
            acceptance_policy_path=policy,
            path=path,
        )

def test_topology_attachment_requires_and_preserves_patch_name(tmp_path):
    registry = photoproduct_registry()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    topology = tmp_path / "candidate.rtf"
    topology.write_text("* test-only topology\n")
    with pytest.raises(ValueError, match="requires its .* CHARMM patch name"):
        attach_photoproduct_asset(
            product_id="tt-cpd-cis-syn",
            kind="topology",
            asset_path=topology,
            path=path,
        )
    record = attach_photoproduct_asset(
        product_id="tt-cpd-cis-syn",
        kind="topology",
        asset_path=topology,
        patch_name="TCPDCS1",
        path=path,
    )
    assert record["patch_name"] == "TCPDCS1"
    assert photoproduct_capability("TT-CPD", "cis-syn", path=path)["asset_audit"][
        "invalid_metadata"
    ] == []


def test_help_trajectory_requires_namd_gate_and_verified_asset(tmp_path):
    registry = photoproduct_registry()
    entry = registry["products"][0]
    payload = {
        "schema": "nadoc.photoproduct-help-trajectory.v1",
        "product_id": entry["id"],
        "units": "angstrom",
        "atom_keys": ["1:C5", "2:C5"],
        "elements": ["C", "C"],
        "bonds": [[0, 1]],
        "frames": [
            [[0.0, 0.0, 0.0], [1.55, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [1.56, 0.0, 0.0]],
        ],
        "source_frame_indices": [0, 10],
        "timestep_fs": 2,
        "stride_steps": 10,
        "provenance": {
            "engine": "NAMD 3",
            "source_dcd_sha256": "1" * 64,
            "topology_sha256": "2" * 64,
            "parameters_sha256": "3" * 64,
            "static_topology_audit_sha256": "4" * 64,
            "namd_smoke_report_sha256": "5" * 64,
        },
    }
    trajectory = tmp_path / "help.json"
    trajectory.write_text(json.dumps(payload))
    entry["assets"]["help_trajectory"] = {
        "path": "help.json",
        "sha256": hashlib.sha256(trajectory.read_bytes()).hexdigest(),
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    assert photoproduct_capability("TT-CPD", "cis-syn", path=path)[
        "help_trajectory"
    ]["available"] is False
    with pytest.raises(PhotoproductRegistryError, match="NAMD smoke"):
        photoproduct_help_trajectory(entry["id"], path=path)

    entry["gates"]["namd_smoke"] = {
        "status": "passed",
        "evidence": ["test-only-real-engine-report"],
    }
    path.write_text(json.dumps(registry))
    with pytest.raises(PhotoproductRegistryError, match="release validation"):
        photoproduct_help_trajectory(entry["id"], path=path)

    for gate in registry["workflow_gates"]:
        entry["gates"][gate] = {"status": "passed", "evidence": ["reviewed"]}
    parameters = tmp_path / "parameters.prm"
    parameters.write_text("* reviewed test parameters\n")
    parameters_hash = hashlib.sha256(parameters.read_bytes()).hexdigest()
    smoke = tmp_path / "namd_smoke_report.json"
    smoke.write_text('{"schema":"test-smoke-evidence"}\n')
    smoke_hash = hashlib.sha256(smoke.read_bytes()).hexdigest()
    payload["provenance"]["parameters_sha256"] = parameters_hash
    payload["provenance"]["namd_smoke_report_sha256"] = smoke_hash
    trajectory.write_text(json.dumps(payload))
    required_assets = {
        "chemical_definition",
        "qm_reference_report",
        "parameter_fit_report",
        "topology",
        "topology_audit_spec",
        "validation_report",
        "release_review",
        "patch_charge_scope",
        "license",
    }
    for kind in required_assets:
        asset = tmp_path / f"{kind}.dat"
        asset.write_text(f"{kind}\n")
        entry["assets"][kind] = {
            "path": asset.name,
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        }
        if kind == "topology":
            entry["assets"][kind]["patch_name"] = "TCPD"
    template = tmp_path / "coordinate_template.json"
    template.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-coordinate-template.v1",
                "product_id": entry["id"],
                "product": entry["product"],
                "stereochemistry": entry["stereochemistry"],
                "release_status": "released",
                "reflection_allowed": False,
                "placement_safety": {
                    "schema": "nadoc.photoproduct-placement-safety.v1",
                    "parameter_asset_sha256": parameters_hash,
                },
            }
        )
    )
    entry["assets"]["coordinate_template"] = {
        "path": template.name,
        "sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
    }
    entry["assets"]["parameters"] = {
        "path": parameters.name,
        "sha256": parameters_hash,
    }
    entry["assets"]["namd_smoke_report"] = {
        "path": smoke.name,
        "sha256": smoke_hash,
    }
    entry["assets"]["help_trajectory"]["sha256"] = hashlib.sha256(
        trajectory.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(registry))
    assert photoproduct_help_trajectory(entry["id"], path=path) == payload

    malformed = json.loads(trajectory.read_text())
    malformed["frames"][1][0][0] = float("nan")
    trajectory.write_text(json.dumps(malformed))
    entry["assets"]["help_trajectory"]["sha256"] = hashlib.sha256(
        trajectory.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(registry))
    with pytest.raises(PhotoproductRegistryError, match="malformed help trajectory"):
        photoproduct_help_trajectory(entry["id"], path=path)

    trajectory.write_text(json.dumps(payload))
    payload["provenance"]["parameters_sha256"] = "0" * 64
    trajectory.write_text(json.dumps(payload))
    entry["assets"]["help_trajectory"]["sha256"] = hashlib.sha256(
        trajectory.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(registry))
    capability = photoproduct_capability("TT-CPD", "cis-syn", path=path)
    assert capability["help_trajectory"]["available"] is False
    assert "help_trajectory" in capability["asset_audit"]["invalid_metadata"]
