"""Threshold review cannot be skipped, reused after edits, or replace provenance."""

import copy
import hashlib
import json
from uuid import UUID

import pytest

from backend.core.models import Design
from experiments.recorded_review_process import Process, ProcessRequired
from scripts import agent_bond_review as review
from scripts import agent_structure_guard as guard


@pytest.fixture
def design():
    process = Process("Bond-review gate test")
    process.append("bundle-create", {
        "_proof_version": 1, "history_seed": str(UUID(int=902)),
        "cells": [[0, 0]], "length_bp": 4, "name": "Bond-review gate test",
        "lattice_type": "HONEYCOMB", "ligate_adjacent": False,
    }, "Create a native four-base-pair helix")
    return process.design


@pytest.fixture
def report(monkeypatch):
    value = {
        "schema_version": 1, "review_required": False, "reason_codes": [],
        "threshold_fraction": .2,
        "counts": {"backbone_bonds": 6, "interhelix_bonds": 0,
                   "matched_forced_bonds": 0, "matched_forced_interhelix_bonds": 0,
                   "unmatched_forced_records": 0},
        "ratios": {"forced_all": 0., "forced_interhelix": 0.},
        "geometry": {"requested": True, "complete": True, "threshold_nm": 1.2,
                     "long_all": 0, "long_interhelix": 0, "fraction_all": 0.,
                     "fraction_interhelix": 0., "measured_bonds": 6,
                     "missing_bonds": 0, "worst_edges": []},
    }
    monkeypatch.setattr(review, "review_design_bonds", lambda design, **kw: copy.deepcopy(value))
    return value


@pytest.fixture
def provenance(monkeypatch):
    calls = []

    def verify(design, **kwargs):
        calls.append((design, kwargs))
        return {"status": "verified", "commands": 1}

    monkeypatch.setattr(guard, "_audit_with_process", verify)
    return calls


def require_review(report, *, incomplete=False):
    report.update(review_required=True,
                  reason_codes=["BOND_GEOMETRY_INCOMPLETE" if incomplete
                                else "FORCED_JUNCTION_FRACTION_GT_20_PERCENT"])
    if incomplete:
        report["geometry"].update(complete=False, missing_bonds=1, measured_bonds=5)
    else:
        report["counts"].update(interhelix_bonds=3, matched_forced_bonds=1,
                                matched_forced_interhelix_bonds=1)
        report["ratios"].update(forced_all=1/6, forced_interhelix=1/3)


