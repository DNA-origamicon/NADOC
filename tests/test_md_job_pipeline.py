"""P1 oracle — MdPipeline stage-spec data model + pure chain builder.

Bright line (Track P): prove a CAPABILITY, not "it renders".  Here the capability is
that ONE ordered stage-spec object reproduces the three special-cased provenance hops
(``parent_job_id`` + ``run_kind="production"`` + ``seed_oxdna/mrdna_job_id``) and chains
them correctly:

* a 3-stage plan builds N stage descriptors chained by ``parent_job_id``, each seeded
  from the IMMEDIATELY-PREVIOUS stage's output (can-go-red if a stage seeds from the
  wrong checkpoint);
* a 1-stage plan is byte-identical in its provenance fields to today's
  ``spawn_md_production`` (parity / no regression);
* the model can REPRESENT a cross-engine hop (stage engine != its seed engine — the
  generalization of ``seed_oxdna/mrdna_job_id``); the actual coordinate handoff is P3.

The builder is PURE (no job submission — that is P2's executor): it takes stage specs
plus the resolved root checkpoint and emits the chained descriptor list.
"""

from __future__ import annotations

import pytest

from backend.core import md_pipeline as mp
from backend.core.md_ensemble import _DEFAULT_BASE_SEED, generate_seeds


# ── construction / validation ────────────────────────────────────────────────

def _stage(engine="namd", protocol="mgh_slow_release", **kw):
    return mp.PipelineStage(engine=engine, protocol=protocol, **kw)


def test_empty_pipeline_is_invalid():
    with pytest.raises(ValueError):
        mp.validate_pipeline(mp.MdPipeline(stages=[]))


def test_bad_run_target_is_invalid():
    p = mp.MdPipeline(stages=[_stage(run_target="the-moon")])
    with pytest.raises(ValueError):
        mp.validate_pipeline(p)


def test_stage_needs_engine_and_protocol():
    with pytest.raises(ValueError):
        mp.validate_pipeline(mp.MdPipeline(stages=[_stage(engine="")]))
    with pytest.raises(ValueError):
        mp.validate_pipeline(mp.MdPipeline(stages=[_stage(protocol="")]))


def test_forces_bundle_groups_field_anchors_surface():
    st = _stage(field={"field_pN": 5.0, "dir": [1, 0, 0]},
                anchors=[{"scope": "base", "helix": 0, "bp": 3}],
                surface={"z_nm": 0.0})
    assert st.forces() == {
        "field": {"field_pN": 5.0, "dir": [1, 0, 0]},
        "anchors": [{"scope": "base", "helix": 0, "bp": 3}],
        "surface": {"z_nm": 0.0},
    }


# ── the chaining oracle (the bright line) ────────────────────────────────────

def test_three_stage_plan_chains_each_stage_from_its_immediate_predecessor():
    """The headline deposition chain: field -> surface -> anchored field-sweep.

    Each stage's parent + seed-checkpoint must reference the IMMEDIATELY previous
    stage, never the root and never two-back.  Can-go-red if the builder mis-wires
    the predecessor index.
    """
    pipe = mp.MdPipeline(
        root_job_id="relax-root",
        root_engine="namd",
        stages=[
            _stage(field={"field_pN": 3.0, "dir": [1, 0, 0]}, label="deposit"),
            _stage(surface={"z_nm": 0.0}, label="immobilize"),
            _stage(field={"field_pN": 3.0, "dir": [0, 1, 0]},
                   anchors=[{"scope": "base", "helix": 0, "bp": 0}], label="sweep"),
        ],
    )
    plan = mp.build_pipeline_plan(pipe, root_checkpoint="equilibrated")

    assert [s.index for s in plan] == [0, 1, 2]

    # Stage 0 seeds from the ROOT job + the resolved root checkpoint.
    assert plan[0].parent_job_id == "relax-root"
    assert plan[0].parent_engine == "namd"
    assert plan[0].start_checkpoint == "equilibrated"

    # Stages 1..N seed from their IMMEDIATE predecessor's output — not root, not i-2.
    for i in (1, 2):
        assert plan[i].parent_job_id == plan[i - 1].stage_id, f"stage {i} parent"
        assert plan[i].start_checkpoint == mp.stage_output_ref(plan[i - 1].stage_id), \
            f"stage {i} seed checkpoint"
        # RED guards: a builder that always seeds from root or from i-2 would trip these.
        assert plan[i].parent_job_id != "relax-root"
        assert plan[i].start_checkpoint != "equilibrated"
    assert plan[2].parent_job_id != plan[0].stage_id  # not two-back

    # Every chained hop is a production-style seed; forces carry per stage.
    assert all(s.run_kind == "production" for s in plan)
    assert plan[0].forces["field"]["dir"] == [1, 0, 0]
    assert plan[1].forces["surface"] == {"z_nm": 0.0}
    assert plan[2].forces["anchors"] == [{"scope": "base", "helix": 0, "bp": 0}]


