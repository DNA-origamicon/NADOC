"""Fixed-pose clearance gates must remain independent of rotational overrides."""

import asyncio
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi import HTTPException

from backend.core.md_image_clearance import (
    clearance_report,
    job_image_clearance,
    require_image_clearance,
)


def test_fixed_pose_does_not_require_rotation_sized_box():
    # A 100 nm rod is fine with a 2.4 nm image gap, even though it cannot tumble.
    report = clearance_report(
        [[0, 0, 0], [10, 10, 1000]], [34, 34, 1024], cutoff_ang=10
    )
    assert report["status"] == "pass"
    assert report["axis_gaps_nm"] == [2.4, 2.4, 2.4]


def test_largest_cutoff_and_negative_envelope_gap():
    report = clearance_report([[0, 0, 0], [10, 10, 100]], [35, 35, 99], cutoff_ang=14)
    assert report["requires_override"]
    assert report["recommended_gap_nm"] == 2.8
    assert report["minimum_gap_nm"] == -0.1
    assert "does not by itself prove" in report["detail"]


@pytest.mark.parametrize("cell", [[30, 0, 50], [float("nan"), 50, 50]])
def test_bad_geometry_is_not_passed(cell):
    with pytest.raises(ValueError):
        clearance_report([[0, 0, 0]], cell, cutoff_ang=10)


def package(tmp_path, *, gap=10):
    pkg = tmp_path / "package"
    pkg.mkdir()
    # Last atom is solvent, outside the solute envelope. HMR hydrogen excluded by name.
    (pkg / "d.psf").write_text(
        "PSF\n\n 4 !NATOM\n"
        "1 D000 1 ADE P P 0 30\n2 D000 1 ADE O1P O 0 16\n"
        "3 D000 1 ADE H1 H 0 3\n4 W000 1 TIP3 OH2 O 0 16\n"
    )
    xyz = np.array([[0.0, 0, 0], [20, 20, 20], [99, 99, 99], [99, 99, 99]])
    (pkg / "equilibrated.coor").write_bytes(
        struct.pack("<i", 4) + xyz.astype("<f8").tobytes()
    )
    (pkg / "equilibrated.xsc").write_text(
        f"# cell\n0 {20 + gap} 0 0 0 60 0 0 0 60 0 0 0\n"
    )
    (pkg / "start.conf").write_text(
        "structure d.psf\ncoordinates missing.pdb\n"
        "binCoordinates equilibrated.coor\nextendedSystem equilibrated.xsc\n"
        "cellBasisVector1 999 0 0\ncellBasisVector2 0 999 0\n"
        "cellBasisVector3 0 0 999\ncutoff 10\n"
    )
    (pkg / "production.conf").write_text("cutoff 12\n")
    return SimpleNamespace(
        package_dir=lambda _: pkg,
        job_dir=lambda _: tmp_path,
        minimization=SimpleNamespace(name="start"),
        segments=[SimpleNamespace(name="production")],
        spawn_params={"allow_undersized_cell": True, "orientation_restraint": True},
        status="queued",
        slurm_job_id=None,
        job_id="j",
        execution_target="alpine",
        resumable=True,
        remote_scratch_dir="/scratch/j",
        cluster_name="alpine",
        to_dict=lambda: {},
    )


def test_checkpoint_cell_overrides_config_and_rotation_override_does_not_apply(
    tmp_path,
):
    job = package(tmp_path)
    report = job_image_clearance(job, tmp_path)
    assert report["status"] == "insufficient"
    assert report["axis_gaps_nm"] == [1.0, 4.0, 4.0]
    assert report["n_solute_heavy_atoms"] == 2
    assert report["coordinate_source"] == "equilibrated.coor"
    assert report["cell_source"] == "equilibrated.xsc"
    with pytest.raises(HTTPException, match="allow_small_image_gap"):
        require_image_clearance(job, tmp_path, allow=False)
    assert (
        require_image_clearance(job, tmp_path, allow=True)["status"] == "insufficient"
    )


def test_missing_checkpoint_cannot_fall_back_to_large_prep_box(tmp_path):
    job = package(tmp_path)
    (job.package_dir(tmp_path) / "equilibrated.xsc").unlink()
    assert job_image_clearance(job, tmp_path)["status"] == "unknown"
    with pytest.raises(HTTPException):
        require_image_clearance(job, tmp_path, allow=False)


def test_resume_cannot_certify_remote_pose_from_old_local_inputs(tmp_path):
    job = package(tmp_path, gap=40)
    assert job_image_clearance(job, tmp_path)["status"] == "pass"
    assert job_image_clearance(job, tmp_path, resume=True)["requires_override"]


