"""Legacy job evidence must not turn missing provenance into a current verdict."""

import asyncio
from copy import deepcopy

import pytest


HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.mark.parametrize("engine", ["oxdna", "namd"])
@pytest.mark.parametrize("before,after,match,reason", [
    (None, "v4:" + HASH_A, None, "missing_model_evidence"),
    ("v4:" + HASH_A, None, None, "missing_model_evidence"),
    ("v4:" + HASH_A, "v4:" + HASH_A, True, "incomplete_input_provenance"),
    ("v4:" + HASH_A, "v4:" + HASH_B, False, "model_projection_changed"),
    ("v3:" + HASH_A, "v4:" + HASH_A, None, "incomparable_model_projection"),
    (HASH_A, "v4:" + HASH_A, None, "incomparable_model_projection"),
    ("v999:" + HASH_A, "v999:" + HASH_A, None, "unsupported_model_projection"),
    ("v4:short", "v4:short", None, "invalid_model_evidence"),
    ({"sha256": HASH_A}, "v4:" + HASH_A, None, "invalid_model_evidence"),
    ("v4:" + "A" * 64, "v4:" + HASH_A, None, "invalid_model_evidence"),
])
def test_legacy_freshness_separates_comparison_from_complete_provenance(engine, before, after, match, reason):
    from backend.core.physical_input_freshness import legacy_input_freshness

    original = deepcopy((before, after))
    result = legacy_input_freshness(before, after, engine=engine)
    assert result["status"] == ("stale" if match is False else "unknown")
    assert result["model_match"] is match
    assert reason in result["reasons"]
    assert result["coverage"]["complete"] is False
    assert result["compared_to"] == {"engine": engine, "subject": "active_part_model"}
    assert (before, after) == original


@pytest.mark.parametrize("engine", ["oxdna", "namd"])
@pytest.mark.parametrize("endpoint", ["list", "get"])
@pytest.mark.parametrize("stale", [False, True])
def test_job_response_exposes_partial_evidence_without_extra_hash_or_job_write(monkeypatch, tmp_path, engine, endpoint, stale):
    from backend.core import design_disk_usage, oxdna_staleness
    from backend.core.md_job import MdStatus, new_job
    from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job
    from backend.api import routes_md, routes_oxdna

    routes = routes_oxdna if engine == "oxdna" else routes_md
    job = new_oxdna_job("Freshness", []) if engine == "oxdna" else new_job("Freshness", "equilibrium_aware", "", "")
    job.status = OxdnaStatus.completed if engine == "oxdna" else MdStatus.completed
    original = deepcopy(job.to_dict())
    monkeypatch.setattr(routes, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes, "_load_job", lambda _id: job)
    monkeypatch.setattr(design_disk_usage, "dir_size_bytes_cached_only", lambda _path: 0)
    monkeypatch.setattr(oxdna_staleness, "current_active_design_fingerprint", lambda: "v4:" + HASH_A)
    calls = []

    def fingerprint(value):
        calls.append(value.job_id)
        return "v4:" + (HASH_B if stale else HASH_A)

    monkeypatch.setattr(routes, "_job_fingerprint" if engine == "oxdna" else "_md_job_fingerprint", fingerprint)
    monkeypatch.setattr(type(job), "save", lambda *_args, **_kw: pytest.fail("Polling wrote a job"))
    if engine == "oxdna":
        monkeypatch.setattr(type(job), "list_jobs", lambda _path: [job])
        monkeypatch.setattr(routes, "reconcile_oxdna_status", lambda value, _ws: value)
        result = routes._list_oxdna_jobs()[0][0] if endpoint == "list" else asyncio.run(routes.get_oxdna_job(job.job_id))
    else:
        result = routes._md_job_list_rows([job], tmp_path, False, None)[0][0] if endpoint == "list" else asyncio.run(routes.get_md_job(job.job_id))
    assert result["input_freshness"]["status"] == ("stale" if stale else "unknown")
    assert result["input_freshness"]["model_match"] is not stale
    assert result["out_of_date"] is stale
    assert calls == [job.job_id]
    assert job.to_dict() == original
    assert list(tmp_path.iterdir()) == []


def test_unavailable_archived_md_job_is_explicitly_unknown_without_snapshot_read(monkeypatch, tmp_path):
    from backend.api import routes_md
    from backend.core import oxdna_staleness
    from backend.core.md_job import new_job

    job = new_job("Archived", "equilibrium_aware", "", "")
    job.archived = True
    monkeypatch.setattr(oxdna_staleness, "current_active_design_fingerprint", lambda: "v4:" + HASH_A)
    monkeypatch.setattr(routes_md, "_md_job_fingerprint", lambda *_args: pytest.fail("Unavailable archive read"))
    row = routes_md._md_job_list_rows([job], tmp_path, False, None)[0][0]
    assert row["input_freshness"]["status"] == "unknown"
    assert "missing_model_evidence" in row["input_freshness"]["reasons"]
