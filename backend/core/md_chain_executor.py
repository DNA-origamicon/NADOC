"""
MD chain EXECUTOR (P2) — runs an :class:`MdPipeline`'s stages back-to-back unattended.

P1 (:mod:`backend.core.md_pipeline`) gave the DATA MODEL (``MdPipeline`` / ``StagePlan``)
plus a pure builder.  This module is the CONTROLLER that turns a resolved plan into a
live, self-advancing chain:

* spawn stage 0 (seeded from the pipeline's root job checkpoint);
* on each stage's COMPLETION, spawn the next stage seeded from the completed stage's
  output (``StagePlan``'s ``stageN-1::output`` reference resolves to the previous stage's
  real child job);
* on any stage FAILURE, HALT the chain (do NOT spawn downstream).  A halted chain is
  RESUMABLE from the failed stage: :func:`resume_chain` re-runs only the failed stage and
  its descendants, never the stages that already completed (retry-only-failed).

**Engine-agnostic.**  The only engine touch-points are two INJECTED callbacks:

* ``spawn(ctx: SpawnContext) -> job_id`` — create + start a child job for a stage;
* ``job_status(job_id) -> "running" | "completed" | "failed"`` — poll a spawned job.

The NAMD wiring (``namd_chain_spawn`` / ``namd_chain_job_status`` / ``advance_chains`` in
:mod:`backend.api.routes_md`, driven by the MD supervisor loop) lives in the API layer so
``backend/core`` stays free of any ``backend/api`` import; the tests inject mocks.  The
sync primitives (:func:`reconcile_running`, :func:`next_spawn`, :func:`mark_spawned`) let
the async driver interleave an ``await``-ed spawn between two pure state transitions;
:func:`step_chain` composes them for a synchronous driver / the oracle.

**Three-Layer Law.**  A stage's forces (field / anchors / surface) are job-request
annotations carried VERBATIM from the pipeline spec into the child job's conf via the
shared :func:`backend.core.md_protocols.external_forces_block` emitter
(:func:`stage_forces_conf`) — never a ``Design`` edit.
"""

from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from backend.core import md_protocols
from backend.core.md_ensemble import _DEFAULT_BASE_SEED
from backend.core.md_pipeline import (
    MdPipeline,
    StagePlan,
    build_pipeline_plan,
    default_stage_id,
)

# ── status vocabularies ─────────────────────────────────────────────────────────
# Stage-level.
STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_DONE = "done"
STAGE_FAILED = "failed"

# Chain-level.
CHAIN_PENDING = "pending"
CHAIN_RUNNING = "running"
CHAIN_COMPLETED = "completed"
CHAIN_FAILED = "failed"

_CHAIN_TERMINAL = (CHAIN_COMPLETED, CHAIN_FAILED)


# ── unattended-spawn ambient flag ─────────────────────────────────────────────────
# The per-engine "is the loaded design current?" guards (routes_oxdna._assert_job_current
# / routes_md._assert_md_job_current) refuse a production/append when the app's LIVE
# active design differs from the job's — the interactive UX guard ("open the right design
# first").  But the UNATTENDED chain supervisor spawns a stage's child from the parent
# job's OWN frozen snapshot + the stage's explicit forces; the loaded design is irrelevant
# to it.  Without a way to say "this spawn isn't a user gesture", switching designs while a
# chain runs halts it (the 6hbx100_1xT failure).  The supervisor sets this flag around each
# spawn; the guards consult it and stand down.  A ContextVar (not a global) so it is scoped
# to the awaiting task and never leaks across concurrent work.
_unattended_chain_spawn: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "unattended_chain_spawn", default=False)


def in_unattended_chain_spawn() -> bool:
    """True while a stage's child is being spawned by the unattended chain supervisor
    (so the interactive live-design currentness guards should stand down)."""
    return _unattended_chain_spawn.get()


@contextmanager
def unattended_chain_spawn():
    """Mark the enclosed (supervisor-driven) spawn as unattended, so the live-design
    guards skip their interactive "loaded design must match" check."""
    token = _unattended_chain_spawn.set(True)
    try:
        yield
    finally:
        _unattended_chain_spawn.reset(token)


@dataclass
class StageState:
    """Live state of one chain stage: which job realises it and where it stands."""

    index: int
    stage_id: str
    engine: str
    status: str = STAGE_PENDING
    job_id: Optional[str] = None
    # How many times the driver has tried (and failed) to spawn this stage's child.
    # A transient spawn failure retries on the next supervisor tick; the driver halts the
    # chain only once this crosses its retry cap (see routes_md.advance_chains).
    spawn_attempts: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StageState":
        return cls(**data)


