"""P2 CHAIN oracle — the chain EXECUTOR advances / halts / resumes correctly.

Bright line (Track P): a stage runs SEEDED FROM the previous stage's output; on a stage
FAILURE the chain HALTS and RESUMES from the failed stage (retry-only-failed) — never
"a panel renders" / "a button exists".  Engine-agnostic: the spawn + status callbacks are
mocked, so this whole file is FAST and headless.  RED-verified offline (see the LITERAL
parent-id guards in ``test_advances_seeded_from_predecessor`` /
``test_resume_reruns_only_the_failed_stage``).
"""

from __future__ import annotations

from backend.core import md_chain_executor as ce
from backend.core.md_pipeline import MdPipeline, PipelineStage


def _pipeline(
    n: int, *, root_job_id: str = "root", engine: str = "namd", **stage_kw
) -> MdPipeline:
    stages = [
        PipelineStage(engine=engine, protocol="production", **stage_kw)
        for _ in range(n)
    ]
    return MdPipeline(stages=stages, root_job_id=root_job_id, root_engine=engine)


class _Harness:
    """Drives a chain with a recording spawner + a controllable job-status table."""

    def __init__(self, chain: ce.ChainRun):
        self.chain = chain
        self.job_status: dict[str, str] = {}  # job_id -> running/completed/failed
        self.spawns: list[ce.SpawnContext] = []

    def _spawn(self, ctx: ce.SpawnContext) -> str:
        self.spawns.append(ctx)
        job_id = f"job{ctx.stage_index}"
        self.job_status[job_id] = "running"
        return job_id

    def _status(self, job_id: str) -> str:
        return self.job_status.get(job_id, "running")

    def step(self) -> ce.ChainRun:
        return ce.step_chain(self.chain, job_status=self._status, spawn=self._spawn)

    def complete(self, job_id: str) -> None:
        self.job_status[job_id] = "completed"

    def fail(self, job_id: str) -> None:
        self.job_status[job_id] = "failed"


def _harness(n: int, **kw) -> _Harness:
    return _Harness(ce.init_chain_run(_pipeline(n, **kw), chain_id="c1"))


# ── init / structure ─────────────────────────────────────────────────────────────


def test_init_builds_a_pending_stage_per_pipeline_stage():
    chain = ce.init_chain_run(_pipeline(3), chain_id="c1")
    assert chain.status == ce.CHAIN_PENDING
    assert [s.status for s in chain.stages] == [ce.STAGE_PENDING] * 3
    assert [s.index for s in chain.stages] == [0, 1, 2]
    assert len(chain.plan) == 3
    assert chain.root_job_id == "root"


# ── the core CHAIN property: seeded from the predecessor ─────────────────────────


def test_advances_seeded_from_predecessor():
    h = _harness(3)

    # Stage 0 spawns first, seeded from the ROOT job.
    h.step()
    assert len(h.spawns) == 1
    assert h.spawns[0].stage_index == 0
    assert h.spawns[0].parent_job_id == "root"  # RED: not a later stage's job
    assert h.chain.stages[0].status == ce.STAGE_RUNNING
    assert h.chain.status == ce.CHAIN_RUNNING

    # While stage 0 runs, stepping is a no-op (one stage in flight at a time).
    h.step()
    assert len(h.spawns) == 1

    # Stage 0 completes -> stage 1 spawns SEEDED FROM STAGE 0's job (not the root).
    h.complete("job0")
    h.step()
    assert h.chain.stages[0].status == ce.STAGE_DONE
    assert len(h.spawns) == 2
    assert h.spawns[1].stage_index == 1
    assert h.spawns[1].parent_job_id == "job0"  # RED guard: predecessor, not "root"

    # Stage 1 completes -> stage 2 spawns seeded from stage 1.
    h.complete("job1")
    h.step()
    assert h.spawns[2].parent_job_id == "job1"

    # Stage 2 completes -> chain COMPLETED, nothing more spawned.
    h.complete("job2")
    h.step()
    assert h.chain.status == ce.CHAIN_COMPLETED
    assert len(h.spawns) == 3


def test_single_stage_chain_completes_with_one_spawn():
    h = _harness(1)
    h.step()
    assert len(h.spawns) == 1
    assert h.spawns[0].parent_job_id == "root"
    h.complete("job0")
    h.step()
    assert h.chain.status == ce.CHAIN_COMPLETED
    assert len(h.spawns) == 1


def test_running_stage_blocks_the_next_spawn():
    h = _harness(2)
    h.step()  # stage 0 running
    for _ in range(3):
        h.step()  # job0 still "running"
    assert len(h.spawns) == 1
    assert h.chain.status == ce.CHAIN_RUNNING


