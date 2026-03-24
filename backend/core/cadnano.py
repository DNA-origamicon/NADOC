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
    length_bp = len(vstrand['scaf'])  (the full caDNAno array length, e.g. 462).
    bp_start  = first active bp index (e.g. 30 for M13 18HB designs).
    Domain start_bp / end_bp values are caDNAno bp array indices (global bp).
    axis_start.z = bp_start * RISE,  axis_end.z = last_bp * RISE.
    Geometry uses the global bp index for both axial position and twist angle,
    so the helix backbone orientation at bp=30 is phase_offset + 30*twist,
    matching caDNAno's angular convention exactly.

X-axis convention
    caDNAno's canvas X increases rightward (col increasing).  NADOC's 3D view
    is mirrored about the YZ plane relative to caDNAno, so x is negated:
        axis_start.x = axis_end.x = -(nc * COL_PITCH)
    This makes the NADOC 3D layout match caDNAno's visual left-right ordering.

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
    SQUARE_TWIST_PER_BP_RAD,
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
from backend.core.sequences import domain_bp_range

# caDNAno grid dimensions (from cadnano2/views/styles.py defaults).
# HC: 30 rows × 32 cols, centre (15, 16).
# SQ: 50 rows × 50 cols, centre (25, 25).
_CADNANO_HC_MAX_ROWS: int = 30
_CADNANO_HC_MAX_COLS: int = 32
_CADNANO_HC_CENTER_ROW: int = _CADNANO_HC_MAX_ROWS // 2   # 15
_CADNANO_HC_CENTER_COL: int = _CADNANO_HC_MAX_COLS // 2   # 16

_CADNANO_SQ_MAX_ROWS: int = 50
_CADNANO_SQ_MAX_COLS: int = 50
_CADNANO_SQ_CENTER_ROW: int = _CADNANO_SQ_MAX_ROWS // 2   # 25
_CADNANO_SQ_CENTER_COL: int = _CADNANO_SQ_MAX_COLS // 2   # 25

# HC phase offsets (radians) — match lattice.py _lattice_phase_offset().
_PHASE_FORWARD = math.radians(322.2)
_PHASE_REVERSE = math.radians(252.2)

# SQ phase offsets (radians) — from lattice.py _lattice_phase_offset() for SQ.
_SQ_PHASE_FORWARD = math.radians(337.0)
_SQ_PHASE_REVERSE = math.radians(287.0)

# HC crossover period = 21 bp; SQ = 32 bp.  Used for lattice detection.
_HC_PERIOD: int = 21
_SQ_PERIOD: int = 32

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
    """Return HONEYCOMB or SQUARE based on the vstrand array length.

    Both HC and SQ use the same direction-parity rule ((row+col)%2==0 →
    FORWARD), so parity alone cannot distinguish the two lattice types.

    The reliable signal is the crossover period baked into the array length:
      - HC designs are created in 21-bp steps  → array_len % 21 == 0
      - SQ designs are created in 32-bp steps  → array_len % 32 == 0
      LCM(21, 32) = 672 bp, an astronomically large design; in practice all
      real designs are unambiguous.

    Fallback for ambiguous lengths (divisible by both or neither): treat as HC,
    which is the caDNAno default.
    """
    if not vstrands:
        return LatticeType.HONEYCOMB
    array_len = len(vstrands[0]["scaf"])
    is_hc = array_len % _HC_PERIOD == 0
    is_sq = array_len % _SQ_PERIOD == 0
    if is_sq and not is_hc:
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
        x = -(nc * SQUARE_COL_PITCH)        # axis_start uses x=-x, giving +(nc*pitch)
        y = -(nr * SQUARE_ROW_PITCH)       # axis_start uses y=y directly
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


def _count_circular_strands(
    by_num: Dict[int, dict],
    strand_key: str,
    visited: Set[Tuple[int, int]],
) -> int:
    """Count circular strands: active positions with no 5′ end, not already visited.

    A circular strand has every position connected on both sides (prev != -1 and
    next != -1).  These are never found by _find_5primes and are silently skipped
    during normal tracing.  This function counts how many distinct circular strands
    exist among positions not already covered by linear strand tracing.
    """
    n_circular = 0
    remaining = set()
    for num, vs in by_num.items():
        for bp, (ph, pp, nh, np_) in enumerate(vs[strand_key]):
            if nh != -1 and ph != -1:          # both ends connected → candidate
                key = (num, bp)
                if key not in visited:
                    remaining.add(key)

    while remaining:
        start = next(iter(remaining))
        # Trace the cycle, consuming all positions in it.
        cur = start
        while cur in remaining:
            remaining.discard(cur)
            num, bp = cur
            _, _, nh, np_ = by_num[num][strand_key][bp]
            if nh == -1:
                break
            cur = (nh, np_)
        n_circular += 1

    return n_circular


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


