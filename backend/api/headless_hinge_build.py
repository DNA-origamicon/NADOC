"""Headless (mouse-free) hinge-primitive construction (AF-33).

Recreate the standard hinge primitives — ``2x2_single`` / ``2x4_double`` /
``2x6_triple`` (``workspace/Primitives/*.nadoc``) — **from scratch**, with zero
mouse, so a script (and eventually an AI builder) can emit one.  A hinge is two
rigid SQUARE leaves (rows 0–1 and 4–5, a 2-row gap between them) bridged across
the gap by reciprocal **forced-ligation** scaffold links.  The saved primitives
carry **0 crossovers** — they are the *input* to autoscaffold (AF-34), not a
routed design.

This module composes the already-shipped :mod:`headless_build` wrappers — it
introduces no new route and re-implements nothing:

* ``hb.create_bundle`` lays the two-leaf SQUARE bundle (length 40, ligated),
* ``hb.resize_strand_end`` (AF-30) shifts every duplex into the canonical bp
  span and trims the gap-bridge scaffold ends, and
* ``hb.force_ligate`` (AF-32) places the ``2N`` cross-gap forced-ligation links.

**The recipe is the golden's own feature log, replayed.**  Each saved primitive
was hand-built in the GUI as ``bundle-create`` → a *Fine Routing* cluster of
``strand-end-resize`` + ``forced-ligation-create`` steps; we replay exactly those
ops (the duplex shift is *derived* from the live strand directions, the
gap-bridge resizes + ligations are a small per-primitive constant — the bridge
geometry is hand-authored gap routing, NOT geometrically re-derived here, which
would be the ASK-FIRST topology/directionality territory ``CLAUDE.md`` reserves
for the user).  Because we replay the same base ops on the same deterministic
``create_bundle`` ids, the code-built hinge is byte-for-byte the validated
hand-built primitive — pinned by
:func:`tests.automation_harness.assert_matches_primitive` (canonical topology +
forced-ligation endpoint set + ``.nadoc`` round-trip + validator).

**Phase split (AF-33):** P1 = ``2x2_single`` (one link, 2 FL — *this module*);
P2 will add ``2x4``/``2x6`` (the same builder, more bridges) once the multi-link
gap geometry is settled with the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import Design, LatticeType

# The saved primitives were created at this length and then shifted into the
# canonical bp span (8 … 39) by the per-helix low-end resize below.  Replaying the
# create-at-40-then-shift (rather than creating at 32 directly) is load-bearing:
# ``strand-end-resize`` re-trims the helix axis as it shrinks (the AF-30 ISSUE-13
# convention), so only the same op sequence reproduces the golden's axis geometry,
# which ``canonical_topology`` fingerprints.
_BASE_LENGTH_BP = 40
_DUPLEX_SHIFT_BP = 8


@dataclass(frozen=True)
class _Bridge:
    """One cross-gap forced-ligation link (with the scaffold trim that precedes it).

    ``trim`` (optional) is a ``(strand_id, helix_id, end, delta_bp)`` resize that
    extends the bridging scaffold toward the gap before it is ligated; ``three``/
    ``five`` are the 3′/5′ scaffold strand ids handed to ``hb.force_ligate``.
    """

    three: str
    five: str
    trim: tuple[str, str, str, int] | None = None


@dataclass(frozen=True)
class _HingeSpec:
    cells: list[tuple[int, int]]
    bridges: list[_Bridge] = field(default_factory=list)


# Two 2×2 SQUARE leaves (rows 0–1 cols 0–1, rows 4–5 cols 0–1) in the serpentine
# cell order the GUI emits, plus the single hinge link (2 reciprocal FLs) bridging
# the inner rows (1 ↔ 4) across the gap.  Strand/helix ids are the deterministic
# ``create_bundle`` names (``scaf_XY_<row>_<col>`` / ``h_XY_<row>_<col>``).
_HINGE_SPECS: dict[str, _HingeSpec] = {
    "2x2_single_hinge_link": _HingeSpec(
        cells=[(0, 0), (0, 1), (1, 1), (1, 0), (4, 0), (4, 1), (5, 1), (5, 0)],
        bridges=[
            _Bridge(
                three="scaf_XY_1_0",
                five="scaf_XY_4_0",
                trim=("scaf_XY_1_0", "h_XY_1_0", "3p", -3),
            ),
            _Bridge(
                three="scaf_XY_4_1",
                five="scaf_XY_1_1",
                trim=("scaf_XY_1_1", "h_XY_1_1", "5p", -16),
            ),
        ],
    ),
}

HINGE_PRIMITIVE_NAMES = tuple(_HINGE_SPECS)


def _shift_duplexes(shift_bp: int) -> None:
    """Move every helix's low-bp duplex end up by ``shift_bp`` (8 … 39 canonical span).

    The ``create_bundle`` step lays each helix's scaffold + staple as a blunt
    duplex over bp ``0 … length-1``; the saved primitives sit at bp ``8 … 39``.
    For each strand we resize the terminus at its *lower* global bp toward higher
    bp — derived from the live domain directions (``5p`` is the low end of a
    forward strand, ``3p`` of a reverse one), so no lattice-parity reasoning is
    needed.  Entries are collected from the post-create state *before* mutating, so
    each resize addresses a stable ``strand_id``.
    """
    design = design_state.get_or_404()
    ops: list[tuple[str, str, str]] = []
    for strand in design.strands:
        dom = strand.domains[0]
        low_end = "5p" if dom.start_bp < dom.end_bp else "3p"
        ops.append((strand.id, dom.helix_id, low_end))
    for strand_id, helix_id, end in ops:
        hb.resize_strand_end(strand_id, helix_id, end, shift_bp)


def build_hinge_primitive(
    name: str = "2x2_single_hinge_link",
    *,
    lattice: LatticeType = LatticeType.SQUARE,
) -> Design:
    """Build a standard hinge primitive from scratch (returns a standalone copy).

    Replays the named primitive's construction — bundle-create → duplex shift →
    per-bridge (scaffold trim → forced ligation) — inside an isolated scratch
    session, so it never disturbs the active design.  The result is byte-for-byte
    equal (canonical topology + FL endpoint set) to ``workspace/Primitives/<name>.nadoc``;
    pin it with :func:`tests.automation_harness.assert_matches_primitive`.

    Three-Layer note: this is pure topological construction (bundle + strands + FL
    records) — an allowed write.  No scaffold routing (the primitive carries 0
    crossovers; routing is AF-34).

    Raises ``KeyError`` for an unknown / not-yet-supported primitive name (P1
    ships ``2x2_single_hinge_link``; 2x4/2x6 are AF-33 P2).
    """
    try:
        spec = _HINGE_SPECS[name]
    except KeyError:
        raise KeyError(
            f"unknown hinge primitive {name!r}; supported: {HINGE_PRIMITIVE_NAMES} "
            "(2x4/2x6 are AF-33 P2)"
        ) from None

    with hb.scratch_session(lattice):
        hb.create_bundle(
            spec.cells, _BASE_LENGTH_BP, lattice=lattice, name=name, ligate_adjacent=True,
        )
        _shift_duplexes(_DUPLEX_SHIFT_BP)
        for bridge in spec.bridges:
            if bridge.trim is not None:
                hb.resize_strand_end(*bridge.trim)
            hb.force_ligate(bridge.three, bridge.five)
        return design_state.get_or_404().model_copy(deep=True)


def build_hinge(
    rows_per_leaf: int,
    n_cols: int,
    *,
    lattice: LatticeType = LatticeType.SQUARE,
    length_bp: int = _BASE_LENGTH_BP,
) -> Design:
    """Build an arbitrary ``rows_per_leaf × n_cols`` hinge primitive from scratch.

    Generalizes the named-primitive builder to any leaf thickness (``k = rows_per_
    leaf ≥ 2``) and column count (``n_cols``, even — hinge rungs come in reciprocal
    pairs).  Two ``k``-row SQUARE leaves separated by the standard 2-row gap (leaf A
    = rows ``0 … k-1``, leaf B = rows ``k+2 … 2k+1``; inner rails = rows ``k-1`` and
    ``k+2``), one cross-gap forced-ligation rung per column joining the inner rails
    at their LO (gap-facing) end.

    Unlike :func:`build_hinge_primitive` (which replays a hand-authored spec to
    reproduce a *saved* primitive byte-for-byte), this generator chooses a uniform
    bridge geometry — every rung at the LO end — so the weave realizer
    (:func:`backend.core.hinge_weave_router.realize_hinge_weave`) routes it to one
    compliant scaffold strand.  The bridge orientation is forced by direction: rail
    A and rail B always have opposite scaffold polarity (their rows differ by 3), so
    the REVERSE rail's 3′ terminus is the one at the LO end and becomes the FL's
    three-prime side — putting every rung on the same (gap) face.

    Returns a standalone copy.  Pure topological construction (no scaffold route).
    Raises ``ValueError`` for ``k < 2`` or odd / non-positive ``n_cols``.
    """
    if rows_per_leaf < 2:
        raise ValueError(f"rows_per_leaf must be ≥ 2, got {rows_per_leaf}")
    if n_cols < 2 or n_cols % 2 != 0:
        raise ValueError(f"n_cols must be an even integer ≥ 2, got {n_cols}")

    k = rows_per_leaf
    rail_a, rail_b = k - 1, k + 2
    leaf_a_rows = range(0, k)
    leaf_b_rows = range(k + 2, 2 * k + 2)

    # Serpentine cell order per leaf (the order the GUI bundle tool emits).
    cells: list[tuple[int, int]] = []
    for rows in (leaf_a_rows, leaf_b_rows):
        for ri, r in enumerate(rows):
            col_iter = range(n_cols) if ri % 2 == 0 else range(n_cols - 1, -1, -1)
            cells.extend((r, c) for c in col_iter)

    def _is_forward(row: int, col: int) -> bool:
        return (row + col) % 2 == 0

    with hb.scratch_session(lattice):
        hb.create_bundle(
            cells, length_bp, lattice=lattice,
            name=f"{k}x{n_cols}_hinge", ligate_adjacent=True,
        )
        _shift_duplexes(_DUPLEX_SHIFT_BP)
        design = design_state.get_or_404()
        gp = {h.id: tuple(h.grid_pos) for h in design.helices}
        scaf_id: dict[tuple[int, int], str] = {}
        for s in design.strands:
            if s.strand_type.value != "scaffold":
                continue
            for dm in s.domains:
                scaf_id.setdefault(gp[dm.helix_id], s.id)
        for c in range(n_cols):
            a, b = scaf_id[(rail_a, c)], scaf_id[(rail_b, c)]
            # The reverse rail's 3′ end sits at the LO (gap) face → three-prime side.
            three, five = (a, b) if not _is_forward(rail_a, c) else (b, a)
            hb.force_ligate(three, five)
        return design_state.get_or_404().model_copy(deep=True)
