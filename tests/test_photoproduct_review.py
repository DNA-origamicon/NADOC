import json
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app

from backend.core.photoproduct_review import (
    BOUNDARY_MODEL_RELATIVES,
    CONFORMER_INDEX_RELATIVE,
    DECISIONS_RELATIVE,
    DEFINITION_PACKET_RELATIVE,
    DEFAULT_STORAGE_ROOT,
    PhotoproductReviewError,
    build_photoproduct_review_catalog,
    record_photoproduct_visual_decision,
)
from backend.parameterization.photoproduct_coupled_conformer import (
    materialize_visual_coupled_conformer_review,
)


def _review_root(tmp_path: Path) -> Path:
    for relative in (DEFINITION_PACKET_RELATIVE, CONFORMER_INDEX_RELATIVE):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_STORAGE_ROOT / relative, destination)
    for relative in BOUNDARY_MODEL_RELATIVES:
        shutil.copytree(DEFAULT_STORAGE_ROOT / relative, tmp_path / relative)
    return tmp_path


def test_review_catalog_revalidates_sources_and_marks_focus_geometry(tmp_path):
    root = _review_root(tmp_path)
    catalog = build_photoproduct_review_catalog(storage_root=root)
    assert catalog["simulation_ready"] is False
    assert catalog["gate_effect"] == "none"
    assert catalog["review_scope"] == "visual_identity_and_stereochemistry_only"
    assert len(catalog["definition_scenes"]) == 7
    assert len(catalog["conformer_groups"]) == 8
    assert all(len(group["frames"]) == 4 for group in catalog["conformer_groups"])
    assert len(catalog["boundary_scenes"]) == 2

    scene = catalog["definition_scenes"][0]
    assert len(scene["atom_keys"]) == len(scene["elements"]) == 12
    assert len(scene["bonds"]) == 12
    assert scene["metadata"]["geometry_source"] == "exact_definition_local_coordinates"
    assert [bond["kind"] for bond in scene["bonds"]].count(
        "photoproduct_crosslink"
    ) == 2
    assert [bond["kind"] for bond in scene["bonds"]].count(
        "cyclobutane_ring"
    ) == 2
    assert len(scene["stereocenters"]) == 4
    assert all(center["passed"] for center in scene["stereocenters"])
    boundary = catalog["boundary_scenes"][0]
    assert len(boundary["atom_keys"]) == 63
    assert boundary["metadata"]["formal_charge"] == -1
    kinds = {bond["kind"] for bond in boundary["bonds"]}
    assert {"terminal_cap", "phosphate_boundary", "glycosidic_boundary"} <= kinds


def test_definition_decision_for_old_embedding_is_marked_stale(tmp_path):
    root = _review_root(tmp_path)
    decision_path = root / DECISIONS_RELATIVE
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    catalog = build_photoproduct_review_catalog(storage_root=root)
    payload = {
        "schema": "nadoc.photoproduct-visual-review-decisions.v1",
        "status": "human_review_in_progress",
        "simulation_ready": False,
        "gate_effect": "none",
        "source_definition_packet": catalog["sources"]["definition_packet"],
        "source_conformer_index": catalog["sources"]["conformer_index"],
        "decisions": [
            {
                "stage": "chemical_definition",
                "product_id": "tt-cpd-cis-syn-ii",
                "conformer_id": None,
                "decision": "approve",
                "partition": None,
                "reviewer": "Jojo Reviewer",
                "reviewed_at": "2026-09-04T00:00:00+00:00",
                "notes": "Reviewed the previous initial candidate embedding.",
                "source_geometry_sha256": "0" * 64,
                "gate_effect": "none",
            }
        ],
    }
    decision_path.write_text(json.dumps(payload, indent=2) + "\n")

    catalog = build_photoproduct_review_catalog(storage_root=root)
    scene = next(
        item
        for item in catalog["definition_scenes"]
        if item["product_id"] == "tt-cpd-cis-syn-ii"
    )
    assert scene["decision"]["stale"] is True
    assert catalog["stale_decision_count"] == 1


def test_visual_decision_is_atomic_gate_neutral_and_revision_stays_unresolved(tmp_path):
    root = _review_root(tmp_path)
    result = record_photoproduct_visual_decision(
        stage="chemical_definition",
        product_id="tt-cpd-cis-syn-ii",
        decision="revise",
        reviewer="Jojo Reviewer",
        notes="Endpoint two requires a corrected atom-mapped configuration.",
        storage_root=root,
    )
    assert result["simulation_ready"] is False
    assert result["gate_effect"] == "none"
    stored = json.loads((root / DECISIONS_RELATIVE).read_text())
    assert stored["status"] == "revision_requested"
    assert stored["decisions"][0]["decision"] == "revise"
    assert stored["decisions"][0]["source_geometry_sha256"]

    catalog = build_photoproduct_review_catalog(storage_root=root)
    scene = next(
        item
        for item in catalog["definition_scenes"]
        if item["product_id"] == "tt-cpd-cis-syn-ii"
    )
    assert scene["decision"]["decision"] == "revise"


