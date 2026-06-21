"""Unit tests for the MD-preparation progress tracker (md_prep_progress.py)."""

from __future__ import annotations

import json

import pytest

from backend.core.md_prep_progress import (
    PrepPhase,
    PrepTracker,
    build_prep_phases,
    clear_prep_progress,
    design_size_factor,
    read_prep_progress,
    write_prep_progress,
)


class FakeClock:
    """Manually advanced monotonic clock for deterministic timing tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _tracker(phases=None, clock=None):
    clock = clock or FakeClock()
    phases = phases or [
        PrepPhase("a", "Phase A", nominal_s=10.0),
        PrepPhase("b", "Phase B", nominal_s=30.0),
        PrepPhase("c", "Phase C", nominal_s=10.0),
    ]
    return PrepTracker(phases, clock=clock), clock


# ── Phase list construction ──────────────────────────────────────────────────

def test_build_prep_phases_seeded_prepends_seed():
    seeded = build_prep_phases(seeded=True)
    unseeded = build_prep_phases(seeded=False)
    assert seeded[0].key == "seed"
    assert "seed" not in [p.key for p in unseeded]
    assert len(seeded) == len(unseeded) + 1


def test_build_prep_phases_scales_with_size():
    small = build_prep_phases(seeded=False, size_factor=0.15)
    big = build_prep_phases(seeded=False, size_factor=4.0)
    sm = next(p for p in small if p.key == "solvate")
    bg = next(p for p in big if p.key == "solvate")
    assert bg.nominal_s > sm.nominal_s


def test_design_size_factor_handles_missing_strands():
    class _D:
        strands = []
    assert design_size_factor(_D()) == 1.0


# ── Fraction monotonicity + weighting ────────────────────────────────────────

def test_fraction_starts_low_and_reaches_one_on_finish():
    tr, clock = _tracker()
    assert tr.snapshot()["fraction"] < 0.05
    tr.report("a", 1.0)
    tr.report("b", 1.0)
    tr.report("c", 1.0)
    tr.finish()
    assert tr.snapshot()["fraction"] == 1.0
    assert tr.snapshot()["done"] is True


def test_fraction_is_weighted_by_nominal_duration():
    # Finishing phase "a" (weight 10/50) should land fraction at 0.2.
    tr, clock = _tracker()
    tr.report("a", 1.0)
    tr.enter("b")  # leaving a marks it complete
    snap = tr.snapshot()
    assert snap["fraction"] == pytest.approx(0.2, abs=1e-3)


def test_fraction_never_decreases_within_phase():
    tr, clock = _tracker()
    tr.report("a", 0.5)
    f1 = tr.snapshot()["fraction"]
    tr.report("a", 0.3)  # smaller report must not regress
    f2 = tr.snapshot()["fraction"]
    assert f2 >= f1


# ── Time-fill of opaque phases ───────────────────────────────────────────────

def test_opaque_phase_time_fills_without_reports():
    phases = [PrepPhase("solo", "Opaque", nominal_s=10.0, fill_cap=0.9)]
    clock = FakeClock()
    tr = PrepTracker(phases, clock=clock)
    assert tr.snapshot()["fraction"] == pytest.approx(0.0, abs=1e-3)
    clock.advance(5.0)
    assert tr.snapshot()["fraction"] == pytest.approx(0.5, abs=1e-3)
    clock.advance(100.0)  # would exceed 1.0 but is capped
    assert tr.snapshot()["fraction"] == pytest.approx(0.9, abs=1e-3)


# ── ETA ──────────────────────────────────────────────────────────────────────

def test_eta_present_and_decreases():
    tr, clock = _tracker()
    clock.advance(5.0)
    eta0 = tr.snapshot()["eta_seconds"]
    assert eta0 is not None and eta0 > 0
    tr.report("a", 1.0)
    tr.enter("b")
    clock.advance(15.0)
    eta1 = tr.snapshot()["eta_seconds"]
    assert eta1 < eta0


def test_eta_recalibrates_to_slow_machine():
    # Phase "a" nominal 10 s but actually takes 30 s → remaining estimate scales up.
    tr, clock = _tracker()
    clock.advance(30.0)
    tr.report("a", 1.0)
    tr.enter("b")
    snap = tr.snapshot()
    # speed_factor = 30/10 = 3; remaining nominal = 30 + 10 = 40 → eta ≈ 120 s.
    assert snap["eta_seconds"] == pytest.approx(120.0, rel=0.1)


def test_eta_zero_when_done():
    tr, _ = _tracker()
    tr.finish()
    assert tr.snapshot()["eta_seconds"] == 0.0


# ── Stall warning ────────────────────────────────────────────────────────────

def test_warning_fires_after_soft_threshold():
    phases = [PrepPhase("a", "Phase A", nominal_s=10.0, soft_factor=2.0)]
    clock = FakeClock()
    tr = PrepTracker(phases, clock=clock)
    clock.advance(15.0)
    assert tr.snapshot()["warning"] == ""
    clock.advance(10.0)  # 25 s > 2 × 10 s
    assert "stalled" in tr.snapshot()["warning"]


def test_no_warning_once_done():
    phases = [PrepPhase("a", "Phase A", nominal_s=10.0, soft_factor=2.0)]
    clock = FakeClock()
    tr = PrepTracker(phases, clock=clock)
    clock.advance(100.0)
    tr.finish()
    assert tr.snapshot()["warning"] == ""


# ── Failure ──────────────────────────────────────────────────────────────────

def test_fail_sets_failed_flags_and_blocks_further_reports():
    tr, _ = _tracker()
    tr.report("a", 0.5)
    tr.fail("GROMACS solvate exceeded 300s — aborted")
    snap = tr.snapshot()
    assert snap["failed"] is True
    assert snap["done"] is True
    assert "GROMACS" in snap["error"]
    assert snap["eta_seconds"] is None
    # Reports after failure are ignored.
    tr.report("b", 1.0)
    assert tr.snapshot()["phase"] == "a"


# ── Sidecar persistence ──────────────────────────────────────────────────────

def test_write_read_clear_prep_progress(tmp_path):
    tr, _ = _tracker()
    snap = tr.snapshot()
    write_prep_progress(tmp_path, snap)
    loaded = read_prep_progress(tmp_path)
    assert loaded["phase"] == snap["phase"]
    assert loaded["n_phases"] == 3
    clear_prep_progress(tmp_path)
    assert read_prep_progress(tmp_path) is None


def test_read_prep_progress_missing_returns_none(tmp_path):
    assert read_prep_progress(tmp_path) is None


def test_write_prep_progress_is_valid_json(tmp_path):
    write_prep_progress(tmp_path, {"phase": "x", "fraction": 0.5})
    raw = (tmp_path / "prep_progress.json").read_text()
    assert json.loads(raw)["fraction"] == 0.5


def test_unknown_phase_key_is_ignored():
    tr, _ = _tracker()
    tr.report("does-not-exist", 1.0)
    assert tr.snapshot()["phase"] == "a"
    assert tr.snapshot()["fraction"] < 0.05
