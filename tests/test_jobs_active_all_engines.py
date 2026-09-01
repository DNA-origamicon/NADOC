"""`/api/jobs/active` scans every simulation engine — MD (NAMD), oxDNA, LAMMPS,
mrDNA and CanDo — so the sidebar can light a spinner on each engine's section
header while that engine has a running/preparing job.

This pins the three newer engines (LAMMPS/mrDNA/CanDo) added alongside MD+oxDNA:
each busy job is reported with the right ``engine`` key, ``resource_class`` and a
``local`` execution target.
"""

from __future__ import annotations

import backend.api.routes_jobs as routes_jobs
import backend.core.cando_runner as cando_runner
import backend.core.lammps_runner as lammps_runner
import backend.core.mrdna_runner as mrdna_runner
from backend.core.cando_job import CandoStatus, new_cando_job
from backend.core.lammps_job import LammpsStatus, new_lammps_job
from backend.core.mrdna_job import MrdnaStatus, new_mrdna_job


def _no_reconcile(monkeypatch):
    # A persisted-running fixture job has no live process; the real reconcilers
    # would flip it to a terminal state, so pin them to identity for the test.
    monkeypatch.setattr(lammps_runner, "reconcile_lammps_status", lambda j, w: j)
    monkeypatch.setattr(mrdna_runner, "reconcile_mrdna_status", lambda j, w: j)
    monkeypatch.setattr(cando_runner, "reconcile_cando_status", lambda j, w: j)


def test_collect_active_covers_lammps_mrdna_cando(tmp_path, monkeypatch):
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    _no_reconcile(monkeypatch)

    lj = new_lammps_job(design_name="lam_d", design_source_path="/w/lam.nadoc")
    lj.status = LammpsStatus.running
    lj.save(ws)

    mj = new_mrdna_job(design_name="mr_d", design_source_path="/w/mr.nadoc")
    mj.status = MrdnaStatus.preparing
    mj.save(ws)

    cj = new_cando_job(design_name="cando_d", design_source_path="/w/cando.nadoc")
    cj.status = CandoStatus.running
    cj.save(ws)

    active = routes_jobs._collect_active()
    by_engine = {j["engine"]: j for j in active}

    # All three appear, keyed by engine.
    assert set(by_engine) == {"lammps", "mrdna", "cando"}

    # Resource class: LAMMPS + CanDo are CPU; mrDNA (ARBD) holds the GPU.
    assert by_engine["lammps"]["resource_class"] == "cpu"
    assert by_engine["cando"]["resource_class"] == "cpu"
    assert by_engine["mrdna"]["resource_class"] == "gpu"

    # None has a remote backend.
    for j in active:
        assert j["execution_target"] == "local"

    # Carries the design source path (drives the welcome-row spinner match).
    assert by_engine["lammps"]["design_source_path"] == "/w/lam.nadoc"

    # Carries created_at (epoch seconds) so the frontend can break ties by the
    # most recent job (e.g. defaulting the Simulate engine dropdown).
    for j in active:
        assert isinstance(j["created_at"], (int, float))


def test_collect_active_skips_non_busy_new_engines(tmp_path, monkeypatch):
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    _no_reconcile(monkeypatch)

    # queued/completed are not "busy" — they must not appear.
    q = new_lammps_job(design_name="q", design_source_path="/w/q.nadoc")
    q.status = LammpsStatus.queued
    q.save(ws)
    done = new_cando_job(design_name="done", design_source_path="/w/done.nadoc")
    done.status = CandoStatus.completed
    done.save(ws)

    active = routes_jobs._collect_active()
    assert active == []

def test_activity_source_path_recovers_unique_legacy_flattened_assembly(tmp_path):
    ws = tmp_path
    (ws / "assemblies").mkdir()
    (ws / "assemblies" / "polymer.nass").write_text(
        '{"metadata":{"name":"polymer"}}', encoding="utf-8"
    )
    job_dir = ws / "md_jobs" / "legacy"
    job_dir.mkdir(parents=True)
    (job_dir / "design.json").write_text('{"id":"flat_assembly-id"}')
    job = type("LegacyJob", (), {
        "design_source_path": None,
        "project_id": "flat_assembly-id",
        "design_name": "polymer",
        "job_dir": lambda self, root: root / "md_jobs" / "legacy",
    })()

    assert routes_jobs._activity_source_path(job, ws) == "assemblies/polymer.nass"


def test_activity_source_path_refuses_ambiguous_assembly_name(tmp_path):
    for folder in ("a", "b"):
        path = tmp_path / folder
        path.mkdir()
        (path / "polymer.nass").write_text('{"metadata":{"name":"polymer"}}')
    job = type("LegacyJob", (), {
        "design_source_path": None,
        "project_id": "flat_assembly-id",
        "design_name": "polymer",
    })()

    assert routes_jobs._activity_source_path(job, tmp_path) is None
