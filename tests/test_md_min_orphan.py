"""A NAMD **minimisation** that outlives its orchestrator must not fail the job.

Real incident (2026-07-12, twice): `just dev` runs uvicorn with `--reload`.  Editing a
backend file restarts the server, so the runner's asyncio task dies — but its NAMD child
keeps going.  `reconcile_job_status` then asked "is a process running for the CURRENT
SEGMENT?", and a minimisation owns no segment name (`..._00_min_enm_k0p5.conf`), so the
answer was no.  It looked at the not-yet-started first segment, found no checkpoint, and
declared the job **failed** — while NAMD was still happily minimising.

Both jobs lost that day were lost this way, during minimisation.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest


def _fake_namd(pkg: Path, tmp_path: Path) -> subprocess.Popen:
    """Spawn a real process that looks like NAMD to /proc: argv[0] contains 'namd' (the
    binary is a copy of `sleep` named namd3) and its cwd is the package dir — exactly
    the two things _package_process_running matches on.  No mocking of /proc."""
    exe = tmp_path / "namd3"
    if not exe.exists():
        shutil.copy(shutil.which("sleep"), exe)
    p = subprocess.Popen([str(exe), "30"], cwd=str(pkg))
    for _ in range(100):                      # wait for /proc to be populated
        if (Path("/proc") / str(p.pid) / "cmdline").exists():
            break
        time.sleep(0.02)
    return p


def _job(tmp_path: Path):
    """A `running` job whose first segment has not started, with its package dir made."""
    from backend.core.md_job import MdSegmentStatus, MdStatus, new_job

    job = new_job("D", "equilibrium_aware", "D", "package/D_namd_solvated")
    job.status = MdStatus.running
    job.current_segment_idx = 0
    job.segments = [
        MdSegmentStatus(name="D_01_300K_NPT_ENM_k0p5_p10", stage="s", percent=10.0,
                        steps=100, status="running"),
    ]
    job.save(tmp_path)
    pkg = job.package_dir(tmp_path)          # workspace/md_jobs/<id>/package/...
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    return job, pkg


@pytest.fixture
def pkg(tmp_path: Path) -> Path:
    d = tmp_path / "package" / "D_namd_solvated"
    (d / "output").mkdir(parents=True)
    return d


def test_package_process_running_sees_a_minimisation(pkg: Path, tmp_path: Path) -> None:
    from backend.core.namd_runner import _package_process_running

    assert _package_process_running(pkg) is False
    proc = _fake_namd(pkg, tmp_path)
    try:
        assert _package_process_running(pkg) is True
    finally:
        proc.kill(); proc.wait()
    assert _package_process_running(pkg) is False


def test_package_process_running_ignores_another_job(pkg: Path, tmp_path: Path) -> None:
    """cwd-matching must not adopt a DIFFERENT job's NAMD."""
    from backend.core.namd_runner import _package_process_running

    other = tmp_path / "package" / "OTHER_namd_solvated"
    other.mkdir(parents=True)
    proc = _fake_namd(other, tmp_path)
    try:
        assert _package_process_running(pkg) is False       # not ours
        assert _package_process_running(other) is True
    finally:
        proc.kill(); proc.wait()


def test_reconcile_does_not_fail_a_job_whose_minimisation_is_still_running(
    tmp_path: Path,
) -> None:
    """THE regression. A live minimisation ⇒ the job stays `running`, not `failed`."""
    from backend.core.md_job import MdStatus
    import backend.core.namd_runner as runner

    job, pkg = _job(tmp_path)
    proc = _fake_namd(pkg, tmp_path)
    try:
        out = runner.reconcile_job_status(job, tmp_path)
        # Before the fix this was MdStatus.failed with "no usable checkpoint".
        assert out.status == MdStatus.running, (
            f"a job whose minimisation is still running was marked {out.status}: {out.error}"
        )
    finally:
        proc.kill(); proc.wait()


def test_reconcile_still_fails_a_job_with_no_process_and_no_checkpoint(
    tmp_path: Path,
) -> None:
    """The fix must not blind the reconciler: a genuinely dead job still fails."""
    from backend.core.md_job import MdStatus
    import backend.core.namd_runner as runner

    job, pkg = _job(tmp_path)
    # The segment is marked `running`, so it was launched — and a launched segment
    # always has a NAMD log.  The log is what separates "died" from "never started";
    # without it this fixture describes a segment that never spawned, which IS
    # resumable (see test_md_resume.TestReconcileDuringMinimisation).
    (pkg / "D_01_300K_NPT_ENM_k0p5_p10.log").write_text(
        "Info: NAMD 3.0.2\nFATAL ERROR: died at startup\n")
    (pkg / "output" / "D_00_min.coor").write_text("minimised")   # minimisation finished
    out = runner.reconcile_job_status(job, tmp_path)     # nothing running at all
    assert out.status == MdStatus.failed
    assert "no usable checkpoint" in (out.error or "")
