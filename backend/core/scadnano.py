"""
scadnano design import for NADOC.

scadnano JSON format
═════════════════════
Top-level:
    {
        "version": str,
        "grid": "square" | "honeycomb" | "none",
        "helices": [helix, ...],
        "strands": [strand, ...],
        "photoproduct_junctions": [junction, ...],  # CPD-fork extension
    }

Each helix:
    {
        "idx": int,               # (optional) explicit index; defaults to array position
        "grid_position": [row, col],
        "max_offset": int,        # exclusive upper bound of bp positions
        "min_offset": int,        # (optional, default 0) lower bound
    }

Each strand:
    {
        "color": "#RRGGBB",       # (optional)
        "sequence": str,          # (optional) full strand sequence
        "is_scaffold": bool,      # (optional, default false)
        "circular": bool,         # (optional, default false)
        "domains": [subdomain, ...]
    }

Each subdomain is one of:
    Helix domain:  {"helix": int, "forward": bool, "start": int, "end": int,
                    "deletions": [int, ...], "insertions": [[int, int], ...]}
    Loopout:       {"loopout": int}           (int = number of bases)
    Extension:     {"extension_num_bases": int}

Mapping to NADOC
════════════════
    Helix domain → Domain (start_bp inclusive, end_bp inclusive)
    Loopout      → CrossoverBases on the intra-strand Crossover flanking it
    Extension    → StrandExtension (five_prime or three_prime)
    photoproduct_junctions → PhotoproductJunction list on Design

Grid types
══════════
    "square"      → LatticeType.SQUARE    (supported)
    "honeycomb"   → LatticeType.HONEYCOMB (supported)
    "none"        → raises ValueError     (not supported)

Direction convention
════════════════════
    Helix phase uses even/odd index parity (same as caDNAno):
        idx % 2 == 0 → FORWARD  (scaffold runs 5′→3′ in increasing bp direction)
        idx % 2 == 1 → REVERSE
    Individual domain directions come from the explicit "forward" field.

Domain bp coordinates
═════════════════════
    scadnano uses half-open intervals [start, end).
    NADOC uses inclusive [start_bp, end_bp].
    For FORWARD:  start_bp = sc_start,  end_bp = sc_end - 1
    For REVERSE:  start_bp = sc_end - 1, end_bp = sc_start
    (start_bp is always the 5′ end of the domain)
"""

from __future__ import annotations

import math
import uuid
from typing import Dict, List, Optional, Tuple

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
    CrossoverBases,
    CrossoverType,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    LoopSkip,
    PhotoproductJunction,
    Strand,
    StrandExtension,
    StrandType,
    Vec3,
)

# Phase offsets (radians) — match cadnano.py convention.
_PHASE_FORWARD    = math.radians(322.2)
_PHASE_REVERSE    = math.radians(252.2)
_SQ_PHASE_FORWARD = math.radians(337.0)
_SQ_PHASE_REVERSE = math.radians(287.0)

# HC row step = 3 × helix radius (same formula as cadnano.py).
_HC_ROW_STEP: float = 3.0 * HONEYCOMB_LATTICE_RADIUS


# ── Coordinate helpers ────────────────────────────────────────────────────────


def _hc_y_down(row: int, col: int) -> float:
    """Physical Y (Y-down) for an HC grid position (same formula as cadnano.py)."""
    odd = (row % 2) ^ (col % 2)
    return row * _HC_ROW_STEP + (HONEYCOMB_LATTICE_RADIUS if odd else 0.0)


def _scadnano_xy(
    row: int, col: int,
    min_row: int, min_col: int, max_row: int,
    max_y_cad: float,
    lattice: LatticeType,
) -> Tuple[float, float]:
    """Return (x_nm, y_nm) for a scadnano helix in NADOC coordinates.

    Y-down → Y-up flip applied; grid normalised so minimum col/row maps to 0.
    Uses the same physical constants as the caDNAno importer.
    """
    nc = col - min_col
    nr = max_row - row
    if lattice == LatticeType.HONEYCOMB:
        x_pre = nc * HONEYCOMB_COL_PITCH
        y_pre = max_y_cad - _hc_y_down(row, col)
    else:  # SQUARE
        x_pre = nc * SQUARE_COL_PITCH
        y_pre = nr * SQUARE_ROW_PITCH
    # Rotate 90° CCW: X→Y, Y→-X
    return -y_pre, x_pre


