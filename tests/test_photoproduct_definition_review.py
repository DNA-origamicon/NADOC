"""Human review-packet assembly for the seven noncanonical TT-CPDs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_definition_review import (
    audit_tt_cpd_definition_review,
    build_minimum_backed_definition_candidate,
    build_tt_cpd_definition_review_packet,
    materialize_visual_definition_review,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path, *, embedded: Path | None = None) -> dict[str, str]:
    return {"path": str(embedded or path), "sha256": _sha256(path)}


def _fixtures(tmp_path: Path) -> tuple[list[Path], Path, Path]:
    stereo_root = tmp_path / "stereo"
    definition_root = tmp_path / "definitions"
    stereo_root.mkdir()
    definition_root.mkdir()
    entries = [
        item
        for item in photoproduct_registry()["products"]
        if item["product"] == "TT-CPD" and item["stereochemistry"] != "cis-syn"
    ]
    manifests: dict[str, Path] = {}
    series_records = []
    independent_records = []
    for index, entry in enumerate(entries):
        product_id = entry["id"]
        item_root = stereo_root / product_id
        item_root.mkdir()
        outputs = {}
        for name, suffix in (
            ("xyz", "xyz"),
            ("atom_map", "json"),
            ("sdf", "sdf"),
            ("graph", "json"),
        ):
            path = item_root / f"{name}.{suffix}"
            path.write_text(f"{product_id} {name}\n")
            outputs[name] = _record(
                path, embedded=Path("/missing/stereo") / product_id / path.name
            )
        manifest = item_root / "candidate_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "nadoc.tt-cpd-stereo-candidate.v1",
                    "status": "candidate_not_reviewed",
                    "gate_effect": "none",
                    "product_id": product_id,
                    "outputs": outputs,
                }
            )
            + "\n"
        )
        manifests[product_id] = manifest
        series_records.append(
            {
                "product_id": product_id,
                "passed": True,
                "manifest_sha256": _sha256(manifest),
            }
        )
        independent_records.append(
            {
                "product_id": product_id,
                "sdf_sha256": outputs["sdf"]["sha256"],
                "canonical_isomeric_smiles": f"stereo-{index}",
                "inchikey": f"INCHIKEY-{index}",
                "constitutional_inchikey_block": (
                    "SYNBLOCK" if "syn" in entry["stereochemistry"] else "ANTIBLOCK"
                ),
            }
        )
    candidate_audit = stereo_root / "candidate_audit.json"
    candidate_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.tt-cpd-stereo-candidate-audit.v1",
                "status": "passed_candidate",
                "passed": True,
                "gate_effect": "none",
                "candidates": series_records,
            }
        )
        + "\n"
    )
    independent = stereo_root / "openbabel_audit.json"
    independent.write_text(
        json.dumps(
            {
                "schema": "nadoc.tt-cpd-openbabel-stereo-audit.v1",
                "status": "software_crosscheck_passed_human_review_required",
                "passed": True,
                "gate_effect": "none",
                "candidate_audit": {"sha256": _sha256(candidate_audit)},
                "records": independent_records,
            }
        )
        + "\n"
    )
    definitions = []
    for entry in entries:
        product_id = entry["id"]
        c5_first, c5_second = entry["structural_class"][
            "ordered_c5_configurations"
        ]
        centers = []
        coordinates = {}
        for endpoint, c5_configuration, offset in (
            (1, c5_first, 0.0),
            (2, c5_second, 10.0),
        ):
            prefix = f"{endpoint}:"
            c5_sign = "positive" if c5_configuration == "R" else "negative"
            c6_configuration = "R" if endpoint == 1 else "S"
            c6_sign = "negative" if endpoint == 1 else "positive"
            coordinates.update(
                {
                    f"{prefix}C5": [offset, 0.0, 0.0],
                    f"{prefix}C4": [offset + 1.0, 0.0, 0.0],
                    f"{prefix}C6": [offset, 1.0, 0.0],
                    f"{prefix}C7": [
                        offset,
                        0.0,
                        1.0 if c5_sign == "positive" else -1.0,
                    ],
                    f"{prefix}N1": [offset + 1.0, 1.0, 0.0],
                    f"{prefix}H6": [
                        offset,
                        1.0,
                        1.0 if c6_sign == "negative" else -1.0,
                    ],
                }
            )
            centers.extend(
                [
                    {
                        "atom": f"{prefix}C5",
                        "ccd_configuration": c5_configuration,
                        "signed_volume_reference_atoms": [
                            f"{prefix}C4",
                            f"{prefix}C6",
                            f"{prefix}C7",
                        ],
                        "expected_signed_volume": c5_sign,
                    },
                    {
                        "atom": f"{prefix}C6",
                        "ccd_configuration": c6_configuration,
                        "signed_volume_reference_atoms": [
                            f"{prefix}N1",
                            f"{prefix}C5",
                            f"{prefix}H6",
                        ],
                        "expected_signed_volume": c6_sign,
                    },
                ]
            )
        definition = definition_root / f"{product_id}.json"
        definition.write_text(
            json.dumps(
                {
                    "schema": "nadoc.photoproduct-chemical-definition-candidate.v1",
                    "status": "review_required",
                    "gate_effect": "none",
                    "id": product_id,
                    "product": "TT-CPD",
                    "stereochemistry": entry["stereochemistry"],
                    "state": "electronic-ground-state-product",
                    "ordered_endpoints": [
                        {
                            "index": endpoint,
                            "precursor": "DNA thymine",
                            "ccd_atom_aliases": {
                                "N1": "N1",
                                "C5": "C5",
                                "C6": "C6",
                            },
                        }
                        for endpoint in (1, 2)
                    ],
                    "product_stereocenters": centers,
                    "graph_delta": {
                        "atoms_added": [],
                        "atoms_removed": [],
                        "formal_charge_change": 0,
                        "bonds_added": [
                            {
                                "atom_1": value.split("--")[0],
                                "atom_2": value.split("--")[1],
                                "order": "single",
                            }
                            for value in entry["graph_delta"]["bonds_added"]
                        ],
                        "bonds_retained": [
                            {
                                "atom_1": value.split("--")[0],
                                "atom_2": value.split("--")[1],
                                "precursor_order": "double",
                                "product_order": "single",
                            }
                            for value in entry["graph_delta"]["bonds_retained"]
                        ],
                        "backbone_and_glycosidic_connectivity": "preserved",
                    },
                    "precursor_local_connectivity": {
                        "scope": "test fixture",
                        "bonds": [["1:C5", "1:C6"], ["2:C5", "2:C6"]],
                    },
                    "source_ring_coordinates_angstrom": coordinates,
                    "model_compounds": {"charge_model": {"charge": 0}},
                    "candidate_evidence": {
                        "manifest": _record(
                            manifests[product_id],
                            embedded=Path("/missing") / product_id / "candidate_manifest.json",
                        ),
                        "series_audit": _record(
                            candidate_audit,
                            embedded=Path("/missing/candidate_audit.json"),
                        ),
                        "independent_stereo_audit": _record(
                            independent,
                            embedded=Path("/missing/openbabel_audit.json"),
                        ),
                    },
                }
            )
            + "\n"
        )
        definitions.append(definition)
    return definitions, candidate_audit, independent


def _complete_review_with_approvals(
    packet_path: Path, definition_candidates: list[Path], root: Path
) -> dict[str, Path]:
    packet = json.loads(packet_path.read_text())
    packet["status"] = "human_review_complete"
    releases: dict[str, Path] = {}
    candidates = {
        json.loads(path.read_text())["id"]: json.loads(path.read_text())
        for path in definition_candidates
    }
    for item in packet["candidates"]:
        product_id = item["product_id"]
        release = candidates[product_id].copy()
        release["schema"] = "nadoc.photoproduct-chemical-definition.v1"
        for field in (
            "status",
            "gate_effect",
            "candidate_evidence",
            "release_blockers",
            "requested_contexts",
            "patch_charge_scope",
        ):
            release.pop(field, None)
        release["source_assets"] = [
            {
                "id": f"TEST-{product_id}",
                "url": "https://example.invalid/reviewed-source",
                "filename": f"{product_id}.sdf",
                "sha256": "0" * 64,
                "license": "test fixture",
            }
        ]
        release_path = root / f"reviewed-{product_id}.json"
        release_path.write_text(json.dumps(release, indent=2) + "\n")
        releases[product_id] = release_path
        item["human_decision"] = {
            "decision": "APPROVE",
            "reviewer": "Independent Reviewer",
            "reviewed_at": "2026-09-05T12:00:00-06:00",
            "atom_mapped_rationale": (
                "Checked ordered endpoints, both crosslinks, and all four signed centers."
            ),
            "evidence_or_corrected_definition_sha256": _sha256(release_path),
        }
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    return releases


def _direct_minimum_evidence(
    definition_path: Path, root: Path
) -> tuple[Path, Path, Path, Path]:
    definition = json.loads(definition_path.read_text())
    product_id = definition["id"]
    model_id = f"n1-methyl-{product_id}"
    coordinates = definition["source_ring_coordinates_angstrom"]
    atom_map = list(coordinates)
    xyz = root / f"{product_id}-optimized.xyz"
    rows = [str(len(atom_map)), "synthetic passed minimum"]
    for key in atom_map:
        atom_name = key.rsplit(":", 1)[-1]
        element = atom_name[0]
        x, y, z = coordinates[key]
        rows.append(f"{element} {x:.12f} {y:.12f} {z:.12f}")
    xyz.write_text("\n".join(rows) + "\n")

    optimized_audit = root / f"{product_id}-optimized-audit.json"
    optimized_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_candidate_identity_and_chirality",
                "gate_effect": "none",
                "product_id": product_id,
                "model_id": model_id,
                "optimized_xyz": {"path": str(xyz), "sha256": _sha256(xyz)},
                "chirality_audit": {"passed": True},
                "final_energy_hartree": -100.0,
            }
        )
        + "\n"
    )
    frequency_job = root / f"{product_id}-frequency-job.json"
    frequency_job.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-qm-job.v1",
                "job_kind": "frequency",
                "product_id": product_id,
                "model_id": model_id,
                "source_xyz": {"sha256": _sha256(xyz)},
                "parent_manifest": {"sha256": _sha256(optimized_audit)},
                "atom_map": atom_map,
            }
        )
        + "\n"
    )
    output = root / f"{product_id}-frequency-output.dat"
    hessian = root / f"{product_id}-hessian.txt"
    output.write_text("passed synthetic frequency output\n")
    hessian.write_text("1.0\n")
    frequency_audit = root / f"{product_id}-frequency-audit.json"
    frequency_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-audit.v1",
                "status": "passed_candidate_harmonic_minimum",
                "gate_effect": "none",
                "product_id": product_id,
                "model_id": model_id,
                "imaginary_mode_count": 0,
                "lowest_frequency_cm_inverse": 40.0,
                "parent_optimized_model_audit": {
                    "sha256": _sha256(optimized_audit)
                },
                "output": _record(output),
                "cartesian_hessian": {
                    **_record(hessian),
                    "status": "passed",
                    "units": "hartree/bohr^2",
                },
            }
        )
        + "\n"
    )
    return frequency_audit, xyz, optimized_audit, frequency_job


def test_review_packet_collates_all_candidates_and_rebases_archive_copies(
    tmp_path: Path,
) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    output = tmp_path / "packet"

    packet = build_tt_cpd_definition_review_packet(
        definition_candidate_paths=definitions,
        candidate_audit_path=candidate_audit,
        independent_audit_path=independent,
        frequency_audit_paths=[],
        output_dir=output,
    )

    assert packet["status"] == "human_review_required"
    assert packet["simulation_ready"] is False
    assert packet["gate_effect"] == "none"
    assert packet["candidate_count"] == 7
    assert packet["all_required_candidates_present"] is True
    assert all(item["human_decision"]["decision"] is None for item in packet["candidates"])
    assert all(
        str(tmp_path / "stereo") in item["candidate_manifest"]["path"]
        for item in packet["candidates"]
    )
    persisted = json.loads((output / "definition_review_packet.json").read_text())
    assert persisted == packet
    markdown = (output / "definition_review_packet.md").read_text()
    assert "Decision: `APPROVE` / `REJECT` / `REVISE`" in markdown
    assert markdown.count("### tt-cpd-") == 7


def test_minimum_backed_candidate_replaces_coordinates_but_stays_review_only(
    tmp_path: Path,
) -> None:
    definitions, _candidate_audit, _independent = _fixtures(tmp_path)
    source = definitions[0]
    frequency, xyz, optimized_audit, frequency_job = _direct_minimum_evidence(
        source, tmp_path
    )

    result = build_minimum_backed_definition_candidate(
        definition_candidate_path=source,
        minimum_evidence_path=frequency,
        optimized_xyz_path=xyz,
        optimized_model_audit_path=optimized_audit,
        frequency_job_manifest_path=frequency_job,
        output_path=tmp_path / "minimum-backed.json",
    )

    assert result["status"] == "review_required"
    assert result["gate_effect"] == "none"
    assert result["minimum_geometry_evidence"]["kind"] == (
        "direct_candidate_harmonic_minimum"
    )
    assert result["minimum_geometry_evidence"]["chirality_audit"]["passed"] is True
    assert not any(
        "replace candidate coordinates" in blocker
        for blocker in result["release_blockers"]
    )
    assert "chemical-definition review still pending" in result["model_compounds"][
        "charge_model"
    ]["source_asset"]

    xyz.write_text(xyz.read_text().replace("1.000000000000", "1.100000000000", 1))
    with pytest.raises(ValueError, match="identity/hash chain"):
        build_minimum_backed_definition_candidate(
            definition_candidate_path=source,
            minimum_evidence_path=frequency,
            optimized_xyz_path=xyz,
            optimized_model_audit_path=optimized_audit,
            frequency_job_manifest_path=frequency_job,
            output_path=tmp_path / "tampered.json",
        )


def test_minimum_backed_candidate_accepts_only_audited_endpoint_exchange(
    tmp_path: Path,
) -> None:
    definitions, _candidate_audit, _independent = _fixtures(tmp_path)
    source_path = next(
        path
        for path in definitions
        if json.loads(path.read_text())["id"] == "tt-cpd-cis-syn-ii"
    )
    source = json.loads(source_path.read_text())
    coordinates = source["source_ring_coordinates_angstrom"]
    atom_map = list(coordinates)
    xyz = tmp_path / "equivalent-source.xyz"
    rows = [str(len(atom_map)), "endpoint-exchange source"]
    for key in atom_map:
        x, y, z = coordinates[key]
        rows.append(f"{key.rsplit(':', 1)[-1][0]} {x} {y} {z}")
    xyz.write_text("\n".join(rows) + "\n")
    hessian = tmp_path / "source-hessian.txt"
    hessian.write_text("1.0\n")
    frequency = tmp_path / "source-frequency.json"
    frequency.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-audit.v1",
                "status": "passed_harmonic_minimum",
                "product_id": "tt-cpd-cis-syn",
                "imaginary_mode_count": 0,
                "cartesian_hessian": {"sha256": _sha256(hessian)},
            }
        )
        + "\n"
    )
    equivalence = tmp_path / "endpoint-equivalence.json"
    equivalence.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-equivalence-audit.v1",
                "status": "passed_candidate_model_equivalence",
                "passed": True,
                "product_ids": ["tt-cpd-cis-syn", "tt-cpd-cis-syn-ii"],
            }
        )
        + "\n"
    )
    reference = tmp_path / "equivalent-reference.json"
    reference.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-equivalent-hessian-reference.v1",
                "status": "passed_candidate_reuse_preconditions",
                "passed": True,
                "gate_effect": "none",
                "source_product_id": "tt-cpd-cis-syn",
                "target_product_id": "tt-cpd-cis-syn-ii",
                "coordinate_frame": "source-retained-no-tensor-rotation",
                "source_atom_map": atom_map,
                "target_atom_map_in_source_matrix_order": atom_map,
                "source_frequency": {
                    "frequency_audit": _record(frequency),
                    "cartesian_hessian": _record(hessian),
                    "source_geometry": _record(xyz),
                },
                "equivalence_audit": _record(equivalence),
            }
        )
        + "\n"
    )

    result = build_minimum_backed_definition_candidate(
        definition_candidate_path=source_path,
        minimum_evidence_path=reference,
        output_path=tmp_path / "equivalent-minimum-backed.json",
    )

    assert result["minimum_geometry_evidence"]["kind"] == (
        "audited_endpoint_exchange_equivalent_minimum"
    )
    assert result["minimum_geometry_evidence"]["independent_target_frequency_run"] is False
    assert result["minimum_geometry_evidence"]["chirality_audit"]["passed"] is True
    assert any(
        "accept endpoint-exchange equivalence" in blocker
        for blocker in result["release_blockers"]
    )


def test_review_packet_rejects_incomplete_series_and_overwrite(tmp_path: Path) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="exactly the seven"):
        build_tt_cpd_definition_review_packet(
            definition_candidate_paths=definitions[:-1],
            candidate_audit_path=candidate_audit,
            independent_audit_path=independent,
            frequency_audit_paths=[],
            output_dir=tmp_path / "incomplete",
        )
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="overwrite"):
        build_tt_cpd_definition_review_packet(
            definition_candidate_paths=definitions,
            candidate_audit_path=candidate_audit,
            independent_audit_path=independent,
            frequency_audit_paths=[],
            output_dir=existing,
        )


def test_completed_review_ingestion_revalidates_and_remains_gate_neutral(
    tmp_path: Path,
) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    packet_dir = tmp_path / "packet"
    build_tt_cpd_definition_review_packet(
        definition_candidate_paths=definitions,
        candidate_audit_path=candidate_audit,
        independent_audit_path=independent,
        frequency_audit_paths=[],
        output_dir=packet_dir,
    )
    packet_path = packet_dir / "definition_review_packet.json"
    releases = _complete_review_with_approvals(packet_path, definitions, tmp_path)

    audit = audit_tt_cpd_definition_review(
        packet_path=packet_path,
        reviewed_definition_paths=releases,
        decision_evidence_paths={},
        output_path=tmp_path / "review-ingestion-audit.json",
    )

    assert audit["status"] == "passed_review_ingestion"
    assert audit["passed"] is True
    assert audit["simulation_ready"] is False
    assert audit["gate_effect"] == "none"
    assert len(audit["approved_product_ids"]) == 7
    assert audit["unresolved_product_ids"] == []
    assert all(
        record["reviewed_definition"]["chirality_audit"]["passed"]
        for record in audit["records"]
    )


def test_review_ingestion_fails_closed_for_blank_or_semantically_changed_approval(
    tmp_path: Path,
) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    packet_dir = tmp_path / "packet"
    build_tt_cpd_definition_review_packet(
        definition_candidate_paths=definitions,
        candidate_audit_path=candidate_audit,
        independent_audit_path=independent,
        frequency_audit_paths=[],
        output_dir=packet_dir,
    )
    packet_path = packet_dir / "definition_review_packet.json"
    with pytest.raises(ValueError, match="completed, gate-neutral"):
        audit_tt_cpd_definition_review(
            packet_path=packet_path,
            reviewed_definition_paths={},
            decision_evidence_paths={},
            output_path=tmp_path / "blank-audit.json",
        )

    releases = _complete_review_with_approvals(packet_path, definitions, tmp_path)
    product_id = next(iter(releases))
    changed = json.loads(releases[product_id].read_text())
    changed["ordered_endpoints"] = list(reversed(changed["ordered_endpoints"]))
    releases[product_id].write_text(json.dumps(changed, indent=2) + "\n")
    packet = json.loads(packet_path.read_text())
    item = next(item for item in packet["candidates"] if item["product_id"] == product_id)
    item["human_decision"]["evidence_or_corrected_definition_sha256"] = _sha256(
        releases[product_id]
    )
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")

    with pytest.raises(ValueError, match="ordered endpoints 1 and 2"):
        audit_tt_cpd_definition_review(
            packet_path=packet_path,
            reviewed_definition_paths=releases,
            decision_evidence_paths={},
            output_path=tmp_path / "changed-audit.json",
        )


def test_review_ingestion_records_revise_as_unresolved_with_signed_evidence(
    tmp_path: Path,
) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    packet_dir = tmp_path / "packet"
    build_tt_cpd_definition_review_packet(
        definition_candidate_paths=definitions,
        candidate_audit_path=candidate_audit,
        independent_audit_path=independent,
        frequency_audit_paths=[],
        output_dir=packet_dir,
    )
    packet_path = packet_dir / "definition_review_packet.json"
    releases = _complete_review_with_approvals(packet_path, definitions, tmp_path)
    product_id = next(iter(releases))
    releases.pop(product_id)
    evidence_path = tmp_path / f"{product_id}-revision.md"
    evidence_path.write_text("Endpoint atom mapping needs a corrected stereochemical assignment.\n")
    packet = json.loads(packet_path.read_text())
    item = next(item for item in packet["candidates"] if item["product_id"] == product_id)
    item["human_decision"] = {
        "decision": "REVISE",
        "reviewer": "Independent Reviewer",
        "reviewed_at": "2026-09-05T12:00:00Z",
        "atom_mapped_rationale": (
            "The ordered endpoint atom mapping requires correction and a regenerated packet."
        ),
        "evidence_or_corrected_definition_sha256": _sha256(evidence_path),
    }
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")

    audit = audit_tt_cpd_definition_review(
        packet_path=packet_path,
        reviewed_definition_paths=releases,
        decision_evidence_paths={product_id: evidence_path},
        output_path=tmp_path / "mixed-review-audit.json",
    )

    assert audit["approved_product_ids"] == [
        item["product_id"]
        for item in packet["candidates"]
        if item["product_id"] != product_id
    ]
    assert audit["unresolved_product_ids"] == [product_id]
    revised = next(item for item in audit["records"] if item["product_id"] == product_id)
    assert revised["decision"] == "REVISE"
    assert revised["decision_evidence"]["sha256"] == _sha256(evidence_path)


def test_visual_review_materializer_pins_exact_definition_geometry_and_stays_neutral(
    tmp_path: Path,
) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    packet_dir = tmp_path / "packet"
    build_tt_cpd_definition_review_packet(
        definition_candidate_paths=definitions,
        candidate_audit_path=candidate_audit,
        independent_audit_path=independent,
        frequency_audit_paths=[],
        output_dir=packet_dir,
    )
    packet_path = packet_dir / "definition_review_packet.json"
    packet = json.loads(packet_path.read_text())
    decisions = []
    revised_id = packet["candidates"][0]["product_id"]
    for item in packet["candidates"]:
        decision = "revise" if item["product_id"] == revised_id else "approve"
        decisions.append(
            {
                "stage": "chemical_definition",
                "product_id": item["product_id"],
                "conformer_id": None,
                "decision": decision,
                "partition": None,
                "reviewer": "Jojo Reviewer",
                "reviewed_at": "2026-09-05T12:00:00-06:00",
                "notes": "Checked both crosslinks and all four highlighted centers.",
                "source_geometry_sha256": item["definition_candidate"]["sha256"],
                "gate_effect": "none",
            }
        )
    visual_path = tmp_path / "visual-decisions.json"
    visual_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-visual-review-decisions.v1",
                "status": "revision_requested",
                "simulation_ready": False,
                "gate_effect": "none",
                "source_definition_packet": {
                    "path": str(packet_path),
                    "sha256": _sha256(packet_path),
                },
                "source_conformer_index": {
                    "path": str(tmp_path / "unused-conformer-index.json"),
                    "sha256": "0" * 64,
                },
                "decisions": decisions,
            },
            indent=2,
        )
        + "\n"
    )
    source_template = (
        Path(__file__).resolve().parents[1]
        / "backend/data/forcefield/photoproducts/tt-cpd-cis-syn/chemical_definition.json"
    )
    result = materialize_visual_definition_review(
        packet_path=packet_path,
        visual_decisions_path=visual_path,
        source_asset_template_path=source_template,
        structural_reference_manifest_path=(
            Path(__file__).resolve().parents[1]
            / "backend/data/forcefield/photoproduct_structural_references.json"
        ),
        output_dir=tmp_path / "materialized",
    )

    assert result["status"] == "passed_gate_neutral_materialization"
    assert result["simulation_ready"] is False
    assert result["gate_effect"] == "none"
    assert result["unresolved_product_ids"] == [revised_id]
    assert len(result["approved_product_ids"]) == 6
    assert not (tmp_path / "materialized/reviewed_definitions" / f"{revised_id}.json").exists()
    released = json.loads(
        next((tmp_path / "materialized/reviewed_definitions").glob("*.json")).read_text()
    )
    assert released["schema"] == "nadoc.photoproduct-chemical-definition.v1"
    assert released["source_assets"]
    taylor = next(
        item for item in released["source_assets"]
        if item["id"] == "Taylor-2023-CPD-stereochemistry"
    )
    assert taylor["hash_scope"] == "embedded_citation_record_not_publisher_article"
    assert "status" not in released

    stale = json.loads(visual_path.read_text())
    stale["decisions"][1]["source_geometry_sha256"] = "f" * 64
    stale_path = tmp_path / "stale-visual-decisions.json"
    stale_path.write_text(json.dumps(stale, indent=2) + "\n")
    with pytest.raises(ValueError, match="stale or reviewed a different geometry"):
        materialize_visual_definition_review(
            packet_path=packet_path,
            visual_decisions_path=stale_path,
            source_asset_template_path=source_template,
            structural_reference_manifest_path=(
                Path(__file__).resolve().parents[1]
                / "backend/data/forcefield/photoproduct_structural_references.json"
            ),
            output_dir=tmp_path / "stale-materialized",
        )


def test_review_packet_distinguishes_audited_equivalent_hessian_from_direct_run(
    tmp_path: Path,
) -> None:
    definitions, candidate_audit, independent = _fixtures(tmp_path)
    source_audit = tmp_path / "source_frequency_audit.json"
    hessian = tmp_path / "source_hessian.txt"
    geometry = tmp_path / "source.xyz"
    equivalence = tmp_path / "equivalence.json"
    hessian.write_text("1.0\n")
    geometry.write_text("1\nsource\nC 0 0 0\n")
    source_audit.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-audit.v1",
                "status": "passed_harmonic_minimum",
                "product_id": "tt-cpd-cis-syn",
                "imaginary_mode_count": 0,
                "cartesian_hessian": {"sha256": _sha256(hessian)},
            }
        )
    )
    equivalence.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-equivalence-audit.v1",
                "status": "passed_candidate_model_equivalence",
                "passed": True,
                "product_ids": ["tt-cpd-cis-syn", "tt-cpd-cis-syn-ii"],
            }
        )
    )
    reference = tmp_path / "equivalent_hessian.json"
    reference.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-equivalent-hessian-reference.v1",
                "status": "passed_candidate_reuse_preconditions",
                "passed": True,
                "gate_effect": "none",
                "source_product_id": "tt-cpd-cis-syn",
                "target_product_id": "tt-cpd-cis-syn-ii",
                "coordinate_frame": "source-retained-no-tensor-rotation",
                "source_atom_map": ["1:C5", "2:C5"],
                "target_atom_map_in_source_matrix_order": ["2:C5", "1:C5"],
                "source_frequency": {
                    "frequency_audit": _record(source_audit),
                    "cartesian_hessian": _record(hessian),
                    "source_geometry": _record(geometry),
                },
                "equivalence_audit": _record(equivalence),
            }
        )
    )

    packet = build_tt_cpd_definition_review_packet(
        definition_candidate_paths=definitions,
        candidate_audit_path=candidate_audit,
        independent_audit_path=independent,
        frequency_audit_paths=[],
        equivalent_hessian_reference_paths=[reference],
        output_dir=tmp_path / "packet-equivalent",
    )

    cis_syn_ii = next(
        item for item in packet["candidates"] if item["product_id"] == "tt-cpd-cis-syn-ii"
    )
    assert cis_syn_ii["frequency_evidence"]["status"] == (
        "passed_equivalent_source_candidate"
    )
    assert cis_syn_ii["frequency_evidence"]["source_product_id"] == "tt-cpd-cis-syn"
    markdown = (tmp_path / "packet-equivalent/definition_review_packet.md").read_text()
    assert "audited endpoint-exchange reuse" in markdown
    assert "no independent run" in markdown