# ── halt on failure ──────────────────────────────────────────────────────────────


def test_halts_on_stage_failure_without_spawning_downstream():
    h = _harness(3)
    h.step()  # stage 0 running
    h.complete("job0")
    h.step()  # stage 1 running
    assert len(h.spawns) == 2

    h.fail("job1")
    h.step()
    assert h.chain.status == ce.CHAIN_FAILED
    assert h.chain.stages[1].status == ce.STAGE_FAILED
    assert h.chain.stages[0].status == ce.STAGE_DONE
    assert h.chain.failed_stage_index() == 1
    assert h.chain.error and "stage 1" in h.chain.error
    # Stage 2 was NEVER spawned.
    assert len(h.spawns) == 2

    # A terminal (failed) chain is inert: stepping does nothing.
    h.step()
    assert len(h.spawns) == 2


# ── resume from the failed stage (retry-only-failed) ─────────────────────────────


def test_resume_reruns_only_the_failed_stage():
    h = _harness(3)
    h.step()
    h.complete("job0")
    h.step()  # stage 1 running
    stage0_job = h.chain.stages[0].job_id
    h.fail("job1")
    h.step()  # HALTED at stage 1
    assert h.chain.status == ce.CHAIN_FAILED

    ce.resume_chain(h.chain)
    assert h.chain.status == ce.CHAIN_RUNNING
    assert h.chain.error is None
    # Completed stage 0 is untouched: same job, still done — NOT reset to pending.
    assert h.chain.stages[0].status == ce.STAGE_DONE
    assert h.chain.stages[0].job_id == stage0_job == "job0"
    # The failed stage is pending again with no stale job id.
    assert h.chain.stages[1].status == ce.STAGE_PENDING
    assert h.chain.stages[1].job_id is None

    spawns_before = len(h.spawns)
    h.step()  # re-spawn ONLY stage 1
    assert len(h.spawns) == spawns_before + 1
    assert h.spawns[-1].stage_index == 1
    assert (
        h.spawns[-1].parent_job_id == "job0"
    )  # RED: stage 0 not re-run, still the seed
    # Stage 0 was never handed to the spawner a second time.
    assert [c.stage_index for c in h.spawns] == [0, 1, 1]

    # Finish the chain from the recovered point.
    h.complete("job1")
    h.step()  # stage 2
    h.complete("job2")
    h.step()
    assert h.chain.status == ce.CHAIN_COMPLETED


def test_resume_is_a_noop_on_a_non_failed_chain():
    h = _harness(2)
    h.step()
    before = h.chain.to_dict()
    ce.resume_chain(h.chain)  # chain is RUNNING, not FAILED
    assert h.chain.to_dict() == before


# ── forces carry into the child conf via the SHARED emitter ──────────────────────


def test_stage_forces_carry_into_spawn_context():
    field = {"field_pN": 5.0, "dir": [1.0, 0.0, 0.0]}
    anchors = [{"scope": "base", "helix_id": 0, "bp_index": 0}]
    h = _harness(1, field=field, anchors=anchors)
    h.step()
    ctx = h.spawns[0]
    assert ctx.forces["field"] == field
    assert ctx.forces["anchors"] == anchors
    assert ctx.forces["surface"] is None


def test_stage_forces_conf_reuses_external_forces_block():
    from backend.core import md_protocols

    field = {"field_pN": 5.0, "dir": [0.0, 1.0, 0.0]}
    # A field-carrying stage emits an eField directive — identical to the shared emitter.
    conf = ce.stage_forces_conf({"field": field, "anchors": None, "surface": None})
    assert "eField" in conf
    assert conf == md_protocols.external_forces_block(None, field)

    # Anchors reach the conf as the fixedAtoms marker (given the restraints file name).
    anch = ce.stage_forces_conf({"field": None}, anchors_file="restraints_anchors.pdb")
    assert "fixedAtomsFile     restraints_anchors.pdb" in anch
    assert anch == md_protocols.external_forces_block("restraints_anchors.pdb", None)

    # No forces -> no directives.
    assert ce.stage_forces_conf(None) == ""
    assert ce.stage_forces_conf({}) == ""


# ── failure diagnosis (the shared brain behind scripts/chain_doctor.py) ──────────


def test_diagnose_healthy_chain_has_no_cause_or_action():
    h = _harness(2)
    h.step()  # stage 0 running, chain running
    dx = ce.diagnose_chain(h.chain)
    assert dx["status"] == ce.CHAIN_RUNNING
    assert dx["cause"] is None and dx["action"] is None
    assert dx["error"] is None


