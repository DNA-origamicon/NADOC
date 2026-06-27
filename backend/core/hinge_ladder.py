"""
Hinge gap-ladder weave — the irreducible combinatorial core of single-strand
hinge scaffold routing.

Background (see ``memory/project_hinge_autoscaffold.md``).  A hinge is two rigid
leaves butted end-to-end across a physical gap.  Each leaf is a ``k × N`` helix
bundle; the two *gap-facing* inner rows (leaf-A inner = "rail A", leaf-B inner =
"rail B") are joined at their LO ends by ``N`` forced-ligation **rungs**, one per
column.  To fold the whole hinge from a single scaffold strand, the scaffold must
thread **every** rung (an unused rung = an orphan bridge strand).

Decoding the five hand-routed reference designs in ``workspace/Scaffold routing``
(2x2/2x4/2x6 two-row leaves, 3x2/3x4 three-row leaves) shows the leaf *bodies*
(every row except the inner rail) are plain seamed double-pass raster — a solved
problem.  The whole difficulty is confined to the **2 inner rails + N rungs**: a
2×N ladder whose rungs all sit at the *same* (LO) end.  This module generates the
abstract weave for that ladder and is deliberately free of any geometry / bp
coordinates / ``Design`` dependency, so the core algorithm can be proven in
isolation before it is wired into a real router.

The universal pattern extracted from the references (identical up to a left/right
reflection across all five):

  * every rung is used exactly once;
  * the **spine rail** (rail A) is double-passed at every column except one end
    column (single there) — a full HI-end sweep across all columns, then its LO
    halves re-entered during the rung weave;
  * the **single rail** (rail B) is single-passed at every column except the
    *opposite* end column, where it is double-passed for the body turnaround;
  * the two free ends of the trail (the body ports) both sit at that far end
    column — one on each rail — so leaf A and leaf B each splice in there.

Even column count is assumed (hinge links come in reciprocal pairs, so N is
even); ``weave_gap_ladder`` raises for odd / degenerate N and the eventual router
falls back to the classic pipeline in that case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter

Rail = str  # "A" (leaf-A inner / spine rail) or "B" (leaf-B inner / single rail)
Junction = str  # "rail" | "rung" | "body"
Half = str  # "hi" | "lo" | "full"


@dataclass(frozen=True)
class LadderVisit:
    """One traversal of an inner-rail helix in the weave."""

    rail: Rail
    col: int
    half: Half
    # junction joining this visit to the PREVIOUS one in the trail
    junction_in: Junction


@dataclass
class LadderWeave:
    """Abstract single-strand weave of a 2×N same-end rung ladder."""

    n_cols: int
    visits: list[LadderVisit] = field(default_factory=list)
    # (rail, col) where each leaf body splices into the ladder (the two trail ends)
    body_port_a: tuple[Rail, int] = ("A", 0)
    body_port_b: tuple[Rail, int] = ("B", 0)

    @property
    def rung_order(self) -> list[int]:
        """Columns at which the trail crosses the gap, in traversal order."""
        return [v.col for v in self.visits if v.junction_in == "rung"]

    def rail_coverage(self, rail: Rail) -> dict[int, int]:
        return dict(
            sorted(Counter(v.col for v in self.visits if v.rail == rail).items())
        )


def weave_gap_ladder(n_cols: int) -> LadderWeave:
    """Generate the abstract single-strand weave for a 2×``n_cols`` rung ladder.

    Returns a :class:`LadderWeave` whose ``visits`` form one connected trail that
    uses every rung once and covers every inner-rail helix, with the two body
    ports at the far end column.  Pure / combinatorial — no geometry.

    Raises ``ValueError`` for ``n_cols`` that is not an even integer ≥ 2.
    """
    if n_cols < 2 or n_cols % 2 != 0:
        raise ValueError(
            f"hinge gap ladder needs an even column count ≥ 2, got {n_cols}"
        )

    n = n_cols
    visits: list[LadderVisit] = []

    # 1. Spine: rail A, HI halves, swept from the far end column (n-1) down to 0.
    #    Entry at col n-1 is the leaf-A body splice.
    for j, c in enumerate(range(n - 1, -1, -1)):
        visits.append(LadderVisit("A", c, "hi", "body" if j == 0 else "rail"))

    # 2. Rung weave.  Dive A_0 -> rung0 -> B_0, then walk alternating rails in
    #    column pairs, consuming rungs 1..n-2, ending on rail B at col n-1.
    visits.append(LadderVisit("B", 0, "full", "rung"))  # rung 0
    rail: Rail = "B"
    c = 1
    while c < n - 1:
        # advance one column along the current rail (a within-row crossover)...
        visits.append(LadderVisit(rail, c, "full" if rail == "B" else "lo", "rail"))
        # ...then hop the rung to the other rail at this column.
        other: Rail = "A" if rail == "B" else "B"
        visits.append(
            LadderVisit(other, c, "full" if other == "B" else "lo", "rung")
        )
        rail = other
        c += 1

    # 3. Reach the far column on rail B as a clean double-pass: its HI half
    #    (rail crossover in from the weave) exits to the leaf-B body, then its LO
    #    half (return from the body) takes the final rung n-1 back to rail A,
    #    which exits to the leaf-A body.  rail is B here for even n.
    visits.append(LadderVisit("B", n - 1, "hi", "rail"))  # weave -> B_{n-1}, body-B out
    visits.append(LadderVisit("B", n - 1, "lo", "body"))  # body-B in -> rung n-1
    visits.append(LadderVisit("A", n - 1, "lo", "rung"))  # rung n-1 -> rail A, body-A out

    return LadderWeave(
        n_cols=n,
        visits=visits,
        body_port_a=("A", n - 1),
        body_port_b=("B", n - 1),
    )


# --- full hinge weave (leaf bodies + gap ladder, unified) ---------------------

@dataclass
class HingeWeave:
    """The complete single-strand hinge route as an ordered helix-visit trail.

    ``trail`` is the scaffold's traversal order as ``(row, col)`` grid positions;
    consecutive entries are joined by exactly one of: a within-row crossover
    (same row, adjacent column), a within-leaf crossover (adjacent row, same
    column), or a gap rung / forced ligation (the two inner rails, same column).
    A helix appears once (single-pass) or twice (double-pass → a seam); never
    more.  This is still geometry-free — the bp realization consumes ``trail``.
    """

    trail: list[tuple[int, int]] = field(default_factory=list)
    rail_a: int = 0  # leaf-A inner (gap-facing) row
    rail_b: int = 0  # leaf-B inner (gap-facing) row
    n_cols: int = 0


def _leaf_raster(rows: list[int], n_cols: int, start_col: int) -> list[tuple[int, int]]:
    """Boustrophedon serpentine through ``rows`` (in the given order).

    The first row sweeps left→right when ``start_col == 0`` else right→left;
    each subsequent row reverses, so consecutive rows meet at a shared column
    (an adjacent-row, same-column crossover).
    """
    out: list[tuple[int, int]] = []
    going_right = start_col == 0
    for row in rows:
        cols = range(n_cols) if going_right else range(n_cols - 1, -1, -1)
        out.extend((row, c) for c in cols)
        going_right = not going_right
    return out


def weave_hinge_full(
    leaf_a_rows: list[int], leaf_b_rows: list[int], n_cols: int
) -> HingeWeave:
    """Generate the complete single-strand hinge route trail.

    ``leaf_a_rows`` / ``leaf_b_rows`` are each leaf's grid rows in ascending
    order; the gap-facing inner rails are ``leaf_a_rows[-1]`` and
    ``leaf_b_rows[0]``.  Composes the proven :func:`weave_gap_ladder` core (inner
    rails + rungs) with standard boustrophedon rasters of the outer rows, spliced
    at the ladder's body ports:

      * leaf-A outer rows descend into the rail-A spine, and return (double-pass)
        off the rail-A end — both trail ends live in leaf A (the scaffold nick);
      * leaf-B outer rows are a mid-trail excursion off the rail-B port.

    Raises ``ValueError`` (via :func:`weave_gap_ladder`) for odd/degenerate
    ``n_cols``.
    """
    rail_a = leaf_a_rows[-1]
    rail_b = leaf_b_rows[0]
    outer_a = leaf_a_rows[:-1]  # a_0 .. a_{k-2}
    outer_b = leaf_b_rows[1:]   # b_1 .. b_{k-1}
    far = n_cols - 1
    ladder = weave_gap_ladder(n_cols).visits

    trail: list[tuple[int, int]] = []

    # 1. Leaf-A outer descent, arranged so its last outer row ends at the far
    #    column (adjacent to the rail-A spine entry).
    if outer_a:
        for start_col in (0, far):
            cand = _leaf_raster(outer_a, n_cols, start_col)
            if cand[-1][1] == far:
                trail.extend(cand)
                break

    # 2. Walk the ladder; at the rail-B body port, splice the leaf-B outer
    #    excursion (down + back, double-passing every outer-B row) so it returns
    #    to the far column adjacent to rail B.
    for lv in ladder:
        if lv.rail == "B" and lv.junction_in == "body" and outer_b:
            down = _leaf_raster(outer_b, n_cols, far)
            up = _leaf_raster(list(reversed(outer_b)), n_cols, down[-1][1])
            trail.extend(down)
            trail.extend(up[1:] if up and up[0] == down[-1] else up)
        trail.append((rail_a if lv.rail == "A" else rail_b, lv.col))

    # 3. Leaf-A outer return (double-pass), descending the outer rows from the
    #    far column off the rail-A trail end.
    if outer_a:
        trail.extend(_leaf_raster(list(reversed(outer_a)), n_cols, far))

    return HingeWeave(trail=trail, rail_a=rail_a, rail_b=rail_b, n_cols=n_cols)