def import_cadnano(data: dict) -> Tuple["Design", List[str]]:
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

    # Keep a full reference dict for all vstrands (including stap-only ones) so
    # that circular-strand detection can scan them even if their scaf is empty.
    all_vstrands_by_num: Dict[int, dict] = {v["num"]: v for v in vstrands}

    # Drop empty vstrands — caDNAno files often include placeholder vstrands
    # with no active bases.  Keep any vstrand that has at least one active
    # scaffold OR staple entry; designs like the "Ultimate Polymer Hinge" have
    # structural arm helices that carry staples but no scaffold at all.
    vstrands = [
        v for v in vstrands
        if any(nh != -1 or ph != -1 for ph, pp, nh, np_ in v["scaf"])
        or any(nh != -1 or ph != -1 for ph, pp, nh, np_ in v["stap"])
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
        if lattice == LatticeType.SQUARE:
            twist = SQUARE_TWIST_PER_BP_RAD
            base_phase = _SQ_PHASE_FORWARD if direction == Direction.FORWARD else _SQ_PHASE_REVERSE
        else:
            twist = BDNA_TWIST_PER_BP_RAD
            base_phase = _PHASE_FORWARD if direction == Direction.FORWARD else _PHASE_REVERSE
        # geometry.py uses local_bp (0-based from first_bp) for the twist angle,
        # but caDNAno defines phase at bp=0 of the full array.  Bake in the shift
        # so that local_bp=0 yields the correct global phase at first_bp.
        phase = base_phase + first_bp * twist

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
            axis_start=Vec3(x=-x, y=y, z=first_bp * BDNA_RISE_PER_BP),
            axis_end=Vec3(x=-x, y=y, z=last_bp * BDNA_RISE_PER_BP),
            phase_offset=phase,
            twist_per_bp_rad=twist,
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
    scaf_visited: Set[Tuple[int, int]] = set()

    for start_num, start_bp in _find_5primes(by_num, "scaf"):
        path = _trace(by_num, start_num, start_bp, "scaf")
        scaf_visited.update(path)
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
    stap_visited: Set[Tuple[int, int]] = set()

    for start_num, start_bp in _find_5primes(by_num, "stap"):
        path = _trace(by_num, start_num, start_bp, "stap")
        stap_visited.update(path)
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

    # ── Detect circular strands ───────────────────────────────────────────────
    warnings: List[str] = []
    n_circ_scaf = _count_circular_strands(all_vstrands_by_num, "scaf", scaf_visited)
    n_circ_stap = _count_circular_strands(all_vstrands_by_num, "stap", stap_visited)
    n_circ = n_circ_scaf + n_circ_stap
    if n_circ:
        warnings.append(
            f"{n_circ} circular strand{'s' if n_circ > 1 else ''} not imported "
            f"(NADOC requires linear strands with a 5\u2032 end)."
        )

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
    ), warnings


# ── Public export entry point ─────────────────────────────────────────────────


