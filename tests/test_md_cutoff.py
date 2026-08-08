"""Relaxation early-stop: pure plateau decision + runner skip integration.

Covers md_cutoff.should_early_stop_stage (multi-criteria), the namd_metrics
per-frame parser it consumes, the MdJob.early_stop_relax flag round-trip, and a
stubbed-NAMD run_job proving a plateaued stage's remaining chunks are skipped
(and that the default-OFF flag preserves the old behaviour).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.core import namd_runner as nr
from backend.core.md_cutoff import (
    energy_plateaued,
    wc_plateaued,
    should_early_stop_stage,
)
from backend.core.md_health import HealthCheckResult
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus
from backend.core.namd_metrics import parse_namd_log_frames


# ── pure decision ─────────────────────────────────────────────────────────────
def _flat_frames(n=20, pot=-98000.0, vol=308000.0):
    return [
        {"POTENTIAL": pot + (i % 2) * 5.0, "VOLUME": vol + (i % 2) * 3.0}
        for i in range(n)
    ]


def _trending_frames(n=20):
    return [
        {"POTENTIAL": -90000.0 - 200.0 * i, "VOLUME": 320000.0 - 50.0 * i}
        for i in range(n)
    ]


def test_energy_plateaued_true_on_flat():
    assert energy_plateaued(_flat_frames()) is True


def test_energy_plateaued_false_on_trend():
    assert energy_plateaued(_trending_frames()) is False


def test_energy_plateaued_false_when_too_few_frames():
    assert energy_plateaued(_flat_frames(n=10)) is False  # < min_frames (20)


def test_noisy_but_settled_energy_plateaus():
    """Calibration regression (2026-07-04): a converged mean with realistic
    atomistic thermal noise (~0.2% instantaneous, but ~0% drift) must read as
    plateaued. The old single 0.1% threshold wrongly rejected this on fast runs."""
    import random as _r

    _r.seed(0)
    base = -98000.0
    # mean flat, per-frame scatter ~0.2% (between old eps 0.1% and new fluct eps 0.35%)
    frames = [
        {"POTENTIAL": base * (1 + _r.uniform(-0.002, 0.002)), "VOLUME": 308000.0}
        for _ in range(24)
    ]
    assert energy_plateaued(frames) is True


def test_drifting_mean_not_plateaued_even_if_quiet():
    """A steadily drifting mean (0.15%/chunk, like a still-relaxing low-k stage)
    must NOT read as plateaued even with low scatter — drift is the real signal."""
    frames = [
        {"POTENTIAL": -98000.0 * (1 + 0.00015 * i), "VOLUME": 308000.0}
        for i in range(24)
    ]
    assert energy_plateaued(frames) is False


def test_wc_plateaued_true_and_false():
    assert (
        wc_plateaued([0.95, 0.951, 0.949, 0.95, 0.95, 0.951, 0.95, 0.949, 0.95, 0.95])
        is True
    )
    assert (
        wc_plateaued([1.0, 0.97, 0.94, 0.90, 0.87, 0.84, 0.82, 0.80, 0.79, 0.78])
        is False
    )
    assert wc_plateaued([]) is False


def test_should_early_stop_requires_both():
    flat_wc = [0.95] * 20
    # both flat -> skip
    ok, diag = should_early_stop_stage(_flat_frames(), flat_wc)
    assert ok is True and diag["energy_plateaued"] and diag["wc_plateaued"]
    # energy flat but WC still drifting -> hold (the fragile-low-k case)
    drifting_wc = [1.0 - 0.02 * i for i in range(20)]
    ok2, _ = should_early_stop_stage(_flat_frames(), drifting_wc)
    assert ok2 is False
    # WC flat but energy trending -> hold
    ok3, _ = should_early_stop_stage(_trending_frames(), flat_wc)
    assert ok3 is False


def test_should_early_stop_empty_wc_holds():
    # no structural signal available -> never skip on energy alone
    assert should_early_stop_stage(_flat_frames(), [])[0] is False


# ── per-frame log parser ──────────────────────────────────────────────────────
def test_parse_namd_log_frames_reads_all_and_dedups_resume(tmp_path: Path):
    log = tmp_path / "seg.log"
    log.write_text(
        "ETITLE: TS BOND POTENTIAL VOLUME\n"
        "ENERGY: 0 1 -100.0 3000\n"
        "ENERGY: 100 1 -101.0 3001\n"
        "ETITLE: TS BOND POTENTIAL VOLUME\n"  # restart re-emits header
        "ENERGY: 100 1 -101.0 3001\n"  # duplicate TS at seam -> dropped
        "ENERGY: 200 1 -102.0 3002\n"
    )
    frames = parse_namd_log_frames(log)
    assert [f["TS"] for f in frames] == [0.0, 100.0, 200.0]
    assert frames[-1]["POTENTIAL"] == -102.0


# ── MdJob flag round-trip ─────────────────────────────────────────────────────
def test_early_stop_flag_roundtrip(tmp_path: Path):
    job = MdJob(
        job_id="cut0001",
        design_name="T",
        protocol="p",
        status=MdStatus.queued,
        created_at=0.0,
        package_subdir="package/T",
        name_stem="T",
        segments=[],
        early_stop_relax=True,
    )
    job.save(tmp_path)
    assert MdJob.load(job.job_id, tmp_path).early_stop_relax is True
    # legacy job.json with no field loads as False
    p = tmp_path / "md_jobs" / job.job_id / "job.json"
    d = json.loads(p.read_text())
    del d["early_stop_relax"]
    p.write_text(json.dumps(d))
    assert MdJob.load(job.job_id, tmp_path).early_stop_relax is False


# ── runner integration: a plateaued stage skips its remaining chunks ──────────
_STEM = "T"
_MIN = "T_00_min"


def _multichunk_segments() -> list[dict]:
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
    # stage T_01 has three chunks; stage T_02 a single chunk
    return [
        {
            "name": "T_01_p10",
            "stage": "k=0.5",
            "percent": 10.0,
            "steps": 100,
            "previous": _MIN,
            **common,
        },
        {
            "name": "T_01_p50",
            "stage": "k=0.5",
            "percent": 50.0,
            "steps": 400,
            "previous": "T_01_p10",
            **common,
        },
        {
            "name": "T_01_p100",
            "stage": "k=0.5",
            "percent": 100.0,
            "steps": 500,
            "previous": "T_01_p50",
            **common,
        },
        {
            "name": "T_02_p100",
            "stage": "k=0.1",
            "percent": 100.0,
            "steps": 500,
            "previous": "T_01_p100",
            **common,
        },
    ]


def _setup(tmp_path: Path, early_stop: bool) -> MdJob:
    segs = _multichunk_segments()
    job = MdJob(
        job_id="cutrun01",
        design_name="T",
        protocol="equilibrium_aware_namd",
        status=MdStatus.running,
        created_at=0.0,
        package_subdir="package/T_solv",
        name_stem=_STEM,
        segments=[
            MdSegmentStatus(
                name=s["name"], stage=s["stage"], percent=s["percent"], steps=s["steps"]
            )
            for s in segs
        ],
        current_segment_idx=0,
        early_stop_relax=early_stop,
    )
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    (pkg / "manifest.json").write_text(
        json.dumps(
            {"name_stem": _STEM, "minimization": {"name": _MIN}, "segments": segs}
        )
    )
    for s in segs:
        (pkg / f"{s['name']}.conf").write_text(
            f"outputName output/{s['name']}\nbinCoordinates output/{s['previous']}.coor\nrun {s['steps']}\n"
        )
    job.save(tmp_path)
    return job


def _install_fakes(monkeypatch, recorder: list[str]):
    monkeypatch.setattr(nr, "find_namd", lambda: "/fake/namd3")
    monkeypatch.setattr(
        nr,
        "run_health_check",
        lambda *a, **k: HealthCheckResult(
            passed=True,
            c1_paired_fraction=0.99,
            wc_ref_relative_fraction=0.95,
            wc_per_frame=[0.95] * 20,
        ),
    )

    async def fake_namd(
        namd_bin,
        conf_name,
        package_dir,
        log_path,
        threads,
        devices,
        job_id=None,
        on_spawn=None,
        on_tick=None,
        **_kw,
    ):
        recorder.append(conf_name)
        if on_spawn is not None:
            on_spawn(4242)
        out = package_dir / "output"
        out.mkdir(exist_ok=True)
        base = conf_name.split(".resume")[0]
        for ext in ("coor", "vel", "xsc"):
            (out / f"{base}.{ext}").write_text("x")
        rows = "".join(f"ENERGY: {i * 100} 1 -98000.0 308000.0\n" for i in range(20))
        log_path.write_text(
            "ETITLE: TS BOND POTENTIAL VOLUME\n"
            + rows
            + "WallClock: 1.0\nEnd of program\n"
        )
        return 0, 4242

    monkeypatch.setattr(nr, "_run_namd_async", fake_namd)


def test_early_stop_skips_remaining_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    job = _setup(tmp_path, early_stop=True)
    confs: list[str] = []
    _install_fakes(monkeypatch, confs)

    asyncio.run(nr.run_job(job, tmp_path))

    final = MdJob.load(job.job_id, tmp_path)
    assert final.status == MdStatus.completed
    # p10 ran, then p50+p100 SKIPPED (never spawned), then next stage ran
    assert confs == [_MIN, "T_01_p10", "T_02_p100"]
    # all segments still marked done (stage reached its endpoint early)
    assert [s.status for s in final.segments] == ["done", "done", "done", "done"]
    # ...but the two never-run chunks are flagged skipped so the UI draws a distinct
    # glyph; the chunk that actually ran (and the next stage) are not.
    assert [s.skipped for s in final.segments] == [False, True, True, False]
    # The next stage (T_02_p100) restarts from T_01_p100 — the SKIPPED last chunk,
    # which never ran.  The runner must bridge the chain by aliasing the completed
    # chunk's (T_01_p10) coordinates onto every skipped chunk's expected output
    # names, or NAMD FATALs on the missing extended-system (.xsc) file.
    out = job.package_dir(tmp_path) / "output"
    for skip in ("T_01_p50", "T_01_p100"):
        for ext in ("coor", "vel", "xsc"):
            assert (out / f"{skip}.{ext}").exists(), f"{skip}.{ext} not bridged"
            assert (out / f"{skip}.restart.{ext}").exists(), (
                f"{skip}.restart.{ext} not bridged"
            )


def test_flag_off_runs_every_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job = _setup(tmp_path, early_stop=False)
    confs: list[str] = []
    _install_fakes(monkeypatch, confs)

    asyncio.run(nr.run_job(job, tmp_path))

    assert confs == [_MIN, "T_01_p10", "T_01_p50", "T_01_p100", "T_02_p100"]


# ── mid-run toggle (set_early_stop) ───────────────────────────────────────────
def test_set_early_stop_persists_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    job = _setup(tmp_path, early_stop=False)
    monkeypatch.setattr(nr, "is_running", lambda jid: False)
    nr._EARLY_STOP_OVERRIDE.pop(job.job_id, None)
    assert nr.set_early_stop(job.job_id, True, tmp_path) is True
    # idle → written straight to disk, no override stashed
    assert MdJob.load(job.job_id, tmp_path).early_stop_relax is True
    assert job.job_id not in nr._EARLY_STOP_OVERRIDE


def test_set_early_stop_override_when_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    job = _setup(tmp_path, early_stop=False)
    monkeypatch.setattr(nr, "is_running", lambda jid: True)
    nr._EARLY_STOP_OVERRIDE.pop(job.job_id, None)
    nr.set_early_stop(job.job_id, True, tmp_path)
    # running → stashed as override, disk NOT touched (runner is the sole writer)
    assert nr._EARLY_STOP_OVERRIDE.get(job.job_id) is True
    assert MdJob.load(job.job_id, tmp_path).early_stop_relax is False
    nr._EARLY_STOP_OVERRIDE.pop(job.job_id, None)


def test_pending_early_stop_reports_queued_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The UI reads pending_early_stop to show a queued-but-not-yet-applied toggle
    (so a slow chunk can't make the live toggle look reverted)."""
    job = _setup(tmp_path, early_stop=False)
    monkeypatch.setattr(nr, "is_running", lambda jid: True)
    nr._EARLY_STOP_OVERRIDE.pop(job.job_id, None)
    assert nr.pending_early_stop(job.job_id) is None  # nothing queued
    nr.set_early_stop(job.job_id, True, tmp_path)
    assert nr.pending_early_stop(job.job_id) is True  # queued override surfaced
    nr._EARLY_STOP_OVERRIDE.pop(job.job_id, None)


