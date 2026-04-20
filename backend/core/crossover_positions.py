"""
Topological layer — crossover site validation and vectorized lookup.

All functions are pure table lookups keyed by (is_forward, bp % period).
No geometric computation; no position or angle math.

is_forward = (row + col) % 2 == 0  (caDNAno parity rule)
"""

from __future__ import annotations

from backend.core.constants import (
    HC_CROSSOVER_OFFSETS,
    HC_CROSSOVER_PERIOD,
    HC_SCAFFOLD_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_PERIOD,
    SQ_SCAFFOLD_CROSSOVER_OFFSETS,
)
from backend.core.models import Crossover, Design, HalfCrossover, LatticeType


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


def extract_crossovers_from_strands(strands: list) -> list[Crossover]:
    """Build Crossover records from cross-helix domain transitions in a strand list.

    A DX crossover is identified by two consecutive domains on different helices
    where the 3′ bp of the first domain equals the 5′ bp of the second domain
    (i.e. d0.end_bp == d1.start_bp).  Loopouts from scadnano produce consecutive
    cross-helix domains where the bp indices differ and are correctly skipped.

    Both scaffold and staple strands are processed.  Each crossover is recorded
    once even if encountered from only one strand (slots cannot be double-occupied
    in a valid design).
    """
    seen: set[tuple] = set()
    crossovers: list[Crossover] = []
    for strand in strands:
        for i in range(len(strand.domains) - 1):
            d0 = strand.domains[i]
            d1 = strand.domains[i + 1]
            if d0.helix_id == d1.helix_id:
                continue  # same helix — not a crossover
            if d0.end_bp != d1.start_bp:
                continue  # loopout or malformed transition — not a DX crossover
            idx = d0.end_bp
            # Normalise order so each physical crossover only appears once.
            key = tuple(sorted([
                (d0.helix_id, idx, d0.direction.value),
                (d1.helix_id, d1.start_bp, d1.direction.value),
            ]))
            if key in seen:
                continue
            seen.add(key)
            crossovers.append(Crossover(
                half_a=HalfCrossover(helix_id=d0.helix_id, index=idx,           strand=d0.direction),
                half_b=HalfCrossover(helix_id=d1.helix_id, index=d1.start_bp,  strand=d1.direction),
            ))
    return crossovers


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
