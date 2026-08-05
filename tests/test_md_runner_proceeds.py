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
        on_spawn=None, on_tick=None, **_kw
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


def test_wc_only_breach_warns_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A WC-only (advisory, non-blocking) health breach must NOT stop the run —
    it warns and the ladder marches to completed.  This is the 2hb_noT case that
    used to die at the k=0.01 checkpoint on WC 78.4% < 80%."""
    job = _setup_package(tmp_path)
    _install_fakes(monkeypatch)
    monkeypatch.setattr(
        nr,
        "run_health_check",
        lambda *a, **k: HealthCheckResult(
            passed=False, blocking=False,
            reason="WC ref-relative 78.4% < 80.0%",
            c1_paired_fraction=0.99, wc_ref_relative_fraction=0.784,
        ),
    )

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.completed
    assert [s.status for s in final.segments] == ["done", "done"]
    assert final.error is None
    # The advisory breach is still recorded on each checkpoint (not silently dropped).
    assert final.health_samples
    assert all((not s.passed) and (not s.blocking) for s in final.health_samples)


def test_c1_breach_warns_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Health is advisory only — a C1' (backbone) breach no longer stops the run.
    The ladder marches to completed and the breach is recorded as a warning on
    every checkpoint sample (surfaced as a ⚠ in the UI)."""
    job = _setup_package(tmp_path)
    _install_fakes(monkeypatch)
    monkeypatch.setattr(
        nr,
        "run_health_check",
        lambda *a, **k: HealthCheckResult(
            passed=False, blocking=True,
            reason="C1' paired 80.0% < 90.0%",
            c1_paired_fraction=0.80, wc_ref_relative_fraction=0.99,
        ),
    )

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.completed
    assert [s.status for s in final.segments] == ["done", "done"]
    assert final.error is None
    # The below-threshold breach is still recorded on each checkpoint.
    assert final.health_samples
    assert all(not s.passed for s in final.health_samples)


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


def _mark_min_done(job: MdJob, tmp_path: Path) -> None:
    """Pre-place the minimization outputs so run_job skips min and reaches seg 0."""
    out = job.package_dir(tmp_path) / "output"
    for ext in ("coor", "vel", "xsc"):
        (out / f"{_MIN_NAME}.{ext}").write_text("min")


def _install_cell_shrink_fake(
    monkeypatch: pytest.MonkeyPatch, recorder: list[str] | None = None
) -> None:
    """Stub NAMD to crash with the self-healing 'periodic cell too small' fatal,
    leaving a valid mid-segment checkpoint (restart.xsc, no final .coor)."""
    monkeypatch.setattr(nr, "find_namd", lambda: "/fake/namd3")

    async def fake_namd(
        namd_bin, conf_name, package_dir, log_path, threads, devices, job_id=None,
        on_spawn=None, on_tick=None, **_kw
    ):
        if recorder is not None:
            recorder.append(conf_name)
        if on_spawn is not None:
            on_spawn(4242)
        out = package_dir / "output"
        out.mkdir(exist_ok=True)
        base = conf_name.split(".resume")[0]
        # Checkpoint present, final output absent → the crash is resumable.
        for ext in ("coor", "vel"):
            (out / f"{base}.restart.{ext}").write_text("checkpoint")
        (out / f"{base}.restart.xsc").write_text(
            "# restart\n#$LABELS step a_x\n500 138.9\n"
        )
        log_path.write_text(
            "ENERGY: 500 300 300 1 1 100 1 1\n"
            "FATAL ERROR: Periodic cell has become too small for original patch grid!\n"
            "End of program\n"
        )
        return 1, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)


