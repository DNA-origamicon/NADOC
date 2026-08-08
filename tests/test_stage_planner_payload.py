"""P4 parity oracle — the "Plan Run" UI payload IS a valid MdPipeline chain.

The frontend `stage_planner_model.buildChainPayload` (unit-tested byte-equal in
`frontend/src/ui/stage_planner_model.test.js`) authors a `CreateChainRequest` JSON.  This
test pins the SAME literal on the backend side and proves it:

1. parses through the `CreateChainRequest` pydantic model (the route's contract),
2. becomes a valid `MdPipeline` (P1) that `validate_pipeline` accepts,
3. `build_pipeline_plan` resolves into a LINEAR chain where stage N seeds from stage N-1
   (the CHAIN capability — not "a button exists").

Keep the FIXTURE dict in sync with the JS test's parity fixture; the two halves together
are the P4 bright-line proof (queued chain == the payload the UI built).
"""

from __future__ import annotations

from backend.api.routes_md import ChainStageRequest, CreateChainRequest
from backend.core.md_pipeline import (
    MdPipeline,
    PipelineStage,
    build_pipeline_plan,
    stage_output_ref,
    validate_pipeline,
)

# BYTE-EQUAL to stage_planner_model.test.js's "3-stage deposition→immobilize→sweep" build.
DEPOSITION_SWEEP_PAYLOAD = {
    "root_job_id": "oxdna-relax-1",
    "root_engine": "oxdna",
    "stages": [
        {
            "engine": "namd",
            "protocol": "production",
            "field": {"field_pN": 5, "dir": [0, 0, 1]},
            "anchors": None,
            "surface": None,
            "run_target": "local",
            "cluster_name": None,
            "length_ns": None,
            "steps": None,
            "label": "deposit",
        },
        {
            "engine": "namd",
            "protocol": "production",
            "field": None,
            "anchors": [{"scope": "strand", "id": 0}],
            "surface": None,
            "run_target": "local",
            "cluster_name": None,
            "length_ns": None,
            "steps": None,
            "label": "immobilize",
        },
        {
            "engine": "namd",
            "protocol": "production",
            "field": {"field_pN": 5, "dir": [1, 0, 0]},
            "anchors": [{"scope": "strand", "id": 0}],
            "surface": None,
            "run_target": "local",
            "cluster_name": None,
            "length_ns": None,
            "steps": None,
            "label": "sweep-x",
        },
    ],
}


def _pipeline_from_payload(payload: dict) -> MdPipeline:
    """Reproduce exactly what the `POST /md/chains` route builds from the request body."""
    body = CreateChainRequest(**payload)
    return MdPipeline(
        root_job_id=body.root_job_id,
        root_engine=(body.root_engine or "namd").lower(),
        stages=[PipelineStage(**s.model_dump()) for s in body.stages],
    )


def test_ui_payload_parses_through_the_route_contract():
    """The UI payload satisfies the pydantic CreateChainRequest / ChainStageRequest schema."""
    body = CreateChainRequest(**DEPOSITION_SWEEP_PAYLOAD)
    assert body.root_job_id == "oxdna-relax-1"
    assert body.root_engine == "oxdna"
    assert len(body.stages) == 3
    assert all(isinstance(s, ChainStageRequest) for s in body.stages)
    # the Forces descriptor round-trips as a plain dict
    assert body.stages[0].field == {"field_pN": 5, "dir": [0, 0, 1]}
    assert body.stages[1].field is None


def test_ui_payload_is_a_valid_mdpipeline():
    pipeline = _pipeline_from_payload(DEPOSITION_SWEEP_PAYLOAD)
    validate_pipeline(pipeline)  # raises on malformed — must not
    assert len(pipeline.stages) == 3
    assert pipeline.root_job_id == "oxdna-relax-1"


def test_ui_payload_builds_a_linear_chain_stage_N_from_N_minus_1():
    """CHAIN capability: the resolved plan seeds each stage from its immediate predecessor."""
    pipeline = _pipeline_from_payload(DEPOSITION_SWEEP_PAYLOAD)
    plan = build_pipeline_plan(pipeline, root_checkpoint="relaxed")

    # stage 0 seeds from the (cross-engine) oxDNA root
    assert plan[0].parent_job_id == "oxdna-relax-1"
    assert plan[0].parent_engine == "oxdna"
    assert plan[0].start_checkpoint == "relaxed"
    assert plan[0].cross_engine is True  # oxdna → namd hop

    # stages 1..2 each seed from the PREVIOUS stage's output (not the root, not two back)
    for i in (1, 2):
        assert plan[i].parent_job_id == f"stage{i - 1}"
        assert plan[i].start_checkpoint == stage_output_ref(f"stage{i - 1}")
        assert plan[i].cross_engine is False  # namd → namd
    # RED guard: a downstream stage must NOT seed from the root
    assert plan[2].parent_job_id != "oxdna-relax-1"
    assert plan[2].parent_job_id != "stage0"

    # forces survive onto the plan verbatim (field carried, anchors carried)
    assert plan[0].forces["field"] == {"field_pN": 5, "dir": [0, 0, 1]}
    assert plan[2].forces["field"] == {"field_pN": 5, "dir": [1, 0, 0]}
    assert plan[1].forces["anchors"] == [{"scope": "strand", "id": 0}]

    # distinct per-stage seeds (base..base+n-1)
    assert len({p.seed for p in plan}) == 3


def test_single_stage_payload_still_valid():
    """The minimal case the UI can queue (a root + one stage)."""
    payload = {
        "root_job_id": "namd-eq-9",
        "root_engine": "namd",
        "stages": [
            {
                "engine": "namd",
                "protocol": "production",
                "field": None,
                "anchors": None,
                "surface": None,
                "run_target": "local",
                "cluster_name": None,
                "length_ns": None,
                "steps": None,
                "label": None,
            }
        ],
    }
    pipeline = _pipeline_from_payload(payload)
    validate_pipeline(pipeline)
    plan = build_pipeline_plan(pipeline)
    assert len(plan) == 1
    assert plan[0].parent_job_id == "namd-eq-9"
    assert plan[0].cross_engine is False
