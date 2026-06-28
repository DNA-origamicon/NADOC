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

**Phase split (AF-33):** P1 = ``2x2_single`` (one link, 2 FL); P2 (DONE) adds
``2x4_double`` (2 links) and ``2x6_triple`` (3 links) — the same builder, more
bridges, each transcribed verbatim from its golden's feature log.  NB the
2x4/2x6 goldens are *builders only*: their multi-link routing falls back (the
``test_hinge_router`` xfail), so AF-34-style autoscaffold validation is still
pending the multi-link merge (algorithm blocker G6, ``project_hinge_autoscaffold.md``).
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

# Paired short/long ssDNA tether lengths (bp). The hinge's cross-gap connections come
# in short/long pairs governed by helical phase: a leaf-A rail helix whose gap-face
# backbone faces TOWARD the far leaf takes the SHORT tether (it can bridge directly);
# the neighbour, whose backbone faces AWAY, takes the LONG one (it must extend ~1
# helical turn to re-phase toward the partner). Verified against the 2x2/2x4 goldens.
# Magnitudes are fixed user-chosen defaults (2026-06-27) — absent design intent we
# cannot derive better ones — and are overridable per call.
_SHORT_SSDNA_BP = 2
_LONG_SSDNA_BP = 16


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


# Two SQUARE leaves (rows 0…k-1 and k+2…2k+1, a 2-row gap between them) in the
# serpentine cell order the GUI emits, plus one hinge link per column (a reciprocal
# FL) bridging the inner rows (rail A = row 1, rail B = row 4) across the gap.
# Strand/helix ids are the deterministic ``create_bundle`` names
# (``scaf_XY_<row>_<col>`` / ``h_XY_<row>_<col>``).
#
# Each spec is the golden primitive's OWN feature log, transcribed verbatim:
# ``bundle-create`` params give ``cells``; the *Fine Routing* cluster's
# ``strand-end-resize`` + ``forced-ligation-create`` children give the per-bridge
# ``trim`` + ``(three, five)``.  The gap-bridge trims encode the **phase-paired
# short/long ssDNA** rule (verified against these goldens, see
# :func:`_rail_faces_toward`): the rail facing TOWARD the far leaf gets a SHORT
# (``±2``) extension, the one facing AWAY a LONG (``±16``) one — so 2x2 alternates
# ``3p −16`` (long) / ``5p −2`` (short), and 2x4 the same magnitudes by column
# parity.  :func:`build_hinge` derives these magnitudes from the live phase and
# reproduces each golden byte-for-byte; the specs transcribe them so the named
# builder stays a self-contained replay (pinned by ``assert_matches_primitive``).
# The 2x6 entry predates the phase-paired rule and carries no explicit ``trim``
# (legacy uniform geometry); :func:`build_hinge(2, 6)` now emits the correct
# short/long 2x6 and supersedes it (the saved 2x6 golden is separately stale).
_HINGE_SPECS: dict[str, _HingeSpec] = {
    "2x2_single_hinge_link": _HingeSpec(
        cells=[(0, 0), (0, 1), (1, 1), (1, 0), (4, 0), (4, 1), (5, 1), (5, 0)],
        bridges=[
            # col 0 — (1,0) faces AWAY → LONG (16-base) tether on the rail-A scaffold.
            _Bridge(
                three="scaf_XY_1_0",
                five="scaf_XY_4_0",
                trim=("scaf_XY_1_0", "h_XY_1_0", "3p", -16),
            ),
            # col 1 — (1,1) faces TOWARD → SHORT (2-base) tether.
            _Bridge(
                three="scaf_XY_4_1",
                five="scaf_XY_1_1",
                trim=("scaf_XY_1_1", "h_XY_1_1", "5p", -2),
            ),
        ],
    ),
    "2x4_double_hinge_link": _HingeSpec(
        cells=[
            (0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (1, 2), (1, 1), (1, 0),
            (4, 0), (4, 1), (4, 2), (4, 3), (5, 3), (5, 2), (5, 1), (5, 0),
        ],
        bridges=[
            _Bridge(
                three="scaf_XY_1_0",
                five="scaf_XY_4_0",
                trim=("scaf_XY_1_0", "h_XY_1_0", "3p", -16),
            ),
            _Bridge(
                three="scaf_XY_4_1",
                five="scaf_XY_1_1",
                trim=("scaf_XY_1_1", "h_XY_1_1", "5p", -2),
            ),
            _Bridge(
                three="scaf_XY_1_2",
                five="scaf_XY_4_2",
                trim=("scaf_XY_1_2", "h_XY_1_2", "3p", -16),
            ),
            _Bridge(
                three="scaf_XY_4_3",
                five="scaf_XY_1_3",
                trim=("scaf_XY_1_3", "h_XY_1_3", "5p", -2),
            ),
        ],
    ),
    "2x6_triple_hinge_link": _HingeSpec(
        cells=[
            (0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5),
            (1, 5), (1, 4), (1, 3), (1, 2), (1, 1), (1, 0),
            (4, 0), (4, 1), (4, 2), (4, 3), (4, 4), (4, 5),
            (5, 5), (5, 4), (5, 3), (5, 2), (5, 1), (5, 0),
        ],
        bridges=[
            _Bridge(three="scaf_XY_1_0", five="scaf_XY_4_0"),
            _Bridge(three="scaf_XY_4_1", five="scaf_XY_1_1"),
            _Bridge(three="scaf_XY_1_2", five="scaf_XY_4_2"),
            _Bridge(three="scaf_XY_4_3", five="scaf_XY_1_3"),
            _Bridge(three="scaf_XY_1_4", five="scaf_XY_4_4"),
            _Bridge(three="scaf_XY_4_5", five="scaf_XY_1_5"),
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

    Raises ``KeyError`` for an unknown primitive name (supported:
    ``2x2_single_hinge_link`` / ``2x4_double_hinge_link`` / ``2x6_triple_hinge_link``).
    """
    try:
        spec = _HINGE_SPECS[name]
    except KeyError:
        raise KeyError(
            f"unknown hinge primitive {name!r}; supported: {HINGE_PRIMITIVE_NAMES}"
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


def _scaffold_on_helix(design: Design, helix_id: str):
    """Return ``(strand, domain_index, domain)`` for the scaffold covering ``helix_id``."""
    for s in design.strands:
        if s.strand_type.value != "scaffold":
            continue
        for di, dm in enumerate(s.domains):
            if dm.helix_id == helix_id:
                return s, di, dm
    return None, None, None


def _rail_faces_toward(design: Design, rail_a_hid: str, rail_b_hid: str, bp: int) -> bool:
    """True iff rail-A's scaffold backbone at ``bp`` points TOWARD rail-B (the far leaf).

    The phase test validated against the 2x2/2x4 goldens: take the scaffold backbone's
    radial direction at the gap-face bp, project out the helix axis, and dot it with the
    rail-A→rail-B chord.  ``> 0`` means the backbone faces toward the opposite leaf (the
    SHORT-tether case); ``< 0`` means it faces away (LONG).  Neighbouring columns
    alternate because adjacent helices carry opposite phase.
    """
    import numpy as np

    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.geometry import nucleotide_positions

    H = {h.id: h for h in design.helices}

    def radial(hid: str):
        h = H[hid]
        _, _, dm = _scaffold_on_helix(design, hid)
        s = h.axis_start.to_array()
        e = h.axis_end.to_array()
        ax = e - s
        ax = ax / np.linalg.norm(ax)
        center = s + ax * ((bp - h.bp_start) * BDNA_RISE_PER_BP)
        for n in nucleotide_positions(h):
            if n.bp_index == bp and n.direction == dm.direction:
                r = np.array(n.position) - center
                r = r - (r @ ax) * ax
                return r / np.linalg.norm(r), center
        raise ValueError(f"no scaffold bead at bp {bp} on helix {hid!r}")

    r_a, c_a = radial(rail_a_hid)
    _, c_b = radial(rail_b_hid)
    gap = c_b - c_a
    gap = gap / np.linalg.norm(gap)
    return float(r_a @ gap) > 0.0


def build_hinge(
    rows_per_leaf: int,
    n_cols: int,
    *,
    lattice: LatticeType = LatticeType.SQUARE,
    length_bp: int = _BASE_LENGTH_BP,
    short_ssdna_bp: int = _SHORT_SSDNA_BP,
    long_ssdna_bp: int = _LONG_SSDNA_BP,
) -> Design:
    """Build an arbitrary ``rows_per_leaf × n_cols`` hinge primitive from scratch.

    Generalizes the named-primitive builder to any leaf thickness (``k = rows_per_
    leaf ≥ 2``) and column count (``n_cols``, even — hinge rungs come in reciprocal
    pairs).  Two ``k``-row SQUARE leaves separated by the standard 2-row gap (leaf A
    = rows ``0 … k-1``, leaf B = rows ``k+2 … 2k+1``; inner rails = rows ``k-1`` and
    ``k+2``), one cross-gap forced-ligation rung per column joining the inner rails
    at their LO (gap-facing) end.

    **Phase-paired fine routing (the core hinge mechanic).**  The cross-gap ssDNA
    connections come in short/long PAIRS set by helical phase, exactly as the
    hand-authored 2x2/2x4 goldens do.  Per column the leaf-A rail scaffold is
    extended into the gap (as unpaired ssDNA) by ``short_ssdna_bp`` when its gap-face
    backbone faces TOWARD leaf B (:func:`_rail_faces_toward`) and by ``long_ssdna_bp``
    when it faces AWAY (then it must reach ~1 helical turn further to re-phase toward
    the partner); the leaf-B rail stays blunt at the duplex edge.  Because adjacent
    helices carry opposite phase, columns alternate short/long.  The bridge
    orientation is forced by direction: rail A and rail B always have opposite
    scaffold polarity (their rows differ by 3), so the REVERSE rail's 3′ terminus is
    the LO-end one and becomes the FL's three-prime side.

    (This supersedes the earlier *uniform* every-rung-at-the-LO-end geometry; the
    weave realizer still routes the result — the goldens it was validated against
    carry exactly this short/long structure.)

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
        pos2hid = {tuple(h.grid_pos): h.id for h in design.helices}
        scaf_id: dict[tuple[int, int], str] = {}
        for s in design.strands:
            if s.strand_type.value != "scaffold":
                continue
            for dm in s.domains:
                scaf_id.setdefault(gp[dm.helix_id], s.id)
        # Classify each rung short/long from the post-shift geometry (the gap-face
        # phase is invariant to the gap extensions that follow, which live below it),
        # then realize the ssDNA extension + forced ligation column by column.
        for c in range(n_cols):
            rail_a_hid, rail_b_hid = pos2hid[(rail_a, c)], pos2hid[(rail_b, c)]
            a, b = scaf_id[(rail_a, c)], scaf_id[(rail_b, c)]
            toward = _rail_faces_toward(design, rail_a_hid, rail_b_hid, _DUPLEX_SHIFT_BP)
            ext = short_ssdna_bp if toward else long_ssdna_bp
            # Extend the leaf-A rail scaffold into the gap (its LO terminus toward
            # lower bp) by `ext` unpaired bases; leaf B stays blunt at the duplex edge.
            _, _, dm_a = _scaffold_on_helix(design, rail_a_hid)
            lo_end = "5p" if dm_a.start_bp < dm_a.end_bp else "3p"
            hb.resize_strand_end(a, rail_a_hid, lo_end, -ext)
            # The reverse rail's 3′ end sits at the LO (gap) face → three-prime side.
            three, five = (a, b) if not _is_forward(rail_a, c) else (b, a)
            hb.force_ligate(three, five)
        return design_state.get_or_404().model_copy(deep=True)
