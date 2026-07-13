"""Reset a scaffold route back to the design's STRUCTURAL seed (ISSUE-9).

Why this exists
---------------
Autoscaffold is not idempotent.  The near/far end-turns legitimately extend each
helix a few bp past the scaffold's terminal face, so the scaffold has ssDNA to turn
around in (>= ``MIN_SSDNA_MARGIN``; see ``scaffold_invariants``).  That extension is
written straight into the helix — ``bp_start``, ``length_bp``, ``axis_start``,
``phase_offset``.  But the router derives the face it extends FROM the current
*scaffold* coverage, i.e. from its own previous output.  So a second call reads the
already-extended face, searches further out from it, and extends again.  Each call
ratchets: measured on a plain 2x2 honeycomb bundle, helices grew 168 -> 189 -> 199
-> 210 bp and crossovers 6 -> 9 -> 12 over three routes, unbounded.  Nothing retracts,
because the extenders are monotone (they only ever push outward), and the extension
overwrites the very information needed to undo it.  It persists to the ``.nadoc``.

The oracle
----------
**Staples are the structure.**  Autoscaffold never touches staple strands, so a
helix's true extent is the bp span of its staple domains — including staples that run
PAST the scaffold on the same helix (overhangs with no crossover).  Verified: across
three re-routes of the bundle above, the staple spans stayed at [0, 167] while the
helices ratcheted out to [-30, 179].  The scaffold is route output; the staples are
the design.

So the fix is not to rewrite the routing algorithm — it is to normalise its INPUT.
Retract every helix to its staple-defined extent and re-seed the scaffold to match,
then let the existing router run exactly as it does on a fresh design.  N calls then
produce what 1 call produces.

Deliberate non-goals
--------------------
* **Forced ligations are left alone.**  A manual fixed-edge topology is not derivable
  from the staples, and re-seeding would destroy it.  Same bail-out the existing
  ``_clear_auto_scaffold_route_for_seamed`` takes; the caller warns.
* **A helix with no staples is left alone.**  Its structural extent is undefined
  (``scaffold_invariants`` calls such a helix "vacuously clear"), so retracting it
  would be a guess.  Leave it exactly as found.
"""

from __future__ import annotations

import math

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, Direction, Domain, Helix, Strand, StrandType, Vec3,
)
from backend.core.scaffold_invariants import _staple_coverage


def structural_intervals(design: Design) -> dict[str, list[tuple[int, int]]]:
    """helix_id -> merged, sorted (lo, hi) intervals actually covered by STAPLES.

    NOT just the outer envelope.  A multi-section design (teeth, dumbbell) has GAPS
    between its sections, and those gaps are the whole point: a prior route's job was
    to keep the scaffold's end-turns out of them.  Collapsing a helix to (min, max)
    would leave a domain that had been pushed into an inter-tooth gap sitting inside
    the envelope, and the reset would silently keep the corruption it exists to undo.
    """
    out: dict[str, list[tuple[int, int]]] = {}
    for hid, ranges in _staple_coverage(design).items():
        merged: list[tuple[int, int]] = []
        for lo, hi in sorted(ranges):
            # Touching/abutting ranges (hi + 1 == lo) are one continuous duplex.
            if merged and lo <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        if merged:
            out[hid] = merged
    return out


def structural_extents(design: Design) -> dict[str, tuple[int, int]]:
    """helix_id -> (lo, hi) outer bp span of its staples — the helix's true extent."""
    return {
        hid: (ivs[0][0], ivs[-1][1])
        for hid, ivs in structural_intervals(design).items()
    }


def _snap_to_interval(lo: int, hi: int, intervals: list[tuple[int, int]]):
    """Clamp [lo, hi] into whichever staple interval it overlaps most (None if none)."""
    best, best_ov = None, 0
    for ilo, ihi in intervals:
        ov = min(hi, ihi) - max(lo, ilo) + 1
        if ov > best_ov:
            best, best_ov = (ilo, ihi), ov
    if best is None:                     # no overlap at all (e.g. a domain wholly in
        return None                      # a gap) — caller decides what to do
    return max(lo, best[0]), min(hi, best[1])


