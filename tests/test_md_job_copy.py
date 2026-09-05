"""Copy is configuration-only; the explicit Run boundary owns preparation."""

import asyncio

import pytest

from backend.api import routes_md
from backend.core.md_job import MdJob, MdStatus
from backend.core.md_queue import job_is_queueable, job_is_startable
from backend.core.models import Design, DesignMetadata


def forbidden(*args, **kwargs):
    pytest.fail("Copy must not prepare, start, or submit a job")


@pytest.mark.parametrize("seeded", [False, True])
@pytest.mark.parametrize("target", ["alpine", "runpod", "local"])
def test_failed_copy_is_persisted_draft_without_execution(
    tmp_path, monkeypatch, target, seeded
):
    from backend.core import md_executor

    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes_md, "_spawn_prep_job", forbidden)
    monkeypatch.setattr(routes_md, "start_job", forbidden)
    monkeypatch.setattr(md_executor, "submit_job", forbidden)
    monkeypatch.setattr(routes_md.design_state, "get_or_404", forbidden)
    body = routes_md.CreateJobRequest(
        execution_target=target,
        autostart=True,
        seed=12345,
        oxdna_job_id="seed-job" if seeded else None,
        anchors=[{"kind": "strand", "strandId": "s1"}],
        graphene_nanopore=True,
        graphene_pore_diameter_nm=8,
        partition="artxpro6000",
        slurm_resources={"cores": 8},
    )
    source = routes_md._spawn_draft_job(body, name="small_plate")
    source.status = MdStatus.failed
    source.slurm_job_id = "32086330"
    source.remote_scratch_dir = "/scratch/failed-source"
    source.error = "cell shrink"
    source.save(tmp_path)
    snapshot = source.job_dir(tmp_path) / "design.json"
    snapshot.write_text(
        Design(metadata=DesignMetadata(name="frozen original")).to_json()
    )
    before = (source.job_dir(tmp_path) / "job.json").read_bytes()

    result = asyncio.run(routes_md.copy_md_job(source.job_id))
    copied = MdJob.load(result["job"]["job_id"], tmp_path)
    assert copied.status == MdStatus.draft
    assert copied.prep_params == {
        **source.prep_params,
        "draft": True,
        "autostart": False,
        "seed": copied.namd_seed,
    }
    assert copied.namd_seed != source.namd_seed
    assert copied.execution_target == target
    assert copied.requested_resources == {"cores": 8}
    assert not copied.slurm_job_id
    assert not copied.remote_scratch_dir
    assert not copied.remote_project_dir
    assert not copied.package_subdir
    assert not copied.error
    assert not job_is_queueable(copied)
    assert not job_is_startable(copied)
    assert (
        copied.job_dir(tmp_path) / "design.json"
    ).read_bytes() == snapshot.read_bytes()
    assert (source.job_dir(tmp_path) / "job.json").read_bytes() == before


def test_explicit_run_of_copied_draft_uses_frozen_design(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes_md, "find_namd", lambda: "/bin/namd3")
    monkeypatch.setattr(routes_md, "find_gmx", lambda: "/bin/gmx")
    monkeypatch.setattr(routes_md.design_state, "get_or_404", forbidden)
    body = routes_md.CreateJobRequest(execution_target="alpine", seed=12345)
    source = routes_md._spawn_draft_job(body, name="frozen original")
    source.status = MdStatus.failed
    source.save(tmp_path)
    frozen = Design(metadata=DesignMetadata(name="frozen original"))
    (source.job_dir(tmp_path) / "design.json").write_text(frozen.to_json())
    copied = asyncio.run(routes_md.copy_md_job(source.job_id))["job"]
    captured = {}

    def prepare(request, **kwargs):
        captured.update(request=request, **kwargs)
        return kwargs["existing_job"]

    monkeypatch.setattr(routes_md, "_spawn_prep_job", prepare)
    monkeypatch.setattr(routes_md, "design_size_factor", lambda design: 1)
    monkeypatch.setattr(
        routes_md, "_infer_graphene_only", lambda request, design: request
    )
    request = routes_md.CreateJobRequest.model_validate(
        copied["prep_params"]
    ).model_copy(update={"autostart": True})
    asyncio.run(routes_md.prepare_draft_job(copied["job_id"], request))
    assert captured["design"].to_json() == frozen.to_json()
    assert captured["request"].autostart is True
    assert captured["request"].draft is False
    assert captured["request"].seed == copied["namd_seed"]
    assert captured["existing_job"].job_id == copied["job_id"]
