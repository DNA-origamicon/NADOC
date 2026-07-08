"""
MD job pipeline — a generic, ordered multi-stage chain that runs unattended.

Today "chaining" exists only as three special-cased provenance hops threaded through the
job models by hand:

* ``MdJob.parent_job_id`` + ``run_kind="production"`` — a production child seeded from a
  relaxation parent's equilibrated checkpoint (:func:`routes_md.spawn_md_production`);
* ``MdJob.seed_oxdna_job_id`` / ``seed_mrdna_job_id`` — a job seeded from another engine's
  relaxed coordinates.

This module generalizes those hops into ONE ordered data object.  An :class:`MdPipeline`
is a list of :class:`PipelineStage` specs (engine + protocol + forces + run target);
:func:`build_pipeline_plan` resolves it into a linear chain of :class:`StagePlan`
descriptors where **stage N is seeded from stage N-1's output** (and stage 0 from the
pipeline's root job checkpoint).

The motivating case (M-DEPOSITION-CHAIN): *E-field -> hard surface (deposition) ->
anchors (immobilize) -> E-field sweep in several directions* — three hand-babysat jobs
today, one Plan Run tomorrow.

**Scope of P1 (this module): the DATA MODEL + a PURE builder only.**  It creates NO jobs
and touches NO topology (Three-Layer Law: forces/anchors/surface are job-request
annotations, never ``Design`` edits).  The chain EXECUTOR that actually submits each
stage on the previous stage's completion (and halts + resumes from a failed stage) is
P2; the cross-engine coordinate conversion is P3; the planner UI is P4.

Seed generation reuses :func:`backend.core.md_ensemble.generate_seeds` so a pipeline's
per-stage velocity seeds match the ensemble/production convention (base .. base+n-1,
base = 54321 so a single-stage plan's seed equals today's single-run production seed).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from backend.core.md_ensemble import _DEFAULT_BASE_SEED, generate_seeds

# The run targets a stage may execute on (mirrors ``MdJob.execution_target``).
_VALID_RUN_TARGETS = ("local", "alpine")


@dataclass
class PipelineStage:
    """One stage in a chain: an engine run with its forces + run target.

    ``field`` / ``anchors`` / ``surface`` are the same job-request force annotations the
    per-engine launch cards already emit (the shared ``efield_math`` /
    ``oxdna_floor_math`` payloads) — never ``Design`` edits.
    """

    engine: str
    protocol: str
    field: Optional[dict] = None
    anchors: Optional[list] = None
    surface: Optional[dict] = None
    run_target: str = "local"
    cluster_name: Optional[str] = None
    length_ns: Optional[float] = None
    steps: Optional[int] = None
    label: Optional[str] = None

    def forces(self) -> dict:
        """The force-annotation bundle for this stage (field/anchors/surface)."""
        return {"field": self.field, "anchors": self.anchors, "surface": self.surface}


@dataclass
class MdPipeline:
    """An ordered list of stages plus the root job they chain off.

    ``root_job_id`` is the already-existing job (typically a completed relaxation) whose
    resolved checkpoint seeds stage 0; ``root_engine`` is that job's engine (so a
    stage-0 cross-engine hop is detectable).  Both may be ``None`` when the pipeline's
    first stage is itself a fresh root run (no upstream seed).
    """

    stages: list[PipelineStage] = field(default_factory=list)
    root_job_id: Optional[str] = None
    root_engine: Optional[str] = None

    # ── persistence (P2/P4 store the plan) ───────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "root_job_id": self.root_job_id,
            "root_engine": self.root_engine,
            "stages": [asdict(s) for s in self.stages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MdPipeline":
        return cls(
            root_job_id=data.get("root_job_id"),
            root_engine=data.get("root_engine"),
            stages=[PipelineStage(**s) for s in data.get("stages", [])],
        )


@dataclass
class StagePlan:
    """A resolved stage descriptor: the provenance a stage's child job would carry.

    ``parent_job_id`` is the job this stage seeds from (the root job for stage 0, else the
    previous stage's ``stage_id`` placeholder — resolved to a real job id by the P2
    executor once the previous stage has run).  ``start_checkpoint`` is the checkpoint
    name it restarts from (the root checkpoint for stage 0, else a reference to the
    previous stage's output).  ``cross_engine`` marks a hop between engines (the
    ``seed_oxdna/mrdna_job_id`` generalization) — P3 converts the coordinates.
    """

    index: int
    stage_id: str
    engine: str
    protocol: str
    parent_job_id: Optional[str]
    parent_engine: Optional[str]
    run_kind: str
    seed: int
    start_checkpoint: Optional[str]
    forces: dict
    run_target: str
    cluster_name: Optional[str]
    length_ns: Optional[float]
    steps: Optional[int]
    label: Optional[str]
    cross_engine: bool

    def to_dict(self) -> dict:
        return asdict(self)


def default_stage_id(index: int) -> str:
    """Deterministic placeholder id for stage ``index`` before its job exists."""
    return f"stage{index}"


def stage_output_ref(stage_id: str) -> str:
    """Reference to a stage's production output checkpoint.

    A downstream stage restarts from ``<stage_id>::output`` — the P2 executor rewrites
    this to the completed stage's real equilibrated/production ``.coor/.xsc`` name.
    """
    return f"{stage_id}::output"


def validate_pipeline(pipeline: MdPipeline) -> None:
    """Raise ``ValueError`` on a malformed pipeline (empty / bad stage fields)."""
    if not pipeline.stages:
        raise ValueError("pipeline must have at least one stage")
    for i, st in enumerate(pipeline.stages):
        if not st.engine:
            raise ValueError(f"stage {i} has no engine")
        if not st.protocol:
            raise ValueError(f"stage {i} has no protocol")
        if st.run_target not in _VALID_RUN_TARGETS:
            raise ValueError(
                f"stage {i} run_target {st.run_target!r} not in {_VALID_RUN_TARGETS}")


def build_pipeline_plan(
    pipeline: MdPipeline,
    *,
    root_checkpoint: Optional[str] = None,
    base_seed: int = _DEFAULT_BASE_SEED,
    stage_id_for: Callable[[int], str] = default_stage_id,
) -> list[StagePlan]:
    """Resolve a pipeline into a linear chain of stage descriptors (PURE).

    Each stage becomes a production-style seeded hop off the previous one:

    * stage 0 seeds from ``pipeline.root_job_id`` at ``root_checkpoint``;
    * stage N (>0) seeds from stage N-1's output (:func:`stage_output_ref`), with
      ``parent_job_id`` = the previous stage's placeholder id.

    Seeds come from :func:`generate_seeds` (base .. base+n-1), so a single-stage plan's
    seed equals ``spawn_md_production``'s first-child seed (54321) — parity, no
    regression.  No jobs are created and no coordinates are touched here.
    """
    validate_pipeline(pipeline)
    seeds = generate_seeds(base_seed, len(pipeline.stages))
    plans: list[StagePlan] = []
    for i, st in enumerate(pipeline.stages):
        stage_id = stage_id_for(i)
        if i == 0:
            parent_job_id: Optional[str] = pipeline.root_job_id
            parent_engine: Optional[str] = pipeline.root_engine
            start_checkpoint: Optional[str] = root_checkpoint
        else:
            prev = pipeline.stages[i - 1]
            parent_job_id = stage_id_for(i - 1)
            parent_engine = prev.engine
            start_checkpoint = stage_output_ref(stage_id_for(i - 1))
        cross_engine = parent_engine is not None and parent_engine != st.engine
        plans.append(StagePlan(
            index=i,
            stage_id=stage_id,
            engine=st.engine,
            protocol=st.protocol,
            parent_job_id=parent_job_id,
            parent_engine=parent_engine,
            run_kind="production",
            seed=seeds[i],
            start_checkpoint=start_checkpoint,
            forces=st.forces(),
            run_target=st.run_target,
            cluster_name=st.cluster_name,
            length_ns=st.length_ns,
            steps=st.steps,
            label=st.label,
            cross_engine=cross_engine,
        ))
    return plans