def test_each_stage_gets_a_distinct_seed():
    pipe = mp.MdPipeline(root_job_id="r", root_engine="namd",
                         stages=[_stage(), _stage(), _stage()])
    plan = mp.build_pipeline_plan(pipe, root_checkpoint="equilibrated")
    seeds = [s.seed for s in plan]
    assert len(set(seeds)) == 3
    # Reuses the ensemble seed generator (base .. base+n-1).
    assert seeds == generate_seeds(_DEFAULT_BASE_SEED, 3)


# ── 1-stage parity with spawn_md_production (no regression) ───────────────────

def test_single_stage_plan_matches_spawn_md_production_provenance():
    """A 1-stage production pipeline reproduces the exact provenance fields
    ``spawn_md_production`` assigns to the first production child (index 0):

        parent_job_id = parent.job_id
        run_kind      = "production"
        ensemble_seed = generate_seeds(_DEFAULT_BASE_SEED, index + 1)[-1]   # index 0 -> 54321
        start_checkpoint = _production_seed_checkpoint(parent).spec.name    # passed as root_checkpoint

    (routes_md.spawn_md_production, lines ~1596-1611).
    """
    pipe = mp.MdPipeline(root_job_id="parent-abc", root_engine="namd",
                         stages=[_stage(field=None, anchors=None)])
    plan = mp.build_pipeline_plan(pipe, root_checkpoint="04_prod_probe")
    assert len(plan) == 1
    only = plan[0]
    assert only.parent_job_id == "parent-abc"
    assert only.run_kind == "production"
    # The literal seed spawn_md_production computes for the first child (index 0).
    assert only.seed == generate_seeds(_DEFAULT_BASE_SEED, 0 + 1)[-1] == _DEFAULT_BASE_SEED
    assert only.start_checkpoint == "04_prod_probe"
    assert only.cross_engine is False


# ── cross-engine representability (generalizes seed_oxdna/mrdna_job_id) ───────

def test_cross_engine_hop_is_flagged():
    """A stage whose engine differs from the job it seeds from is a cross-engine hop
    (the generalization of seed_oxdna_job_id / seed_mrdna_job_id).  P1 must be able to
    REPRESENT it; P3 performs the coordinate conversion."""
    pipe = mp.MdPipeline(
        root_job_id="ox-relax", root_engine="oxdna",
        stages=[
            _stage(engine="oxdna", protocol="relax"),   # same engine as root -> not cross
            _stage(engine="namd", protocol="mgh_slow_release"),  # oxdna -> namd: cross
        ],
    )
    plan = mp.build_pipeline_plan(pipe, root_checkpoint="last_conf")
    assert plan[0].parent_engine == "oxdna" and plan[0].cross_engine is False
    assert plan[1].parent_engine == "oxdna" and plan[1].engine == "namd"
    assert plan[1].cross_engine is True


# ── persistence round-trip (P2/P4 persist the plan) ──────────────────────────

def test_pipeline_dict_round_trip():
    pipe = mp.MdPipeline(
        root_job_id="r", root_engine="namd",
        stages=[
            _stage(field={"field_pN": 2.0, "dir": [0, 0, 1]}, run_target="alpine",
                   cluster_name="alpine", length_ns=5.0, label="s0"),
            _stage(surface={"z_nm": 1.0}, steps=100_000, label="s1"),
        ],
    )
    back = mp.MdPipeline.from_dict(pipe.to_dict())
    assert back == pipe
    # And a built plan is JSON-serializable.
    plan = mp.build_pipeline_plan(pipe, root_checkpoint="eq")
    dicts = [s.to_dict() for s in plan]
    assert [d["stage_id"] for d in dicts] == [plan[0].stage_id, plan[1].stage_id]
    assert dicts[1]["start_checkpoint"] == mp.stage_output_ref(plan[0].stage_id)
