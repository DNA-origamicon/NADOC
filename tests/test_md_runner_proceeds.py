"""End-to-end validation that the NAMD runner state machine *proceeds* correctly.

These tests stub the NAMD subprocess (and the health check) so the full
``run_job`` coroutine can run in-process in milliseconds.  They assert the UX-
critical invariants that the real system depends on:

  * a fresh job marches through every segment to ``completed``;
  * a job interrupted mid-segment resumes from its checkpoint (a resume conf is
    generated) rather than restarting the segment from scratch;
  * a resumed job never keeps a stale "interrupted / stopped" message in
    ``error`` once it is running again (the bug where the sidebar showed
    "resume to continue from ..." on a live run);
  * re-running ``run_job`` on an already-finished job is idempotent.

No NAMD, GROMACS, or MDAnalysis required.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.core import namd_runner as nr
from backend.core.md_health import HealthCheckResult
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus


_NAME_STEM = "T"
_MIN_NAME = "T_00_min"


def _segment_dicts() -> list[dict]:
    common = dict(
        temp=300.0,
        damping=5.0,
        scale=None,
        npt=True,
        reinit=False,
        dcd_freq=100,
        min_c1_paired=0.9,
        min_wc_ref_relative=0.85,
    )
    return [
        {
            "name": "T_01_p100",
            "stage": "300K NPT ENM k=0.5",
            "percent": 100.0,
            "steps": 1000,
            "previous": _MIN_NAME,
            **common,
        },
        {
            "name": "T_02_p100",
            "stage": "300K NPT ENM k=0.1",
            "percent": 100.0,
            "steps": 1000,
            "previous": "T_01_p100",
            **common,
        },
    ]


def _seg_conf_text(name: str, previous: str) -> str:
    return (
        f"outputName         output/{name}\n"
        f"dcdFile            output/{name}.dcd\n"
        f"dcdFreq            100\n"
        f"xstFile            output/{name}.xst\n"
        f"binCoordinates     output/{previous}.coor\n"
        f"binVelocities      output/{previous}.vel\n"
        f"extendedSystem     output/{previous}.xsc\n"
        f"run                1000\n"
    )


def _setup_package(tmp_path: Path) -> MdJob:
    segs = _segment_dicts()
    job = MdJob(
        job_id="proceed0001",
        design_name="T",
        protocol="equilibrium_aware_namd",
        status=MdStatus.running,
        created_at=0.0,
        package_subdir="package/T_solv",
        name_stem=_NAME_STEM,
        segments=[
            MdSegmentStatus(
                name=s["name"], stage=s["stage"], percent=s["percent"], steps=s["steps"]
            )
            for s in segs
        ],
        current_segment_idx=0,
    )
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name_stem": _NAME_STEM,
        "minimization": {"name": _MIN_NAME},
        "segments": segs,
    }
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    for s in segs:
        (pkg / f"{s['name']}.conf").write_text(_seg_conf_text(s["name"], s["previous"]))
    job.save(tmp_path)
    return job


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, recorder: list[str] | None = None
) -> None:
    """Stub NAMD execution + health so run_job can complete in-process."""
    monkeypatch.setattr(nr, "find_namd", lambda: "/fake/namd3")
    monkeypatch.setattr(
        nr,
        "run_health_check",
        lambda *a, **k: HealthCheckResult(
            passed=True,
            c1_paired_fraction=0.99,
            wc_ref_relative_fraction=0.9,
        ),
    )

    async def fake_namd(
        namd_bin, conf_name, package_dir, log_path, threads, devices, job_id=None,
        on_spawn=None,
    ):
        if recorder is not None:
            recorder.append(conf_name)
        if on_spawn is not None:
            on_spawn(4242)
        out = package_dir / "output"
        out.mkdir(exist_ok=True)
        # A resume conf (<seg>.resumeN) keeps the segment's outputName, so its
        # final files land under the bare segment name.
        base = conf_name.split(".resume")[0]
        for ext in ("coor", "vel", "xsc"):
            (out / f"{base}.{ext}").write_text("x")
        log_path.write_text(
            "ETITLE: TS TEMP TEMPAVG PRESSURE GPRESSURE VOLUME PRESSAVG GPRESSAVG\n"
            "ENERGY: 1000 300 300 1 1 100 1 1\n"
            "WallClock: 1.0  CPUTime: 1.0  Memory: 1.0 MB\n"
            "End of program\n"
        )
        return 0, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)


def test_fresh_job_marches_to_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _setup_package(tmp_path)
    confs: list[str] = []
    _install_fakes(monkeypatch, confs)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.completed
    assert final.current_segment_idx == 2
    assert [s.status for s in final.segments] == ["done", "done"]
    assert final.error is None
    # ran minimization + both segments, in order, none resumed
    assert confs == [_MIN_NAME, "T_01_p100", "T_02_p100"]


def test_resume_clears_stale_error_and_uses_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _setup_package(tmp_path)
    pkg = job.package_dir(tmp_path)
    out = pkg / "output"
    # Minimization already done; segment 0 interrupted mid-run with a full
    # NAMD checkpoint set (.coor/.vel/.xsc) but no final output yet.
    for ext in ("coor", "vel", "xsc"):
        (out / f"{_MIN_NAME}.{ext}").write_text("min")
        (out / f"T_01_p100.restart.{ext}").write_text("checkpoint")
    (out / "T_01_p100.restart.xsc").write_text(
        "# restart\n#$LABELS step a_x\n500 138.9\n"
    )
    # A stale interruption message must not survive into the running state.
    job.error = "Interrupted during T_01_p100 at step 500/1000; resume to continue."
    job.save(tmp_path)

    confs: list[str] = []
    _install_fakes(monkeypatch, confs)
    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.completed
    assert final.error is None
    # segment 0 was resumed (resume conf), not restarted from scratch
    assert (pkg / "T_01_p100.resume1.conf").exists()
    assert "T_01_p100.resume1" in confs
    # minimization was skipped (its .coor already existed)
    assert _MIN_NAME not in confs


def test_rerun_on_completed_job_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _setup_package(tmp_path)
    confs: list[str] = []
    _install_fakes(monkeypatch, confs)
    asyncio.run(nr.run_job(job, tmp_path))

    # Re-run from the persisted completed state: no NAMD should be launched.
    reran = MdJob.load(job.job_id, tmp_path)
    reran.status = MdStatus.running  # pretend a supervisor relaunched it
    confs.clear()
    asyncio.run(nr.run_job(reran, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.completed
    # segments already complete → skipped, nothing re-executed
    assert confs == []
