"""Infer auxiliary-track lattice locations from polarity and scaffold anchors.

No native reference or atomistic pose is an input. Equal minima remain explicit;
this inference is an idealized lattice assignment, not experimental geometry.
"""

import math

from backend.core.constants import (
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_ROW_PITCH,
    HONEYCOMB_LATTICE_RADIUS,
)
from backend.core.lattice import _lattice_direction, _lattice_position
from backend.core.models import LatticeType


TIE_ABS_NM2 = 1e-9


def rank_vacant_cells(cells, anchors, direction, *, max_candidates=65536):
    """Globally minimize summed squared transverse distances on the HC lattice.

    An exterior vacant cell supplies an upper bound. The identity
    sum(|x-a|²) = N|x-mean(a)|² + constant bounds every possible minimizer
    inside a finite disk. Enumerating its enclosing rectangle is exhaustive,
    including vacant interior cells. Repeated anchors count distinct connections.
    """
    lattice = LatticeType.HONEYCOMB
    occupied = {tuple(c) for c in cells.values()}
    if not occupied or not anchors or direction not in ("FORWARD", "REVERSE"):
        raise ValueError("Occupied cells, scaffold anchors and direction are required")
    if any(h not in cells for h in anchors):
        raise ValueError("An attachment has no recovered lattice position")
    targets = [_lattice_position(*cells[h], lattice) for h in anchors]
    mean = tuple(sum(p[i] for p in targets) / len(targets) for i in (0, 1))

    def measure(row, col):
        xy = _lattice_position(row, col, lattice)
        distances = [math.dist(xy, p) for p in targets]
        return {
            "cell": [row, col],
            "score_nm2": sum(d * d for d in distances),
            "attachment_distances_nm": distances,
        }

    row = min(r for r, _ in occupied) - 1
    col = min(c for _, c in occupied) - 1
    if _lattice_direction(row, col, lattice).value != direction:
        col -= 1
    incumbent = measure(row, col)["score_nm2"]
    constant = sum(math.dist(mean, p) ** 2 for p in targets)
    radius = math.sqrt(max(0, incumbent - constant) / len(targets)) + 1e-8
    stagger = HONEYCOMB_LATTICE_RADIUS if direction == "REVERSE" else 0
    rlo = math.ceil((mean[1] - radius - stagger) / HONEYCOMB_ROW_PITCH)
    rhi = math.floor((mean[1] + radius - stagger) / HONEYCOMB_ROW_PITCH)
    clo = math.ceil((mean[0] - radius) / HONEYCOMB_COL_PITCH)
    chi = math.floor((mean[0] + radius) / HONEYCOMB_COL_PITCH)
    if (rhi - rlo + 1) * (chi - clo + 1) > max_candidates:
        return {
            "resolved": False,
            "reason": "Attachment search exceeds its explicit cell budget",
            "search_complete": False,
            "best_cells": [],
            "candidates": [],
        }
    candidates = [
        measure(r, c)
        for r in range(rlo, rhi + 1)
        for c in range(clo, chi + 1)
        if (r, c) not in occupied
        and _lattice_direction(r, c, lattice).value == direction
    ]
    candidates.sort(key=lambda x: (x["score_nm2"], x["cell"]))
    best = candidates[0]["score_nm2"]
    tied = [
        c
        for c in candidates
        if math.isclose(c["score_nm2"], best, rel_tol=1e-12, abs_tol=TIE_ABS_NM2)
    ]
    tied.sort(key=lambda c: c["cell"])
    next_score = next((c["score_nm2"] for c in candidates if c not in tied), None)
    return {
        "resolved": len(tied) == 1,
        "search_complete": True,
        "objective": "sum of squared XY distances to each scaffold attachment",
        "direction": direction,
        "anchors": anchors,
        "best_score_nm2": best,
        "best_cells": [c["cell"] for c in tied],
        "best_candidates": tied,
        "candidates": candidates[:8],
        "candidates_tested": len(candidates),
        "bounds": {"row": [rlo, rhi], "col": [clo, chi]},
        "next_score_gap_nm2": None if next_score is None else next_score - best,
        "tie_tolerance_nm2": TIE_ABS_NM2,
    }


