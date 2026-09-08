from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_post_qm_efficient_sequence as sequence
from scripts.run_post_qm_efficient_sequence import (
    CONFORMERS,
    PRODUCTS,
    build_shortlist,
    build_pilot_plan,
    stable_base_key,
    validate_qm_completion,
)
from scripts.assemble_photoproduct_qm_completion import assemble_completion


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_stable_base_key_preserves_colon_ids_and_copy_identity() -> None:
    assert stable_base_key({
        "kind": "crossover_insert", "crossover_id": "x:with:colons", "extra_base_k": 1,
    }) == "__xb__:x:with:colons:1"
    assert stable_base_key({
        "kind": "base", "helix_id": "h:1", "bp_index": -2,
        "direction": "reverse", "copy_k": 3,
    }) == "h:1:-2:REVERSE:3"


def test_qm_completion_requires_all_32_identity_checked_batches(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    root = tmp_path / "qm"
    _write(queue, {"schema": "nadoc.photoproduct-local-response-queue.v1", "status": "passed"})
    for product in PRODUCTS:
        for conformer in CONFORMERS:
            name = "local-batch-report-v2.json" if product == "tt-cpd-cis-syn" else "local-batch-report-v1.json"
            _write(root / product / f"conformer-{conformer}" / name, {
                "schema": "nadoc.photoproduct-local-fixed-hessian-batch.v1",
                "status": "passed", "product_id": product,
                "conformer_id": f"conformer-{conformer}",
            })
    result = validate_qm_completion(queue, root)
    assert result["batch_count"] == 32
    assert len(result["batches"]) == 32


def test_qm_completion_rejects_stale_product_identity(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    root = tmp_path / "qm"
    _write(queue, {"schema": "nadoc.photoproduct-local-response-queue.v1", "status": "passed"})
    for product in PRODUCTS:
        for conformer in CONFORMERS:
            name = "local-batch-report-v2.json" if product == "tt-cpd-cis-syn" else "local-batch-report-v1.json"
            _write(root / product / f"conformer-{conformer}" / name, {
                "schema": "nadoc.photoproduct-local-fixed-hessian-batch.v1",
                "status": "passed", "product_id": product,
                "conformer_id": f"conformer-{conformer}",
            })
    bad = root / PRODUCTS[-1] / "conformer-004" / "local-batch-report-v1.json"
    payload = json.loads(bad.read_text())
    payload["product_id"] = PRODUCTS[0]
    _write(bad, payload)
    with pytest.raises(RuntimeError, match="stale identity"):
        validate_qm_completion(queue, root)


def test_hash_pinned_all_form_completion_across_source_roots(tmp_path: Path) -> None:
    old = tmp_path / "old"
    current = tmp_path / "current"
    for product in PRODUCTS:
        source = old if product == PRODUCTS[0] else current
        for conformer in CONFORMERS:
            _write(
                source
                / product
                / f"conformer-{conformer}"
                / "local-batch-report-v2.1.0.json",
                {
                    "schema": "nadoc.photoproduct-local-fixed-hessian-batch.v1",
                    "status": "passed",
                    "simulation_ready": False,
                    "gate_effect": "none",
                    "product_id": product,
                    "conformer_id": f"conformer-{conformer}",
                    "task_count": 211,
                },
            )
    receipt_path = tmp_path / "all-form-completion.json"
    receipt = assemble_completion(
        source_roots=[old, current], output_path=receipt_path
    )
    assert receipt["product_count"] == 8
    assert receipt["conformer_count"] == 32
    assert receipt["task_count"] == 6752
    validated = validate_qm_completion(receipt_path, tmp_path)
    assert validated["batch_count"] == 32

    first = Path(receipt["batches"][0]["batch_report"]["path"])
    first.write_text(first.read_text() + "\n")
    with pytest.raises(RuntimeError, match="hash-mismatched"):
        validate_qm_completion(receipt_path, tmp_path)


def test_pilot_plan_fails_closed_without_released_product_assets(
    tmp_path: Path,
) -> None:
    registry = Path("backend/data/forcefield/photoproduct_registry.json")
    shortlist = {
        "primary_pilot_sites": [{
            "arrangement": "1-1",
            "priority_class": "interstrand:designed_extra_extra",
            "base_keys": ["__xb__:one:0", "__xb__:two:0"],
        }],
    }
    result = build_pilot_plan(shortlist, tmp_path, registry)
    assert result["status"] == "blocked_fail_closed"
    assert result["launch_effect"] == "none"
    assert all(arm["timestep_fs"] == 2.0 for arm in result["arms"])
    assert (tmp_path / "pilot_plan.json").is_file()


def test_shortlist_keeps_stable_keys_and_intrastrand_competition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sequence, "_near_insert_keys", lambda: {"24hb": set()})
    summary = tmp_path / "summary.json"
    pair = {
        "site_a": {"design_identity": {
            "kind": "crossover_insert", "crossover_id": "left:one", "extra_base_k": 0,
        }},
        "site_b": {"design_identity": {
            "kind": "crossover_insert", "crossover_id": "left:one", "extra_base_k": 1,
        }},
        "same_strand": True,
        "intended_weld": False,
        "screen_min_midpoint_ang": 4.0,
        "periodic_propensity_mean": 0.25,
        "pct_reactive_corner": 5.0,
        "d_mid_min_nm": 0.4,
        "representative_max_propensity": {"trajectory_frame": 2},
    }
    _write(summary, {
        "post_qm_sequence": {
            "job_id": "job", "family": "24hb", "arrangement": "2-2",
            "lineage_id": "lineage",
        },
        "pairs": [pair],
    })
    result = build_shortlist(
        [{"summary": {"path": str(summary), "sha256": "0" * 64}}], tmp_path,
    )
    assert result["primary_pilot_sites"][0]["priority_class"] == (
        "intrastrand:other_extra_extra"
    )
    assert result["primary_pilot_sites"][0]["base_keys"] == [
        "__xb__:left:one:0", "__xb__:left:one:1",
    ]