def test_cell_shrink_auto_resumes_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 'periodic cell too small' fatal with a live checkpoint must leave the job
    RUNNING (resumable) with the per-segment resume counter bumped — not failed —
    so the supervisor restarts it and the patch grid rebuilds for the shrunk box."""
    job = _setup_package(tmp_path)
    _mark_min_done(job, tmp_path)
    job.save(tmp_path)
    confs: list[str] = []
    _install_cell_shrink_fake(monkeypatch, confs)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.running
    assert final.segments[0].status == "running"
    assert final.segments[0].auto_resumes == 1
    assert final.failure_kind is None
    assert "auto-resuming" in (final.error or "").lower()
    assert _MIN_NAME not in confs  # minimization was skipped


def test_cell_shrink_gives_up_after_resume_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the per-segment auto-resume budget is spent, a repeat cell-shrink fatal
    fails the job (classified 'cell_shrink') rather than resuming forever."""
    job = _setup_package(tmp_path)
    _mark_min_done(job, tmp_path)
    job.segments[0].auto_resumes = nr.MAX_CELL_SHRINK_RESUMES
    job.save(tmp_path)
    _install_cell_shrink_fake(monkeypatch)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.failed
    assert final.segments[0].status == "failed"
    assert final.failure_kind == "cell_shrink"


def _install_host_oom_fake(
    monkeypatch: pytest.MonkeyPatch, recorder: list[str] | None = None
) -> None:
    """Stub NAMD to crash with a host pinned-memory OOM at the FIRST integration step
    (cudaHostAlloc in the bonded-CUDA path) — i.e. AFTER startup but with NO
    mid-segment checkpoint written, the way a transient host starvation aborts."""
    monkeypatch.setattr(nr, "find_namd", lambda: "/fake/namd3")

    async def fake_namd(
        namd_bin, conf_name, package_dir, log_path, threads, devices, job_id=None,
        on_spawn=None, on_tick=None, **_kw
    ):
        if recorder is not None:
            recorder.append(conf_name)
        if on_spawn is not None:
            on_spawn(4242)
        (package_dir / "output").mkdir(exist_ok=True)  # no restart files: step-0 death
        log_path.write_text(
            "Info: Finished startup at 7.1 s\n"
            "TCL: Running for 480000 steps\n"
            "FATAL ERROR: CUDA error cudaHostAlloc(pp, sizeofT*(*curlen), flag) in "
            "file src/CudaUtils.C, function reallocate_host_T, line 208\n"
            " on Pe 2 (device 0): out of memory\n"
            "  ComputeBondedCUDA::copyTupleDataSN()\n"
        )
        return 1, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)


