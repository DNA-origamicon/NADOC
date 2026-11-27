"""Rank fixed-register auxiliary lattice sites by native Full endpoint lengths.

Pure prospective geometry: no Design/Helix, atomistic candidate, or saved model
is constructed. Positions use the same O5' projection and locked phase constants
as the native viewer. A score is not a chemical bond or loop-conformation fit.
"""

import math

import numpy as np

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_ROW_PITCH,
    HONEYCOMB_LATTICE_RADIUS,
    FULL_REP_BALANCE_ROLL_HONEYCOMB_DEG,
    ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG,
)
from backend.core.geometry import _frame_from_helix_axis
from backend.core.lattice import (
    _lattice_direction,
    _lattice_position,
    _lattice_phase_offset,
    _lattice_twist,
)
from backend.core.models import Direction, LatticeType
from backend.core.native_full_placement import positions_in_native_frame, SOURCE


def scaffold_endpoint(cell, bp):
    """Prospective scaffold O5' in the untransformed HC frame, no indels."""
    lt = LatticeType.HONEYCOMB
    direction = _lattice_direction(*cell, lt)
    x, y = _lattice_position(*cell, lt)
    z = np.array([0.0, 0.0, 1.0])
    frame = _frame_from_helix_axis(z)
    angle = (
        _lattice_phase_offset(direction, lt)
        + bp * _lattice_twist(lt)
        + math.radians(
            FULL_REP_BALANCE_ROLL_HONEYCOMB_DEG - ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG
        )
    )
    radial = math.cos(angle) * frame[:, 0] + math.sin(angle) * frame[:, 1]
    return positions_in_native_frame(
        np.array([x, y, bp * BDNA_RISE_PER_BP]),
        radial,
        z,
        direction == Direction.REVERSE,
    )[0]


def rank_ligation_cells(cells, excursions, direction, *, max_candidates=65536):
    """Minimize SUM of full 3D O5'-O5' spans at the drawn covalent joins.

    All candidate cells have the same parity, hence the same endpoint offsets
    relative to their axes. Triangle inequality gives score >= N|xy-mean(t)|,
    where t are anchor XY minus those offsets. An exterior vacant cell supplies
    an upper bound; its score/N radius encloses EVERY possible minimum. The
    search therefore does not merely re-rank the old center-distance shortlist.
    """
    if not cells or not excursions or direction not in ("FORWARD", "REVERSE"):
        raise ValueError("Cells, excursions and a scaffold direction are required")
    lt = LatticeType.HONEYCOMB
    reference = (0, 1) if direction == "REVERSE" else (0, 0)
    reference_xy = np.array(_lattice_position(*reference, lt))
    endpoints = []
    for number, ex in enumerate(excursions):
        for endpoint, anchor in [
            ("start", "attachment_before"),
            ("end", "attachment_after"),
        ]:
            h, bp = ex[anchor]
            if h not in cells:
                raise ValueError("Scaffold attachment has no resolved lattice position")
            fixed = scaffold_endpoint(cells[h], bp)
            moving = scaffold_endpoint(reference, ex[endpoint][1])
            endpoints.append(
                {
                    "excursion": number,
                    "auxiliary_site": ex[endpoint],
                    "scaffold_site": ex[anchor],
                    "fixed": fixed,
                    "offset": np.array([*(moving[:2] - reference_xy), moving[2]]),
                }
            )
    occupied = {tuple(c) for c in cells.values()}

    def measure(row, col):
        xy = _lattice_position(row, col, lt)
        shift = np.array([*xy, 0.0])
        spans = [
            float(np.linalg.norm(shift + e["offset"] - e["fixed"])) for e in endpoints
        ]
        return {
            "cell": [row, col],
            "total_length_nm": sum(spans),
            "max_length_nm": max(spans),
            "ligation_lengths_nm": spans,
            "excursion_totals_nm": [
                sum(spans[2 * i : 2 * i + 2]) for i in range(len(excursions))
            ],
        }

    r = min(r for r, _ in occupied) - 1
    c = min(c for _, c in occupied) - 1
    if _lattice_direction(r, c, lt).value != direction:
        c -= 1
    incumbent = measure(r, c)["total_length_nm"]
    mean = np.mean([e["fixed"][:2] - e["offset"][:2] for e in endpoints], axis=0)
    radius = incumbent / len(endpoints) + 1e-8
    stagger = HONEYCOMB_LATTICE_RADIUS if direction == "REVERSE" else 0
    rlo = math.ceil((mean[1] - radius - stagger) / HONEYCOMB_ROW_PITCH)
    rhi = math.floor((mean[1] + radius - stagger) / HONEYCOMB_ROW_PITCH)
    clo = math.ceil((mean[0] - radius) / HONEYCOMB_COL_PITCH)
    chi = math.floor((mean[0] + radius) / HONEYCOMB_COL_PITCH)
    if (rhi - rlo + 1) * (chi - clo + 1) > max_candidates:
        return {
            "resolved": False,
            "search_complete": False,
            "best_cells": [],
            "reason": "Forced-ligation search exceeds its explicit cell budget",
        }
    candidates = [
        measure(r, c)
        for r in range(rlo, rhi + 1)
        for c in range(clo, chi + 1)
        if (r, c) not in occupied and _lattice_direction(r, c, lt).value == direction
    ]
    candidates.sort(key=lambda p: (p["total_length_nm"], p["cell"]))
    best = candidates[0]["total_length_nm"]
    tied = [
        p
        for p in candidates
        if math.isclose(p["total_length_nm"], best, rel_tol=1e-12, abs_tol=1e-9)
    ]
    tied.sort(key=lambda p: p["cell"])
    runner = next((p["total_length_nm"] for p in candidates if p not in tied), None)
    return {
        "resolved": len(tied) == 1,
        "search_complete": True,
        "direction": direction,
        "objective": "sum of native Full O5 endpoint spans at drawn forced ligations",
        "placement_source": SOURCE,
        "best_total_length_nm": best,
        "best_cells": [p["cell"] for p in tied],
        "best_candidates": tied,
        "candidates": candidates[:8],
        "candidates_tested": len(candidates),
        "next_length_gap_nm": None if runner is None else runner - best,
        "bounds": {"row": [rlo, rhi], "col": [clo, chi]},
        "endpoints": [
            {k: v for k, v in e.items() if k not in ("fixed", "offset")}
            for e in endpoints
        ],
        "fixed_register": True,
        "axial_translation_nm": 0,
        "limitation": "Unrelaxed source register; no axial/phase fitting or flexible-loop geometry. Long spans remain long.",
    }
