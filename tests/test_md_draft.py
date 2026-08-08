"""Deferred-prep DRAFT NAMD jobs ("Use as NAMD seed").

A draft records the seed source + provenance but DEFERS the expensive solvation so
the user can set advanced options first; the prep runs later on
POST /md/jobs/{id}/prepare ("Relax from oxDNA").  These pin that a draft persists
as its own state and that the local status-reconciler never disturbs it.
"""

from __future__ import annotations

import backend.api.routes_md as routes_md
from backend.core.md_job import MdJob, MdStatus, new_job
from backend.core.namd_runner import reconcile_job_status


def test_draft_status_roundtrips(tmp_path):
    job = new_job(
        design_name="D",
        protocol="mgh_slow_release",
        name_stem="",
        package_subdir="",
        seed_oxdna_job_id="ox1",
    )
    job.status = MdStatus.draft
    job.prep_params = {"padding_nm": 1.2, "draft": True}
    job.save(tmp_path)

    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.status == MdStatus.draft
    assert loaded.seed_oxdna_job_id == "ox1"
    assert loaded.package_subdir == ""  # no package built yet


def test_reconcile_leaves_draft_untouched(tmp_path):
    """The /proc reconciler only repairs stale RUNNING jobs — a draft is inert."""
    job = new_job(
        design_name="D",
        protocol="p",
        name_stem="",
        package_subdir="",
        seed_oxdna_job_id="ox1",
    )
    job.status = MdStatus.draft
    job.save(tmp_path)

    out = reconcile_job_status(job, tmp_path)
    assert out.status == MdStatus.draft


def test_spawn_draft_job_defers_prep(tmp_path, monkeypatch):
    """_spawn_draft_job creates a persisted draft (no solvation) that remembers its
    seed + default advanced params for later pre-fill."""
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    body = routes_md.CreateJobRequest(
        oxdna_job_id="ox1",
        draft=True,
        design_source_path="part.nadoc",
    )
    job = routes_md._spawn_draft_job(body, name="GT_corner_v2")

    assert job.status == MdStatus.draft
    assert job.seed_oxdna_job_id == "ox1"
    assert job.seed_mrdna_job_id is None
    assert job.design_name == "GT_corner_v2"
    assert job.prep_params["draft"] is True
    # Persisted to disk in the draft state, with no package.
    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.status == MdStatus.draft
    assert loaded.package_subdir == ""


# ── Live-Display design resolution (2026-07-16) ──────────────────────────────
# The live "Display MD" WS must map a trajectory onto the RUN's OWN design, not
# whatever design is open in the editor — a mismatch scrambles the P-atom→(helix,bp)
# assignment into cross-structure streaks.  _md_run_design / md_display_design_for_job
# resolve the run's design WITHOUT the active-session fallback.


def _tiny_design_json(tmp_path, name="run_design"):
    """A minimal valid Design .nadoc on disk (via the demo design)."""
    from backend.api.routes import _demo_design

    d = _demo_design()
    d = d.model_copy(update={"metadata": d.metadata.model_copy(update={"name": name})})
    p = tmp_path / f"{name}.nadoc"
    p.write_text(d.model_dump_json())
    return p, d


def test_md_run_design_resolves_from_source_path(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    _tiny_design_json(tmp_path, "run_design")
    job = new_job(
        design_name="run_design",
        protocol="p",
        name_stem="s",
        package_subdir="",
        design_source_path="run_design.nadoc",
    )
    job.save(tmp_path)
    # no design.json snapshot in the job dir → falls back to the recorded source .nadoc
    got = routes_md._md_run_design(job)
    assert got is not None
    assert got.metadata.name == "run_design"


def test_md_run_design_none_when_unresolvable(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(
        design_name="d",
        protocol="p",
        name_stem="s",
        package_subdir="",
        design_source_path="missing.nadoc",
    )
    job.save(tmp_path)
    # neither snapshot nor a loadable source → None (NO active-session fallback)
    assert routes_md._md_run_design(job) is None


def test_md_display_design_for_job_returns_design_and_name(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    _tiny_design_json(tmp_path, "run_design")
    job = new_job(
        design_name="run_design",
        protocol="p",
        name_stem="s",
        package_subdir="",
        design_source_path="run_design.nadoc",
    )
    job.save(tmp_path)
    design, name = routes_md.md_display_design_for_job(job.job_id)
    assert design is not None and design.metadata.name == "run_design"
    assert name == "run_design"


def test_md_display_design_for_job_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    assert routes_md.md_display_design_for_job("nope") == (None, None)
