"""
caDNAno v2 import for NADOC.

caDNAno v2 JSON format
══════════════════════
Top-level:
    {"name": str, "vstrands": [vstrand, ...]}

Each vstrand:
    {
        "row": int,            # grid row in caDNAno canvas
        "col": int,            # grid column
        "num": int,            # helix number (0-based ordering)
        "scaf": [[ph,pp,nh,np], ...],   # scaffold linked list, length = N bp
        "stap": [[ph,pp,nh,np], ...],   # staple linked list, length = N bp
        "loop": [int, ...],    # per-bp loop counts (+n = n extra bases inserted)
        "skip": [int, ...],    # per-bp skip flags (-1 = deletion)
        "stap_colors": [[bp_index, color_int], ...],  # color at 5′ of each staple
        "scaf_colors": [[bp_index, color_int], ...]   # scaffold color hints (unused)
    }

Linked-list entry format
    [prev_helix_num, prev_bp, next_helix_num, next_bp]
    -1 in any position = no connection (5′ or 3′ terminus).

Direction convention
    vstrand.num % 2 == 0 → scaffold runs FORWARD (5′→3′, bp increasing)
    vstrand.num % 2 == 1 → scaffold runs REVERSE (5′→3′, bp decreasing)

Global bp coordinate system
    bp_start = 0 for all imported helices.
    length_bp = len(vstrand['scaf'])  (the full caDNAno array length).
    Domain start_bp / end_bp values are caDNAno bp array indices (global bp).
    All helices share the same bp=0 slice plane (z=0).  Designs that begin at
    bp≥30 simply have empty slots at indices 0..29; the active DNA starts at
    whatever bp the linked list first becomes non-empty.

Colour
    stap_colors stores a 24-bit RGB integer (e.g. 0xF7931E = orange).
    We convert to "#RRGGBB" and store in Strand.color for roundtrip fidelity.
"""

from __future__ import annotations

import math
import uuid
from typing import Dict, List, Optional, Set, Tuple

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_LATTICE_RADIUS,
    SQUARE_COL_PITCH,
    SQUARE_ROW_PITCH,
)
from backend.core.models import (
    Crossover,
    CrossoverType,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    LoopSkip,
    Strand,
    StrandType,
    Vec3,
)

# Phase offsets (radians) — same as native NADOC bundles.
_PHASE_FORWARD = math.radians(322.2)
_PHASE_REVERSE = math.radians(252.2)

# caDNAno2 HC row step (from honeycombpart.py: y = row * radius * 3 + stagger).
# This is 3 × LATTICE_RADIUS = 3.375 nm — NOT the NADOC ROW_PITCH of 2.25 nm.
_HC_ROW_STEP: float = 3.0 * HONEYCOMB_LATTICE_RADIUS  # 3.375 nm


def _cadnano_y_hc(row: int, col: int) -> float:
    """Physical Y (Y-down) of a caDNAno HC vstrand, per caDNAno2 source.

    honeycombpart.py::latticeCoordToPositionXY:
        if isOddParity(row, col):   # (row%2) ^ (col%2)
            y = row * radius * 3 + radius
        else:
            y = row * radius * 3
    """
    odd_parity = (row % 2) ^ (col % 2)
    return row * _HC_ROW_STEP + (HONEYCOMB_LATTICE_RADIUS if odd_parity else 0.0)


# ── Lattice detection ─────────────────────────────────────────────────────────


def _detect_lattice(vstrands: List[dict]) -> LatticeType:
    """Return HONEYCOMB or SQUARE based on vstrand placement.

    Heuristic: scan for any vstrand whose (row, col) falls on a caDNAno HC
    hole position.  In caDNAno HC the num % 2 parity must match the cell
    parity rule; in SQ every cell is valid regardless of parity.

    caDNAno HC validity (from the caDNAno source): a cell (row, col) is
    valid for a FORWARD helix when (row % 2 + col % 2) % 2 == 0  (i.e. same
    parity), and for REVERSE when they differ.  No cell is a "hole" in the
    abstract grid; caDNAno just never places vstrands at invalid positions.

    We detect SQ by checking whether any (row, col) pair has a num parity
    that DISAGREES with the HC formula.  If all agree → HC; any disagree → SQ.
    """
    for v in vstrands:
        row, col, num = v["row"], v["col"], v["num"]
        # HC expected parity: (row % 2 + col % 2) % 2 == 0 → FORWARD (even num)
        hc_expected_forward = ((row % 2 + col % 2) % 2) == 0
        is_forward = (num % 2) == 0
        if hc_expected_forward != is_forward:
            return LatticeType.SQUARE
    return LatticeType.HONEYCOMB


