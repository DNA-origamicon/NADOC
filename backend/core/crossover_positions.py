"""
Topological layer — crossover site validation and vectorized lookup.

All functions are pure table lookups keyed by (is_forward, bp % period).
No geometric computation; no position or angle math.

is_forward = (row + col) % 2 == 0  (caDNAno parity rule)
"""

from __future__ import annotations

from typing import TypedDict

from backend.core.constants import (
    HC_CROSSOVER_OFFSETS,
    HC_CROSSOVER_PERIOD,
    HC_SCAFFOLD_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_PERIOD,
    SQ_SCAFFOLD_CROSSOVER_OFFSETS,
)
from backend.core.models import Crossover, Design, ForcedLigation, HalfCrossover, Helix, LatticeType, StrandType


def _is_forward(row: int, col: int) -> bool:
    """True for even-parity (forward scaffold) cells."""
    return (row + col) % 2 == 0


def build_strand_ranges(
    design: Design,
) -> dict[tuple[str, str], list[tuple[int, int]]]:
    """Build ``(helix_id, direction_value)`` → ``[(lo, hi), …]`` from strand domains."""
    sr: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for strand in design.strands:
        for dom in strand.domains:
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            sr.setdefault((dom.helix_id, dom.direction.value), []).append((lo, hi))
    return sr


def slot_covered(
    sr: dict[tuple[str, str], list[tuple[int, int]]],
    helix_id: str,
    bp: int,
    direction: str,
) -> bool:
    """Return True if any strand domain covers *bp* on *helix_id* in *direction*."""
    for lo, hi in sr.get((helix_id, direction), []):
        if lo <= bp <= hi:
            return True
    return False


def crossover_neighbor(
    lattice_type: LatticeType,
    row: int,
    col: int,
    index: int,
    *,
    is_scaffold: bool = False,
) -> tuple[int, int] | None:
    """Return (neighbor_row, neighbor_col) for this cell at bp index, or None.

    None means this index is not a valid crossover site for this cell.
    Scaffold and staple crossovers occupy disjoint bp offset sets; pass
    ``is_scaffold=True`` to query the scaffold-specific table.
    """
    fwd = _is_forward(row, col)
    if lattice_type == LatticeType.HONEYCOMB:
        table = HC_SCAFFOLD_CROSSOVER_OFFSETS if is_scaffold else HC_CROSSOVER_OFFSETS
        delta = table.get((fwd, index % HC_CROSSOVER_PERIOD))
    else:
        table = SQ_SCAFFOLD_CROSSOVER_OFFSETS if is_scaffold else SQ_CROSSOVER_OFFSETS
        delta = table.get((fwd, index % SQ_CROSSOVER_PERIOD))
    if delta is None:
        return None
    return (row + delta[0], col + delta[1])


def all_valid_crossover_sites(
    design: Design,
    *,
    filter_by_strand_coverage: bool = True,
) -> list[dict]:
    """Return all valid crossover sites for helices currently in the design.

    A site is included only when both helices exist in the design (by grid_pos).
    Returns a list of dicts: {helix_a_id, helix_b_id, index}.

    Vectorizable: iterates all helices × all bp indices once.
    Both directions (A→B and B→A) are included so callers can filter by either
    helix without needing to check both orderings.
    """
    cell_to_helix = {
        (h.grid_pos[0], h.grid_pos[1]): h
        for h in design.helices
        if h.grid_pos is not None
    }
    # Compute per-helix minimum bp from strand domains (may be < bp_start for ss loops).
    min_domain_bp: dict[str, int] = {}
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hid = domain.helix_id
            if hid not in min_domain_bp or lo < min_domain_bp[hid]:
                min_domain_bp[hid] = lo

    # Strand coverage lookup — only built when filtering is requested.
    sr = build_strand_ranges(design) if filter_by_strand_coverage else None

    results = []
    for h in design.helices:
        if h.grid_pos is None:
            continue
        row, col = h.grid_pos
        lo = min_domain_bp.get(h.id, h.bp_start)
        hi = h.bp_start + h.length_bp
        for index in range(lo, hi):
            nb = crossover_neighbor(design.lattice_type, row, col, index)
            if nb is not None and nb in cell_to_helix:
                hb = cell_to_helix[nb]
                # Gate on strand occupancy: both helices must have a strand
                # at this bp index in the appropriate staple direction.
                if sr is not None:
                    fwd = _is_forward(row, col)
                    stap_a = "REVERSE" if fwd else "FORWARD"
                    stap_b = "FORWARD" if fwd else "REVERSE"
                    if not (slot_covered(sr, h.id, index, stap_a)
                            and slot_covered(sr, hb.id, index, stap_b)):
                        continue
                results.append({
                    "helix_a_id": h.id,
                    "helix_b_id": hb.id,
                    "index": index,
                })
    return results


