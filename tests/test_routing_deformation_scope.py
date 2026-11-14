"""Autoscaffold caps inherit end membership, including cached and native history."""
import numpy as np
import pytest

from backend.api import state
from backend.api.crud import BundleRequest, create_bundle, _seek_feature_log
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.routes_deformation import AddDeformationBody, add_deformation
from backend.api.routes_scaffold_routing import _run_auto_scaffold_with_feature_log
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.deformation_scope import membership_classifier
from backend.core.models import Design
from tests.test_part_history_navigation import strip_recovery, proof


@pytest.fixture
def bent():
    token = set_current_doc('routing-deformation-scope-test')
    try:
        create_bundle(BundleRequest(cells=[[0,0],[0,1],[1,0],[1,1]], length_bp=48,
                                    lattice_type='SQUARE'))
        d = state.get_or_404()
        add_deformation(AddDeformationBody(type='bend', plane_a_bp=0, plane_b_bp=47,
            targets=[{'kind':'cluster', 'id':d.cluster_transforms[0].id}],
            params={'curvature_deg_per_bp':30/47, 'direction_deg':0}))
        yield state.get_or_404().model_copy(deep=True)
    finally:
        state.close_session()
        reset_current_doc(token)


def sites(design):
    return {(dm.helix_id,bp,dm.direction) for s in design.scaffolds() for dm in s.domains
            for bp in range(min(dm.start_bp,dm.end_bp),max(dm.start_bp,dm.end_bp)+1)}


def route():
    return _run_auto_scaffold_with_feature_log('auto-scaffold-seamed', 'Auto Scaffold', {})[0]


def test_caps_inherit_without_moving_original_bases_or_staples(bent):
    before = bent.model_dump_json()
    routed = route()
    added = sites(routed) - sites(bent)
    assert added
    classify = membership_classifier(routed)
    assert all(classify(*site) == (0,) for site in added)
    assert bent.model_dump_json() == before
    assert routed.feature_log[1].op_snapshot == bent.deformations[0]
    for old in bent.helices:
        new = next(h for h in routed.helices if h.id == old.id)
        a, b = deformed_nucleotide_arrays(old,bent), deformed_nucleotide_arrays(new,routed)
        indices = {(int(bp),int(d)):i for i,(bp,d) in enumerate(zip(b['bp_indices'],b['directions']))}
        for i,(bp,d) in enumerate(zip(a['bp_indices'],a['directions'])):
            np.testing.assert_allclose(a['positions'][i], b['positions'][indices[(int(bp),int(d))]], atol=1e-8)
    proof(routed)


@pytest.mark.parametrize('cached',[True,False])
@pytest.mark.parametrize('optimized',[True,False])
def test_seek_revert_and_reopen_preserve_inherited_ranges(bent,cached,optimized):
    routed = route()
    source = Design.model_validate_json(routed.model_dump_json())
    if not cached:
        source = strip_recovery(source)
    earlier = _seek_feature_log(source,1,optimized=optimized)
    assert earlier.deformations == bent.deformations
    end = _seek_feature_log(earlier,-1,optimized=optimized)
    assert end.deformations == routed.deformations
    assert sites(end) == sites(routed)
    proof(end)
    state.undo()
    assert state.get_or_404().deformations == bent.deformations
    state.redo()
    assert state.get_or_404().deformations == routed.deformations


def test_unselected_direction_does_not_inherit_and_legacy_replay_stays_frozen(bent):
    from backend.api.part_auto_commands import build
    from backend.core.routing_deformation_scope import inherit_scaffold_ends
    old = build('auto-scaffold-seamed',bent,{'history_seed':'00000000-0000-0000-0000-000000000123'})
    assert old.deformations == bent.deformations
    # Restrict the classifier fixture to one existing directional range. This is
    # an in-memory scope unit test, never an authored/published example.
    op = bent.deformations[0]
    selected = op.target_ranges[0]
    source = bent.copy_with(deformations=[op.model_copy(update={'target_ranges':[selected]})])
    result = inherit_scaffold_ends(source,old.copy_with(deformations=source.deformations))
    classify = membership_classifier(result)
    added = sites(result)-sites(source)
    for hid,bp,direction in added:
        assert bool(classify(hid,bp,direction)) == (hid == selected.helix_id and direction == selected.direction)