# ── Main import function ──────────────────────────────────────────────────────


def import_scadnano(data: dict) -> Tuple[Design, List[str]]:
    """Parse a scadnano JSON dict and return a NADOC Design.

    Parameters
    ----------
    data : dict
        Parsed JSON from a scadnano .sc file.

    Returns
    -------
    (Design, List[str])
        Fully populated topological Design and a list of import warnings.

    Raises
    ------
    ValueError
        If the design uses an unsupported grid type ("none") or is otherwise
        malformed in a way that prevents import.
    """
    warnings: List[str] = []

    # ── Grid / lattice ────────────────────────────────────────────────────────
    grid = data.get("grid", "square")
    if grid == "none":
        raise ValueError(
            "scadnano 'none' grid (arbitrary 3-D helix positions) is not "
            "supported for import.  Use a square or honeycomb grid design."
        )
    lattice = LatticeType.SQUARE if grid == "square" else LatticeType.HONEYCOMB
    twist   = SQUARE_TWIST_PER_BP_RAD if lattice == LatticeType.SQUARE else BDNA_TWIST_PER_BP_RAD

    sc_helices: List[dict] = data.get("helices", [])
    if not sc_helices:
        raise ValueError("scadnano file contains no helices.")

    # ── Coordinate normalisation ──────────────────────────────────────────────
    grid_positions = [h["grid_position"] for h in sc_helices]
    rows = [gp[0] for gp in grid_positions]
    cols = [gp[1] for gp in grid_positions]
    min_row, min_col, max_row = min(rows), min(cols), max(rows)
    max_y_cad = (
        max(_hc_y_down(r, c) for r, c in zip(rows, cols))
        if lattice == LatticeType.HONEYCOMB
        else 0.0
    )

    # ── Pre-pass: actual bp ranges used per helix ────────────────────────────
    # scadnano helices often have [min_offset, max_offset) that spans more bp
    # than any strand actually occupies (e.g. max_offset=288 but strands only
    # use bp 96–189).  Trimming axis_start/axis_end to the real strand extent
    # ensures arrowheads, blunt-end rings, and labels sit at the actual bead
    # positions rather than floating off in empty space.
    _helix_bp_ranges: Dict[int, Tuple[int, int]] = {}
    for _sc in data.get("strands", []):
        if _sc.get("circular", False):
            continue
        for _d in _sc.get("domains", []):
            if "loopout" in _d or "extension_num_bases" in _d:
                continue
            _h_idx = _d["helix"]
            _lo, _hi = _d["start"], _d["end"] - 1   # inclusive [lo, hi]
            if _h_idx in _helix_bp_ranges:
                _plo, _phi = _helix_bp_ranges[_h_idx]
                _helix_bp_ranges[_h_idx] = (min(_plo, _lo), max(_phi, _hi))
            else:
                _helix_bp_ranges[_h_idx] = (_lo, _hi)

    # ── Build helices ─────────────────────────────────────────────────────────
    helices: List[Helix] = []
    # helix_by_idx maps helix index → (Helix, loop_skip_accumulator dict)
    helix_by_idx: Dict[int, Tuple[Helix, Dict[int, int]]] = {}

    for hi, h in enumerate(sc_helices):
        idx        = h.get("idx", hi)
        row, col   = h["grid_position"]
        min_offset = h.get("min_offset", 0)
        max_offset = h["max_offset"]

        x, y = _scadnano_xy(row, col, min_row, min_col, max_row, max_y_cad, lattice)

        direction = Direction.FORWARD if idx % 2 == 0 else Direction.REVERSE
        if lattice == LatticeType.SQUARE:
            base_phase = _SQ_PHASE_FORWARD if direction == Direction.FORWARD else _SQ_PHASE_REVERSE
        else:
            base_phase = _PHASE_FORWARD if direction == Direction.FORWARD else _PHASE_REVERSE

        # Skip empty helices (no strand domains) — they are derelict or placeholder
        # entries that carry no topology.  Warn and continue.
        if idx not in _helix_bp_ranges:
            warnings.append(
                f"Helix {idx} has no strand domains and was skipped."
            )
            continue

        actual_min, actual_max = _helix_bp_ranges[idx]

        # phase_offset = backbone angle at bp actual_min (local_i = 0).
        phase = base_phase + actual_min * twist

        helix = Helix(
            id=f"h_sc_{idx}",
            axis_start=Vec3(x=x, y=y, z=actual_min * BDNA_RISE_PER_BP),
            axis_end=Vec3(x=x, y=y, z=actual_max * BDNA_RISE_PER_BP),
            phase_offset=phase,
            twist_per_bp_rad=twist,
            length_bp=actual_max - actual_min + 1,
            bp_start=actual_min,
            loop_skips=[],
        )
        helices.append(helix)
        helix_by_idx[idx] = (helix, {})

    # ── Process strands ───────────────────────────────────────────────────────
    strands:         List[Strand]          = []
    crossovers:      List[Crossover]       = []
    crossover_bases: List[CrossoverBases]  = []
    extensions:      List[StrandExtension] = []

    for si, sc in enumerate(data.get("strands", [])):
        if sc.get("circular", False):
            warnings.append(
                f"Strand {si}: circular strands are not supported and were skipped."
            )
            continue

        is_scaffold = sc.get("is_scaffold", False)
        strand_type = StrandType.SCAFFOLD if is_scaffold else StrandType.STAPLE
        color_hex   = sc.get("color") if not is_scaffold else None
        sc_seq: Optional[str] = sc.get("sequence")

        # ── Classify subdomains ───────────────────────────────────────────────
        parsed: List[Tuple[str, dict]] = []
        for d in sc.get("domains", []):
            if "loopout" in d:
                parsed.append(("loopout", d))
            elif "extension_num_bases" in d:
                parsed.append(("ext", d))
            else:
                parsed.append(("helix", d))

        # Detect terminal extensions (first / last only).
        ext5_entry = parsed[0]  if (parsed and parsed[0][0]  == "ext") else None
        ext3_entry = parsed[-1] if (parsed and parsed[-1][0] == "ext") else None
        # Edge case: single-element list that is an extension — treat as 5′ only.
        if ext3_entry is ext5_entry:
            ext3_entry = None

        terminal_positions = set()
        if ext5_entry is not None: terminal_positions.add(0)
        if ext3_entry is not None: terminal_positions.add(len(parsed) - 1)

        for k, (t, _) in enumerate(parsed):
            if t == "ext" and k not in terminal_positions:
                warnings.append(
                    f"Strand {si}: extension at internal position {k} ignored."
                )

        # ── Build NADOC domains ───────────────────────────────────────────────
        nadoc_domains: List[Domain] = []
        for t, d in parsed:
            if t != "helix":
                continue
            helix_idx = d["helix"]
            entry = helix_by_idx.get(helix_idx)
            if entry is None:
                warnings.append(
                    f"Strand {si} domain: references unknown helix {helix_idx}, skipped."
                )
                continue
            helix, ls_map = entry

            fwd     = d["forward"]
            sc_s    = d["start"]
            sc_e    = d["end"]
            start_bp = sc_s     if fwd else sc_e - 1
            end_bp   = sc_e - 1 if fwd else sc_s
            direction = Direction.FORWARD if fwd else Direction.REVERSE

            # Accumulate loop/skip entries for this helix.
            for del_bp in d.get("deletions", []):
                ls_map[del_bp] = -1
            for off, cnt in d.get("insertions", []):
                ls_map[off] = cnt  # positive count → insertion

            nadoc_domains.append(Domain(
                helix_id=helix.id,
                start_bp=start_bp,
                end_bp=end_bp,
                direction=direction,
            ))

        if not nadoc_domains:
            warnings.append(f"Strand {si}: no helix domains found, skipped.")
            continue

        sid = f"sc_strand_{si}"
        strand = Strand(
            id=sid,
            domains=nadoc_domains,
            strand_type=strand_type,
            sequence=None,
            color=color_hex,
        )

        # ── Intra-strand crossovers ───────────────────────────────────────────
        xover_type = CrossoverType.SCAFFOLD if is_scaffold else CrossoverType.STAPLE
        strand_xovers: List[Crossover] = []
        for i in range(len(nadoc_domains) - 1):
            xo = Crossover(
                strand_a_id=sid,
                domain_a_index=i,
                strand_b_id=sid,
                domain_b_index=i + 1,
                crossover_type=xover_type,
            )
            strand_xovers.append(xo)

        # ── CrossoverBases for loopouts ───────────────────────────────────────
        # Walk parsed in order, tracking which helix domain pair each loopout
        # falls between.
        strand_cbs: List[Optional[CrossoverBases]] = []
        hd_count = 0  # number of helix domains seen so far

        for t, d in parsed:
            if t == "helix":
                hd_count += 1
            elif t == "loopout":
                prev_di = hd_count - 1
                next_di = hd_count
                if prev_di < 0 or next_di >= len(nadoc_domains):
                    warnings.append(
                        f"Strand {si}: loopout not between two helix domains, skipped."
                    )
                    strand_cbs.append(None)
                    continue
                if nadoc_domains[prev_di].helix_id == nadoc_domains[next_di].helix_id:
                    warnings.append(
                        f"Strand {si}: loopout between same-helix domains not supported, skipped."
                    )
                    strand_cbs.append(None)
                    continue
                xo = strand_xovers[prev_di]
                num_bases = d["loopout"]
                cb = CrossoverBases(
                    crossover_id=xo.id,
                    strand_id=sid,
                    sequence="N" * num_bases,
                )
                strand_cbs.append(cb)

        # ── StrandExtensions ──────────────────────────────────────────────────
        ext5_obj: Optional[StrandExtension] = None
        ext3_obj: Optional[StrandExtension] = None

        if ext5_entry is not None:
            ext5_obj = StrandExtension(
                strand_id=sid,
                end="five_prime",
                sequence="N" * ext5_entry[1]["extension_num_bases"],
            )
        if ext3_entry is not None:
            ext3_obj = StrandExtension(
                strand_id=sid,
                end="three_prime",
                sequence="N" * ext3_entry[1]["extension_num_bases"],
            )

        # ── Sequence slicing ──────────────────────────────────────────────────
        if sc_seq is not None:
            offset = 0
            helix_parts:   List[str] = []
            loopout_seqs:  List[str] = []
            ext_seqs:      List[str] = []

            for k, (t, d) in enumerate(parsed):
                if t == "helix":
                    ins  = sum(cnt for _, cnt in d.get("insertions", []))
                    dels = len(d.get("deletions", []))
                    n = (d["end"] - d["start"]) + ins - dels
                    helix_parts.append(sc_seq[offset : offset + n])
                    offset += n
                elif t == "loopout":
                    n = d["loopout"]
                    loopout_seqs.append(sc_seq[offset : offset + n])
                    offset += n
                elif t == "ext":
                    n = d["extension_num_bases"]
                    if k in terminal_positions:
                        ext_seqs.append(sc_seq[offset : offset + n])
                    offset += n

            strand.sequence = "".join(helix_parts) or None

            # Patch CrossoverBases sequences from actual loopout slices.
            loopout_iter = iter(loopout_seqs)
            for cb in strand_cbs:
                if cb is not None:
                    cb.sequence = next(loopout_iter, cb.sequence)

            # Patch extension sequences.
            ext_iter = iter(ext_seqs)
            if ext5_obj:
                ext5_obj.sequence = next(ext_iter, ext5_obj.sequence)
            if ext3_obj:
                ext3_obj.sequence = next(ext_iter, ext3_obj.sequence)

        # ── Collect results ───────────────────────────────────────────────────
        strands.append(strand)
        crossovers.extend(strand_xovers)
        crossover_bases.extend(cb for cb in strand_cbs if cb is not None)
        if ext5_obj:
            extensions.append(ext5_obj)
        if ext3_obj:
            extensions.append(ext3_obj)

    # ── Apply accumulated loop_skips to helices ───────────────────────────────
    for _idx, (helix, ls_map) in helix_by_idx.items():
        helix.loop_skips = sorted(
            [LoopSkip(bp_index=bp, delta=delta) for bp, delta in ls_map.items()],
            key=lambda ls: ls.bp_index,
        )

    # ── Photoproduct junctions (CPD fork) ────────────────────────────────────
    pj_list: List[PhotoproductJunction] = [
        PhotoproductJunction(
            t1_stable_id=pj["t1_stable_id"],
            t2_stable_id=pj["t2_stable_id"],
            photoproduct_id=pj.get("photoproduct_id", "TT-CPD"),
        )
        for pj in data.get("photoproduct_junctions", [])
    ]

    # ── Assemble Design ───────────────────────────────────────────────────────
    design = Design(
        helices=helices,
        strands=strands,
        crossovers=crossovers,
        crossover_bases=crossover_bases,
        extensions=extensions,
        lattice_type=lattice,
        photoproduct_junctions=pj_list,
        metadata=DesignMetadata(name=data.get("name", "scadnano import")),
    )

    return design, warnings