def extract_crossovers_from_strands(
    strands: list,
    helices: list[Helix] | None = None,
    lattice_type: LatticeType | None = None,
) -> tuple[list[Crossover], list[ForcedLigation]]:
    """Classify cross-helix domain transitions as Crossovers or ForcedLigations.

    Iterates consecutive cross-helix domain pairs ``(d0, d1)`` within each
    strand and emits one record per transition:

    * A **Crossover** when ``d0.end_bp == d1.start_bp`` AND the two helices
      are valid lattice neighbours at that bp (per the lattice's offset
      table, checking both staple and scaffold offsets).
    * A **ForcedLigation** otherwise — i.e. when the two halves disagree
      on bp index, or when the helices are not lattice neighbours at that
      site. This covers scadnano-style loopouts and any cross-helix junction
      that doesn't satisfy the strict DX-crossover geometry.

    When *helices* or *lattice_type* are not supplied (callers that don't
    have a Design context yet), the lattice-neighbour test is skipped and
    only the same-bp test is used.

    Each crossover is recorded once per ``(helix_a, idx_a, dir_a) /
    (helix_b, idx_b, dir_b)`` orbit so it never appears twice. Forced
    ligations preserve direction (3' side of d0 → 5' side of d1).
    """
    helix_grid: dict[str, tuple[int, int]] = {}
    if helices is not None:
        for h in helices:
            if h.grid_pos is not None:
                helix_grid[h.id] = (h.grid_pos[0], h.grid_pos[1])

    def _is_lattice_neighbor(d0_helix: str, d1_helix: str, idx: int) -> bool:
        """Check whether the two helices are valid crossover-neighbours at bp idx."""
        if lattice_type is None or not helix_grid:
            # No lattice context → assume neighbour (preserves old behaviour).
            return True
        a = helix_grid.get(d0_helix)
        b = helix_grid.get(d1_helix)
        if a is None or b is None:
            return False
        # Either staple-offset or scaffold-offset table maps a→b at this index.
        for is_scaf in (False, True):
            ab = crossover_neighbor(lattice_type, a[0], a[1], idx, is_scaffold=is_scaf)
            ba = crossover_neighbor(lattice_type, b[0], b[1], idx, is_scaffold=is_scaf)
            if (ab is not None and ab == b) or (ba is not None and ba == a):
                return True
        return False

    seen_xo: set[tuple] = set()
    seen_fl: set[tuple] = set()
    crossovers: list[Crossover] = []
    forced_ligations: list[ForcedLigation] = []
    for strand in strands:
        for i in range(len(strand.domains) - 1):
            d0 = strand.domains[i]
            d1 = strand.domains[i + 1]
            if d0.helix_id == d1.helix_id:
                continue  # same helix — not a junction
            same_bp = (d0.end_bp == d1.start_bp)
            if same_bp and _is_lattice_neighbor(d0.helix_id, d1.helix_id, d0.end_bp):
                idx = d0.end_bp
                key = tuple(sorted([
                    (d0.helix_id, idx, d0.direction.value),
                    (d1.helix_id, d1.start_bp, d1.direction.value),
                ]))
                if key in seen_xo:
                    continue
                seen_xo.add(key)
                crossovers.append(Crossover(
                    half_a=HalfCrossover(helix_id=d0.helix_id, index=idx,          strand=d0.direction),
                    half_b=HalfCrossover(helix_id=d1.helix_id, index=d1.start_bp,  strand=d1.direction),
                ))
            else:
                # Anything that fails the strict DX-neighbour test is recorded as a
                # ForcedLigation: same-bp non-neighbours, scadnano loopouts, etc.
                # The 3' side is d0's exit (end_bp); the 5' side is d1's entry (start_bp).
                key_fl = (
                    d0.helix_id, d0.end_bp, d0.direction.value,
                    d1.helix_id, d1.start_bp, d1.direction.value,
                )
                if key_fl in seen_fl:
                    continue
                seen_fl.add(key_fl)
                forced_ligations.append(ForcedLigation(
                    three_prime_helix_id=d0.helix_id,
                    three_prime_bp=d0.end_bp,
                    three_prime_direction=d0.direction,
                    five_prime_helix_id=d1.helix_id,
                    five_prime_bp=d1.start_bp,
                    five_prime_direction=d1.direction,
                ))
    return crossovers, forced_ligations


