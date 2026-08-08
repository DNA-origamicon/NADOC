"""
Chain-spawn engine dispatch (routes_md) — the relax-rooted + oxDNA extensions.

The pure executor is engine-agnostic; the ENGINE routing lives in ``_chain_spawn``:
a rootless stage 0 creates a fresh relax, an oxDNA stage branches an oxDNA child,
a same-engine NAMD stage restarts a production, a cross-engine CG→NAMD stage rebuilds
an atomistic seed. These assert the routing without spawning real jobs (the four
job-creators are monkeypatched to record which path fired).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.api import routes_md
from backend.core.md_pipeline import MdPipeline, PipelineStage, build_pipeline_plan
from backend.core.md_chain_executor import SpawnContext


def _ctx(pipeline: MdPipeline, index: int, parent_job_id):
    plan = build_pipeline_plan(pipeline)[index]
    return SpawnContext(
        stage_index=index, plan=plan, parent_job_id=parent_job_id, forces=plan.forces
    )


@pytest.fixture
def spies(monkeypatch):
    calls = {}

    async def fresh_relax(plan):
        calls["fresh_relax"] = plan
        return "fresh-job"

    async def oxdna_child(parent, plan):
        calls["oxdna_child"] = (parent, plan)
        return "oxdna-child-job"

    async def spawn_prod(parent, body):
        calls["spawn_prod"] = (parent, body)
        return {"job": {"job_id": "namd-prod-job"}}

    async def create_md(body):
        calls["create_md"] = body
        return {"job_id": "namd-cross-job"}

    monkeypatch.setattr(routes_md, "_spawn_fresh_relax", fresh_relax)
    monkeypatch.setattr(routes_md, "_spawn_oxdna_child", oxdna_child)
    monkeypatch.setattr(routes_md, "spawn_md_production", spawn_prod)
    monkeypatch.setattr(routes_md, "create_md_job", create_md)
    return calls


def test_rootless_stage0_routes_to_fresh_relax(spies):
    pipe = MdPipeline(
        stages=[PipelineStage(engine="oxdna", protocol="relax")], root_job_id=None
    )
    jid = asyncio.run(routes_md._chain_spawn(_ctx(pipe, 0, None)))
    assert jid == "fresh-job"
    assert "fresh_relax" in spies and "oxdna_child" not in spies


def test_oxdna_stage_with_parent_routes_to_oxdna_child(spies):
    pipe = MdPipeline(
        stages=[PipelineStage(engine="oxdna", protocol="production", steps=1_000_000)],
        root_job_id="ox-root",
        root_engine="oxdna",
    )
    jid = asyncio.run(routes_md._chain_spawn(_ctx(pipe, 0, "ox-root")))
    assert jid == "oxdna-child-job"
    assert spies["oxdna_child"][0] == "ox-root"


def test_same_engine_namd_routes_to_spawn_production(spies):
    pipe = MdPipeline(
        stages=[PipelineStage(engine="namd", protocol="production")],
        root_job_id="namd-root",
        root_engine="namd",
    )
    jid = asyncio.run(routes_md._chain_spawn(_ctx(pipe, 0, "namd-root")))
    assert jid == "namd-prod-job"
    assert spies["spawn_prod"][0] == "namd-root"


def test_cross_engine_oxdna_to_namd_routes_to_create_md_job(spies):
    # A NAMD stage seeded from an oxDNA parent → cross-engine atomistic rebuild.
    pipe = MdPipeline(
        stages=[PipelineStage(engine="namd", protocol="production")],
        root_job_id="ox-root",
        root_engine="oxdna",
    )
    jid = asyncio.run(routes_md._chain_spawn(_ctx(pipe, 0, "ox-root")))
    assert jid == "namd-cross-job"
    assert "create_md" in spies


def test_is_relax_protocol():
    assert routes_md._is_relax_protocol("relax")
    assert routes_md._is_relax_protocol("Relaxation")
    assert not routes_md._is_relax_protocol("production")
    assert not routes_md._is_relax_protocol(None)


def test_pipeline_propagates_design_source_path_into_every_stage_plan():
    pipe = MdPipeline(
        stages=[
            PipelineStage(engine="oxdna", protocol="relax"),
            PipelineStage(engine="oxdna", protocol="production"),
        ],
        root_job_id=None,
        design_source_path="/ws/26hb.nadoc",
    )
    plans = build_pipeline_plan(pipe)
    assert [p.design_source_path for p in plans] == ["/ws/26hb.nadoc", "/ws/26hb.nadoc"]


def test_fresh_relax_stamps_design_source_path_onto_the_create_body(monkeypatch):
    # A fresh oxDNA / NAMD relax root must stamp design_source_path so the child appears
    # in the per-design engine job list (the list filters on it).
    seen = {}

    async def create_ox(body):
        seen["oxdna"] = body.design_source_path
        return {"job_id": "ox", "status": "queued"}

    async def create_md(body):
        seen["namd"] = body.design_source_path
        return {"job_id": "md"}

    # Patch the create endpoints the spawner imports lazily.
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "create_oxdna_job", create_ox)
    monkeypatch.setattr(routes_md, "create_md_job", create_md)

    ox_plan = build_pipeline_plan(
        MdPipeline(
            stages=[PipelineStage(engine="oxdna", protocol="relax")],
            design_source_path="/ws/d.nadoc",
        )
    )[0]
    namd_plan = build_pipeline_plan(
        MdPipeline(
            stages=[PipelineStage(engine="namd", protocol="relax")],
            design_source_path="/ws/d.nadoc",
        )
    )[0]

    asyncio.run(routes_md._spawn_fresh_relax(ox_plan))
    asyncio.run(routes_md._spawn_fresh_relax(namd_plan))
    assert seen == {"oxdna": "/ws/d.nadoc", "namd": "/ws/d.nadoc"}