def test_host_oom_auto_resumes_without_a_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host pinned-memory OOM is transient, so the job stays RUNNING (resumable)
    and the resume counter bumps — even though the step-0 death left no checkpoint
    (it re-runs the segment fresh from the previous segment's coordinates)."""
    job = _setup_package(tmp_path)
    _mark_min_done(job, tmp_path)
    job.save(tmp_path)
    _install_host_oom_fake(monkeypatch)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.running
    assert final.segments[0].status == "running"
    assert final.segments[0].auto_resumes == 1
    assert final.failure_kind is None
    assert "auto-resuming" in (final.error or "").lower()


def test_host_oom_gives_up_after_resume_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the host-OOM auto-resume budget is spent, a repeat failure fails the job
    (classified 'host_oom' → the host-OOM Fix popup) instead of looping forever."""
    job = _setup_package(tmp_path)
    _mark_min_done(job, tmp_path)
    job.segments[0].auto_resumes = nr.MAX_HOST_OOM_RESUMES
    job.save(tmp_path)
    _install_host_oom_fake(monkeypatch)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.failed
    assert final.segments[0].status == "failed"
    assert final.failure_kind == "host_oom"


# ── instability (RATTLE) auto-soften-and-resume ────────────────────────────────

def _make_confs_hard(job: MdJob, tmp_path: Path) -> None:
    """Give every segment conf the fast ladder's rigidBonds all + 4 fs, so the softener
    has something to flip (the base _seg_conf_text has neither)."""
    pkg = job.package_dir(tmp_path)
    for seg in job.segments:
        conf = pkg / f"{seg.name}.conf"
        conf.write_text(conf.read_text() + "rigidBonds         all\ntimestep           4\n")


def _install_instability_fake(
    monkeypatch: pytest.MonkeyPatch, recorder: list[str] | None = None
) -> None:
    """Stub NAMD to blow up with a RATTLE constraint failure (rigid-bond instability),
    the way a strained seed aborts when the restraint ladder loosens."""
    monkeypatch.setattr(nr, "find_namd", lambda: "/fake/namd3")

    async def fake_namd(
        namd_bin, conf_name, package_dir, log_path, threads, devices, job_id=None,
        on_spawn=None, on_tick=None, **_kw
    ):
        if recorder is not None:
            recorder.append(conf_name)
        if on_spawn is not None:
            on_spawn(4242)
        (package_dir / "output").mkdir(exist_ok=True)  # step-0 death: no checkpoint
        log_path.write_text(
            "ENERGY: 0 300 300 1 1 100 1 1\n"
            "ERROR: Constraint failure in RATTLE algorithm for atom 9409!\n"
            "ERROR: Constraint failure; simulation has become unstable.\n"
            "FATAL ERROR: Exiting prematurely; see error messages above.\n"
        )
        return 1, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)


def test_instability_softens_ladder_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A RATTLE blow-up on the hard (rigidBonds all + 4 fs) ladder must SOFTEN every
    remaining segment to rigidBonds none + 1 fs, keep a .conf.hard backup, and leave the
    job RUNNING (resumable) so the supervisor relaunches it gently — not fail."""
    job = _setup_package(tmp_path)
    _mark_min_done(job, tmp_path)
    _make_confs_hard(job, tmp_path)
    job.save(tmp_path)
    _install_instability_fake(monkeypatch)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.running
    assert final.segments[0].status == "running"
    assert final.segments[0].auto_resumes == 1
    assert final.failure_kind is None
    assert "soft" in (final.error or "").lower()

    pkg = job.package_dir(tmp_path)
    for seg in job.segments:               # failing + every later segment softened
        text = (pkg / f"{seg.name}.conf").read_text()
        assert "rigidBonds         none" in text
        assert "timestep           1" in text
        assert (pkg / f"{seg.name}.conf.hard").exists()


def test_instability_gives_up_after_resume_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the (single) instability auto-resume is spent, a repeat RATTLE fails the job
    (classified 'instability' → the gentler-relaxation Fix popup) instead of looping."""
    job = _setup_package(tmp_path)
    _mark_min_done(job, tmp_path)
    _make_confs_hard(job, tmp_path)
    job.segments[0].auto_resumes = nr.MAX_INSTABILITY_RESUMES
    job.save(tmp_path)
    _install_instability_fake(monkeypatch)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.failed
    assert final.segments[0].status == "failed"
    assert final.failure_kind == "instability"


def test_instability_on_an_already_soft_segment_fails_without_looping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a conf is ALREADY soft (no rigidBonds all) and STILL blows up, there is nothing
    to soften → the job fails (seed genuinely un-relaxable) rather than resuming forever.
    The resume counter is never bumped (softening rewrote nothing)."""
    job = _setup_package(tmp_path)          # base confs have no rigidBonds all
    _mark_min_done(job, tmp_path)
    job.save(tmp_path)
    _install_instability_fake(monkeypatch)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.failed
    assert final.failure_kind == "instability"
    assert final.segments[0].auto_resumes == 0


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


# ── GPU tile-list pre-flight → CPU auto-routing ───────────────────────────────
#
# NAMD 3.0.2's CUDA buildTileLists kernel dies on the first step for certain
# (patch-grid x atom-density) geometries.  run_job probes for it and reroutes a
# genuinely-unsafe package to the CPU build instead of crashing.  See LESSONS K2.

def _install_gpu_fakes(monkeypatch, gpu_safe: bool, launched: list[tuple[str, str]]):
    """CUDA build resolved for the job; probe returns *gpu_safe*; record what ran."""
    _install_fakes(monkeypatch)
    monkeypatch.setattr(nr, "resolve_namd_launch", lambda *a, **k: ("/fake/cuda-namd3", "0"))
    monkeypatch.setattr(nr, "namd_is_cuda_build", lambda b: "cuda" in b)
    monkeypatch.setattr(nr, "find_namd", lambda **k: "/fake/cpu-namd3")
    monkeypatch.setattr(nr, "gpu_tilelist_probe", lambda *a, **k: gpu_safe)

    async def fake_namd(namd_bin, conf_name, package_dir, log_path, threads, devices,
                        job_id=None, on_spawn=None, on_tick=None, **_kw):
        launched.append((namd_bin, devices))
        if on_spawn is not None:
            on_spawn(4242)
        out = package_dir / "output"
        out.mkdir(exist_ok=True)
        base = conf_name.split(".resume")[0]
        for ext in ("coor", "vel", "xsc"):
            (out / f"{base}.{ext}").write_text("x")
        log_path.write_text(
            "ETITLE: TS TEMP TEMPAVG PRESSURE GPRESSURE VOLUME PRESSAVG GPRESSAVG\n"
            "ENERGY: 1000 300 300 1 1 100 1 1\n"
            "WallClock: 1.0  CPUTime: 1.0  Memory: 1.0 MB\nEnd of program\n"
        )
        return 0, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)