# ── Position helpers ──────────────────────────────────────────────────────────


def _helix_xy(
    cadnano_row: int,
    cadnano_col: int,
    max_row: int,
    min_col: int,
    max_y_cad: float,
    lattice: LatticeType,
) -> Tuple[float, float, int, int]:
    """Return (x_nm, y_nm, nadoc_nr, nadoc_nc) for a caDNAno vstrand.

    Honeycomb
    ---------
    Uses the exact caDNAno2 physical formula (honeycombpart.py):
        x    = col  * COL_PITCH                         (COL_PITCH = R√3)
        y_dn = row  * 3R + (R if odd_parity else 0)     (Y-down, R = 1.125 nm)

    The row step is 3R = 3.375 nm — NOT NADOC's 2.25 nm ROW_PITCH.
    Adjacent HC rows (row ± 1) within the same column are 2.25 nm or 4.5 nm
    apart depending on which direction gives an antiparallel neighbour.
    Each helix has exactly 3 antiparallel neighbours at 2.25 nm with 120° gaps.

    After Y-flip (NADOC is Y-up):  y = max_y_cad - y_dn
    max_y_cad is the maximum y_dn across all vstrands (precomputed by caller).

    Square
    ------
    Standard 2D grid: x = nc * 2.25 nm, y = nr * 2.25 nm (after Y-flip).
    """
    nc = cadnano_col - min_col
    nr = max_row - cadnano_row
    if lattice == LatticeType.HONEYCOMB:
        x = nc * HONEYCOMB_COL_PITCH
        y = max_y_cad - _cadnano_y_hc(cadnano_row, cadnano_col)
    else:
        x = nc * SQUARE_COL_PITCH
        y = nr * SQUARE_ROW_PITCH
    return x, y, nr, nc


# ── Colour conversion ─────────────────────────────────────────────────────────


def _int_to_hex(color_int: int) -> str:
    """Convert a caDNAno 24-bit RGB integer to '#RRGGBB' string."""
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return f"#{r:02X}{g:02X}{b:02X}"


def _hex_to_int(hex_color: str) -> int:
    """Convert '#RRGGBB' string to a 24-bit RGB integer."""
    h = hex_color.lstrip("#")
    return int(h, 16)


# ── Strand tracing ────────────────────────────────────────────────────────────


def _find_5primes(by_num: Dict[int, dict], strand_key: str) -> List[Tuple[int, int]]:
    """Find all 5′ ends: positions where prev == (-1, -1) but next is valid."""
    starts: List[Tuple[int, int]] = []
    for num, vs in sorted(by_num.items()):
        for bp, (ph, pp, nh, np_) in enumerate(vs[strand_key]):
            if ph == -1 and nh != -1:
                starts.append((num, bp))
    return starts


def _trace(
    by_num: Dict[int, dict],
    start_num: int,
    start_bp: int,
    strand_key: str,
) -> List[Tuple[int, int]]:
    """Walk the linked list from (start_num, start_bp) to 3′ end.

    Returns ordered list of (helix_num, bp_index) pairs, 5′→3′.
    """
    path: List[Tuple[int, int]] = []
    visited: Set[Tuple[int, int]] = set()
    cur_num, cur_bp = start_num, start_bp
    while True:
        key = (cur_num, cur_bp)
        if key in visited:
            break  # circular — shouldn't happen in well-formed files
        visited.add(key)
        path.append(key)
        ph, pp, nh, np_ = by_num[cur_num][strand_key][cur_bp]
        if nh == -1:
            break
        cur_num, cur_bp = nh, np_
    return path


