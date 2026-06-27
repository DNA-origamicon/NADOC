"""Unit tests for the hinge gap-ladder weave core (``backend/core/hinge_ladder``).

These pin the *combinatorial* correctness of the inner-rail weave in isolation —
no geometry, no ``Design``.  The reference-reproduction test checks the generated
weave matches the rung-usage and inner-row coverage extracted from the five
hand-routed designs in ``workspace/Scaffold routing`` (the column-reflection of
the rung *order* is irrelevant; coverage multiplicity is the topological pin).
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from backend.core.hinge_ladder import weave_gap_ladder, weave_hinge_full

ROUTED_DIR = Path(__file__).resolve().parents[1] / "workspace" / "Scaffold routing"


@pytest.mark.parametrize("n", [2, 4, 6, 8, 10])
def test_every_rung_used_exactly_once(n):
    weave = weave_gap_ladder(n)
    assert sorted(weave.rung_order) == list(range(n))
    assert len(weave.rung_order) == n  # no rung reused


@pytest.mark.parametrize("n", [2, 4, 6, 8])
def test_rail_coverage_is_the_asymmetric_pattern(n):
    weave = weave_gap_ladder(n)
    cov_a = weave.rail_coverage("A")
    cov_b = weave.rail_coverage("B")
    # rail A (spine): single-pass at col 0, double-pass at every other column
    assert cov_a == {0: 1, **{c: 2 for c in range(1, n)}}
    # rail B (single): single-pass everywhere except the far column (turnaround)
    assert cov_b == {**{c: 1 for c in range(n - 1)}, n - 1: 2}


@pytest.mark.parametrize("n", [2, 4, 6, 8])
def test_single_connected_trail(n):
    """Consecutive visits must be joined by a structurally valid junction."""
    visits = weave_gap_ladder(n).visits
    for prev, cur in zip(visits, visits[1:]):
        if cur.junction_in == "rung":
            # rung: hop between rails at the SAME column (LO end)
            assert prev.col == cur.col and prev.rail != cur.rail
        elif cur.junction_in == "rail":
            # within-row crossover: same rail, adjacent column
            assert prev.rail == cur.rail and abs(prev.col - cur.col) == 1
        elif cur.junction_in == "body":
            # leaf-body excursion: re-enters the same helix it left
            assert prev.rail == cur.rail and prev.col == cur.col
        else:  # pragma: no cover
            pytest.fail(f"unknown junction {cur.junction_in!r}")


@pytest.mark.parametrize("n", [2, 4, 6, 8])
def test_body_ports_at_far_column_one_per_rail(n):
    weave = weave_gap_ladder(n)
    assert weave.body_port_a == ("A", n - 1)
    assert weave.body_port_b == ("B", n - 1)


@pytest.mark.parametrize("n", [1, 3, 5, 0, -2])
def test_odd_or_degenerate_column_count_rejected(n):
    with pytest.raises(ValueError):
        weave_gap_ladder(n)


# --- reproduction against the hand-routed reference designs -------------------

# --- full hinge weave -------------------------------------------------------

def _is_valid_step(prev, cur, rows, rail_a, rail_b):
    (r1, c1), (r2, c2) = prev, cur
    within_row = r1 == r2 and abs(c1 - c2) == 1
    rung = {r1, r2} == {rail_a, rail_b} and c1 == c2
    within_leaf = c1 == c2 and abs(rows.index(r1) - rows.index(r2)) == 1
    return within_row or rung or within_leaf


@pytest.mark.parametrize("k", [2, 3, 4])
@pytest.mark.parametrize("n", [2, 4, 6])
def test_full_weave_is_a_valid_single_trail(k, n):
    # leaf A rows 0..k-1, gap, leaf B rows (2k-1)..(3k-2) — any gap ≥ 1 row works
    leaf_a = list(range(k))
    leaf_b = list(range(2 * k, 3 * k))
    rows = leaf_a + leaf_b
    cols = list(range(n))
    weave = weave_hinge_full(leaf_a, leaf_b, n)
    trail = weave.trail

    # connected single trail
    for prev, cur in zip(trail, trail[1:]):
        assert _is_valid_step(prev, cur, rows, weave.rail_a, weave.rail_b), (
            f"invalid step {prev} -> {cur}"
        )
    # every helix covered, none visited more than twice (physically realizable)
    cov = Counter(trail)
    for r in rows:
        for c in cols:
            assert 1 <= cov[(r, c)] <= 2, f"helix ({r},{c}) visited {cov[(r, c)]}x"
    # every rung (gap crossing) used exactly once
    rungs = [
        c1 for (r1, c1), (r2, c2) in zip(trail, trail[1:])
        if {r1, r2} == {weave.rail_a, weave.rail_b} and c1 == c2
    ]
    assert sorted(rungs) == cols
    # both trail ends live in leaf A (the scaffold nick), per the parity result
    assert trail[0][0] in leaf_a and trail[-1][0] in leaf_a


@pytest.mark.parametrize(
    "fname,k,n",
    [
        ("2x2_single_hinge_link_routed.nadoc", 2, 2),
        ("2x4_single_hinge_link_routed.nadoc", 2, 4),
        ("2x6_single_hinge_link_routed.nadoc", 2, 6),
        ("3x2_hinge_routed.nadoc", 3, 2),
        ("3x4_hinge_routed.nadoc", 3, 4),
    ],
)
def test_full_weave_matches_reference_domain_count(fname, k, n):
    """The generated trail length equals the hand-routed strand's domain count."""
    path = ROUTED_DIR / fname
    if not path.exists():
        pytest.skip(f"reference design {fname} not present")
    d = json.loads(path.read_text())
    scaf = next(
        s for s in d["strands"]
        if s["strand_type"] == "scaffold" and not s.get("is_reference")
    )
    hm = {h["id"]: tuple(h["grid_pos"]) for h in d["helices"]}
    rows = sorted({r for r, _ in hm.values()})
    gi = next(i for i in range(len(rows) - 1) if rows[i + 1] - rows[i] > 1)
    leaf_a, leaf_b = rows[: gi + 1], rows[gi + 1:]

    weave = weave_hinge_full(leaf_a, leaf_b, n)
    assert len(weave.trail) == len(scaf["domains"])