def validate_crossover(
    design: Design,
    half_a: HalfCrossover,
    half_b: HalfCrossover,
) -> str | None:
    """Return an error string, or None if the crossover is valid.

    Checks in order:
      1. Both helices exist and have grid_pos
      2. Indices are equal
      3. half_a's index maps to half_b's cell via the offset table
      4. Both slots are unoccupied

    NOTE: crossovers on overhang domains are intentionally allowed.  In the
    caDNAno tradition, overhangs are simply staple-only domains on neighbouring
    helices connected via crossovers — there is no overhang-specific guard here.
    """
    helix_map = {h.id: h for h in design.helices}
    ha = helix_map.get(half_a.helix_id)
    hb = helix_map.get(half_b.helix_id)
    if ha is None:
        return f"Helix {half_a.helix_id!r} not found"
    if hb is None:
        return f"Helix {half_b.helix_id!r} not found"
    if ha.grid_pos is None:
        return f"Helix {half_a.helix_id!r} has no grid_pos"
    if hb.grid_pos is None:
        return f"Helix {half_b.helix_id!r} has no grid_pos"
    if half_a.index != half_b.index:
        return f"Crossover indices must match ({half_a.index} ≠ {half_b.index})"
    # Check both staple and scaffold offset tables — a crossover is valid if
    # either table maps half_a's helix to half_b's cell (or vice versa).
    def _is_valid_neighbor(is_scaffold: bool) -> bool:
        eb = crossover_neighbor(design.lattice_type, *ha.grid_pos, half_a.index, is_scaffold=is_scaffold)
        ea = crossover_neighbor(design.lattice_type, *hb.grid_pos, half_b.index, is_scaffold=is_scaffold)
        return (
            (eb is not None and eb == tuple(hb.grid_pos))
            or (ea is not None and ea == tuple(ha.grid_pos))
        )

    if not (_is_valid_neighbor(False) or _is_valid_neighbor(True)):
        return f"Index {half_a.index} is not a valid crossover site for this helix pair"

    # 5. Both halves must connect strands of the same type (both scaffold or both staple).
    def _strand_type_at(helix_id: str, bp: int, direction) -> str | None:
        for s in design.strands:
            for dom in s.domains:
                if dom.helix_id != helix_id or dom.direction != direction:
                    continue
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                if lo <= bp <= hi:
                    return s.strand_type.value
        return None

    type_a = _strand_type_at(half_a.helix_id, half_a.index, half_a.strand)
    type_b = _strand_type_at(half_b.helix_id, half_b.index, half_b.strand)
    if type_a and type_b and type_a != type_b:
        return f"Crossover would connect {type_a} to {type_b} — both halves must be the same strand type"

    occupied: set[tuple[str, int, object]] = set()
    for xo in design.crossovers:
        occupied.add((xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand))
        occupied.add((xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand))
    for slot in (
        (half_a.helix_id, half_a.index, half_a.strand),
        (half_b.helix_id, half_b.index, half_b.strand),
    ):
        if slot in occupied:
            return f"Slot {slot} is already occupied by an existing crossover"
    return None