def check_cadnano_compatibility(design: Design) -> List[str]:
    """Return a list of informational/warning strings about the design's
    compatibility with caDNAno v2 export.  An empty list means clean export.
    Strings prefixed with 'ERROR' indicate export will fail outright.
    """
    msgs: List[str] = []
    if design.lattice_type not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        msgs.append(
            "ERROR: caDNAno v2 export only supports HC and SQ lattices."
        )
    n_scaf = sum(1 for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    if n_scaf == 0:
        msgs.append("WARNING: No scaffold strand — only staple strands will be exported.")
    elif n_scaf > 1:
        msgs.append(
            f"WARNING: Design has {n_scaf} scaffold strands. "
            "caDNAno treats the scaffold as a single continuous loop."
        )
    if any(h.loop_skips for h in design.helices):
        msgs.append("INFO: Loop/skip insertions present and will be exported.")
    if any(s.sequence for s in design.strands):
        msgs.append(
            "INFO: Strand sequences are not stored in caDNAno v2 JSON. "
            "Export sequences separately via 'Export Sequences (CSV)'."
        )
    if design.overhangs:
        msgs.append(
            "INFO: Overhangs will be exported as regular staple strands "
            "(caDNAno has no overhang concept)."
        )
    return msgs


def _assign_grid_coords(
    helices: List[Helix],
    helix_scaffold_dir: Dict[str, Optional[Direction]],
    lattice: LatticeType,
) -> tuple:
    """Recover caDNAno (row, col) and direction for each helix.

    Returns (rows, cols, export_dirs) — dicts keyed by helix_id.

    HC geometry
    -----------
    col pitch = HONEYCOMB_COL_PITCH (≈1.9486 nm); row step = 3R (3.375 nm).
    FORWARD rows have no stagger; REVERSE rows are staggered by +R in y_cad.
    Parity rule: (row+col)%2 == 0 → FORWARD.

    SQ geometry
    -----------
    col pitch = row pitch = SQUARE_COL_PITCH (2.25 nm); no stagger.
    Parity rule identical to HC: (row+col)%2 == 0 → FORWARD.
    """
    import math as _math

    R = HONEYCOMB_LATTICE_RADIUS       # 1.125 nm (HC stagger unit)
    max_y = max(h.axis_start.y for h in helices)

    rows: Dict[str, int] = {}
    cols: Dict[str, int] = {}
    export_dirs: Dict[str, Direction] = {}

    if lattice == LatticeType.SQUARE:
        col_pitch = SQUARE_COL_PITCH   # 2.25 nm
        row_step  = SQUARE_ROW_PITCH   # 2.25 nm (uniform, no stagger)
    else:
        col_pitch = HONEYCOMB_COL_PITCH
        row_step  = _HC_ROW_STEP       # 3.375 nm

    for h in helices:
        nc = round(abs(h.axis_start.x) / col_pitch)
        col = nc
        cols[h.id] = col
        delta_y = max_y - h.axis_start.y

        direction = helix_scaffold_dir[h.id]

        if lattice == LatticeType.SQUARE:
            # SQ: no stagger — both directions use the same row formula.
            # Only the parity constraint differs.
            row = round(delta_y / row_step)
            if direction is None:
                # Infer: pick whichever parity gives better fit (same formula,
                # just choose parity that rounds more cleanly).
                if (row + col) % 2 == 0:
                    export_dirs[h.id] = Direction.FORWARD
                else:
                    export_dirs[h.id] = Direction.REVERSE
                rows[h.id] = row
            elif direction == Direction.FORWARD:
                if (row + col) % 2 != 0:
                    row += 1
                rows[h.id] = row
                export_dirs[h.id] = Direction.FORWARD
            else:  # REVERSE
                if (row + col) % 2 != 1:
                    row += 1
                rows[h.id] = row
                export_dirs[h.id] = Direction.REVERSE
        else:
            # HC: FORWARD rows have y_cad = row*3R; REVERSE = row*3R + R.
            if direction is None:
                row_f = round(delta_y / row_step)
                if (row_f % 2) != (col % 2):
                    row_f += 1
                err_f = abs(delta_y - row_f * row_step)

                row_r = round((delta_y - R) / row_step)
                if (row_r % 2) == (col % 2):
                    row_r += 1
                err_r = abs(delta_y - R - row_r * row_step)

                if err_f <= err_r:
                    rows[h.id] = row_f
                    export_dirs[h.id] = Direction.FORWARD
                else:
                    rows[h.id] = row_r
                    export_dirs[h.id] = Direction.REVERSE

            elif direction == Direction.FORWARD:
                row = round(delta_y / row_step)
                if (row % 2) != (col % 2):
                    row += 1
                rows[h.id] = row
                export_dirs[h.id] = Direction.FORWARD

            else:  # REVERSE
                row = round((delta_y - R) / row_step)
                if (row % 2) == (col % 2):
                    row += 1
                rows[h.id] = row
                export_dirs[h.id] = Direction.REVERSE

    # Centre in the caDNAno grid.  Offsets must have equal parity to
    # preserve FORWARD/REVERSE assignments (parity rule: (row+col)%2).
    if lattice == LatticeType.SQUARE:
        center_row, center_col = _CADNANO_SQ_CENTER_ROW, _CADNANO_SQ_CENTER_COL
    else:
        center_row, center_col = _CADNANO_HC_CENTER_ROW, _CADNANO_HC_CENTER_COL

    all_rows = list(rows.values())
    all_cols = list(cols.values())
    raw_row_off = center_row - (min(all_rows) + max(all_rows)) / 2
    raw_col_off = center_col - (min(all_cols) + max(all_cols)) / 2
    row_off = round(raw_row_off)
    col_off = round(raw_col_off)
    if (row_off % 2) != (col_off % 2):
        if abs(raw_row_off - row_off) >= abs(raw_col_off - col_off):
            row_off += 1
        else:
            col_off += 1
    for h_id in rows:
        rows[h_id] += row_off
        cols[h_id] += col_off

    return rows, cols, export_dirs


def export_cadnano(design: Design) -> dict:
    """Convert a NADOC Design to a caDNAno v2 JSON dict.

    Supports HC and SQ designs (native or imported).  Raises ValueError if
    helix positions cannot be mapped to valid caDNAno grid coordinates.

    Algorithm
    ---------
    1. Recover caDNAno (row, col) via _assign_grid_coords():
       HC  — col = round(|x|/COL_PITCH); FORWARD row via 3R step+stagger.
       SQ  — col = round(|x|/2.25nm);    row via uniform 2.25 nm step.
       Both: centre result in the caDNAno default grid.
    2. Assign unique num: even for FORWARD, odd for REVERSE.
    3. Build scaf/stap linked-list arrays from Domain objects.
    4. Write loop/skip from Helix.loop_skips; stap_colors from Strand.color.
    """
    if design.lattice_type not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        raise NotImplementedError(
            "caDNAno export only supports HC and SQ lattices."
        )

    helices = design.helices
    if not helices:
        raise ValueError("Design has no helices.")

    # ── Scaffold direction per helix ────────────────────────────────────────────
    helix_scaffold_dir: Dict[str, Optional[Direction]] = {h.id: None for h in helices}
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for domain in strand.domains:
            helix_scaffold_dir[domain.helix_id] = domain.direction

    # ── Assign (row, col) from XY positions ────────────────────────────────────
    rows, cols, export_dirs = _assign_grid_coords(
        helices, helix_scaffold_dir, design.lattice_type
    )

    # ── Assign caDNAno num (even=FORWARD, odd=REVERSE) ─────────────────────────
    sorted_helices = sorted(
        helices, key=lambda h: (rows[h.id], cols[h.id])
    )
    helix_num_map: Dict[str, int] = {}
    fwd_i = rev_i = 0
    for h in sorted_helices:
        if export_dirs[h.id] == Direction.FORWARD:
            helix_num_map[h.id] = fwd_i * 2
            fwd_i += 1
        else:
            helix_num_map[h.id] = rev_i * 2 + 1
            rev_i += 1

    # ── Build linked-list arrays ────────────────────────────────────────────────
    array_len = max(h.length_bp for h in helices)

    scaf_arrs: Dict[str, List[List[int]]] = {
        h.id: [[-1, -1, -1, -1] for _ in range(array_len)] for h in helices
    }
    stap_arrs: Dict[str, List[List[int]]] = {
        h.id: [[-1, -1, -1, -1] for _ in range(array_len)] for h in helices
    }

    def _fill_strand(strand: Strand, arrays: Dict[str, List[List[int]]]) -> None:
        domains = strand.domains
        n_domains = len(domains)
        for d_idx, domain in enumerate(domains):
            h_num = helix_num_map[domain.helix_id]
            bp_list = list(domain_bp_range(domain))
            n = len(bp_list)
            prev_d = domains[d_idx - 1] if d_idx > 0 else None
            next_d = domains[d_idx + 1] if d_idx < n_domains - 1 else None
            for i, bp in enumerate(bp_list):
                if i > 0:
                    ph, pp = h_num, bp_list[i - 1]
                elif prev_d is not None:
                    ph = helix_num_map[prev_d.helix_id]
                    pp = prev_d.end_bp
                else:
                    ph, pp = -1, -1
                if i < n - 1:
                    nh, np_ = h_num, bp_list[i + 1]
                elif next_d is not None:
                    nh = helix_num_map[next_d.helix_id]
                    np_ = next_d.start_bp
                else:
                    nh, np_ = -1, -1
                arrays[domain.helix_id][bp] = [ph, pp, nh, np_]

    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            _fill_strand(strand, scaf_arrs)
        else:
            _fill_strand(strand, stap_arrs)

    # ── stap_colors ────────────────────────────────────────────────────────────
    stap_colors_map: Dict[str, List[List[int]]] = {h.id: [] for h in helices}
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        color_int = _hex_to_int(strand.color) if strand.color else 0xF7931E
        bp_5p = strand.domains[0].start_bp
        h_id = strand.domains[0].helix_id
        if h_id in stap_colors_map:
            stap_colors_map[h_id].append([bp_5p, color_int])

    # ── loop / skip arrays ─────────────────────────────────────────────────────
    loop_map: Dict[str, List[int]] = {}
    skip_map: Dict[str, List[int]] = {}
    for h in helices:
        loop_arr = [0] * array_len
        skip_arr = [0] * array_len
        for ls in h.loop_skips:
            if 0 <= ls.bp_index < array_len:
                if ls.delta > 0:
                    loop_arr[ls.bp_index] = ls.delta
                elif ls.delta < 0:
                    skip_arr[ls.bp_index] = ls.delta
        loop_map[h.id] = loop_arr
        skip_map[h.id] = skip_arr

    # ── Assemble vstrands ──────────────────────────────────────────────────────
    vstrands = []
    for h in sorted_helices:
        vstrands.append({
            "row": rows[h.id],
            "col": cols[h.id],
            "num": helix_num_map[h.id],
            "scaf": scaf_arrs[h.id],
            "stap": stap_arrs[h.id],
            "loop": loop_map[h.id],
            "skip": skip_map[h.id],
            "stap_colors": stap_colors_map[h.id],
            "scaf_colors": [],
        })

    return {
        "name": design.metadata.name or "NADOC Export",
        "vstrands": vstrands,
    }
