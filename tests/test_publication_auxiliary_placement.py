from pathlib import Path
import math

import pymupdf
import pytest

from backend.core.publication_auxiliary_placement import (
    rank_vacant_cells,
    infer_auxiliary_placement,
)
from backend.core.lattice import _lattice_direction, _lattice_position
from backend.core.models import LatticeType


def test_unique_minimum_excludes_occupied_and_wrong_polarity_cells():
    cells = {0: (0, 0), 1: (0, -1), 3: (0, 1)}
    result = rank_vacant_cells(cells, [0, 0], "REVERSE")
    assert result["resolved"] and result["search_complete"]
    assert result["best_cells"] == [[-1, 0]]
    assert result["best_score_nm2"] == pytest.approx(2 * 2.25**2)
    assert all(tuple(c["cell"]) not in cells.values() for c in result["candidates"])


def test_symmetric_cells_are_all_retained_instead_of_float_tiebreak():
    result = rank_vacant_cells({0: (0, 0)}, [0], "REVERSE")
    assert not result["resolved"] and result["search_complete"]
    assert result["best_cells"] == [[-1, 0], [0, -1], [0, 1]]


@pytest.mark.parametrize("shift", [(0, 0), (2, -4), (-6, 8)])
def test_analytic_search_bound_matches_large_independent_bruteforce(shift):
    cells = {
        0: (shift[0], shift[1]),
        2: (shift[0] + 2, shift[1] + 2),
        4: (shift[0] + 1, shift[1] - 1),
    }
    result = rank_vacant_cells(cells, [0, 2, 4, 4], "REVERSE")
    lt = LatticeType.HONEYCOMB
    targets = [_lattice_position(*cells[h], lt) for h in [0, 2, 4, 4]]
    scores = {}
    for row in range(-20, 21):
        for col in range(-20, 21):
            if (row, col) in cells.values() or _lattice_direction(
                row, col, lt
            ).value != "REVERSE":
                continue
            xy = _lattice_position(row, col, lt)
            scores[row, col] = sum(math.dist(xy, p) ** 2 for p in targets)
    best = min(scores.values())
    assert result["best_score_nm2"] == pytest.approx(best)
    assert result["best_cells"] == [
        list(c) for c, score in sorted(scores.items()) if abs(score - best) < 1e-9
    ]


def test_budget_and_unknown_anchor_do_not_produce_an_inferred_cell():
    result = rank_vacant_cells({0: (0, 0)}, [0], "REVERSE", max_candidates=1)
    assert (
        not result["resolved"]
        and not result["search_complete"]
        and not result["best_cells"]
    )
    with pytest.raises(ValueError, match="attachment"):
        rank_vacant_cells({0: (0, 0)}, [1], "REVERSE")


PDF = Path("workspace/Shared Designs/.provenance/D005/twist-supp.pdf")


@pytest.fixture
def d006():
    if not PDF.exists():
        pytest.skip("Local supplement unavailable")
    from backend.core.publication_routing import (
        extract_publication_paths,
        staple_tables,
        pair_endpoint_table,
        classify_scaffold,
        resolve_insertions,
    )
    from backend.core.publication_sequence_search import search_declared_scaffold
    from backend.core.publication_unpaired_scaffold import aligned_unpaired_scaffold

    with pymupdf.open(PDF) as doc:
        graph = extract_publication_paths(doc[19])
        table = next(t for t in staple_tables(doc) if t["page"] == 39)
    pairing = pair_endpoint_table(graph, table)
    classified = classify_scaffold(pairing)
    insertions = resolve_insertions(pairing, classified, table)
    sequence = search_declared_scaffold(classified, insertions, table)
    unpaired = aligned_unpaired_scaffold(
        classified, insertions, table, sequence, graph["lattice"]
    )
    return graph["lattice"], classified, unpaired


def test_d006_independent_ligation_minima_replace_center_distance_tie(d006):
    result = infer_auxiliary_placement(*d006)
    assert result["resolved"] and not result["native_reference_consulted"]
    (track,) = result["tracks"]
    assert track["helix"] == 19 and track["direction"] == "REVERSE"
    center = track["center_distance_rank"]
    assert center["best_cells"] == [[0, 5], [1, 6]]
    assert center["best_score_nm2"] == pytest.approx(40.5)
    assert [segment["best_cells"] for segment in track["segments"]] == [
        [[0, 5]],
        [[0, 3]],
    ]
    assert track["common_cell_rank"]["best_cells"] == [[0, 5]]
    assert len(result["segment_placements"]) == 2
    assert "cells" not in result  # one cell per source row cannot represent both loops


def test_direction_conflict_and_unsupported_excursion_stay_unresolved(d006):
    lattice, classified, unpaired = d006
    unpaired["auxiliary_tracks"][0]["supported_excursion"] = False
    assert (
        "attachments"
        in infer_auxiliary_placement(lattice, classified, unpaired)["reason"]
    )
    classified["scaf"][0]["sites"].reverse()
    assert (
        "parity conflicts"
        in infer_auxiliary_placement(lattice, classified, unpaired)["reason"]
    )


def test_staple_link_between_excursions_prevents_independent_placement(d006):
    lattice, classified, unpaired = d006
    classified["stap"].append({"sites": [(19, 180), (19, 150)]})
    result = infer_auxiliary_placement(lattice, classified, unpaired)
    assert not result["resolved"] and "connects outside" in result["reason"]


def test_inserted_endpoint_is_not_silently_scored_as_an_ordinary_base(d006):
    lattice, classified, unpaired = d006
    unpaired["insertion_sites"] = [(19, 256)]
    result = infer_auxiliary_placement(lattice, classified, unpaired)
    assert not result["resolved"] and "copy selection" in result["reason"]