@dataclass
class SpawnContext:
    """Everything a spawner needs to realise a stage as a child job.

    ``parent_job_id`` is the RESOLVED real job this stage seeds from — the chain's root
    job for stage 0, else the previous stage's realised child job id (its output
    checkpoint is what the child restarts from).  ``forces`` is the stage's
    field/anchors/surface bundle, carried verbatim from the pipeline spec.
    """

    stage_index: int
    plan: StagePlan
    parent_job_id: Optional[str]
    forces: dict


@dataclass
class ChainRun:
    """A live pipeline run: the resolved plan plus each stage's realisation state."""

    chain_id: str
    stages: list[StageState] = field(default_factory=list)
    plan: list[StagePlan] = field(default_factory=list)
    root_job_id: Optional[str] = None
    root_checkpoint: Optional[str] = None
    status: str = CHAIN_PENDING
    error: Optional[str] = None

    def failed_stage_index(self) -> Optional[int]:
        """Index of the first failed stage (``None`` if none)."""
        for s in self.stages:
            if s.status == STAGE_FAILED:
                return s.index
        return None

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "status": self.status,
            "error": self.error,
            "root_job_id": self.root_job_id,
            "root_checkpoint": self.root_checkpoint,
            "stages": [s.to_dict() for s in self.stages],
            "plan": [p.to_dict() for p in self.plan],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChainRun":
        return cls(
            chain_id=data["chain_id"],
            status=data.get("status", CHAIN_PENDING),
            error=data.get("error"),
            root_job_id=data.get("root_job_id"),
            root_checkpoint=data.get("root_checkpoint"),
            stages=[StageState.from_dict(s) for s in data.get("stages", [])],
            plan=[StagePlan(**p) for p in data.get("plan", [])],
        )


def init_chain_run(
    pipeline: MdPipeline,
    *,
    chain_id: str,
    root_checkpoint: Optional[str] = None,
    base_seed: int = _DEFAULT_BASE_SEED,
    stage_id_for: Callable[[int], str] = default_stage_id,
) -> ChainRun:
    """Resolve ``pipeline`` (via P1's :func:`build_pipeline_plan`) into a fresh chain.

    Every stage starts ``pending``; the chain starts ``pending``.  No jobs are created —
    the first :func:`step_chain` spawns stage 0.
    """
    plan = build_pipeline_plan(
        pipeline,
        root_checkpoint=root_checkpoint,
        base_seed=base_seed,
        stage_id_for=stage_id_for,
    )
    stages = [
        StageState(index=p.index, stage_id=p.stage_id, engine=p.engine) for p in plan
    ]
    return ChainRun(
        chain_id=chain_id,
        stages=stages,
        plan=plan,
        root_job_id=pipeline.root_job_id,
        root_checkpoint=root_checkpoint,
        status=CHAIN_PENDING,
    )


# ── advance primitives (used by the async driver AND step_chain) ─────────────────

def reconcile_running(chain: ChainRun, job_status: Callable[[str], str]) -> ChainRun:
    """Fold the currently-running stage's job status into the chain state.

    A completed stage becomes ``done`` (the run loop then spawns the next); a failed
    stage HALTS the chain (``CHAIN_FAILED``) so no downstream stage is spawned.  A
    still-running stage is left in place.  No-op on a terminal chain.
    """
    if chain.status in _CHAIN_TERMINAL:
        return chain
    running = next((s for s in chain.stages if s.status == STAGE_RUNNING), None)
    if running is None:
        return chain
    st = job_status(running.job_id)
    if st == "completed":
        running.status = STAGE_DONE
    elif st == "failed":
        running.status = STAGE_FAILED
        chain.status = CHAIN_FAILED
        chain.error = f"stage {running.index} ({running.engine}) failed"
    else:
        chain.status = CHAIN_RUNNING
    return chain


def next_spawn(chain: ChainRun) -> Optional[SpawnContext]:
    """The next stage to spawn, or ``None`` if nothing should spawn right now.

    Returns ``None`` (and marks the chain ``completed``) when every stage is done; also
    ``None`` while a stage is in flight (one stage at a time) or the chain is terminal.
    Stage 0 seeds from ``root_job_id``; stage N>0 from stage N-1's realised child job.
    Pure except for the completion transition, which naturally belongs here.
    """
    if chain.status in _CHAIN_TERMINAL:
        return None
    if any(s.status == STAGE_RUNNING for s in chain.stages):
        return None
    nxt = next((s for s in chain.stages if s.status == STAGE_PENDING), None)
    if nxt is None:
        chain.status = CHAIN_COMPLETED
        return None
    parent_job_id = (
        chain.root_job_id if nxt.index == 0 else chain.stages[nxt.index - 1].job_id
    )
    plan = chain.plan[nxt.index]
    return SpawnContext(
        stage_index=nxt.index,
        plan=plan,
        parent_job_id=parent_job_id,
        forces=plan.forces,
    )