def receipt_files(tmp_path, design):
    envelope = review.bond_report(design)
    report_file = tmp_path / "bond-report.json"
    report_file.write_text(json.dumps(envelope))
    visual = tmp_path / "inspection.svg"
    visual.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Test review evidence</text></svg>')
    receipt = {
        "schema": review.REVIEW_SCHEMA, "design_sha256": envelope["design_sha256"],
        "report_sha256": envelope["report_sha256"], "reviewer": "Test reviewer",
        "reviewed_at": "2026-11-22T12:00:00-07:00", "decision": "reviewed-for-publication",
        "rationale": "Inspected the labeled junctions and traced the routing exception to source connectivity.",
        "evidence": [{"kind": kind, "path": path.name,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                     for kind, path in [("bond-report", report_file), ("visual", visual)]],
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    return path, receipt


def test_clear_report_and_provenance_have_independent_status(design, report, provenance):
    result = guard.audit(design)
    assert result["status"] == "verified"
    assert result["bond_review"]["review_status"] == "not_required"
    assert len(provenance) == 1


@pytest.mark.parametrize("reason", [
    "FORCED_BACKBONE_FRACTION_GT_20_PERCENT", "FORCED_JUNCTION_FRACTION_GT_20_PERCENT",
    "LONG_BACKBONE_FRACTION_GT_20_PERCENT", "LONG_JUNCTION_FRACTION_GT_20_PERCENT",
    "BOND_GEOMETRY_INCOMPLETE",
])
def test_unreviewed_breach_refuses_before_writing(design, report, provenance, tmp_path, reason):
    require_review(report)
    report["reason_codes"] = [reason]
    with pytest.raises(review.BondReviewRequired, match="DESIGN_BOND_REVIEW_REQUIRED") as error:
        guard.publish(design, tmp_path / "refused.nadoc")
    assert error.value.report["report"]["reason_codes"] == [reason]
    assert not provenance
    assert list(tmp_path.iterdir()) == []


def test_accepted_receipt_still_runs_provenance(design, report, provenance, tmp_path):
    require_review(report)
    path, _ = receipt_files(tmp_path, design)
    result = guard.audit(design, bond_review=path)
    assert result["status"] == "verified"
    assert result["bond_review"]["review_status"] == "reviewed"
    assert result["bond_review"]["report"]["review_required"] is True
    assert len(provenance) == 1


def test_publication_passes_receipt_and_saved_identity_remains_reviewed(design, report, provenance, tmp_path):
    require_review(report)
    path, _ = receipt_files(tmp_path, design)
    target = tmp_path / "reviewed.nadoc"
    result = guard.publish(design, target, bond_review=path)
    reopened = Design.model_validate_json(target.read_text())
    assert result["bond_review"]["review_status"] == "reviewed"
    assert guard.audit(reopened, bond_review=path)["bond_review"]["review_status"] == "reviewed"
    assert len(provenance) == 2


def test_receipt_cannot_override_failed_process(design, report, monkeypatch, tmp_path):
    require_review(report)
    path, _ = receipt_files(tmp_path, design)

    def refuse(*args, **kwargs):
        raise ProcessRequired("Construction stage is missing")

    monkeypatch.setattr(guard, "_audit_with_process", refuse)
    with pytest.raises(ProcessRequired, match="stage is missing"):
        guard.publish(design, tmp_path / "refused.nadoc", bond_review=path)
    assert not (tmp_path / "refused.nadoc").exists()
    assert not (tmp_path / "refused.nadoc.agent-writing").exists()


@pytest.mark.parametrize("change", ["design", "report", "visual", "report-evidence"])
def test_receipt_is_invalid_after_document_report_or_evidence_changes(design, report, tmp_path, change):
    require_review(report)
    path, receipt = receipt_files(tmp_path, design)
    if change == "design":
        metadata = design.metadata.model_copy(update={"name": "Adversarial stale receipt"})
        design = design.model_copy(update={"metadata": metadata})
    elif change == "report":
        report["counts"]["unmatched_forced_records"] = 1
    elif change == "visual":
        (tmp_path / "inspection.svg").write_text("Changed evidence")
    else:
        evidence = tmp_path / "bond-report.json"
        evidence.write_text('{}')
        receipt["evidence"][0]["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
        path.write_text(json.dumps(receipt))
    with pytest.raises(review.BondReviewRequired, match="Invalid review receipt"):
        review.require_bond_review(design, path)


@pytest.mark.parametrize(("key", "value"), [
    ("reviewer", "  "), ("rationale", "  "), ("decision", "approved"),
    ("reviewed_at", "2026-11-22T12:00:00"), ("accept_all_designs", True),
])
def test_receipt_requires_explicit_bounded_review_fields(design, report, tmp_path, key, value):
    require_review(report)
    path, receipt = receipt_files(tmp_path, design)
    receipt[key] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(review.BondReviewRequired, match="Invalid review receipt"):
        review.require_bond_review(design, path)


def test_visual_and_complete_numeric_evidence_are_both_required(design, report, tmp_path):
    require_review(report)
    path, receipt = receipt_files(tmp_path, design)
    receipt["evidence"] = [receipt["evidence"][0], receipt["evidence"][0]]
    path.write_text(json.dumps(receipt))
    with pytest.raises(review.BondReviewRequired, match="Both visual inspection"):
        review.require_bond_review(design, path)


def test_receipt_file_size_is_bounded(design, report, tmp_path):
    require_review(report)
    path = tmp_path / "oversized-receipt.json"
    path.write_text(" " * 65537)
    with pytest.raises(review.BondReviewRequired, match="exceeds 65536 bytes"):
        review.require_bond_review(design, path)


def test_incomplete_geometry_requires_explicit_limitations(design, report, tmp_path):
    require_review(report, incomplete=True)
    path, receipt = receipt_files(tmp_path, design)
    with pytest.raises(review.BondReviewRequired, match="explicit limitations"):
        review.require_bond_review(design, path)
    receipt["limitations"] = "One endpoint lacks geometry; no conclusion about its physical length is possible."
    path.write_text(json.dumps(receipt))
    accepted = review.require_bond_review(design, path)
    assert accepted["review_status"] == "reviewed"
    assert accepted["report"]["geometry"]["complete"] is False


def test_exact_normalized_identity_survives_saved_reopened_json(design, report):
    reopened = Design.model_validate_json(design.model_dump_json(indent=2))
    assert review.bond_report(reopened) == review.bond_report(design)


def test_read_only_cli_reports_a_refused_design_without_accepting_it(
    design, report, provenance, tmp_path, capsys,
):
    source = tmp_path / "recorded.nadoc"
    guard.publish(design, source)
    original = source.read_bytes()
    require_review(report)
    assert review.main([str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["report"]["review_required"] is True
    assert "review_status" not in result
    assert source.read_bytes() == original
    output = tmp_path / "report.json"
    assert review.main([str(source), "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == result
    with pytest.raises(FileExistsError):
        review.main([str(source), "--output", str(output)])
    assert source.read_bytes() == original
