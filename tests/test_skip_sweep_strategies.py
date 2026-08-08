"""Skip-placement strategies for the skip-count → twist/curvature sweep (exp31).

Pure-function pins (no oxDNA / no GPU): all three strategies change the total skip count by
exactly ``delta · n_helices``, coincide at the baseline, stay on the dsDNA core, and are
deterministic.  Strategy-specific behaviour: uniform spreads evenly, incremental keeps the
baseline marks fixed, deviation places at the prior sim's hotspot.
"""

from __future__ import annotations

import pytest

from backend.api.skip_twist_tuning import build_sq_skip_design, square_cells
from backend.core.regional_skip_placer import core_candidates
from backend.core.skip_sweep_strategies import (
    STRATEGIES,
    baseline_skips,
    place_deviation_step,
    place_incremental,
    place_uniform,
)


@pytest.fixture(scope="module")
def sq_design():
    """A routed, sequenced 2x3x40 square-lattice bundle, NO skips (the candidate source)."""
    return build_sq_skip_design(square_cells(2, 3), 40, None)


def _total(skips: dict) -> int:
    return sum(len(v) for v in skips.values())


def _all_on_core(design, skips: dict) -> bool:
    for h in design.helices:
        cands = set(core_candidates(design, h))
        if any(bp not in cands for bp in skips.get(h.id, [])):
            return False
    return True


def _no_dups(skips: dict) -> bool:
    return all(len(v) == len(set(v)) for v in skips.values())


def test_baseline_is_nonempty_and_on_core(sq_design):
    base = baseline_skips(sq_design, skip_period=8)
    assert base and _total(base) > 0
    assert _all_on_core(sq_design, base) and _no_dups(base)


@pytest.mark.parametrize("delta", [-2, -1, 1, 2])
def test_uniform_changes_total_by_delta_per_helix(sq_design, delta):
    base = baseline_skips(sq_design, skip_period=8)
    n = len(sq_design.helices)
    out = place_uniform(sq_design, base, delta)
    assert _total(out) == _total(base) + delta * n
    assert _all_on_core(sq_design, out) and _no_dups(out)
    # exactly base_count+delta on each helix
    for h in sq_design.helices:
        assert len(out.get(h.id, [])) == len(base.get(h.id, [])) + delta


@pytest.mark.parametrize("delta", [-2, -1, 1, 2])
def test_incremental_changes_total_and_keeps_baseline_marks(sq_design, delta):
    base = baseline_skips(sq_design, skip_period=8)
    n = len(sq_design.helices)
    out = place_incremental(sq_design, base, delta)
    assert _total(out) == _total(base) + delta * n
    assert _all_on_core(sq_design, out) and _no_dups(out)
    if delta > 0:
        # adding never moves an existing baseline mark
        for h in sq_design.helices:
            assert set(base.get(h.id, [])) <= set(out.get(h.id, []))


def test_incremental_adds_at_largest_gap(sq_design):
    """A +1 step inserts into the widest gap, so the new mark is interior, not at an end."""
    base = baseline_skips(sq_design, skip_period=8)
    out = place_incremental(sq_design, base, 1)
    h = sorted(sq_design.helices, key=lambda x: x.id)[0]
    added = sorted(set(out[h.id]) - set(base.get(h.id, [])))
    assert len(added) == 1
    bp = added[0]
    assert min(base[h.id]) < bp < max(base[h.id])  # landed between existing marks


def test_deviation_step_uses_hotspot(sq_design):
    """+1 deviation round places each helix's new skip nearest its max-deviation bp."""
    base = baseline_skips(sq_design, skip_period=8)
    h = sorted(sq_design.helices, key=lambda x: x.id)[0]
    free = [c for c in core_candidates(sq_design, h) if c not in base.get(h.id, [])]
    hotspot = free[len(free) // 3]
    dev = {(h.id, hotspot): 9.0}  # one strong hotspot on this helix
    out = place_deviation_step(sq_design, base, +1, dev)
    added = sorted(set(out[h.id]) - set(base.get(h.id, [])))
    assert len(added) == 1
    nearest = min(free, key=lambda c: abs(c - hotspot))
    assert added[0] == nearest


def test_deviation_step_total_and_remove(sq_design):
    base = baseline_skips(sq_design, skip_period=8)
    n = len(sq_design.helices)
    add = place_deviation_step(sq_design, base, +1, {})
    rem = place_deviation_step(sq_design, base, -1, {})
    assert _total(add) == _total(base) + n
    assert _total(rem) == _total(base) - n
    assert _all_on_core(sq_design, add) and _no_dups(add)


def test_deviation_step_is_sequential_chain(sq_design):
    """Chaining two outward rounds adds exactly 2 per helix (round N from round N−1)."""
    base = baseline_skips(sq_design, skip_period=8)
    n = len(sq_design.helices)
    r1 = place_deviation_step(sq_design, base, +1, {})
    r2 = place_deviation_step(sq_design, r1, +1, {})
    assert _total(r2) == _total(base) + 2 * n
    assert _all_on_core(sq_design, r2) and _no_dups(r2)


def test_strategies_coincide_at_delta_zero(sq_design):
    """Every strategy reduces to the baseline at delta = 0 (the shared anchor)."""
    base = baseline_skips(sq_design, skip_period=8)
    assert place_uniform(sq_design, base, 0) == {
        k: sorted(v) for k, v in base.items() if v
    }
    assert place_incremental(sq_design, base, 0) == {
        k: sorted(v) for k, v in base.items() if v
    }
    assert place_deviation_step(sq_design, base, 0, {}) == {
        k: sorted(v) for k, v in base.items() if v
    }


def test_determinism(sq_design):
    base = baseline_skips(sq_design, skip_period=8)
    for fn, args in (
        (place_uniform, (sq_design, base, 2)),
        (place_incremental, (sq_design, base, -2)),
        (place_deviation_step, (sq_design, base, +1, {})),
    ):
        assert fn(*args) == fn(*args)


def test_strategies_tuple():
    assert STRATEGIES == ("uniform", "incremental", "deviation")