def _axis_unit(helix: Helix):
    ax = helix.axis_end.to_array() - helix.axis_start.to_array()
    ax_len = float(math.sqrt(float((ax * ax).sum())))
    return ax / ax_len if ax_len > 1e-9 else None


def _set_helix_extent(helix: Helix, lo: int, hi: int) -> Helix:
    """Return *helix* re-cut to exactly [lo, hi] bp.

    The exact inverse of ``seamed_router._extend_helix_lo`` / ``_extend_helix_hi``,
    generalised to shrink as well as grow:

    * moving the LO end by ``d`` bp shifts ``axis_start`` along the axis by
      ``d * rise``, changes ``length_bp`` by ``-d``, and rotates ``phase_offset`` by
      ``d * twist_per_bp_rad`` — the helical phase is anchored at ``bp_start``, so
      moving that anchor must carry the phase with it or every downstream crossover
      site shifts.
    * moving the HI end changes ``axis_end`` and ``length_bp`` only (phase unaffected).
    """
    unit = _axis_unit(helix)
    if unit is None:
        return helix

    cur_lo = helix.bp_start
    cur_hi = helix.bp_start + helix.length_bp - 1
    d_lo = lo - cur_lo          # >0 shrink from the lo end, <0 grow
    d_hi = cur_hi - hi          # >0 shrink from the hi end, <0 grow
    if d_lo == 0 and d_hi == 0:
        return helix

    return helix.model_copy(update={
        "axis_start":   Vec3.from_array(
            helix.axis_start.to_array() + d_lo * BDNA_RISE_PER_BP * unit),
        "axis_end":     Vec3.from_array(
            helix.axis_end.to_array() - d_hi * BDNA_RISE_PER_BP * unit),
        "bp_start":     lo,
        "length_bp":    hi - lo + 1,
        "phase_offset": helix.phase_offset + d_lo * helix.twist_per_bp_rad,
    })


# Every ``process_id`` an autoscaffold route stamps on a crossover it creates.
#
# The seamed router uses THREE, not one: ``auto_scaffold_seamed:seam`` for the seam
# pair, and the bare ``create_near_ends`` / ``create_far_ends`` for the end-turns.
# ``seamed_router._auto_scaffold_process_id`` only matches the ``auto_scaffold_``
# prefix, so the near/far end crossovers survived every "clear" — which is why a
# re-route accumulated crossovers 6 -> 9 -> 12 even though clearing looked correct.
# (Same list as ``section_router._is_scaffold_route_xover``, which had it right.)
_ROUTE_XOVER_PREFIXES = ("auto_scaffold_",)
_ROUTE_XOVER_IDS = frozenset({"create_near_ends", "create_far_ends"})


def is_route_crossover(process_id: str | None) -> bool:
    """True if this crossover was created BY an autoscaffold route (so a reset owns it)."""
    pid = process_id or ""
    return pid.startswith(_ROUTE_XOVER_PREFIXES) or pid in _ROUTE_XOVER_IDS