def test_gpu_unsafe_geometry_ASKS_before_rerouting_to_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe says the geometry trips the tile-list bug → PAUSE and ask (Gate B2).

    REPLACES test_gpu_unsafe_geometry_reroutes_to_cpu_build, which asserted the silent
    reroute. The CPU build is ~12x slower; swapping to it behind the user's back changed
    the cost of the run by an order of magnitude with only a log line to show for it.
    """
    job = _setup_package(tmp_path)
    launched: list[tuple[str, str]] = []
    _install_gpu_fakes(monkeypatch, gpu_safe=False, launched=launched)

    asyncio.run(nr.run_job(job, tmp_path))

    assert not launched, "nothing may run until the user has chosen"
    saved = MdJob.load(job.job_id, tmp_path)
    assert saved.status == MdStatus.paused
    assert saved.decision["gate"] == "cpu_reroute"
    assert [o["id"] for o in saved.decision["options"]] == ["cpu", "cancel"]


def test_an_accepted_cpu_reroute_runs_without_asking_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once chosen, the reroute is a recorded decision — not a question every resume."""
    job = _setup_package(tmp_path)
    job.prep_params = {**(job.prep_params or {}), "cpu_reroute_accepted": True}
    job.save(tmp_path)
    launched: list[tuple[str, str]] = []
    _install_gpu_fakes(monkeypatch, gpu_safe=False, launched=launched)

    asyncio.run(nr.run_job(job, tmp_path))

    assert launched, "an accepted reroute should run"
    assert all(b == "/fake/cpu-namd3" for b, _ in launched), launched
    assert all(d == "" for _, d in launched), launched
    assert MdJob.load(job.job_id, tmp_path).status == MdStatus.completed


def test_gpu_safe_geometry_stays_on_cuda_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: a safe geometry must NOT be demoted to the CPU build."""
    job = _setup_package(tmp_path)
    launched: list[tuple[str, str]] = []
    _install_gpu_fakes(monkeypatch, gpu_safe=True, launched=launched)

    asyncio.run(nr.run_job(job, tmp_path))

    assert launched
    assert all(b == "/fake/cuda-namd3" for b, _ in launched), launched
    assert all(d == "0" for _, d in launched), launched


def test_cpu_job_never_pays_for_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compute=CPU already routes to the CPU build — probing it would just waste 15 s."""
    job = _setup_package(tmp_path)
    job.devices = "cpu"
    job.save(tmp_path)
    launched: list[tuple[str, str]] = []
    _install_fakes(monkeypatch)
    monkeypatch.setattr(nr, "resolve_namd_launch", lambda *a, **k: ("/fake/cpu-namd3", ""))

    probed: list[int] = []
    monkeypatch.setattr(nr, "gpu_tilelist_probe",
                        lambda *a, **k: probed.append(1) or True)

    async def fake_namd(namd_bin, conf_name, package_dir, log_path, threads, devices,
                        job_id=None, on_spawn=None, on_tick=None, **_kw):
        launched.append((namd_bin, devices))
        out = package_dir / "output"
        out.mkdir(exist_ok=True)
        base = conf_name.split(".resume")[0]
        for ext in ("coor", "vel", "xsc"):
            (out / f"{base}.{ext}").write_text("x")
        log_path.write_text("WallClock: 1.0\nEnd of program\n")
        return 0, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)
    asyncio.run(nr.run_job(job, tmp_path))

    assert probed == [], "a Compute=CPU job must not run the GPU pre-flight probe"