@pytest.mark.parametrize("resume", [False, True])
def test_routes_block_before_executor_and_record_explicit_override(
    tmp_path, monkeypatch, resume
):
    from backend.api import routes_md as routes
    from backend.core import cluster_config, cluster_ssh, md_executor

    job = package(tmp_path)
    monkeypatch.setattr(routes, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes, "_load_job", lambda _: job)
    monkeypatch.setattr(routes, "_remote_resources", lambda *args: {})
    monkeypatch.setattr(cluster_config, "load_profiles", lambda _: {"alpine": object()})
    monkeypatch.setattr(
        cluster_ssh, "get_manager", lambda: SimpleNamespace(is_connected=lambda: True)
    )
    execute = AsyncMock(return_value=job)
    monkeypatch.setattr(md_executor, "resume_job" if resume else "submit_job", execute)
    route = routes.resume_md_job_remote if resume else routes.submit_md_job_remote
    model = routes.ResumeRemoteRequest if resume else routes.SubmitRemoteRequest
    with pytest.raises(HTTPException) as exc:
        asyncio.run(route("j", model()))
    assert exc.value.status_code == 409
    execute.assert_not_called()
    asyncio.run(route("j", model(allow_small_image_gap=True)))
    execute.assert_awaited_once()
    audit = json.loads((tmp_path / "image_clearance_reviews.jsonl").read_text())
    assert audit["allow_small_image_gap"] is True


def test_ensemble_checks_every_replica_before_submitting_any(tmp_path, monkeypatch):
    from backend.api import routes_md as routes
    from backend.core import cluster_config, cluster_ssh, md_executor
    from backend.core.md_job import MdJob

    job = package(tmp_path, gap=40)
    bad = SimpleNamespace(**{**job.__dict__, "job_id": "bad", "ensemble_index": 1})
    job.parent_job_id = bad.parent_job_id = "parent"
    job.ensemble_seed = bad.ensemble_seed = 1
    job.ensemble_index = 0
    monkeypatch.setattr(routes, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes, "_load_job", lambda _: job)
    monkeypatch.setattr(MdJob, "list_jobs", lambda _: [job, bad])
    monkeypatch.setattr(cluster_config, "load_profiles", lambda _: {"alpine": object()})
    monkeypatch.setattr(
        cluster_ssh, "get_manager", lambda: SimpleNamespace(is_connected=lambda: True)
    )

    def check(child, *args, **kwargs):
        if child.job_id == "bad":
            raise HTTPException(409, "unsafe replica")
        return {"status": "pass"}

    monkeypatch.setattr(routes, "require_image_clearance", check)
    execute = AsyncMock()
    monkeypatch.setattr(md_executor, "submit_job", execute)
    with pytest.raises(HTTPException):
        asyncio.run(
            routes.submit_md_ensemble(
                "parent", routes.EnsembleSubmitRequest(resources={"cores": 1})
            )
        )
    execute.assert_not_called()


def test_prepared_pdb_and_translation_invariance(tmp_path):
    job = package(tmp_path, gap=40)
    pkg = job.package_dir(tmp_path)
    conf = (pkg / "start.conf").read_text()
    conf = "\n".join(
        line
        for line in conf.splitlines()
        if not line.startswith(("binCoordinates", "extendedSystem"))
    )
    (pkg / "start.conf").write_text(conf)
    with (pkg / "missing.pdb").open("w") as handle:
        for i, xyz in enumerate(
            [(0, 0, 0), (20, 20, 20), (99, 99, 99), (99, 99, 99)], 1
        ):
            handle.write(
                f"ATOM  {i:5d}  P   ADE A   1    {xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}\n"
            )
    report = job_image_clearance(job, tmp_path)
    assert report["status"] == "pass"
    assert report["coordinate_source"] == "missing.pdb"
    assert report["axis_gaps_nm"] == [97.9, 97.9, 97.9]
    original = clearance_report([[0, 0, 0], [20, 20, 20]], [50, 50, 50], cutoff_ang=10)
    translated = clearance_report(
        [[100, 100, 100], [120, 120, 120]], [50, 50, 50], cutoff_ang=10
    )
    assert translated == original


def test_ensemble_preview_exposes_other_replica_block(tmp_path, monkeypatch):
    from backend.core import md_image_clearance as clearance
    from backend.core.md_job import MdJob

    first = SimpleNamespace(
        job_id="safe",
        parent_job_id="p",
        ensemble_seed=1,
        execution_target="alpine",
        slurm_job_id=None,
    )
    second = SimpleNamespace(**{**vars(first), "job_id": "unsafe"})
    monkeypatch.setattr(MdJob, "list_jobs", lambda _: [first, second])
    monkeypatch.setattr(
        clearance,
        "job_image_clearance",
        lambda job, _: {
            "status": "pass" if job is first else "insufficient",
            "requires_override": job is second,
            "minimum_gap_nm": 3 if job is first else 0.5,
            "detail": "Measured.",
        },
    )
    result = clearance.ensemble_image_clearance(first, tmp_path)
    assert result["requires_override"]
    assert result["review_job_id"] == "unsafe"
    assert result["checked_jobs"] == 2
