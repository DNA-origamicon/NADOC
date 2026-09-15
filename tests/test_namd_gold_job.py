"""Managed gold lifecycle and fail-closed checkpoint/remote contracts."""

import asyncio
import json

import numpy as np
import pytest

from backend.core import namd_gold_job as gold
from backend.core import gold_model
from backend.core.md_job import MdJob, MdStatus
from backend.core.namd_gold_package import sha


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    def build(package, geometry, **options):
        package.mkdir(parents=True)
        (package/"output").mkdir()
        return dict(gold_model=gold_model.specification(), geometry=geometry, cell_nm=[5.]*3,
                    mobility="mobile", temperature_K=298.15, seed=17, n_atoms=1,
                    asset_sha256={}, validation={}, qualified=False)
    monkeypatch.setattr(gold, "build_package", build)
    return gold.prepare_job(tmp_path, {"kind": "nanoparticle"}, steps=20), tmp_path


def write_checkpoint(package, prefix, step, nonfinite=False):
    xyz = np.array([[np.nan if nonfinite else 1., 2., 3.]], dtype="<f8")
    for ext in ("coor", "vel"):
        (package/"output"/f"{prefix}.{ext}").write_bytes((1).to_bytes(4, "little")+xyz.tobytes())
    (package/"output"/f"{prefix}.xsc").write_text(f"# xsc\n{step} 50 0 0\n")


def test_prepare_snapshot_roundtrip(prepared):
    job, workspace = prepared
    loaded = MdJob.load(job.job_id, workspace)
    assert loaded.protocol == gold.PROTOCOL and loaded.run_kind == "qualification"
    m = json.loads((loaded.package_dir(workspace)/"manifest.json").read_text())
    assert m["qualified"] is False and m["qualification_only"] is True
    assert m["segments"][0]["first_step"] == 200
    assert m["segments"][0]["timestep_fs"] == 1.


def test_checkpoint_rejects_nonfinite(prepared):
    job, workspace = prepared
    package = job.package_dir(workspace)
    write_checkpoint(package, "bad", 200, nonfinite=True)
    with pytest.raises(ValueError, match="nonfinite"):
        gold.checkpoint(package, "bad", 1)


def test_managed_native_and_continuation(prepared, monkeypatch):
    from backend.core import namd_runner
    job, workspace = prepared
    binary = workspace/"namd"
    binary.write_text("pinned executable")
    monkeypatch.setattr(namd_runner, "find_namd", lambda: str(binary))
    calls = []

    async def native(binary, name, package, log, *args, **kwargs):
        calls.append(name)
        m = json.loads((package/"manifest.json").read_text())
        step = 200 if name == "minimize" else next(r["first_step"]+r["steps"] for r in m["segments"] if r["name"] == name)
        write_checkpoint(package, name, step)
        log.write_text("Running with GPU-resident mode\nEnd of program\n")
        return 0, None

    monkeypatch.setattr(namd_runner, "_run_namd_async", native)
    asyncio.run(namd_runner.run_job(job, workspace))
    assert job.status == MdStatus.completed
    previous = sha(job.package_dir(workspace)/"output/gold_001.coor")
    child = gold.extend_job(job.job_id, workspace, steps=30)
    asyncio.run(namd_runner.run_job(child, workspace))
    assert child.status == MdStatus.completed
    assert calls == ["minimize", "gold_001", "gold_002"]
    assert previous == sha(job.package_dir(workspace)/"output/gold_001.coor")
    assert gold.checkpoint(job.package_dir(workspace), "gold_002", 1) == 250


def test_remote_rejected_before_engine_lookup(prepared, monkeypatch):
    from backend.core import namd_runner
    job, workspace = prepared
    job.execution_target = "alpine"
    def forbidden():
        pytest.fail("Remote gold must fail before engine lookup")
    monkeypatch.setattr(namd_runner, "find_namd", forbidden)
    asyncio.run(gold.run_job(job, workspace))
    assert job.status == MdStatus.failed
    assert "local GPU" in job.error


def test_changed_stage_config_fails(prepared, monkeypatch):
    from backend.core import namd_runner
    job, workspace = prepared
    package = job.package_dir(workspace)
    binary = workspace/"namd"
    binary.write_text("engine")
    monkeypatch.setattr(namd_runner, "find_namd", lambda: str(binary))
    job.minimization.status = "done"
    write_checkpoint(package, "minimize", 200)
    with (package/"gold_001.conf").open("a") as f:
        f.write("# altered\n")
    asyncio.run(gold.run_job(job, workspace))
    assert job.status == MdStatus.failed and "configuration differs" in job.error
