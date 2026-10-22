"""Isolated pair-edge exploration, using native enumeration and backbone order."""

import numpy as np
import pytest

from backend.core.models import Direction
from backend.core.mrdna_bridge import _build_nt_arrays
from tests.test_part_member_motion_order import _source, _target, _nucleotide, D
from tools.unpair_topology_probe import inspect_unpairing


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("bps,kind,anchors", [
    (range(8), "free_strand", 0),
    (range(3), "overhang", 1),
    (range(5, 8), "overhang", 1),
    (range(2, 6), "linker", 2),
])
def test_unpair_only_removes_pair_edges_and_reports_both_strands(direction, bps, kind, anchors):
    source = _source()
    # Nonuniform authored sequence makes preservation more than an all-N check.
    source = source.copy_with(strands=[
        strand.model_copy(update={"sequence": "ACGTTCAG"}) for strand in source.strands
    ])
    before = source.model_dump_json()
    arrays = _build_nt_arrays(source, return_nt_key=True, return_identity=True)
    keys = [(source.helices[0].id, bp, direction.value, 0) for bp in bps]
    report = inspect_unpairing(source, keys)
    assert len(report["removed_pairs"]) == len(bps)
    assert len(report["selected"]) == len(bps)
    assert len(report["affected_runs"]) == 2
    for run in report["affected_runs"]:
        assert run["kind"] == kind and len(run["anchors"]) == anchors
        assert len(run["residues"]) == len(bps)
        indices = [r["index"] for r in run["residues"]]
        assert all(arrays[3][a] == b for a, b in zip(indices, indices[1:]))
        for residue in run["residues"]:
            index = residue["index"]
            assert residue["identity"] == arrays[7][index]
            assert residue["base"] == arrays[5][index]
    assert sum(r["selected"] for run in report["affected_runs"] for r in run["residues"]) == len(bps)
    assert source.model_dump_json() == before
    after = _build_nt_arrays(source, return_nt_key=True, return_identity=True)
    for a, b in zip(arrays[:5], after[:5]):
        np.testing.assert_array_equal(a, b)
    assert arrays[5:] == after[5:]


def test_separated_pose_still_has_native_pairing_and_does_not_implicitly_unpair():
    source = _source()
    _, target = _target(source, Direction.FORWARD)
    moved = _nucleotide(source, target, D, "move")
    key = (target["helix_id"], 3, "FORWARD", 0)
    before, after = (inspect_unpairing(d, [key]) for d in (source, moved))
    assert before == after
    assert len(after["removed_pairs"]) == 1


def test_duplicate_and_both_partner_selection_removes_each_pair_once():
    source = _source()
    key = (source.helices[0].id, 3, "FORWARD", 0)
    other = (*key[:2], "REVERSE", 0)
    report = inspect_unpairing(source, [key, key, other])
    assert len(report["selected"]) == 2
    assert len(report["removed_pairs"]) == 1


@pytest.mark.parametrize("keys", [[], [("missing", 0, "FORWARD", 0)]])
def test_invalid_selection_refuses_without_mutation(keys):
    source = _source()
    before = source.model_dump_json()
    with pytest.raises(ValueError):
        inspect_unpairing(source, keys)
    assert source.model_dump_json() == before


def test_unpair_merges_with_existing_ssdna_without_selecting_it():
    source = _source()
    reverse, _ = _target(source, Direction.REVERSE)
    shortened = reverse.model_copy(update={"domains": [
        reverse.domains[0].model_copy(update={"end_bp": 3})
    ]})
    source = source.copy_with(strands=[
        shortened if s.id == reverse.id else s for s in source.strands
    ])
    report = inspect_unpairing(source, [(source.helices[0].id, 3, "FORWARD", 0)])
    selected_run = next(run for run in report["affected_runs"]
                        if any(r["selected"] for r in run["residues"]))
    assert selected_run["kind"] == "overhang"
    assert [r["key"][1] for r in selected_run["residues"]] == [0, 1, 2, 3]
    assert sum(r["selected"] for r in selected_run["residues"]) == 1
    assert len(report["removed_pairs"]) == 1


def test_already_unpaired_selection_is_a_noop():
    source = _source()
    reverse, _ = _target(source, Direction.REVERSE)
    source = source.copy_with(strands=[s for s in source.strands if s.id != reverse.id])
    before = source.model_dump_json()
    report = inspect_unpairing(source, [(source.helices[0].id, 3, "FORWARD", 0)])
    assert report["removed_pairs"] == []
    assert len(report["affected_runs"]) == 1
    assert report["affected_runs"][0]["kind"] == "free_strand"
    assert len(report["affected_runs"][0]["residues"]) == 8
    assert source.model_dump_json() == before
