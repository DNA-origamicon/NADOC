"""The interhelical push-bond rule (mrdna's, used by the vacuum ENRG-MD pre-stage).

These were exp48's `_self_test()`, which lived under `if __name__ == "__main__"` and so
was never collected.  The rule's whole subtlety is the 11-nt exclusion zone at each end
of a crossover-free span: it means a span must exceed ~22 nt to place ANY bond, so a
densely crossed-over honeycomb bundle correctly generates zero.  That is easy to
"fix" into a bug, hence pinning it.

See backend/core/namd_push_bonds.py and experiments/exp48_vacuum_enrgmd/REPORT.md.
"""

from __future__ import annotations

from backend.core.namd_push_bonds import (
    CROSSOVER_EXCLUSION_NT,
    qualifying_positions,
)


class _Half:
    def __init__(self, helix_id, index):
        self.helix_id, self.index = helix_id, index


class _Crossover:
    def __init__(self, half_a, half_b):
        self.half_a, self.half_b = half_a, half_b


class _Design:
    def __init__(self, crossovers):
        self.crossovers = crossovers


def _xo(i, j, ha="A", hb="B"):
    """One crossover joining helix ``ha`` at index i to helix ``hb`` at index j."""
    return _Crossover(_Half(ha, i), _Half(hb, j))


def test_single_holliday_junction_generates_nothing():
    """2hb_1xT has its reciprocal pair at 13/14 — 1 nt apart, nowhere near 22."""
    assert qualifying_positions(_Design([_xo(13, 13), _xo(14, 14)])) == []


def test_honeycomb_21bp_repeat_generates_nothing():
    """Crossovers to a given neighbour recur every 21 bp on the honeycomb lattice.
    A span of 22 nt still fails: it needs i >= 11 AND (i2 - idx) >= 11 simultaneously.
    This is why a dense bundle yields zero push bonds — expected, not a failure."""
    assert qualifying_positions(_Design([_xo(0, 0), _xo(21, 21)])) == []


def test_forty_nt_span_bonds_only_inside_the_exclusion_zones():
    got = qualifying_positions(_Design([_xo(0, 0), _xo(40, 40)]))
    assert got, "a 40-nt crossover-free span must generate push bonds"
    idxs = [i for _, i, _, _ in got]
    assert min(idxs) >= CROSSOVER_EXCLUSION_NT
    assert max(idxs) <= 40 - CROSSOVER_EXCLUSION_NT


def test_antiparallel_run_is_skipped():
    """mrdna has an explicit `continue` here — "not yet implemented"."""
    assert qualifying_positions(_Design([_xo(0, 40), _xo(40, 0)])) == []


def test_one_crossover_is_never_enough():
    assert qualifying_positions(_Design([_xo(0, 0)])) == []


def test_bonds_are_reported_for_both_helices_of_the_pair():
    got = qualifying_positions(_Design([_xo(0, 0), _xo(40, 40)]))
    assert {(h_i, h_j) for h_i, _, h_j, _ in got} == {("A", "B")}


def test_crossover_orientation_does_not_depend_on_input_order():
    """Half A/B may be recorded either way round; the pair key is sorted, so the
    result must be identical."""
    forward = qualifying_positions(_Design([_xo(0, 0), _xo(40, 40)]))
    flipped = qualifying_positions(
        _Design(
            [
                _Crossover(_Half("B", 0), _Half("A", 0)),
                _Crossover(_Half("B", 40), _Half("A", 40)),
            ]
        )
    )
    assert forward == flipped


def test_index_is_interpolated_on_the_longer_span():
    """When the two helices span different nucleotide counts between the same pair of
    crossovers, the shorter one drives the walk and the longer is interpolated."""
    got = qualifying_positions(_Design([_xo(0, 0), _xo(40, 80)]))
    assert got
    for _, idx_i, _, idx_j in got:
        assert 0 <= idx_i <= 40
        assert 0 <= idx_j <= 80
        # j advances about twice as fast as i.
        assert abs(idx_j - 2 * idx_i) <= 2