def _path_to_domains_and_xovers(
    path: List[Tuple[int, int]],
    helix_by_num: Dict[int, Helix],
    strand_id: str,
) -> Tuple[List[Domain], List[Tuple[int, int, int]]]:
    """Convert a 5′→3′ path to Domain list and raw crossover info.

    Returns:
        domains   — list of Domain objects
        xover_raw — list of (domain_index_before, next_helix_num, next_bp)
                    for each cross-helix step in the path.  The domain at
                    domain_index_before is the one ENDING at the crossover.
    """
    if not path:
        return [], []

    domains: List[Domain] = []
    xover_raw: List[Tuple[int, int, int]] = []

    seg_start_num, seg_start_bp = path[0]
    prev_num, prev_bp = path[0]

    for i in range(1, len(path)):
        cur_num, cur_bp = path[i]

        if cur_num == prev_num:
            # Still on same helix — extend current segment.
            prev_num, prev_bp = cur_num, cur_bp
            continue

        # Cross-helix jump: close the current domain.
        direction = (
            Direction.FORWARD
            if prev_bp >= seg_start_bp
            else Direction.REVERSE
        )
        domains.append(Domain(
            helix_id=helix_by_num[seg_start_num].id,
            start_bp=seg_start_bp,
            end_bp=prev_bp,
            direction=direction,
        ))
        # Record crossover: (index of domain just closed, next helix num, next bp)
        xover_raw.append((len(domains) - 1, cur_num, cur_bp))

        # Start new segment.
        seg_start_num, seg_start_bp = cur_num, cur_bp
        prev_num, prev_bp = cur_num, cur_bp

    # Close final domain.
    direction = (
        Direction.FORWARD
        if path[-1][1] >= seg_start_bp
        else Direction.REVERSE
    )
    domains.append(Domain(
        helix_id=helix_by_num[seg_start_num].id,
        start_bp=seg_start_bp,
        end_bp=path[-1][1],
        direction=direction,
    ))

    return domains, xover_raw


# ── Crossover assembly ────────────────────────────────────────────────────────


def _build_crossovers(
    strands: List[Strand],
    xover_raw_by_strand: Dict[str, List[Tuple[int, int, int]]],
    helix_by_num: Dict[int, Helix],
) -> List[Crossover]:
    """Build Crossover objects from raw cross-helix steps.

    For each strand, xover_raw contains (domain_before_idx, next_helix_num,
    next_bp).  The crossover connects domain[i] (3′ end) → domain[i+1] (5′
    end) on consecutive domains of the SAME strand.

    Crossover type is inferred from the strand type.
    """
    crossovers: List[Crossover] = []

    for strand in strands:
        raw = xover_raw_by_strand.get(strand.id, [])
        xtype = (
            CrossoverType.SCAFFOLD
            if strand.strand_type == StrandType.SCAFFOLD
            else CrossoverType.STAPLE
        )
        for domain_before_idx, _next_num, _next_bp in raw:
            # domain_before_idx → domain after it in the same strand
            domain_after_idx = domain_before_idx + 1
            if domain_after_idx >= len(strand.domains):
                continue  # should not happen
            crossovers.append(Crossover(
                strand_a_id=strand.id,
                domain_a_index=domain_before_idx,
                strand_b_id=strand.id,
                domain_b_index=domain_after_idx,
                crossover_type=xtype,
            ))

    return crossovers


# ── Public import entry point ─────────────────────────────────────────────────