def mark_spawned(chain: ChainRun, stage_index: int, job_id: str) -> ChainRun:
    """Record that ``stage_index`` was realised as ``job_id`` and is now running."""
    st = chain.stages[stage_index]
    st.job_id = job_id
    st.status = STAGE_RUNNING
    chain.status = CHAIN_RUNNING
    return chain


def step_chain(
    chain: ChainRun,
    *,
    job_status: Callable[[str], str],
    spawn: Callable[[SpawnContext], str],
) -> ChainRun:
    """Advance the chain by at most one transition (synchronous convenience).

    Composes :func:`reconcile_running` -> :func:`next_spawn` -> :func:`mark_spawned`.
    Call repeatedly (on a timer or on a job-completion event); idempotent once the chain
    is terminal.  The async driver uses the primitives directly so it can ``await`` the
    real spawn between the two pure transitions.
    """
    reconcile_running(chain, job_status)
    ctx = next_spawn(chain)
    if ctx is not None:
        job_id = spawn(ctx)
        mark_spawned(chain, ctx.stage_index, job_id)
    return chain


def resume_chain(chain: ChainRun) -> ChainRun:
    """Reset a HALTED (failed) chain from its failed stage, for retry-only-failed.

    Stages that already completed keep their ``done`` status and realised ``job_id`` and
    are NEVER re-run; the failed stage and everything after it reset to ``pending`` (and
    lose their stale ``job_id``).  The chain returns to ``running``; the next
    :func:`step_chain` / :func:`next_spawn` re-spawns from the failed stage.  No-op unless
    the chain is failed.
    """
    if chain.status != CHAIN_FAILED:
        return chain
    fi = chain.failed_stage_index()
    if fi is None:  # defensive: failed chain with no failed marker -> first non-done
        fi = next((s.index for s in chain.stages if s.status != STAGE_DONE), None)
    if fi is not None:
        for s in chain.stages[fi:]:
            s.status = STAGE_PENDING
            s.job_id = None
            s.spawn_attempts = 0   # a manual resume grants a fresh retry budget
    chain.status = CHAIN_RUNNING
    chain.error = None
    return chain


# ── failure diagnosis (the shared brain behind scripts/chain_doctor.py) ──────────
# A halted chain records WHY in ``chain.error`` — but that raw string (a 409 body, a
# FileNotFoundError, a bare exception repr) is not something the queue readout should
# show verbatim, nor is it obvious what to DO about it.  This turns a ChainRun into a
# plain-language {cause, action} so both the CLI doctor and the UI can explain a failure
# and point at the fix.  Pure + engine-agnostic: it pattern-matches the recorded message,
# it does not touch jobs or disk (the doctor pulls job logs separately).

# Substring needles matched (case-insensitively) against ``chain.error``, most specific
# first.  Match the STABLE phrase, not the whole sentence, so a reworded message still
# classifies.  Each maps to (cause, action).
_FAILURE_PATTERNS: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("different design is loaded",),
        "A DIFFERENT design was loaded in the app when the supervisor tried to spawn "
        "this stage. The production/append spawn validates against the LIVE active "
        "design, so switching designs mid-chain halts it — even though the chain seeds "
        "from the previous stage's own job, not whatever is loaded.",
        "Re-open the design this chain was built from (the stage plan's "
        "design_source_path), then Resume the chain.",
    ),
    (
        ("has been edited", "design has changed"),
        "The design this chain runs on was EDITED after the stage's job was prepared, so "
        "its topology/sequence/geometry no longer matches the job's frozen copy.",
        "Roll the design's feature log back to the run state (or re-run the upstream "
        "stage), then Resume.",
    ),
    (
        ("needs ≥1 anchor", "nothing to hold", "drifts the whole structure"),
        "This stage applies a uniform electric field but nothing holds the structure "
        "against the resulting centre-of-mass drift — no strand anchor, and no hard "
        "surface the field presses into.",
        "Add ≥1 strand anchor to the stage, orient a hard surface for the field to press "
        "into (a deposition setup), or disable the field; then re-launch.",
    ),
    (
        ("no such file", "filenotfounderror", "not available", "seed", "checkpoint"),
        "The stage could not find the checkpoint it seeds from — the previous stage's "
        "output frame isn't on disk yet (a remote run still downloading) or was removed.",
        "Resume to retry (a transient missing seed self-heals within the retry budget); "
        "if it persists, re-run the upstream stage so its output frame exists.",
    ),
]