def infer_auxiliary_placement(lattice, classified, unpaired):
    """Use label parity only when it agrees with sequence-directed scaffold runs."""
    result = {
        "resolved": False,
        "tracks": [],
        "native_reference_consulted": False,
        "basis": "User-authorized label parity and minimum forced-ligation lengths for independent scaffold excursions",
        "limitation": "Inferred idealized lattice location; axial pose and loop conformation are not fitted.",
    }
    if not lattice.get("missing_helices"):
        return {
            **result,
            "resolved": bool(lattice.get("resolved")),
            "status": "no_auxiliary_placement_needed",
        }
    if (
        not lattice.get("inset_resolved")
        or lattice.get("kind") != "honeycomb"
        or not unpaired.get("resolved")
    ):
        return {
            **result,
            "reason": "Resolved inset and supported unpaired scaffold evidence are required",
        }
    if len(classified["scaf"]) != 1 or classified["unresolved"]:
        return {**result, "reason": "Complete directed scaffold routing is required"}
    steps = {}
    for a, b in zip(classified["scaf"][0]["sites"], classified["scaf"][0]["sites"][1:]):
        if a[0] == b[0] and abs(a[1] - b[1]) == 1:
            steps.setdefault(a[0], set()).add(1 if b[1] > a[1] else -1)
    cells = {int(h): tuple(c) for h, c in lattice["cells"].items()}
    missing = set(lattice["missing_helices"])
    for h in set(cells) | missing:
        if steps.get(h) != ({1} if h % 2 == 0 else {-1}):
            return {
                **result,
                "reason": "Label parity conflicts with directed scaffold evidence",
                "helix": h,
            }
    lt = LatticeType.HONEYCOMB
    shifts = [
        s
        for s in (0, 1)
        if all(
            _lattice_direction(r + s, c, lt).value
            == ("FORWARD" if h % 2 == 0 else "REVERSE")
            for h, (r, c) in cells.items()
        )
    ]
    if len(shifts) != 1:
        return {**result, "reason": "Inset parity translation is ambiguous"}
    cells = {h: (r + shifts[0], c) for h, (r, c) in cells.items()}
    result.update(lattice_translation_rows=shifts[0], inset_cells=cells)
    for h in sorted(missing):
        excursions = [a for a in unpaired["auxiliary_tracks"] if a["helix"] == h]
        if not excursions or not all(a["supported_excursion"] for a in excursions):
            return {
                **result,
                "reason": "Missing inset track lacks supported return attachments",
                "helix": h,
            }
        anchors = [
            a[k][0]
            for a in excursions
            for k in ("attachment_before", "attachment_after")
        ]
        from backend.core.publication_ligation_placement import rank_ligation_cells

        direction = "FORWARD" if h % 2 == 0 else "REVERSE"
        ranges = [
            {
                (h, bp)
                for bp in range(
                    min(a["start"][1], a["end"][1]), max(a["start"][1], a["end"][1]) + 1
                )
            }
            for a in excursions
        ]
        # Independent scaffold excursions may still be tied by a staple. Never
        # split a path-view row into independent pieces across such evidence.
        for path in classified["stap"]:
            sites = {tuple(site) for site in path["sites"]}
            if any(site[0] == h for site in sites) and not any(
                sites <= span for span in ranges
            ):
                return {
                    **result,
                    "reason": "Auxiliary staple connects outside an independent excursion",
                    "helix": h,
                }
        endpoint_sites = {
            tuple(a[k])
            for a in excursions
            for k in ("start", "end", "attachment_before", "attachment_after")
        }
        if endpoint_sites & {
            tuple(site) for site in unpaired.get("insertion_sites", [])
        }:
            return {
                **result,
                "reason": "Inserted endpoint needs an explicit copy selection",
                "helix": h,
            }
        segments = [
            {
                "source_start": a["start"],
                "source_end": a["end"],
                "attachment_before": a["attachment_before"],
                "attachment_after": a["attachment_after"],
                "paired_bases": a["paired_bases"],
                "unpaired_bases": a["unpaired_bases"],
                **rank_ligation_cells(cells, [a], direction),
            }
            for a in excursions
        ]
        common = rank_ligation_cells(cells, excursions, direction)
        result["tracks"].append(
            {
                "helix": h,
                "excursions": excursions,
                "segments": segments,
                "common_cell_rank": common,
                "center_distance_rank": rank_vacant_cells(cells, anchors, direction),
                "resolved": all(segment["resolved"] for segment in segments),
                "direction": direction,
            }
        )
    if not all(t["resolved"] for t in result["tracks"]):
        return {
            **result,
            "status": "ambiguous_or_incomplete",
            "reason": "Minimum forced-ligation length placement is not uniquely resolved",
        }
    inferred = [
        {
            "source_helix": t["helix"],
            "source_start": segment["source_start"],
            "source_end": segment["source_end"],
            "cell": segment["best_cells"][0],
        }
        for t in result["tracks"]
        for segment in t["segments"]
    ]
    if len({tuple(p["cell"]) for p in inferred}) != len(inferred):
        return {
            **result,
            "reason": "Independent excursions compete for the same cell; joint assignment unresolved",
        }
    return {
        **result,
        "resolved": True,
        "status": "inferred_independent_segments",
        "segment_placements": inferred,
        "limitation": "Unique fixed-register cell minima; long ligation spans remain. Native segment/loop authoring and geometry review are still required.",
    }
