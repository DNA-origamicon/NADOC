"""Unit + route tests for the unified simulation job list (backend/core/sim_jobs +
GET /api/simulate/jobs).

The pure normalization/merge/filter is the meat (testable without a workspace); a light
route test drives the HTTP layer with monkeypatched engine job lists.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core import sim_jobs

client = TestClient(app)


# ── pure normalization ────────────────────────────────────────────────────────


def _ox(**kw) -> dict:
    base = {
        "job_id": "ox1",
        "design_name": "d",
        "status": "completed",
        "created_at": 1.0,
        "n_nucleotides": 100,
        "parent_job_id": None,
        "stages": [],
        "design_source_path": "/w/d.nadoc",
        "out_of_date": False,
        "size_bytes": 10,
    }
    base.update(kw)
    return base


def _lm(**kw) -> dict:
    base = {
        "job_id": "lm1",
        "design_name": "d",
        "status": "completed",
        "created_at": 2.0,
        "n_atoms": 200,
        "frames": 5,
        "design_source_path": "/w/d.nadoc",
        "size_bytes": 20,
    }
    base.update(kw)
    return base


def test_normalize_oxdna_root_relax():
    n = sim_jobs.normalize_oxdna_job(_ox())
    assert n["engine"] == "oxdna"
    assert n["kind"] == "relax" and n["is_child"] is False
    assert n["production_state"] == "none"
    assert n["n_units"] == 100
    # passthrough fields kept so frontend label fns work on the node verbatim
    assert n["design_source_path"] == "/w/d.nadoc" and n["out_of_date"] is False


def test_normalize_oxdna_child_run_is_indented_and_kind_run():
    n = sim_jobs.normalize_oxdna_job(_ox(job_id="ox2", parent_job_id="ox1"))
    assert n["kind"] == "run" and n["is_child"] is True


def test_normalize_oxdna_production_state_reflects_latest_production():
    stages = [
        {"kind": "production", "status": "done"},
        {"kind": "production", "status": "running"},
    ]
    assert (
        sim_jobs.normalize_oxdna_job(_ox(stages=stages))["production_state"]
        == "running"
    )


def test_normalize_oxdna_viewable_once_a_stage_started():
    assert (
        sim_jobs.normalize_oxdna_job(_ox(stages=[{"kind": "mc", "status": "done"}]))[
            "viewable"
        ]
        is True
    )
    assert (
        sim_jobs.normalize_oxdna_job(_ox(stages=[{"kind": "mc", "status": "pending"}]))[
            "viewable"
        ]
        is False
    )


def test_normalize_lammps_is_flat_root():
    n = sim_jobs.normalize_lammps_job(_lm())
    assert n["engine"] == "lammps"
    assert n["kind"] == "lammps" and n["is_child"] is False
    assert n["production_state"] is None
    assert n["n_units"] == 200
    assert n["viewable"] is True  # completed + frames>0


def test_normalize_lammps_not_viewable_while_active_or_frameless():
    assert sim_jobs.normalize_lammps_job(_lm(status="running"))["viewable"] is False
    assert sim_jobs.normalize_lammps_job(_lm(frames=0))["viewable"] is False


# ── mrDNA / CanDo / NAMD normalization (full-consolidation: one cross-engine list) ──


def test_normalize_mrdna_is_flat_root():
    n = sim_jobs.normalize_mrdna_job(_ox(job_id="mr1", n_nucleotides=64))
    assert n["engine"] == "mrdna"
    assert n["kind"] == "relax" and n["is_child"] is False
    assert n["production_state"] is None
    assert n["n_units"] == 64
    assert n["design_source_path"] == "/w/d.nadoc"  # passthrough kept


def test_normalize_cando_is_flat_root():
    n = sim_jobs.normalize_cando_job(_ox(job_id="cd1"))
    assert n["engine"] == "cando"
    assert n["kind"] == "relax" and n["is_child"] is False
    assert n["production_state"] is None


def test_normalize_md_root_and_child():
    root = sim_jobs.normalize_md_job(_ox(job_id="md1", parent_job_id=None))
    child = sim_jobs.normalize_md_job(_ox(job_id="md2", parent_job_id="md1"))
    assert root["engine"] == "namd"
    assert root["kind"] == "relax" and root["is_child"] is False
    assert child["kind"] == "run" and child["is_child"] is True


def test_normalize_viewable_only_when_completed():
    assert sim_jobs.normalize_mrdna_job(_ox(status="completed"))["viewable"] is True
    assert sim_jobs.normalize_cando_job(_ox(status="running"))["viewable"] is False
    assert sim_jobs.normalize_md_job(_ox(status="failed"))["viewable"] is False


# ── path filter (mirrors frontend filterJobsForPart / normalizeWorkspacePath) ──


def test_filter_matches_normalized_path():
    nodes = [
        sim_jobs.normalize_oxdna_job(_ox()),
        sim_jobs.normalize_lammps_job(_lm(design_source_path="/other.nadoc")),
    ]
    kept = sim_jobs.filter_nodes(nodes, "/w/d.nadoc", show_all=False)
    assert [n["job_id"] for n in kept] == ["ox1"]


def test_filter_backslash_and_trailing_slash_normalized():
    n = sim_jobs.normalize_oxdna_job(_ox(design_source_path="C:\\w\\d.nadoc"))
    assert sim_jobs.filter_nodes([n], "C:/w/d.nadoc/", show_all=False)


def test_filter_workspace_prefixed_open_path_matches_historical_job_path():
    n = sim_jobs.normalize_oxdna_job(_ox(design_source_path="VoltronCoreArm.nadoc"))
    assert sim_jobs.filter_nodes(
        [n], "workspace/VoltronCoreArm.nadoc", show_all=False
    )
    assert sim_jobs.filter_nodes(
        [n], "/home/user/NADOC/workspace/VoltronCoreArm.nadoc", show_all=False
    )


def test_filter_no_path_shows_nothing_unless_show_all():
    nodes = [sim_jobs.normalize_oxdna_job(_ox())]
    assert sim_jobs.filter_nodes(nodes, None, show_all=False) == []
    assert sim_jobs.filter_nodes(nodes, None, show_all=True) == nodes


# ── route ─────────────────────────────────────────────────────────────────────


def test_simulate_jobs_route_merges_and_filters(monkeypatch):
    """oxDNA + LAMMPS jobs merge into one filtered node list; each carries its overlay."""
    from backend.core.lammps_job import new_lammps_job
    from backend.core.oxdna_job import new_oxdna_job

    ox = new_oxdna_job("d", [], n_nucleotides=100, design_source_path="/w/d.nadoc")
    ox.status = ox.status.__class__("completed")
    lm = new_lammps_job("d", n_atoms=200, design_source_path="/w/d.nadoc")
    lm.status = lm.status.__class__("completed")
    lm.frames = 5
    other = new_lammps_job("e", n_atoms=50, design_source_path="/w/e.nadoc")

    import backend.core.oxdna_job as oxj
    import backend.core.lammps_job as lmj

    monkeypatch.setattr(oxj.OxdnaJob, "list_jobs", classmethod(lambda cls, ws: [ox]))
    monkeypatch.setattr(
        lmj.LammpsJob, "list_jobs", classmethod(lambda cls, ws: [lm, other])
    )

    r = client.get("/api/simulate/jobs", params={"design_source_path": "/w/d.nadoc"})
    assert r.status_code == 200
    nodes = r.json()
    by_engine = {n["engine"] for n in nodes}
    assert by_engine == {"oxdna", "lammps"}  # merged
    assert all(n["design_source_path"] == "/w/d.nadoc" for n in nodes)  # filtered
    ox_node = next(n for n in nodes if n["engine"] == "oxdna")
    lm_node = next(n for n in nodes if n["engine"] == "lammps")
    assert "out_of_date" in ox_node and "size_bytes" in ox_node
    assert lm_node["viewable"] is True and lm_node["kind"] == "lammps"


def test_simulate_jobs_route_includes_all_four_engines(monkeypatch):
    """The unified list folds in mrDNA + CanDo + NAMD too, each design-filtered, each
    isolated so one failing engine list doesn't drop the others."""
    import backend.api.routes_cando as rc
    import backend.api.routes_md as rmd
    import backend.api.routes_mrdna as rmr
    import backend.core.lammps_job as lmj
    import backend.core.oxdna_job as oxj

    monkeypatch.setattr(oxj.OxdnaJob, "list_jobs", classmethod(lambda cls, ws: []))
    monkeypatch.setattr(lmj.LammpsJob, "list_jobs", classmethod(lambda cls, ws: []))

    async def _mr():
        return [_ox(job_id="mr1", n_nucleotides=64)]

    async def _cd():
        return [_ox(job_id="cd1")]

    async def _md():
        return [_ox(job_id="md1"), _ox(job_id="md2", parent_job_id="md1")]

    monkeypatch.setattr(rmr, "list_mrdna_jobs", _mr)
    monkeypatch.setattr(rc, "list_cando_jobs", _cd)
    monkeypatch.setattr(rmd, "list_md_jobs", _md)

    r = client.get("/api/simulate/jobs", params={"design_source_path": "/w/d.nadoc"})
    assert r.status_code == 200
    nodes = r.json()
    assert {n["engine"] for n in nodes} == {"mrdna", "cando", "namd"}
    md_child = next(n for n in nodes if n["job_id"] == "md2")
    assert md_child["is_child"] is True and md_child["kind"] == "run"


def test_simulate_jobs_route_one_engine_failing_keeps_others(monkeypatch):
    import backend.api.routes_md as rmd
    import backend.core.lammps_job as lmj
    import backend.core.oxdna_job as oxj

    monkeypatch.setattr(oxj.OxdnaJob, "list_jobs", classmethod(lambda cls, ws: []))
    monkeypatch.setattr(lmj.LammpsJob, "list_jobs", classmethod(lambda cls, ws: []))

    async def _boom():
        raise RuntimeError("mrdna list broke")

    async def _md():
        return [_ox(job_id="md1")]

    import backend.api.routes_mrdna as rmr

    monkeypatch.setattr(rmr, "list_mrdna_jobs", _boom)
    monkeypatch.setattr(rmd, "list_md_jobs", _md)

    r = client.get("/api/simulate/jobs", params={"design_source_path": "/w/d.nadoc"})
    assert r.status_code == 200
    assert {n["engine"] for n in r.json()} == {"namd"}