def import_cadnano(data: dict) -> Design:
    """Parse a caDNAno v2 JSON dict and return a NADOC Design.

    Parameters
    ----------
    data : dict
        Parsed JSON from a .json caDNAno v2 file.

    Returns
    -------
    Design
        Fully populated topological Design.  Geometry (nucleotide positions)
        is computed on demand from the Helix axes as usual.
    """
    vstrands: List[dict] = data.get("vstrands", [])
    if not vstrands:
        raise ValueError("caDNAno file contains no vstrands.")

    # Drop empty vstrands — caDNAno files often include placeholder vstrands
    # with no active bases (all scaf entries are [-1,-1,-1,-1]).  These have
    # no DNA content and should not become helices in the NADOC design.
    vstrands = [
        v for v in vstrands
        if any(nh != -1 or ph != -1 for ph, pp, nh, np_ in v["scaf"])
    ]
    if not vstrands:
        raise ValueError("caDNAno file contains no vstrands with active bases.")

    lattice = _detect_lattice(vstrands)

    # ── Build helices ─────────────────────────────────────────────────────────
    # All helices share the same bp array length (caDNAno convention).
    array_len = len(vstrands[0]["scaf"])

    # Coordinate normalisation anchors.
    max_row = max(v["row"] for v in vstrands)
    min_col = min(v["col"] for v in vstrands)

    # For HC: precompute the Y-down maximum so Y-flip gives min y = 0.
    if lattice == LatticeType.HONEYCOMB:
        max_y_cad = max(_cadnano_y_hc(v["row"], v["col"]) for v in vstrands)
    else:
        max_y_cad = 0.0

    helices: List[Helix] = []
    helix_by_num: Dict[int, Helix] = {}

    for v in vstrands:
        row, col, num = v["row"], v["col"], v["num"]
        x, y, nr, nc = _helix_xy(row, col, max_row, min_col, max_y_cad, lattice)

        # Trim axis to the actual active bp range so blunt-end rings sit at
        # the real DNA ends, not the empty caDNAno array boundaries.
        scaf_arr = v["scaf"]
        stap_arr = v["stap"]
        _inactive = [-1, -1, -1, -1]
        active_bps = [bp for bp in range(array_len)
                      if scaf_arr[bp] != _inactive or stap_arr[bp] != _inactive]
        first_bp = active_bps[0] if active_bps else 0
        last_bp  = active_bps[-1] if active_bps else array_len - 1

        direction = Direction.FORWARD if num % 2 == 0 else Direction.REVERSE
        phase = _PHASE_FORWARD if direction == Direction.FORWARD else _PHASE_REVERSE

        # Loop/skip: sum both arrays; caDNAno stores them separately but they
        # act at the same bp column.
        loop_skips: List[LoopSkip] = []
        for bp in range(array_len):
            lv = v["loop"][bp] if bp < len(v["loop"]) else 0
            sv = v["skip"][bp] if bp < len(v["skip"]) else 0
            if lv != 0:
                loop_skips.append(LoopSkip(bp_index=bp, delta=int(lv)))
            if sv != 0:
                # caDNAno skip is stored as -1 per base deleted
                loop_skips.append(LoopSkip(bp_index=bp, delta=int(sv)))

        helix = Helix(
            id=f"h_XY_{nr}_{nc}",
            axis_start=Vec3(x=x, y=y, z=first_bp * BDNA_RISE_PER_BP),
            axis_end=Vec3(x=x, y=y, z=last_bp * BDNA_RISE_PER_BP),
            phase_offset=phase,
            twist_per_bp_rad=BDNA_TWIST_PER_BP_RAD,
            length_bp=array_len,
            bp_start=first_bp,
            loop_skips=loop_skips,
        )
        helices.append(helix)
        helix_by_num[num] = helix

    # ── Build stap_colors lookup: (vstrand_num, bp) → "#RRGGBB" ──────────────
    stap_color_map: Dict[Tuple[int, int], str] = {}
    for v in vstrands:
        for bp_idx, color_int in v.get("stap_colors", []):
            if color_int > 0:  # skip near-zero placeholder values
                stap_color_map[(v["num"], bp_idx)] = _int_to_hex(color_int)

    by_num: Dict[int, dict] = {v["num"]: v for v in vstrands}

    # ── Trace scaffold strands ────────────────────────────────────────────────
    strands: List[Strand] = []
    xover_raw_by_strand: Dict[str, List[Tuple[int, int, int]]] = {}

    for start_num, start_bp in _find_5primes(by_num, "scaf"):
        path = _trace(by_num, start_num, start_bp, "scaf")
        strand_id = f"scaf_{start_num}_{start_bp}"
        domains, raw = _path_to_domains_and_xovers(path, helix_by_num, strand_id)
        strand = Strand(
            id=strand_id,
            domains=domains,
            strand_type=StrandType.SCAFFOLD,
            sequence=None,
            color=None,
        )
        strands.append(strand)
        xover_raw_by_strand[strand_id] = raw

    # ── Trace staple strands ──────────────────────────────────────────────────
    for start_num, start_bp in _find_5primes(by_num, "stap"):
        path = _trace(by_num, start_num, start_bp, "stap")
        strand_id = f"stap_{start_num}_{start_bp}"
        domains, raw = _path_to_domains_and_xovers(path, helix_by_num, strand_id)
        color = stap_color_map.get((start_num, start_bp))
        strand = Strand(
            id=strand_id,
            domains=domains,
            strand_type=StrandType.STAPLE,
            sequence=None,
            color=color,
        )
        strands.append(strand)
        xover_raw_by_strand[strand_id] = raw

    # ── Build Crossover objects ───────────────────────────────────────────────
    crossovers = _build_crossovers(strands, xover_raw_by_strand, helix_by_num)

    # ── Assemble Design ───────────────────────────────────────────────────────
    name = data.get("name", "Imported Design")
    # Strip .json extension if present
    if name.endswith(".json"):
        name = name[: -len(".json")]

    return Design(
        helices=helices,
        strands=strands,
        crossovers=crossovers,
        lattice_type=lattice,
        metadata=DesignMetadata(name=name),
    )
