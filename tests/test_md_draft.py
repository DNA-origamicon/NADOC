"""Deferred-prep DRAFT NAMD jobs ("Use as NAMD seed").

A draft records the seed source + provenance but DEFERS the expensive solvation so
the user can set advanced options first; the prep runs later on
POST /md/jobs/{id}/prepare ("Relax from oxDNA").  These pin that a draft persists
as its own state and that the local status-reconciler never disturbs it.
"""

from __future__ import annotations

import asyncio

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
    monkeypatch.setattr(routes_md, "random_seed", lambda: 987654321)
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
    assert job.namd_seed == 987654321
    assert job.prep_params["seed"] == 987654321
    assert job.prep_params["draft"] is True
    # Persisted to disk in the draft state, with no package.
    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.status == MdStatus.draft
    assert loaded.package_subdir == ""


def test_copy_draft_preserves_settings_and_changes_only_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes_md, "random_seed", lambda exclude=(): 246802468)
    body = routes_md.CreateJobRequest(
        oxdna_job_id="ox1", draft=True, seed=135791357,
        design_source_path="part.nadoc", padding_nm=2.4,
    )
    source = routes_md._spawn_draft_job(body, name="D")

    result = asyncio.run(routes_md.copy_md_job(source.job_id))
    copied = MdJob.load(result["job"]["job_id"], tmp_path)

    assert copied.status == MdStatus.draft
    assert copied.job_id != source.job_id
    assert copied.namd_seed == result["seed"] == 246802468
    assert copied.prep_params["padding_nm"] == source.prep_params["padding_nm"]
    assert copied.prep_params["oxdna_job_id"] == source.prep_params["oxdna_job_id"]
    assert copied.prep_params["seed"] != source.prep_params["seed"]


def test_editing_a_draft_updates_the_same_record_without_preparing(tmp_path, monkeypatch):
    """Save changes is an update, never clone-and-delete or an implicit launch."""
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(
        design_name="D", protocol="old", name_stem="", package_subdir="",
        seed_oxdna_job_id="ox1",
    )
    job.status = MdStatus.draft
    job.prep_params = {"protocol": "old", "draft": True}
    job.save(tmp_path)
    from backend.core import md_queue
    md_queue.enqueue(tmp_path, job.job_id)  # stale/manual entry must not survive an edit

    out = asyncio.run(routes_md.update_md_job_settings(job.job_id, {
        "protocol": "mgh_slow_release", "threads": 7, "draft": False,
    }))

    assert out["job_id"] == job.job_id
    saved = MdJob.load(job.job_id, tmp_path)
    assert saved.status == MdStatus.draft
    assert saved.threads == 7
    assert saved.protocol == "mgh_slow_release"
    assert [j.job_id for j in MdJob.list_jobs(tmp_path)] == [job.job_id]
    assert md_queue.load_queue(tmp_path) == []


def test_edit_cleanup_preserves_job_identity_but_removes_every_stale_artifact(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(design_name="D", protocol="p", name_stem="s", package_subdir="package/x")
    job.status = MdStatus.queued
    job.save(tmp_path)
    job_dir = job.job_dir(tmp_path)
    (job_dir / "package" / "x" / "output").mkdir(parents=True)
    (job_dir / "package" / "x" / "output" / "old.dcd").write_text("stale")
    (job_dir / "prep_progress.json").write_text("old")

    routes_md._clear_editable_job_artifacts(job)

    assert (job_dir / "job.json").exists()
    assert [p.name for p in job_dir.iterdir()] == ["job.json"]
    assert MdJob.load(job.job_id, tmp_path).job_id == job.job_id


def test_edit_rejects_a_submitted_queued_job(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(design_name="D", protocol="p", name_stem="s", package_subdir="p")
    job.status = MdStatus.queued
    job.slurm_job_id = "123"
    job.save(tmp_path)

    from fastapi import HTTPException

    try:
        asyncio.run(routes_md.update_md_job_settings(job.job_id, {"threads": 4}))
        assert False, "submitted job was editable"
    except HTTPException as exc:
        assert exc.status_code == 409


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