def _extract_reference(path: Path):
    """Return (n_cols, innerA_coverage, innerB_coverage, rung_cols) from a design."""
    d = json.loads(path.read_text())
    hm = {h["id"]: tuple(h["grid_pos"]) for h in d["helices"]}
    rows = sorted({r for r, _ in hm.values()})
    cols = sorted({c for _, c in hm.values()})
    inner_a = inner_b = None
    for lo, hi in zip(rows, rows[1:]):
        if hi - lo > 1:  # the gap
            inner_a, inner_b = lo, hi
            break
    scaf = next(
        s for s in d["strands"]
        if s["strand_type"] == "scaffold" and not s.get("is_reference")
    )
    seq = [hm[dm["helix_id"]] for dm in scaf["domains"]]
    rungs = [
        c1 for (r1, c1), (r2, c2) in zip(seq, seq[1:])
        if {r1, r2} == {inner_a, inner_b} and c1 == c2
    ]
    cov_a = dict(sorted(Counter(c for r, c in seq if r == inner_a).items()))
    cov_b = dict(sorted(Counter(c for r, c in seq if r == inner_b).items()))
    return len(cols), cov_a, cov_b, rungs


@pytest.mark.parametrize(
    "fname",
    [
        "2x2_single_hinge_link_routed.nadoc",
        "2x4_single_hinge_link_routed.nadoc",
        "2x6_single_hinge_link_routed.nadoc",
        "3x2_hinge_routed.nadoc",
        "3x4_hinge_routed.nadoc",
    ],
)
def test_generator_matches_reference_coverage(fname):
    path = ROUTED_DIR / fname
    if not path.exists():
        pytest.skip(f"reference design {fname} not present")
    n, ref_cov_a, ref_cov_b, ref_rungs = _extract_reference(path)

    # every reference uses every rung exactly once (the load-bearing invariant)
    assert sorted(ref_rungs) == list(range(n))

    weave = weave_gap_ladder(n)
    gen_a = weave.rail_coverage("A")
    gen_b = weave.rail_coverage("B")

    # The reference may be column-reflected and/or have rail A/B swapped relative
    # to our canonical orientation; match coverage as an unordered multiset of
    # per-column visit counts on each rail, up to reflection and rail swap.
    def signature(cov):
        return tuple(sorted(cov.values()))

    ref_sigs = {signature(ref_cov_a), signature(ref_cov_b)}
    gen_sigs = {signature(gen_a), signature(gen_b)}
    assert ref_sigs == gen_sigs, (
        f"{fname}: coverage signatures differ\n"
        f"  ref A={ref_cov_a} B={ref_cov_b}\n"
        f"  gen A={gen_a} B={gen_b}"
    )