def reset_scaffold_to_structure(design: Design) -> tuple[Design, list[str]]:
    """Retract a prior auto-route back to the staple-defined structural seed.

    Idempotent and safe on a never-routed design (nothing to retract → returns it
    unchanged).  Returns ``(design, warnings)``.
    """
    warnings: list[str] = []

    if design.forced_ligations:
        warnings.append(
            "Prior scaffold route was NOT reset because manual forced ligations are "
            "present (their fixed-edge topology is not derivable from the staples). "
            "Re-routing will build on the existing route; clear the forced ligations "
            "first if a clean rebuild is intended."
        )
        return design, warnings

    intervals = structural_intervals(design)
    extents = structural_extents(design)
    if not extents:
        return design, warnings          # no staples anywhere → nothing to anchor to

    # 1. Helices: re-cut to the staple span (skip any helix with no staples).
    new_helices, retracted = [], 0
    for h in design.helices:
        target = extents.get(h.id)
        if target is None:
            new_helices.append(h)
            continue
        # RETRACT ONLY.  The route only ever extends a helix outward past its staples,
        # so pulling back to the staple span is enough to undo it.  Growing a helix
        # that was already shorter than its staples would be editing a design nobody
        # routed — out of scope for a reset.
        cur_hi = h.bp_start + h.length_bp - 1
        cut = _set_helix_extent(h, max(h.bp_start, target[0]), min(cur_hi, target[1]))
        if cut is not h:
            retracted += 1
        new_helices.append(cut)

    # 2. Scaffold strands: back to one bare per-helix domain, clamped to the extent.
    #    (A routed scaffold is one long multi-domain strand; the seed is one strand
    #    per domain, which is the shape a freshly built design has.)
    # 2. Scaffold: REBUILD the seed rather than patch the route.  The seed shape a
    #    freshly built design has (lattice.make_bundle_design) is ONE bare scaffold
    #    strand per helix, holding ONE domain that spans it, 5'->3' along the helix's
    #    scaffold direction.  Clamping the routed strand's domains instead is not
    #    enough: a routed helix carries TWO domains (split at the seam), so the seam
    #    split would survive the reset and the re-route would start from a different
    #    seed than the first route did — converging, but to the wrong fixed point
    #    (measured: 5 scaffold strands out, instead of 1).  One strand per (helix,
    #    staple interval) reproduces the fresh shape exactly, and gives a
    #    multi-section design (teeth) one seed per tooth, which is what it wants.
    #    CLAMP INTO the staple interval; never GROW the scaffold to fill it.  A route
    #    only ever pushes the scaffold PAST the staples (that is the whole bug), so
    #    clamping is sufficient to undo it — while growing would also "fix" a scaffold
    #    the user deliberately left short of its staples, silently editing a design
    #    that was never routed.  (Pinned by test_two_group_design_has_bridge_xovers,
    #    whose arms carry a short scaffold under full-length staples.)
    scaf_dir: dict[str, Direction] = {}
    scaf_cov: dict[str, list[tuple[int, int]]] = {}
    for s in design.strands:
        if s.is_reference or s.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in s.domains:
            scaf_dir.setdefault(dom.helix_id, dom.direction)
            scaf_cov.setdefault(dom.helix_id, []).append(
                (min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)))

    def _touches_reset_helix(strand) -> bool:
        return any(dom.helix_id in intervals for dom in strand.domains)

    new_strands, seeds = [], 0
    for s in design.strands:
        # Staples ARE the structure — never touched.  A scaffold strand on a helix we
        # are not resetting (no staples → extent undefined) is likewise left alone.
        if s.is_reference or s.strand_type != StrandType.SCAFFOLD or not _touches_reset_helix(s):
            new_strands.append(s)

    for h in design.helices:
        ivs = intervals.get(h.id)
        direction = scaf_dir.get(h.id)
        if ivs is None or direction is None:
            continue                     # no staples, or no scaffold on this helix
        for i, (ilo, ihi) in enumerate(ivs):
            # The scaffold's OWN reach inside this staple interval.  A routed helix has
            # two domains here (split at the seam, e.g. (0,81) + (82,167)); they are
            # adjacent, so their union heals the split back into one seed domain.
            reach = [(lo, hi) for lo, hi in scaf_cov[h.id] if lo <= ihi and hi >= ilo]
            if not reach:
                continue                 # no scaffold in this section — nothing to seed
            lo = max(ilo, min(r[0] for r in reach))
            hi = min(ihi, max(r[1] for r in reach))
            # Convention (lattice.make_bundle_design): start_bp = 5' end, end_bp = 3'.
            start, end = (lo, hi) if direction == Direction.FORWARD else (hi, lo)
            new_strands.append(Strand(
                id=f"scaf_seed_{h.id}_{i}",
                domains=[Domain(helix_id=h.id, start_bp=start, end_bp=end,
                                direction=direction)],
                strand_type=StrandType.SCAFFOLD,
            ))
            seeds += 1

    # 3. Drop the prior route's own crossovers (manual ones are kept).
    kept = [xo for xo in design.crossovers if not is_route_crossover(xo.process_id)]
    dropped = len(design.crossovers) - len(kept)

    if retracted or dropped:
        warnings.append(
            f"Reset prior auto-scaffold route to the structural seed: retracted "
            f"{retracted} helix/helices to their staple extent, re-seeded {seeds} "
            f"scaffold domain(s), dropped {dropped} auto-scaffold crossover(s)."
        )

    return design.copy_with(
        helices=new_helices, strands=new_strands, crossovers=kept
    ), warnings
