"""Crash recovery for an interrupted oxDNA stage.

Motivated by a real loss: the host restarted mid-production, NADOC resumed from the
stage's ``last_conf.dat``, that resumed run diverged ("Invalid cell … pos: inf"), and the
job then reported **0 %** despite having banked 26.6 M of 50 M steps. Three separate
defects, one per section below.
"""
from __future__ import annotations

import pytest

from backend.core.oxdna_protocol import OxdnaStageSpec
from backend.core.oxdna_runner import (
    conf_is_restartable,
    last_complete_trajectory_frame,
    resume_point,
    stage_completed_steps,
    stage_fraction,
)

N = 8                    # particles in the toy configurations
STEPS = 1_000_000
EVERY = STEPS // 100     # print_energy_every = 10_000


def _spec(**kw) -> OxdnaStageSpec:
    base = dict(name="1_production", kind="production", sim_type="MD",
                steps=STEPS, backend="CUDA")
    base.update(kw)
    return OxdnaStageSpec(**base)


def _frame(step: int, *, particles: int = N, jitter: float = 0.0) -> str:
    """One well-formed oxDNA configuration frame."""
    head = f"t = {step}\nb = 100 100 100\nE = -1.0 -1.2 0.2\n"
    row = " ".join(["{:.4f}"] * 15)
    body = "".join(
        row.format(*[i + jitter + c * 0.01 for c in range(15)]) + "\n"
        for i in range(particles)
    )
    return head + body


def _energy(rows: int) -> str:
    """`rows` energy lines — row 0 is the starting state, so this represents
    (rows-1)*EVERY simulated steps."""
    return "".join(f"{i*EVERY*0.005:14.4f}  -1.24  0.29  -0.95 \n" for i in range(rows))


@pytest.fixture
def stage(tmp_path):
    d = tmp_path / "1_production"
    d.mkdir()
    return d


# ── 1. A torn checkpoint must be detected, not loaded ────────────────────────────

def test_intact_last_conf_is_restartable(stage):
    (stage / "last_conf.dat").write_text(_frame(500_000))
    assert conf_is_restartable(stage / "last_conf.dat", N)


@pytest.mark.parametrize("corrupt,label", [
    (lambda t: t.rsplit("\n", 2)[0] + "\n", "truncated mid-frame"),
    (lambda t: t.replace("4.0400", "inf"), "non-finite coordinate"),
    (lambda t: "\n".join(ln[:20] for ln in t.splitlines()), "short columns"),
    (lambda t: "", "empty"),
])
def test_torn_last_conf_is_rejected(stage, corrupt, label):
    """A crash during the in-place last_conf.dat rewrite leaves a file of plausible size
    but inconsistent contents. A size>0 check (the old behaviour) lets it through; oxDNA
    then loads it and diverges millions of steps later."""
    (stage / "last_conf.dat").write_text(corrupt(_frame(500_000)))
    assert not conf_is_restartable(stage / "last_conf.dat", N), label


def test_torn_checkpoint_falls_back_to_last_complete_trajectory_frame(stage):
    (stage / "trajectory.dat").write_text(_frame(100_000) + _frame(200_000) + _frame(300_000))
    (stage / "energy.dat").write_text(_energy(31))          # 30*EVERY = 300_000 steps
    (stage / "last_conf.dat").write_text(_frame(300_000)[:-40])  # torn tail
    conf, consumed, note = resume_point(stage, _spec(), N)
    assert conf is not None and conf.name == "restart_conf.dat"
    assert conf.read_text().startswith("t = 300000")
    assert consumed == 300_000, f"expected the frame's own step, got {consumed}"
    assert "TORN" in note


def test_recovered_conf_is_written_to_a_separate_file(stage):
    """oxDNA's conf_file and lastconf_file were both last_conf.dat, so a resumed run
    overwrote the very checkpoint it started from — making a second crash unrecoverable.
    The recovered frame must land somewhere the run will not clobber."""
    (stage / "trajectory.dat").write_text(_frame(100_000))
    (stage / "last_conf.dat").write_text("garbage")
    conf, _consumed, _note = resume_point(stage, _spec(), N)
    assert conf.name == "restart_conf.dat"
    assert (stage / "last_conf.dat").read_text() == "garbage", "must not touch last_conf"


def test_truncated_final_trajectory_frame_is_skipped(stage):
    (stage / "trajectory.dat").write_text(_frame(100_000) + _frame(200_000) + "t = 300000\nb = 1 1 1\n")
    found = last_complete_trajectory_frame(stage / "trajectory.dat", N)
    assert found is not None
    _text, step = found
    assert step == 200_000, "the half-written tail frame must not be offered as a restart point"


def test_no_usable_restart_point_is_reported_not_guessed(stage):
    (stage / "last_conf.dat").write_text("garbage")
    conf, _consumed, note = resume_point(stage, _spec(), N)
    assert conf is None and "no complete trajectory frame" in note


# ── 2. A diverged attempt must be discarded, not resumed from ────────────────────