def diagnose_chain(chain: ChainRun) -> dict:
    """Plain-language diagnosis of a chain's state.

    Returns ``{status, headline, failed_index, failed_job_id, error, cause, action}``:

    * ``error`` — the raw ``chain.error`` (``None`` when healthy);
    * ``cause`` — a classified, human reason the chain HALTED (``None`` if not failed);
    * ``action`` — the concrete next step (``None`` if not failed).

    Two failure shapes are told apart: a **spawn** failure (the failed stage never got a
    job — ``chain.error`` is classified by :data:`_FAILURE_PATTERNS`) vs a **job** failure
    (the stage's job ran and crashed — ``failed_job_id`` is set so the caller can pull
    that job's log).
    """
    done = sum(1 for s in chain.stages if s.status == STAGE_DONE)
    total = len(chain.stages)
    fi = chain.failed_stage_index()
    failed_job_id = chain.stages[fi].job_id if fi is not None else None

    if chain.status == CHAIN_COMPLETED:
        headline = f"Chain complete — {total} of {total} stages done."
    elif chain.status == CHAIN_FAILED:
        at = (fi + 1) if fi is not None else "?"
        headline = f"Halted at stage {at} of {total} — {done} done, then failed."
    elif chain.status == CHAIN_RUNNING:
        headline = f"Running — {done} of {total} stages done."
    else:
        headline = f"Queued — {total} stage{'' if total == 1 else 's'} pending."

    cause = action = None
    if chain.status == CHAIN_FAILED:
        if failed_job_id:
            # The stage spawned a job that then failed — the crash is INSIDE the job.
            cause = (f"Stage {fi}'s job ({failed_job_id}) ran but failed — the simulation "
                     "crashed or was stopped. Its own error/log carries the detail.")
            action = (f"Inspect job {failed_job_id}'s log (chain_doctor prints the tail), "
                      "fix the cause, then Resume the chain.")
        else:
            err = (chain.error or "").lower()
            for needles, why, act in _FAILURE_PATTERNS:
                if any(n in err for n in needles):
                    cause, action = why, act
                    break
            if cause is None:
                cause = "The stage's child job could not be spawned (see the raw error)."
                action = "Resume to retry from the failed stage."

    return {
        "status": chain.status,
        "headline": headline,
        "failed_index": fi,
        "failed_job_id": failed_job_id,
        "error": chain.error,
        "cause": cause,
        "action": action,
    }


# ── forces carry-through (the shared conf emitter) ───────────────────────────────

def stage_forces_conf(forces: Optional[dict], *, anchors_file: Optional[str] = None) -> str:
    """The NAMD conf snippet a stage's forces contribute, via the SHARED emitter.

    Reuses :func:`backend.core.md_protocols.external_forces_block` so a chained stage's
    field/anchors reach its child conf through the exact ``fixedAtoms`` + ``eField``
    directives every per-engine launch card already writes — no bespoke chain-only force
    path.  ``anchors_file`` is the restraints PDB the executor writes before spawning (the
    ``fixedAtoms`` marker); the field vector is derived from the shared descriptor.
    """
    forces = forces or {}
    return md_protocols.external_forces_block(anchors_file, forces.get("field"))


# ── persistence ──────────────────────────────────────────────────────────────────

def chains_dir(workspace) -> Path:
    return Path(workspace) / "md_chains"


def chain_path(workspace, chain_id: str) -> Path:
    return chains_dir(workspace) / chain_id / "chain.json"


def save_chain(chain: ChainRun, workspace) -> Path:
    path = chain_path(workspace, chain.chain_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chain.to_dict(), indent=2))
    return path


def load_chain(chain_id: str, workspace) -> ChainRun:
    return ChainRun.from_dict(json.loads(chain_path(workspace, chain_id).read_text()))


def list_chains(workspace) -> list[ChainRun]:
    root = chains_dir(workspace)
    if not root.exists():
        return []
    chains: list[ChainRun] = []
    for d in sorted(root.iterdir()):
        f = d / "chain.json"
        if f.exists():
            try:
                chains.append(ChainRun.from_dict(json.loads(f.read_text())))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return chains
