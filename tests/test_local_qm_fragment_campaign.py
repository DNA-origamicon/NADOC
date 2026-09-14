from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_EVIDENCE = Path(
    "/media/jojo/Archive/NADOC_archive/photoproduct_evidence"
)
ANTI_SOURCE = (
    ARCHIVE_EVIDENCE
    / "tt-cpd-work-v1-completions/fit/all-forms"
    / "dna-boundary-flex-seeds-v1/screened-flexible-seeds"
    / "tt-cpd-cis-anti-i/chain-b/candidate_manifest.json"
)


def _load_builder():
    path = ROOT / "scripts/local_qm_fragment_campaign/build_campaign.py"
    spec = importlib.util.spec_from_file_location("local_fragment_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fragment_policy_is_hierarchical_and_fail_closed() -> None:
    policy = json.loads(
        (
            ROOT
            / "backend/data/forcefield/photoproduct_qm_fragment_policy_v1.json"
        ).read_text()
    )
    assert policy["simulation_ready"] is False
    assert policy["gate_effect"] == "none"
    assert policy["chemical_partition"]["core"]["atom_count"] == 36
    boundary = policy["chemical_partition"]["single_endpoint_glycosidic_boundary"]
    assert boundary["atom_count"] == 49
    assert boundary["charge"] == 0
    phosphate = policy["chemical_partition"]["phosphate_and_remote_backbone"]
    assert phosphate["new_qm_job"] is False
    assert "escalate" in phosphate["validation"].lower()
    assert len(policy["literature_basis"]) >= 5


def test_local_campaign_prepares_four_primary_and_two_heldout_fragments() -> None:
    builder = _load_builder()
    cases = builder.FRAGMENT_CASES
    assert len(cases) == 6
    assert sum(item["tier"] == "primary" for item in cases) == 4
    assert sum(item["tier"] == "heldout" for item in cases) == 2
    assert {item["retained_endpoint"] for item in cases[:4]} == {1, 2}
    assert all("full" not in item["id"] for item in cases)


def test_local_runner_has_no_default_execution_path() -> None:
    runner = (
        ROOT / "scripts/local_qm_fragment_campaign/run_selected.sh"
    ).read_text()
    assert 'action="${2:---list}"' in runner
    assert "an exact --run CASE_ID selection is required" in runner
    assert "run-qm-job" in runner
    assert '--scratch-dir "$scratch_root"' in runner


def test_core_inventory_does_not_call_interrupted_or_failed_jobs_prepared(tmp_path: Path) -> None:
    builder = _load_builder()
    products = (
        "tt-cpd-cis-anti-i", "tt-cpd-cis-anti-ii", "tt-cpd-cis-syn-ii",
        "tt-cpd-trans-anti-i", "tt-cpd-trans-anti-ii", "tt-cpd-trans-syn-i",
        "tt-cpd-trans-syn-ii",
    )
    base = tmp_path / "tt-cpd-work-v1/qm"
    for product in (*products, "geometry"):
        directory = base / ("geometry" if product == "geometry" else f"stereo-geometries/{product}")
        directory.mkdir(parents=True)
        (directory / "job_manifest.json").write_text("{}")
        (directory / "input.dat").write_text("input")
        if product in {"geometry", "tt-cpd-cis-anti-i"}:
            (directory / "optimized_model_audit.json").write_text(json.dumps({
                "status": "passed_identity_and_chirality", "chirality_audit": {"passed": True}}))
        if product == "tt-cpd-cis-anti-ii":
            (directory / "output.dat").write_text("interrupted")
        if product == "tt-cpd-trans-anti-i":
            (directory / "optimized_model_audit.json").write_text('{"status": "failed"}')
    states = {row['product_id']: row['state'] for row in builder._existing_core_inventory(tmp_path)}
    assert states['tt-cpd-cis-anti-i'] == 'completed_identity_audit'
    assert states['tt-cpd-cis-anti-ii'] == 'existing_attempt_requires_review'
    assert states['tt-cpd-trans-anti-i'] == 'existing_attempt_requires_review'
    assert states['tt-cpd-trans-anti-ii'] == 'prepared_not_run'


@pytest.mark.skipif(
    not ANTI_SOURCE.is_file(), reason="Archive-backed reviewed boundary source unavailable"
)
def test_anti_fragment_keeps_crossed_product_graph_and_one_sugar(
    tmp_path: Path,
) -> None:
    pytest.importorskip("rdkit")
    from backend.parameterization.photoproduct_fragments import (
        build_single_endpoint_glycosidic_fragment,
    )

    manifest = build_single_endpoint_glycosidic_fragment(
        source_manifest_path=ANTI_SOURCE,
        retained_endpoint=1,
        output_dir=tmp_path / "fragment",
    )
    graph = json.loads((tmp_path / "fragment/model_graph.json").read_text())
    edges = {frozenset(item["atoms"]) for item in graph["bonds"]}
    atom_map = manifest["atom_map"]

    assert manifest["atom_count"] == 49
    assert manifest["formal_charge"] == 0
    assert manifest["chirality_audit"]["passed"]
    assert frozenset(("1:C5", "2:C6")) in edges
    assert frozenset(("1:C6", "2:C5")) in edges
    assert "1:C1'" in atom_map
    assert "2:CM" in atom_map
    assert "1:HO3'" in atom_map
    assert not any(key in atom_map for key in ("2:P", "2:OP1", "2:OP2"))
