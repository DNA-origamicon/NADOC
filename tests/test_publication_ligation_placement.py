import numpy as np
import pytest

from backend.core.publication_ligation_placement import (
    scaffold_endpoint,
    rank_ligation_cells,
)
from backend.core.lattice import _lattice_direction
from backend.core.models import LatticeType


def excursions():
    return [
        {
            "start": [19, 256],
            "end": [19, 179],
            "attachment_before": [0, 172],
            "attachment_after": [0, 173],
        },
        {
            "start": [19, 163],
            "end": [19, 98],
            "attachment_before": [1, 173],
            "attachment_after": [1, 172],
        },
    ]


def test_prospective_endpoint_matches_recorded_native_full_geometry():
    from tools.design_archive.recorded_authoring import construct
    from backend.core.design_geometry import native_full_nucleotide_at
    from backend.core.models import Direction

    recipe = {
        "version": 1,
        "name": "Endpoint regression",
        "design_id": "endpoint-test",
        "lattice": "HONEYCOMB",
        "unresolved": [],
        "sources": [],
        "operations": [],
    }
    for h, cell in enumerate([(0, 0), (0, 1)]):
        hid = f"00000000-0000-4000-8000-{h + 1:012d}"
        recipe["operations"].append(
            {
                "kind": "helix-add-at-cell",
                "label": f"Endpoint test helix {h}",
                "params": {
                    "row": cell[0],
                    "col": cell[1],
                    "length_bp": 280,
                    "populate_strands": False,
                    "_helix_id": hid,
                },
                "evidence": ["Regression of prospective native Full endpoints"],
            }
        )
    design = construct(recipe)
    for h, cell in zip(design.helices, [(0, 0), (0, 1)]):
        direction = _lattice_direction(*cell, LatticeType.HONEYCOMB)
        assert direction in (Direction.FORWARD, Direction.REVERSE)
        for bp in (98, 163, 172, 173, 179, 256):
            native = native_full_nucleotide_at(h, design, bp, direction)
            assert scaffold_endpoint(cell, bp) == pytest.approx(
                native["backbone_position"], abs=1e-10
            )


def test_ligation_ranking_searches_beyond_center_distance_tie():
    cells = {
        h: (r, c)
        for h, (r, c) in enumerate(
            [
                (1, 5),
                (1, 4),
                (1, 3),
                (1, 2),
                (1, 1),
                (1, 0),
                (2, 0),
                (2, 1),
                (2, 2),
                (2, 3),
                (2, 4),
                (2, 5),
                (3, 5),
                (3, 4),
                (3, 3),
                (3, 2),
                (3, 1),
                (3, 0),
            ]
        )
    }
    a, b = [rank_ligation_cells(cells, [ex], "REVERSE") for ex in excursions()]
    common = rank_ligation_cells(cells, excursions(), "REVERSE")
    assert a["best_cells"] == [[0, 5]]
    assert b["best_cells"] == [[0, 3]]
    assert common["best_cells"] == [[0, 5]]
    assert all(r["resolved"] and r["search_complete"] for r in (a, b, common))
    assert a["best_total_length_nm"] == pytest.approx(31.131770914683244)
    assert b["best_total_length_nm"] == pytest.approx(29.988155505820124)
    assert (
        a["best_total_length_nm"] + b["best_total_length_nm"]
        < common["best_total_length_nm"]
    )
    # Global independent oracle over a deliberately larger box, without using
    # the new search's bound or candidate scoring closure.
    for result, exs in [
        (a, excursions()[:1]),
        (b, excursions()[1:]),
        (common, excursions()),
    ]:
        scored = []
        for row in range(-20, 21):
            for col in range(-20, 21):
                cell = (row, col)
                if (
                    cell in cells.values()
                    or _lattice_direction(*cell, LatticeType.HONEYCOMB).value
                    != "REVERSE"
                ):
                    continue
                spans = []
                for ex in exs:
                    for end, anchor in [
                        ("start", "attachment_before"),
                        ("end", "attachment_after"),
                    ]:
                        fixed = scaffold_endpoint(cells[ex[anchor][0]], ex[anchor][1])
                        moving = scaffold_endpoint(cell, ex[end][1])
                        spans.append(float(np.linalg.norm(moving - fixed)))
                scored.append((sum(spans), cell))
        best, cell = min(scored)
        assert result["best_cells"] == [list(cell)]
        assert result["best_total_length_nm"] == pytest.approx(best)
        assert result["best_total_length_nm"] == pytest.approx(
            sum(result["best_candidates"][0]["ligation_lengths_nm"])
        )


def test_budget_failure_and_missing_anchor_do_not_choose_a_cell():
    result = rank_ligation_cells(
        {0: (1, 5)}, excursions()[:1], "REVERSE", max_candidates=1
    )
    assert not result["resolved"] and not result["search_complete"]
    with pytest.raises(ValueError, match="attachment"):
        rank_ligation_cells({0: (1, 5)}, excursions()[1:], "REVERSE")