# ── Bow-direction lookup sets (same as auto_crossover in crud.py) ─────────────
_HC_BOW_RIGHT: frozenset[int] = frozenset({0, 7, 14})    # bp % 21 → bow-right
_SQ_BOW_RIGHT: frozenset[int] = frozenset({0, 8, 16, 24})  # bp % 32 → bow-right


class CrossoverRecord(TypedDict):
    """Fully enriched snapshot of a single crossover."""
    id: str
    bp_index: int
    from_helix_id: str
    from_helix_label: str   # helix.label if set, else str(positional index in design.helices)
    from_strand_direction: str  # "FORWARD" or "REVERSE" — strand direction on the from-helix
    to_helix_id: str
    to_helix_label: str
    to_strand_direction: str    # "FORWARD" or "REVERSE" — strand direction on the to-helix
    arc_direction: str          # "bow_right" or "bow_left"
    crossover_type: str         # "scaffold", "staple", or "unknown"
    process_id: str | None      # operation that placed this crossover
    extra_bases: str | None


def enumerate_crossovers(design: Design) -> list[CrossoverRecord]:
    """Return a CrossoverRecord for every crossover in the design.

    Fields:
    - from_helix / to_helix: half_a is the 3′-exit side (per extract_crossovers_from_strands
      convention); half_b is the 5′-entry side.  For manually placed crossovers the
      assignment follows the frontend request ordering.
    - arc_direction: "bow_right" when bp_index % period falls in the bow-right set for
      this lattice type, otherwise "bow_left".
    - crossover_type: derived from the strand_type of any strand domain that covers
      half_a's slot; "unknown" if no strand is found there.
    - process_id: whatever was written to Crossover.process_id at placement time.
    """
    # Build helix label and positional-index maps.
    helix_label: dict[str, str] = {}
    for i, h in enumerate(design.helices):
        helix_label[h.id] = h.label if h.label is not None else str(i)

    # Build strand-type lookup: (helix_id, direction_value) → list of (lo, hi, strand_type)
    slot_type: dict[tuple[str, str], list[tuple[int, int, str]]] = {}
    for strand in design.strands:
        stype = strand.strand_type.value
        for dom in strand.domains:
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            slot_type.setdefault((dom.helix_id, dom.direction.value), []).append((lo, hi, stype))

    def _crossover_type(helix_id: str, bp: int, direction_val: str) -> str:
        for lo, hi, stype in slot_type.get((helix_id, direction_val), []):
            if lo <= bp <= hi:
                return stype
        return "unknown"

    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow_right_set = _HC_BOW_RIGHT if is_hc else _SQ_BOW_RIGHT

    records: list[CrossoverRecord] = []
    for xo in design.crossovers:
        bp = xo.half_a.index
        arc_dir = "bow_right" if (bp % period) in bow_right_set else "bow_left"
        ctype = _crossover_type(xo.half_a.helix_id, bp, xo.half_a.strand.value)
        records.append(CrossoverRecord(
            id=xo.id,
            bp_index=bp,
            from_helix_id=xo.half_a.helix_id,
            from_helix_label=helix_label.get(xo.half_a.helix_id, xo.half_a.helix_id),
            from_strand_direction=xo.half_a.strand.value,
            to_helix_id=xo.half_b.helix_id,
            to_helix_label=helix_label.get(xo.half_b.helix_id, xo.half_b.helix_id),
            to_strand_direction=xo.half_b.strand.value,
            arc_direction=arc_dir,
            crossover_type=ctype,
            process_id=xo.process_id,
            extra_bases=xo.extra_bases,
        ))
    return records
