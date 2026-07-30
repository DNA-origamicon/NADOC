"""Ladder chunking: how finely each ENM stage is cut into resumable/skippable pieces.

The tutorial does not chunk at all — each k runs for a flat 4.8 ns.  Chunking is a NADOC
addition, and the original 10/50/100 split was arbitrary.  It sets two things:

  * how much of an already-settled stage ``early_stop_relax`` has to pay for (it can only
    cut at a boundary), and
  * how finely "how much ladder do we actually need" can be read off an ordinary relax,
    since health and energy are sampled per chunk.

Total simulated time must NOT change with the split — that would be a science change
smuggled in as a scheduling one.
"""
from __future__ import annotations

import pytest

from backend.core.md_protocols import (LADDER_CHUNK_PCTS, LADDER_CHUNK_PCTS_COARSE,
                                       _chunk_fractions, mgh_slow_release_segments)


def _total_ns(segments, timestep_fs=2.0):
    return sum(s.steps * timestep_fs / 1e6 for s in segments)


# ── the fraction derivation ───────────────────────────────────────────────────
def test_fractions_are_increments_of_the_cumulative_percents():
    assert _chunk_fractions((10.0, 50.0, 100.0)) == [
        (10.0, 0.10), (50.0, 0.40), (100.0, 0.50)]


def test_fractions_sum_to_one_for_any_valid_split():
    for pcts in ((100.0,), (10.0, 50.0, 100.0), LADDER_CHUNK_PCTS,
                 (5.0, 10.0, 20.0, 40.0, 80.0, 100.0)):
        assert sum(f for _p, f in _chunk_fractions(pcts)) == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [
    (10.0, 10.0, 100.0),      # not ascending
    (10.0, 50.0),             # does not reach 100
    (0.0, 100.0),             # zero-length first chunk
    (10.0, 120.0),            # past 100
])
def test_invalid_splits_are_rejected(bad):
    with pytest.raises(ValueError):
        _chunk_fractions(bad)


# ── the ladder ────────────────────────────────────────────────────────────────
def test_default_split_is_finer_than_the_historical_one():
    assert len(LADDER_CHUNK_PCTS) > len(LADDER_CHUNK_PCTS_COARSE)
    _, fine = mgh_slow_release_segments("X")
    _, coarse = mgh_slow_release_segments("X", chunk_pcts=LADDER_CHUNK_PCTS_COARSE)
    assert len(fine) > len(coarse)


def test_total_simulated_time_is_unchanged_by_the_split():
    """Finer chunking is a scheduling change, not a science change."""
    _, fine = mgh_slow_release_segments("X")
    _, coarse = mgh_slow_release_segments("X", chunk_pcts=LADDER_CHUNK_PCTS_COARSE)
    assert _total_ns(fine) == pytest.approx(_total_ns(coarse), rel=1e-3)


def test_finer_chunks_halve_the_worst_case_early_stop_waste():
    """early_stop can only cut at a boundary, so the largest chunk is the most time a
    settled stage can still burn."""
    _, fine = mgh_slow_release_segments("X")
    _, coarse = mgh_slow_release_segments("X", chunk_pcts=LADDER_CHUNK_PCTS_COARSE)
    assert max(s.steps for s in fine) < max(s.steps for s in coarse)
    assert max(s.steps for s in fine) <= 0.55 * max(s.steps for s in coarse)


def test_every_stage_gets_the_same_chunk_labels_ending_at_p100():
    _, segs = mgh_slow_release_segments("X")
    by_stage: dict[str, list[float]] = {}
    for s in segs:
        by_stage.setdefault(s.stage, []).append(s.percent)
    assert len(by_stage) == 4                     # k=0.5, 0.1, 0.01, and k=0
    for pcts in by_stage.values():
        assert pcts == list(LADDER_CHUNK_PCTS)


def test_chunk_names_match_their_cumulative_percent():
    _, segs = mgh_slow_release_segments("X")
    for s in segs:
        assert s.name.endswith(f"_p{int(s.percent)}")


def test_restraint_schedule_and_soft_start_survive_the_finer_split():
    """The k ladder and the soft first segment are the parts that must not move."""
    _, segs = mgh_slow_release_segments("X")
    scales = [s.scale for s in segs]
    assert scales[0] == 0.5 and scales[-1] is None
    # k descends monotonically, with None (unrestrained) last
    numeric = [s for s in scales if s is not None]
    assert numeric == sorted(numeric, reverse=True)
    assert segs[0].soft is True
    assert not any(s.soft for s in segs[1:])


def test_a_single_chunk_per_stage_is_legal():
    """The degenerate split — one chunk per k — is what the tutorial itself does."""
    _, segs = mgh_slow_release_segments("X", chunk_pcts=(100.0,))
    assert len(segs) == 4
    assert _total_ns(segs) == pytest.approx(
        _total_ns(mgh_slow_release_segments("X")[1]), rel=1e-3)