def test_conformer_approval_requires_partition_and_source_hashes_are_immutable(tmp_path):
    root = _review_root(tmp_path)
    with pytest.raises(PhotoproductReviewError, match="require a training"):
        record_photoproduct_visual_decision(
            stage="coupled_conformer",
            product_id="tt-cpd-cis-syn",
            conformer_id="conformer-001",
            decision="approve",
            reviewer="Jojo Reviewer",
            notes="Geometry preserves identity and the audited stereochemistry.",
            storage_root=root,
        )

    record_photoproduct_visual_decision(
        stage="coupled_conformer",
        product_id="tt-cpd-cis-syn",
        conformer_id="conformer-001",
        decision="approve",
        partition="training",
        reviewer="Jojo Reviewer",
        notes="Geometry preserves identity and the audited stereochemistry.",
        storage_root=root,
    )
    decision_path = root / DECISIONS_RELATIVE
    payload = json.loads(decision_path.read_text())
    payload["source_conformer_index"]["sha256"] = "0" * 64
    decision_path.write_text(json.dumps(payload))
    with pytest.raises(PhotoproductReviewError, match="stale"):
        build_photoproduct_review_catalog(storage_root=root)


def test_boundary_review_is_hash_pinned_without_fit_partition(tmp_path):
    root = _review_root(tmp_path)
    result = record_photoproduct_visual_decision(
        stage="dna_boundary_model",
        product_id="tt-cpd-cis-syn",
        conformer_id="chain-b",
        decision="approve",
        reviewer="Jojo Reviewer",
        notes="Terminal caps, phosphate, glycosidic bonds, and lesion look consistent.",
        storage_root=root,
    )
    assert result["decision"]["partition"] is None
    assert result["decision"]["source_geometry_sha256"]
    with pytest.raises(PhotoproductReviewError, match="cannot enter a fit partition"):
        record_photoproduct_visual_decision(
            stage="dna_boundary_model",
            product_id="tt-cpd-cis-syn",
            conformer_id="chain-d",
            decision="approve",
            partition="training",
            reviewer="Jojo Reviewer",
            notes="Terminal caps, phosphate, glycosidic bonds, and lesion look consistent.",
            storage_root=root,
        )


def test_complete_visual_conformer_decisions_materialize_audited_plans(tmp_path):
    root = _review_root(tmp_path)
    catalog = build_photoproduct_review_catalog(storage_root=root)
    decisions = []
    for group in catalog["conformer_groups"]:
        for index, frame in enumerate(group["frames"]):
            decisions.append(
                {
                    "stage": "coupled_conformer",
                    "product_id": group["product_id"],
                    "conformer_id": frame["conformer_id"],
                    "decision": "approve",
                    "partition": "training" if index % 2 == 0 else "validation",
                    "reviewer": "Jojo Reviewer",
                    "reviewed_at": "2026-09-05T12:00:00-06:00",
                    "notes": "Identity, ring geometry, and nonbonded contacts look consistent.",
                    "source_geometry_sha256": frame["source_geometry"]["sha256"],
                    "gate_effect": "none",
                }
            )
    visual_path = root / DECISIONS_RELATIVE
    visual_path.parent.mkdir(parents=True, exist_ok=True)
    visual_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-visual-review-decisions.v1",
                "status": "human_review_in_progress",
                "simulation_ready": False,
                "gate_effect": "none",
                "source_definition_packet": catalog["sources"]["definition_packet"],
                "source_conformer_index": catalog["sources"]["conformer_index"],
                "decisions": decisions,
            },
            indent=2,
        )
        + "\n"
    )
    single = materialize_visual_coupled_conformer_review(
        review_index_path=root / CONFORMER_INDEX_RELATIVE,
        visual_decisions_path=visual_path,
        output_dir=tmp_path / "materialized-cis-syn-conformers",
        product_ids=["tt-cpd-cis-syn"],
    )
    assert single["product_count"] == 1
    assert len(
        list(
            (tmp_path / "materialized-cis-syn-conformers/reviewed_plans").glob(
                "*.reviewed.json"
            )
        )
    ) == 1
    receipt = materialize_visual_coupled_conformer_review(
        review_index_path=root / CONFORMER_INDEX_RELATIVE,
        visual_decisions_path=visual_path,
        output_dir=tmp_path / "materialized-conformers",
    )
    assert receipt["status"] == "passed_human_review_structure"
    assert receipt["product_count"] == 8
    assert receipt["simulation_ready"] is False
    plans = list((tmp_path / "materialized-conformers/reviewed_plans").glob("*.reviewed.json"))
    assert len(plans) == 8


def test_scientific_review_api_serves_geometry_and_records_gate_neutral_decisions(
    tmp_path, monkeypatch
):
    root = _review_root(tmp_path)
    monkeypatch.setenv("NADOC_PHOTOPRODUCT_STORAGE_ROOT", str(root))
    client = TestClient(app)
    response = client.get("/api/design/photoproducts/scientific-review")
    assert response.status_code == 200, response.text
    assert len(response.json()["definition_scenes"]) == 7

    response = client.put(
        "/api/design/photoproducts/scientific-review/decision",
        json={
            "stage": "chemical_definition",
            "product_id": "tt-cpd-trans-syn-i",
            "decision": "approve",
            "reviewer": "Jojo Reviewer",
            "notes": "Atom mapping and all four highlighted centers look consistent.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["gate_effect"] == "none"
    assert response.json()["simulation_ready"] is False