def test_runner_consumes_midrun_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A job started with early-stop OFF picks up a mid-run override and skips the
    plateaued stage's remaining chunks."""
    job = _setup(tmp_path, early_stop=False)
    confs: list[str] = []
    _install_fakes(monkeypatch, confs)
    nr._EARLY_STOP_OVERRIDE[job.job_id] = True  # toggled on mid-flight
    try:
        asyncio.run(nr.run_job(job, tmp_path))
    finally:
        nr._EARLY_STOP_OVERRIDE.pop(job.job_id, None)

    # consumed at the p10 boundary → p50/p100 skipped, next stage runs
    assert confs == [_MIN, "T_01_p10", "T_02_p100"]
    assert (
        MdJob.load(job.job_id, tmp_path).early_stop_relax is True
    )  # persisted by runner


class TestEarlyStopFrameBudget:
    """The print cadence must give every chunk enough ENERGY frames to be JUDGED.

    This is the silent-failure class of bug: the accelerator is still emitted, still
    runs, and still answers — it just answers HOLD every single time, because the
    evaluator refuses to judge a plateau on too few frames ("insufficient data" fails
    SAFE to "run the whole thing"). Nothing errors. The only symptom is a 4x bill.

    What happened: outputEnergies was a hardcoded 9600 STEPS. Chunk step-counts are
    derived from a target simulated TIME, so enabling `fast` (2 fs -> 4 fs) halves every
    chunk's steps for identical physics — and a step-denominated print interval then
    fires half as often per nanosecond. A p10 chunk fell from 25 frames to 12, under
    min_frames=20, and NO p10 in the ladder could ever bridge.
    """

    # The real 3x6x400 ladder: same simulated time, different timestep.
    P10_AT_2FS = 240_000
    P10_AT_4FS = 120_000  # identical physics — 120k*4fs == 240k*2fs == 480 ps

    def test_frame_count_is_invariant_under_the_timestep(self):
        from backend.core.md_protocols import _output_freq

        frames_2fs = self.P10_AT_2FS // _output_freq(self.P10_AT_2FS)
        frames_4fs = self.P10_AT_4FS // _output_freq(self.P10_AT_4FS)
        assert frames_2fs == frames_4fs, (
            f"the same 480 ps yields {frames_2fs} frames at 2 fs but {frames_4fs} at "
            f"4 fs — enabling `fast` would silently disable early-stop"
        )

    def test_every_chunk_clears_the_evaluators_min_frames(self):
        """Including the SHORTEST chunk (p10), which is the one that saves the most:
        bridging at p10 skips p50+p100, i.e. 90% of the stage."""
        from backend.core.md_cutoff import CutoffParams
        from backend.core.md_protocols import _output_freq

        min_frames = CutoffParams().min_frames
        for steps in (self.P10_AT_4FS, 480_000, 600_000):  # p10, p50, p100 (fast)
            got = steps // _output_freq(steps)
            assert got >= min_frames, (
                f"a {steps}-step chunk yields {got} ENERGY frames but the evaluator "
                f"needs {min_frames} — it will report HOLD forever and never bridge"
            )

    def test_the_cadence_is_a_multiple_of_stepspercycle(self):
        """NAMD wants output intervals aligned to stepspercycle."""
        from backend.core.md_protocols import (
            AKSIMENTIEV_STEPS_PER_CYCLE,
            _output_freq,
        )

        for steps in (120_000, 240_000, 480_000, 600_000, 100):
            assert _output_freq(steps) % AKSIMENTIEV_STEPS_PER_CYCLE == 0

    def test_a_tiny_chunk_still_gets_a_sane_cadence(self):
        from backend.core.md_protocols import _output_freq

        assert _output_freq(100) > 0
        assert _output_freq(0) > 0