def test_diverged_attempt_is_skipped_in_favour_of_the_previous_one(stage):
    """error_conf.dat means oxDNA aborted on a blown-up structure. That attempt's
    checkpoint is already on its way to inf, so resuming from it just reproduces the
    divergence — the real fix is to fall back to the attempt that ended cleanly."""
    (stage / "trajectory.r1.dat").write_text(_frame(100_000) + _frame(200_000))   # good attempt
    (stage / "energy.r1.dat").write_text(_energy(21))                     # 200_000 steps
    (stage / "trajectory.dat").write_text(_frame(50_000))                    # diverged attempt
    (stage / "energy.dat").write_text(_energy(6))                         # 50_000 steps
    (stage / "last_conf.dat").write_text(_frame(50_000))                     # parses fine!
    (stage / "error_conf.dat").write_text(_frame(50_000, jitter=float("inf")))

    conf, consumed, note = resume_point(stage, _spec(), N)
    assert conf.read_text().startswith("t = 200000"), "must come from the pre-divergence attempt"
    assert "DIVERGED" in note
    # 200_000 banked by attempt 1; the diverged attempt's 50_000 is thrown away.
    assert consumed == 200_000


def test_intact_checkpoint_is_preferred_when_nothing_diverged(stage):
    (stage / "trajectory.dat").write_text(_frame(100_000) + _frame(200_000))
    (stage / "energy.dat").write_text(_energy(21))
    (stage / "last_conf.dat").write_text(_frame(200_000))
    conf, consumed, note = resume_point(stage, _spec(), N)
    assert conf.name == "last_conf.dat" and "intact" in note
    assert consumed == 200_000
    assert not (stage / "restart_conf.dat").exists(), "no need to materialise a copy"


# ── 3. Banked work must be visible, and must not be re-run ───────────────────────

def test_progress_sums_every_attempt(stage):
    """The bug the user saw: after the resume archived run 1's energy.dat to
    energy.r1.dat, progress counted only the new (tiny) energy.dat."""
    (stage / "energy.r1.dat").write_text(_energy(54))    # 53 * EVERY = 530_000
    (stage / "energy.dat").write_text(_energy(8))        #  7 * EVERY =  70_000
    assert stage_completed_steps(stage, _spec()) == 600_000
    assert stage_fraction(stage, _spec()) == pytest.approx(0.6)


def test_progress_excludes_a_diverged_attempt(stage):
    (stage / "energy.r1.dat").write_text(_energy(54))    # 530_000 kept
    (stage / "energy.dat").write_text(_energy(8))        #  70_000 discarded
    (stage / "error_conf.dat").write_text("boom")
    assert stage_completed_steps(stage, _spec()) == 530_000


def test_progress_is_cheap_and_writes_nothing(stage):
    """stage_fraction runs on the job-list poll path — it must not scan a multi-GB
    trajectory or materialise restart_conf.dat as a side effect."""
    (stage / "energy.r1.dat").write_text(_energy(54))
    (stage / "trajectory.r1.dat").write_text(_frame(100_000) * 50)
    (stage / "error_conf.dat").write_text("boom")
    before = {p.name for p in stage.iterdir()}
    stage_fraction(stage, _spec())
    assert {p.name for p in stage.iterdir()} == before


def test_cheap_and_authoritative_agree_within_one_frame_interval(stage):
    (stage / "trajectory.r1.dat").write_text("".join(_frame(s) for s in range(100_000, 600_000, 100_000)))
    (stage / "energy.r1.dat").write_text(_energy(51))     # 500_000
    (stage / "last_conf.dat").write_text(_frame(500_000))
    cheap = stage_completed_steps(stage, _spec())
    _conf, authoritative, _note = resume_point(stage, _spec(), N)
    assert abs(cheap - authoritative) <= EVERY


def test_zero_step_spec_does_not_divide_by_zero(stage):
    assert stage_fraction(stage, _spec(steps=0)) == 0.0


# ── 4. Banked steps must not survive a from-scratch restart ──────────────────────

def test_production_retry_clears_banked_steps():
    """A production retry halves dt and restarts the stage from the RELAXED SEED, so it
    begins at step 0. Real regression: the banked 26,600,000 from an earlier resume was
    left on the stage, so a rerun that was 20 % done reported 63 %."""
    from backend.core.oxdna_job import OxdnaJob, OxdnaStageStatus, OxdnaStatus
    from backend.core.oxdna_runner import _halve_dt_and_restart
    import tempfile
    from pathlib import Path as _P

    with tempfile.TemporaryDirectory() as td:
        ws = _P(td)
        job = OxdnaJob(job_id="j", design_name="d", status=OxdnaStatus.running,
                       created_at=0.0, n_nucleotides=N)
        job.stages = [OxdnaStageStatus(name="1_production", kind="production",
                                       steps=STEPS, status="failed", resumed=True,
                                       completed_steps=26_600_000)]
        (ws / "oxdna_jobs" / "j" / "1_production").mkdir(parents=True)
        specs = [_spec(dt=0.005)]
        _halve_dt_and_restart(job, ws, specs, 0)

        assert specs[0].dt == 0.0025, "retry must halve the timestep"
        assert job.stages[0].resumed is False
        assert job.stages[0].completed_steps == 0, (
            "a from-scratch restart must bank nothing — otherwise progress is inflated "
            "by the discarded attempt")
