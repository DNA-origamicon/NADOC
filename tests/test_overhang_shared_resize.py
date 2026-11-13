"""Sequence edits keep the selected overhang root and shared helix occupants fixed."""
import pytest

from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.core.part_history_contract import assess_part_history
from backend.api.part_proof_commands import execute, dependencies
from backend.core.models import Design
from tests.conftest import valid_overhang_sites


@pytest.fixture
def shared_overhangs():
    token = set_current_doc('__test_shared_overhang_resize')
    try:
        crud.create_bundle(crud.BundleRequest(
            cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42))
        sites = [s for s in valid_overhang_sites(state.get_or_404())
                 if (s['neighbor_row'], s['neighbor_col']) == (0, 4)]
        for site in sites:
            crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=8))
        yield state.get_or_404().model_copy(deep=True)
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize('end', ['5p', '3p'])
@pytest.mark.parametrize('length', [1, 5, 12])
def test_sequence_resize_preserves_own_root_shared_helix_and_undo(shared_overhangs, end, length, tmp_path):
    before = shared_overhangs
    target = next(o for o in before.overhangs if o.id.endswith(end))
    other = next(o for o in before.overhangs if o.id != target.id)
    assert other.helix_id == target.helix_id
    strand = before.find_strand(target.strand_id)
    domain = next(d for d in strand.domains if d.overhang_id == target.id)
    root = domain.end_bp if end == '5p' else domain.start_bp
    tip_field = 'start_bp' if end == '5p' else 'end_bp'
    root_field = 'end_bp' if end == '5p' else 'start_bp'
    tip_sign = 1 if getattr(domain, tip_field) > root else -1
    crud.patch_overhang(target.id, crud.OverhangPatchRequest(sequence='A' * length))
    after = state.get_or_404()
    resized = next(d for d in after.find_strand(strand.id).domains if d.overhang_id == target.id)
    assert getattr(resized, root_field) == root
    assert getattr(resized, tip_field) == root + tip_sign * (length - 1)
    assert after.crossovers == before.crossovers
    assert after.helices == before.helices  # both ends remain within the shared span
    for previous in before.strands:
        actual = after.find_strand(previous.id)
        assert [d for d in actual.domains if d.overhang_id != target.id] == [
            d for d in previous.domains if d.overhang_id != target.id]
    assert verify_current_part()['status'] == 'verified'
    from scripts.agent_structure_guard import publish
    path = tmp_path / "shared-overhang-resized.nadoc"
    publish(after, path)
    reopened = Design.model_validate_json(path.read_text())
    assert assess_part_history(reopened, execute=execute, dependencies=dependencies)['status'] == 'verified'
    undone, _ = state.undo()
    assert undone.strands == before.strands
    assert undone.helices == before.helices
    assert undone.crossovers == before.crossovers
    redone, _ = state.redo()
    assert redone.strands == after.strands
    assert redone.crossovers == after.crossovers


@pytest.mark.parametrize('five_prime', [True, False])
def test_dedicated_overhang_root_pose_survives_shrink_to_one_and_regrowth(five_prime, tmp_path):
    import numpy as np
    from backend.core.geometry import nucleotide_positions
    from scripts.agent_structure_guard import publish, audit

    token = set_current_doc('__test_dedicated_overhang_resize')
    try:
        crud.create_bundle(crud.BundleRequest(
            cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42))
        site = next(s for s in valid_overhang_sites(state.get_or_404())
                    if (s['neighbor_row'], s['neighbor_col']) == (0, 4)
                    and s['is_five_prime'] == five_prime)
        crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=8))
        before = state.get_or_404().model_copy(deep=True)
        target = before.overhangs[0]

        def root_pose(design):
            helix = next(h for h in design.helices if h.id == target.helix_id)
            return [n for n in nucleotide_positions(helix) if n.bp_index == site['bp_index']]

        original = root_pose(before)
        for length in [1, 12, 5]:
            crud.patch_overhang(target.id, crud.OverhangPatchRequest(sequence='A' * length))
            for actual, expected in zip(root_pose(state.get_or_404()), original, strict=True):
                np.testing.assert_allclose(actual.position, expected.position, atol=1e-12)
                np.testing.assert_allclose(actual.base_normal, expected.base_normal, atol=1e-12)
        path = tmp_path / 'root-preservation.nadoc'
        publish(state.get_or_404(), path)
        assert audit(Design.model_validate_json(path.read_text()))['status'] == 'verified'
    finally:
        state.close_session()
        reset_current_doc(token)


def test_partial_resize_geometry_matches_complete_recomputation(shared_overhangs):
    from backend.core.render_diff import _strand_occupancy, _local_changed_helices
    from backend.core.design_geometry import _geometry_for_design, _geometry_for_helices

    before = shared_overhangs
    target = next(o for o in before.overhangs if o.id.endswith('3p'))
    response = crud.patch_overhang(target.id, crud.OverhangPatchRequest(sequence='ACGTA'))
    assert response['partial_geometry'] is True
    assert response['changed_helix_ids'] == [target.helix_id]
    assert 'nucleotides' in response or 'nucleotides_compact' in response
    after = state.get_or_404()
    changed = _local_changed_helices(_strand_occupancy(before), _strand_occupancy(after))
    assert changed == [target.helix_id]
    old_geometry = _geometry_for_design(before)
    patch = _geometry_for_helices(after, frozenset(changed))
    complete = _geometry_for_design(after)
    key = lambda n: (n['helix_id'], n['bp_index'], n['direction'])
    merged = {key(n): n for n in old_geometry if n['helix_id'] not in changed}
    merged.update({key(n): n for n in patch})
    assert merged == {key(n): n for n in complete}


def test_same_length_sequence_response_preserves_complete_geometry(shared_overhangs):
    from backend.core.design_geometry import _geometry_for_design
    target = next(o for o in shared_overhangs.overhangs if o.id.endswith('3p'))
    crud.patch_overhang(target.id, crud.OverhangPatchRequest(sequence='ACGTA'))
    before = _geometry_for_design(state.get_or_404())
    response = crud.patch_overhang(target.id, crud.OverhangPatchRequest(sequence='TTTTT'))
    assert response['geometry_unchanged'] is True
    assert _geometry_for_design(state.get_or_404()) == before
    assert 'nucleotides' not in response