def test_diagnose_completed_chain():
    h = _harness(1)
    h.step()
    h.complete("job0")
    h.step()
    dx = ce.diagnose_chain(h.chain)
    assert dx["status"] == ce.CHAIN_COMPLETED
    assert "complete" in dx["headline"].lower()
    assert dx["cause"] is None


def test_diagnose_classifies_the_design_mismatch_spawn_failure():
    # The REAL 6hbx100_1xT failure: stage 1 could not spawn because a different design
    # was loaded. A spawn failure has NO job on the failed stage.
    h = _harness(3)
    h.step()
    h.chain.status = ce.CHAIN_FAILED
    h.chain.stages[1].status = ce.STAGE_FAILED
    h.chain.error = (
        "stage 1 spawn failed after 3 attempts: 409: A different design is "
        "loaded: the app currently has 'Bundle' ..."
    )
    dx = ce.diagnose_chain(h.chain)
    assert dx["failed_index"] == 1
    assert dx["failed_job_id"] is None  # spawn failure — no job realised
    assert "different design" in dx["cause"].lower()
    assert "resume" in dx["action"].lower()


def test_diagnose_classifies_the_field_without_anchor_spawn_failure():
    h = _harness(2)
    h.chain.status = ce.CHAIN_FAILED
    h.chain.stages[1].status = ce.STAGE_FAILED
    h.chain.error = (
        "stage 1 spawn failed after 3 attempts: 400: An electric field needs "
        "≥1 anchor OR a hard surface it pushes into"
    )
    dx = ce.diagnose_chain(h.chain)
    assert "field" in dx["cause"].lower() and "hold" in dx["cause"].lower()
    assert "anchor" in dx["action"].lower() or "surface" in dx["action"].lower()


def test_diagnose_missing_seed_checkpoint_is_a_retry():
    h = _harness(2)
    h.chain.status = ce.CHAIN_FAILED
    h.chain.stages[0].status = ce.STAGE_FAILED
    h.chain.error = "stage 0 spawn failed: FileNotFoundError: no such file seed.dat"
    dx = ce.diagnose_chain(h.chain)
    assert "seed" in dx["cause"].lower() or "checkpoint" in dx["cause"].lower()
    assert "retry" in dx["action"].lower()


def test_diagnose_job_failure_points_at_the_jobs_log():
    # A stage that SPAWNED a job which then failed — the failed stage keeps its job_id,
    # so the diagnosis routes the user to that job's log (not a spawn-error classifier).
    h = _harness(2)
    h.step()  # stage 0 running with job0
    h.fail("job0")
    h.step()  # reconcile -> chain failed, stage 0 keeps job0
    dx = ce.diagnose_chain(h.chain)
    assert dx["failed_index"] == 0
    assert dx["failed_job_id"] == "job0"
    assert "job0" in dx["cause"] and "job0" in dx["action"]


def test_diagnose_unknown_spawn_error_falls_back_to_generic_resume():
    h = _harness(1)
    h.chain.status = ce.CHAIN_FAILED
    h.chain.stages[0].status = ce.STAGE_FAILED
    h.chain.error = "stage 0 spawn failed: something nobody has a pattern for"
    dx = ce.diagnose_chain(h.chain)
    assert dx["cause"] and dx["action"]
    assert "resume" in dx["action"].lower()


# ── persistence ──────────────────────────────────────────────────────────────────


def test_chain_run_dict_roundtrip_preserves_state_and_plan():
    h = _harness(2)
    h.step()
    h.complete("job0")
    h.step()  # stage 0 done, stage 1 running
    restored = ce.ChainRun.from_dict(h.chain.to_dict())
    assert restored.chain_id == h.chain.chain_id
    assert restored.status == h.chain.status
    assert [s.to_dict() for s in restored.stages] == [
        s.to_dict() for s in h.chain.stages
    ]
    assert [p.to_dict() for p in restored.plan] == [p.to_dict() for p in h.chain.plan]


def test_save_load_list_chain(tmp_path):
    h = _harness(2)
    h.step()
    ce.save_chain(h.chain, tmp_path)
    loaded = ce.load_chain("c1", tmp_path)
    assert loaded.to_dict() == h.chain.to_dict()
    listed = ce.list_chains(tmp_path)
    assert [c.chain_id for c in listed] == ["c1"]


def test_list_chains_empty_workspace(tmp_path):
    assert ce.list_chains(tmp_path) == []
