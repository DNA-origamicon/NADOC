"""MD-job out-of-date detection + the snapshot roll (parity with oxDNA).  GPU-free —
the stale guard fires before any NAMD/package work."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

import backend.api.routes_md as routes_md
from backend.api import state as design_state
# Imported at MODULE level (collection time) so the app is built with the REAL routers
# BEFORE any test that swaps a fake fastapi into sys.modules (test_md_milestone1) runs.
from backend.api.main import app
from backend.core.md_job import MdStatus, new_job
from backend.core.oxdna_staleness import design_build_fingerprint
from tests.conftest import make_18hb_design, make_6hb_design


@pytest.fixture(autouse=True)
def _clean_default_doc():
    # Reset any leaked doc-context contextvar to the default doc, so set_design (which
    # uses the contextvar) and the TestClient routes (which use the default doc) agree.
    from backend.api import doc_context
    from backend.api import state as design_state
    doc_context.set_current_doc(None)
    yield
    design_state.drop_doc(doc_context.DEFAULT_DOC_ID)


def _make_md_job(tmp_path, design, *, fingerprint):
    job = new_job("6hb", "equilibrium_aware", "", "")
    job.status = MdStatus.completed
    job.design_fingerprint = fingerprint
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(design.model_dump_json())
    return job


def test_md_out_of_date_flag_and_roll_clears_it(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)

    prepared = make_6hb_design()
    for s in prepared.strands:
        s.sequence = "ACGT"
    job = _make_md_job(tmp_path, prepared, fingerprint=design_build_fingerprint(prepared))

    # User edits the design (clears sequences) → MD job is out of date.
    edited = prepared.model_copy(deep=True)
    for s in edited.strands:
        s.sequence = ""
    design_state.set_design(edited)
    c = TestClient(app)
    assert c.get(f"/api/md/jobs/{job.job_id}").json()["out_of_date"] is True

    # Production is refused (409) on a stale MD job.
    r409 = c.post(f"/api/md/jobs/{job.job_id}/production", json={"steps": 1000})
    assert r409.status_code == 409
    # Same design edited in place (sequences cleared) → identity matches, so the
    # message names the edit-and-roll case rather than "a different design is loaded".
    detail = r409.json()["detail"].lower()
    assert "has been edited" in detail and "roll" in detail

    # Roll to the job's prepared state → restores the sequenced snapshot, clears ⚠.
    r = c.post(f"/api/md/jobs/{job.job_id}/roll-design")
    assert r.status_code == 200, r.text
    assert r.json().get("return_loadout_id")
    restored = design_state.get_or_404()
    assert all(s.sequence == "ACGT" for s in restored.strands)
    assert design_build_fingerprint(restored) == job.design_fingerprint
    assert c.get(f"/api/md/jobs/{job.job_id}").json()["out_of_date"] is False


def test_md_stale_message_names_a_different_loaded_design(monkeypatch, tmp_path):
    """When a WHOLLY different design is loaded (not an edit of the job's design), the
    409 must say so and name both designs — rolling the feature log can't fix it.
    This is the real-world 'Bundle loaded instead of the job's design' case."""
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)

    prepared = make_6hb_design()          # what the job was built from
    job = _make_md_job(tmp_path, prepared, fingerprint=design_build_fingerprint(prepared))

    other = make_18hb_design()            # a different structure entirely
    assert len(other.helices) != len(prepared.helices)
    design_state.set_design(other)

    r409 = TestClient(app).post(f"/api/md/jobs/{job.job_id}/production", json={"steps": 1000})
    assert r409.status_code == 409
    detail = r409.json()["detail"].lower()
    assert "different design is loaded" in detail
    assert f"{len(other.helices)} helices" in detail        # names the loaded design's size
    assert f"{len(prepared.helices)} helices" in detail      # and the job's design's size
