"""Chain-completion INTEGRATION oracle — the *authored* chain in a real ``.nadoc``
drives to ``completed`` through the real API path.

Where the sibling files stop:

* ``test_md_chain_executor.py`` proves the PURE state machine (``step_chain``);
* ``test_chain_spawn_dispatch.py`` proves the engine ROUTING of one ``_chain_spawn``.

Neither runs the API-layer supervisor. This file does: it loads
``workspace/6hbx100_1xT.nadoc`` (which ships a 3-stage oxDNA chain-sim project:
relax -> production[field+surface] -> production[field+surface+anchors]), folds that
authored project into the ``POST /md/chains`` payload the frontend Launch would send,
then drives ``routes_md.advance_chains`` — the *actual* MD-supervisor tick — flipping
each stage's job to "completed" until the chain terminates.

The four engine job-CREATORS are stubbed (no real oxDNA), so this is FAST and headless,
but everything above them is the production path: ``create_md_chain`` validation, the
``MdPipeline`` build, ``advance_chains`` reconcile+spawn, workspace persistence, and
``_chain_job_status`` resolution. This closes the "does a whole chain actually finish"
gap (MV-33) at the integration layer, minus the binaries.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import routes_md
from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core import md_chain_executor as ce
from backend.core.models import Design

client = TestClient(app)

FIXTURE = Path(__file__).resolve().parents[1] / "workspace" / "6hbx100_1xT.nadoc"

# The fields a ChainSimStage contributes to the backend ChainStageRequest (drops the
# UI-only seed_job_name / seed_engine / id). Mirrors chain_sim_model.toChainStagePayload.
_STAGE_KEYS = (
    "engine", "protocol", "field", "anchors", "surface",
    "run_target", "cluster_name", "length_ns", "steps", "label", "seed_job_id",
)


def _stage_payload(stage) -> dict:
    d = stage.model_dump()
    return {k: d.get(k) for k in _STAGE_KEYS}


class _Spawns:
    """Records every stubbed spawn and hands out unique fake job ids.

    Substitutes for the real oxDNA job-creators so no simulation runs, while capturing
    the call order + parent seeding + carried forces the assertions check.
    """

    def __init__(self):
        self.calls: list[dict] = []   # {kind, parent, plan, unattended}
        self.status: dict[str, str] = {}   # job_id -> running/completed/failed
        self._n = 0

    def _new_job(self) -> str:
        jid = f"stub-job-{self._n}"
        self._n += 1
        self.status[jid] = "running"
        return jid

    async def fresh_relax(self, plan):
        jid = self._new_job()
        self.calls.append({"kind": "fresh_relax", "parent": None, "plan": plan, "job_id": jid,
                           "unattended": ce.in_unattended_chain_spawn()})
        return jid

    async def oxdna_child(self, parent, plan):
        jid = self._new_job()
        self.calls.append({"kind": "oxdna_child", "parent": parent, "plan": plan, "job_id": jid,
                           "unattended": ce.in_unattended_chain_spawn()})
        return jid

    def chain_job_status(self, job_id):
        return self.status.get(job_id, "running")

    def complete(self, job_id):
        self.status[job_id] = "completed"

    def fail(self, job_id):
        self.status[job_id] = "failed"


@pytest.fixture
def spawns(monkeypatch, tmp_path):
    """Redirect the chain workspace to tmp, stub the oxDNA creators, and route job-status
    through a controllable table. NAMD creators raise if hit (this chain is all-oxDNA —
    a call there would mean the engine routing regressed)."""
    s = _Spawns()
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_md, "_spawn_fresh_relax", s.fresh_relax)
    monkeypatch.setattr(routes_md, "_spawn_oxdna_child", s.oxdna_child)
    monkeypatch.setattr(routes_md, "_chain_job_status", s.chain_job_status)

    async def _no_namd(*a, **k):  # pragma: no cover - only fires on a routing regression
        raise AssertionError("all-oxDNA chain must not touch the NAMD spawn path")

    monkeypatch.setattr(routes_md, "spawn_md_production", _no_namd)
    monkeypatch.setattr(routes_md, "create_md_job", _no_namd)
    s.workspace = tmp_path
    return s


@pytest.fixture(autouse=True)
def _restore_design():
    yield
    design_state.set_design(_demo_design())


def _load_authored_chain_request():
    """The design + the ``CreateChainRequest`` its authored chain-sim project folds into.

    The fixture's single lineage (relax -> production -> production) is exactly the
    ``chainGroups`` "relax starts a rootless chain, each production appends" case, so it
    yields ONE rootless chain carrying all three stages in order."""
    design = Design.model_validate(json.loads(FIXTURE.read_text()))
    project = design.chain_sim_projects[0]
    stages = [_stage_payload(st) for st in project.stages]
    request = {
        "root_job_id": None,             # rootless: stage 0 CREATES the structure
        "root_engine": stages[0]["engine"],
        "design_source_path": str(FIXTURE),
        "stages": stages,
    }
    return design, project, request


def _tick(workspace) -> None:
    """One real MD-supervisor pass over every persisted chain."""
    asyncio.run(routes_md.advance_chains(Path(workspace)))


def _running_job(chain: dict) -> str | None:
    return next((s["job_id"] for s in chain["stages"] if s["status"] == "running"), None)


def _get_chain(chain_id: str) -> dict:
    r = client.get(f"/api/md/chains/{chain_id}")
    assert r.status_code == 200, r.text
    return r.json()["chain"]


# ── fixture sanity: the authored chain is what we think it is ────────────────────────

def test_fixture_ships_the_expected_three_stage_oxdna_chain():
    _, project, req = _load_authored_chain_request()
    kinds = [(s["engine"], s["protocol"]) for s in req["stages"]]
    assert kinds == [("oxdna", "relax"), ("oxdna", "production"), ("oxdna", "production")]
    # The two productions carry the field/surface the launch card echoes; the last also
    # pins anchors. (Guards the fixture — if it changes, the drive assertions would lie.)
    assert req["stages"][1]["field"] and req["stages"][1]["surface"]
    assert req["stages"][2]["field"] and req["stages"][2]["surface"] and req["stages"][2]["anchors"]


# ── the core property: the authored chain DRIVES TO COMPLETED ────────────────────────

def test_authored_chain_runs_all_stages_to_completed(spawns):
    design, _, request = _load_authored_chain_request()
    design_state.set_design(design)

    # Launch: create_md_chain builds the pipeline, persists it, and spawns stage 0
    # synchronously (its own advance_chains call) before returning.
    r = client.post("/api/md/chains", json=request)
    assert r.status_code == 200, r.text
    chain = r.json()["chain"]
    chain_id = chain["chain_id"]
    assert chain["status"] == "running"
    assert _running_job(chain) is not None          # stage 0 is live immediately

    # Drive the supervisor: complete the in-flight stage, tick, repeat. Bounded so a
    # regression that never converges fails loudly instead of hanging.
    for _ in range(10):
        chain = _get_chain(chain_id)
        if chain["status"] in ("completed", "failed"):
            break
        job = _running_job(chain)
        assert job is not None, f"no stage running yet chain not terminal: {chain}"
        spawns.complete(job)
        _tick(spawns.workspace)

    chain = _get_chain(chain_id)
    assert chain["status"] == ce.CHAIN_COMPLETED
    assert [s["status"] for s in chain["stages"]] == [ce.STAGE_DONE] * 3

    # Routing: stage 0 went through the fresh-relax creator, stages 1+2 through the
    # same-engine oxDNA child hop (never NAMD — the stubbed NAMD path would have raised).
    assert [c["kind"] for c in spawns.calls] == ["fresh_relax", "oxdna_child", "oxdna_child"]

    # Seeding: each production is seeded FROM THE PREVIOUS STAGE's realised job — the
    # chain property. (RED guard: not the root, not a later stage.)
    j0, j1, j2 = (c["job_id"] for c in spawns.calls)
    assert spawns.calls[1]["parent"] == j0
    assert spawns.calls[2]["parent"] == j1
    assert len({j0, j1, j2}) == 3                    # three distinct child jobs

    # Forces carried VERBATIM into each stage's spawn (Three-Layer Law: annotations,
    # not Design edits). Stage 1 = field+surface; stage 2 = field+surface+anchors.
    p1, p2 = spawns.calls[1]["plan"].forces, spawns.calls[2]["plan"].forces
    assert p1["field"] and p1["surface"] and not p1.get("anchors")
    assert p2["field"] and p2["surface"] and p2["anchors"]

    # design_source_path stamped onto the root create so the job lands in the per-design
    # engine list (the list filters on it — the MV-33 visibility fix).
    assert spawns.calls[0]["plan"].design_source_path == str(FIXTURE)

    # Every stage was spawned under the unattended-chain flag, so the per-engine
    # live-design guards stood down — a chain no longer dies when a different design is
    # loaded (the 6hbx100_1xT failure this whole path guards against).
    assert all(c["unattended"] for c in spawns.calls)


# ── up-front launch validation: a doomed chain is refused at Launch ──────────────────
# The automation that would have caught "the second job failed": a production stage with a
# field but nothing to hold it (no anchor, no opposing surface) is rejected by
# create_md_chain BEFORE any stage spawns — not left to run the relax then die at stage 1.

def test_launch_rejects_a_field_stage_with_nothing_to_hold_it(spawns):
    design, _, request = _load_authored_chain_request()
    design_state.set_design(design)
    request["stages"][1]["surface"] = None      # strip the opposing surface
    request["stages"][1]["anchors"] = None       # and it has no strand anchor
    r = client.post("/api/md/chains", json=request)
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "field" in detail and "stage 1" in detail
    # Nothing was spawned — the chain never started.
    assert not spawns.calls


def test_launch_accepts_the_real_deposition_chain(spawns):
    # The real file's stage 1 — a field pressing into an opposing surface, no strand
    # anchor — is a legal deposition setup and passes validation (would 400 before the fix).
    design, _, request = _load_authored_chain_request()
    design_state.set_design(design)
    r = client.post("/api/md/chains", json=request)
    assert r.status_code == 200, r.text


# ── the root-cause fix: the live-design guard stands down for a chain spawn ──────────
# The 6hbx100_1xT chain died because stage 1's oxDNA production spawn ran the interactive
# "is the loaded design current?" guard and 409'd (a different design was open). Under the
# unattended-chain flag that guard must stand down — the stage seeds from the parent job's
# own frozen state, not the loaded design.

def test_oxdna_design_guard_409s_interactively_but_stands_down_for_a_chain(monkeypatch):
    from fastapi import HTTPException

    from backend.api import routes_oxdna

    class _Job:
        def job_dir(self, ws):
            return Path("/nonexistent")

    # Force the "design differs" condition without needing a real job on disk.
    monkeypatch.setattr(routes_oxdna, "_job_is_out_of_date", lambda job, fp: True)
    monkeypatch.setattr(routes_oxdna, "_current_design_fingerprint", lambda: "live-fp")
    monkeypatch.setattr(routes_oxdna, "_load_snapshot_design", lambda pjd: None)
    design_state.set_design(_demo_design())

    # Interactive (default): the guard refuses with a 409.
    with pytest.raises(HTTPException) as ei:
        routes_oxdna._assert_job_current(_Job())
    assert ei.value.status_code == 409

    # Unattended chain spawn: the guard stands down — no raise.
    with ce.unattended_chain_spawn():
        routes_oxdna._assert_job_current(_Job())


def test_namd_design_guard_409s_interactively_but_stands_down_for_a_chain(monkeypatch):
    from fastapi import HTTPException

    from backend.api import routes_md
    from backend.core import oxdna_staleness

    monkeypatch.setattr(oxdna_staleness, "job_out_of_date", lambda a, b: True)
    monkeypatch.setattr(oxdna_staleness, "current_active_design_fingerprint", lambda: "live-fp")
    monkeypatch.setattr(routes_md, "_md_job_fingerprint", lambda job: "job-fp")
    monkeypatch.setattr(routes_md, "_md_snapshot_design", lambda job: None)
    design_state.set_design(_demo_design())

    with pytest.raises(HTTPException) as ei:
        routes_md._assert_md_job_current(object())
    assert ei.value.status_code == 409

    with ce.unattended_chain_spawn():
        routes_md._assert_md_job_current(object())


def test_unattended_flag_resets_after_the_context():
    assert ce.in_unattended_chain_spawn() is False
    with ce.unattended_chain_spawn():
        assert ce.in_unattended_chain_spawn() is True
    assert ce.in_unattended_chain_spawn() is False


# ── recovery: a mid-chain failure HALTS, and Resume drives it to completion ──────────

def test_mid_chain_failure_halts_then_resume_completes(spawns):
    design, _, request = _load_authored_chain_request()
    design_state.set_design(design)

    r = client.post("/api/md/chains", json=request)
    chain_id = r.json()["chain"]["chain_id"]

    # Stage 0 completes; stage 1 spawns then FAILS -> chain halts, stage 2 never spawns.
    chain = _get_chain(chain_id)
    spawns.complete(_running_job(chain))
    _tick(spawns.workspace)                          # stage 1 now running
    chain = _get_chain(chain_id)
    stage1_job = _running_job(chain)
    spawns.fail(stage1_job)
    _tick(spawns.workspace)

    chain = _get_chain(chain_id)
    assert chain["status"] == ce.CHAIN_FAILED
    assert chain["stages"][0]["status"] == ce.STAGE_DONE
    assert chain["stages"][1]["status"] == ce.STAGE_FAILED
    assert chain["stages"][2]["status"] == ce.STAGE_PENDING   # downstream never spawned
    spawns_at_halt = len(spawns.calls)               # fresh_relax + one oxdna_child

    # Resume: retry-only-failed re-spawns from stage 1 (stage 0 stays done, not re-run).
    r = client.post(f"/api/md/chains/{chain_id}/resume")
    assert r.status_code == 200, r.text
    chain = _get_chain(chain_id)
    assert chain["status"] == "running"
    assert chain["stages"][0]["status"] == ce.STAGE_DONE     # completed stage untouched

    # Drive the recovered chain to completion.
    for _ in range(10):
        chain = _get_chain(chain_id)
        if chain["status"] in ("completed", "failed"):
            break
        spawns.complete(_running_job(chain))
        _tick(spawns.workspace)

    chain = _get_chain(chain_id)
    assert chain["status"] == ce.CHAIN_COMPLETED
    assert [s["status"] for s in chain["stages"]] == [ce.STAGE_DONE] * 3
    # Resume re-spawned only stage 1 + then stage 2: stage 0 was never handed to a
    # creator a second time.
    assert [c["kind"] for c in spawns.calls] == [
        "fresh_relax", "oxdna_child", "oxdna_child", "oxdna_child"]
    assert len(spawns.calls) == spawns_at_halt + 2


# ── the real thing: a full chain through the REAL spawn path (mock oxDNA binary) ──────
# The unit e2e above STUBS the four job-creators, so it proves the state machine but NOT
# that a stage's real spawn (create_oxdna_job / append_oxdna_run) actually succeeds — the
# gap that let "the second job failed" slip through. This test drives the REAL create ->
# relax -> seed -> append -> append -> completion orchestration on the real design, mocking
# only the oxDNA BINARY (a fake runner that carries the configuration forward), so every
# spawn precondition, seed resolution, force-file write, and file copy is exercised for real.

@pytest.mark.slow
def test_full_chain_runs_end_to_end_with_a_mock_binary(tmp_path, monkeypatch):
    import shutil

    from backend.api import routes_oxdna
    from backend.core import oxdna_runner as r
    from backend.core.oxdna_health import OxdnaHealthResult
    from backend.core.oxdna_job import OxdnaJob, OxdnaStatus

    # Point every module's workspace at tmp.
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)

    # Mock the oxDNA binary + analysis + health so the REAL orchestration runs fast.
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda *a, **k: "/fake/oxDNA")
    monkeypatch.setattr(routes_oxdna, "oxdna_supports_cuda", lambda *a, **k: True)
    monkeypatch.setattr(r, "find_oxdna", lambda *a, **k: "/fake/oxDNA")
    monkeypatch.setattr(r, "find_dnanalysis", lambda *a, **k: None)
    monkeypatch.setattr(
        r, "run_oxdna_health_check",
        lambda *a, **k: OxdnaHealthResult(passed=True, bp_retained_fraction=0.95,
                                          potential_energy=-1.3, fene_safe=True))

    def _conf_file_from_input(input_path):
        for line in Path(input_path).read_text().splitlines():
            s = line.strip()
            if s.startswith("conf_file"):
                return s.split("=", 1)[1].strip()
        return None

    async def fake_run(oxdna_bin, input_path, stage_dir, log_path, job_id, on_spawn=None):
        # Carry the starting configuration forward as the "relaxed" last_conf so downstream
        # seed resolution + wall/anchor placement (which READ the conf) work on real coords.
        if on_spawn:
            on_spawn(4242)
        stage_dir = Path(stage_dir)
        conf = _conf_file_from_input(input_path)
        candidates = []
        if conf:
            p = Path(conf)
            candidates = [p, stage_dir / p.name, stage_dir.parent / p.name]
        src = next((c for c in candidates if c.exists()), None)
        if src is not None:
            shutil.copy(src, stage_dir / "last_conf.dat")
        else:
            (stage_dir / "last_conf.dat").write_text("t = 0\nb = 100 100 100\nE = 0 0 0\n")
        (stage_dir / "energy.dat").write_text("0 -1.3 0.3 -1.0\n")
        Path(log_path).write_text("INFO: END OF THE SIMULATION, everything went OK!\n")
        return 0, 4242

    monkeypatch.setattr(r, "_run_oxdna_async", fake_run)

    design, _, request = _load_authored_chain_request()
    design_state.set_design(design)

    resp = client.post("/api/md/chains", json=request)
    assert resp.status_code == 200, resp.text
    chain_id = resp.json()["chain"]["chain_id"]

    def _drain():
        # Join every running oxDNA runner thread (mock → fast) so the stage's job is
        # completed on disk before the next supervisor tick reconciles it.
        for handle in list(r._RUNNING.values()):
            handle.thread.join(timeout=60)

    # Drive: drain the running stage, tick the supervisor (which spawns the next), repeat.
    for _ in range(12):
        _drain()
        asyncio.run(routes_md.advance_chains(tmp_path))
        chain = _get_chain(chain_id)
        if chain["status"] in ("completed", "failed"):
            break
    _drain()

    chain = _get_chain(chain_id)
    assert chain["status"] == ce.CHAIN_COMPLETED, chain.get("error")
    assert [s["status"] for s in chain["stages"]] == [ce.STAGE_DONE] * 3
    # Three REAL oxDNA jobs were created and each completed on disk.
    job_ids = [s["job_id"] for s in chain["stages"]]
    assert all(job_ids) and len(set(job_ids)) == 3
    for jid in job_ids:
        assert OxdnaJob.load(jid, tmp_path).status == OxdnaStatus.completed
