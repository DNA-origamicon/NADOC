"""Older mixed-frame parts recover addresses without changing molecular geometry."""
import numpy as np
import pytest
from backend.core.models import Design, LatticeType, ClusterRigidTransform, DeformationOp, BendParams
from backend.core.lattice_frames import append_independent_bundle
from backend.core.lattice import make_bundle_segment
from backend.core.lattice_frame_compatibility import repair_lattice_frame_membership
from backend.core.vr_lattice_context import lattice_plane_context
from backend.core.deformation import deformed_nucleotide_arrays


def mixed_part(plane='XY', lattice=LatticeType.SQUARE):
    original = append_independent_bundle(Design(lattice_type=lattice), [[0, i] for i in range(8)], 88, plane=plane)
    added = make_bundle_segment(original, [(-1, 0), (-1, 1)], 120, plane=plane)
    ids = [h.id for h in added.helices[8:]]
    return added.copy_with(
        helices=[h.model_copy(update={'lattice_frame_id': None}) if h.id in ids else h for h in added.helices],
        cluster_transforms=[*original.cluster_transforms, ClusterRigidTransform(id='separate', helix_ids=ids)],
        deformations=[DeformationOp(type='bend', plane_a_bp=70, plane_b_bp=119,
            affected_helix_ids=ids, cluster_ids=['separate'], params=BendParams(curvature_deg_per_bp=60/49, direction_deg=0))])


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('lattice', list(LatticeType))
def test_load_repairs_only_metadata_and_roundtrips(plane, lattice):
    old = mixed_part(plane, lattice)
    before = old.model_dump()
    repaired = repair_lattice_frame_membership(Design.from_json(old.to_json()))
    assert len(lattice_plane_context(repaired, plane)['cells']) == 10
    expected = old.model_dump()
    for h in expected['helices']:
        h['lattice_frame_id'] = old.lattice_frames[0].id
    assert repaired.model_dump() == expected
    assert old.model_dump() == before
    assert Design.from_json(repaired.to_json()) == repaired
    for a, b in zip(old.helices, repaired.helices):
        np.testing.assert_array_equal(deformed_nucleotide_arrays(a, old)['positions'],
                                      deformed_nucleotide_arrays(b, repaired)['positions'])


def test_new_desktop_segments_retain_frame_without_joining_clusters():
    old = append_independent_bundle(Design(), [[0, 0]], 42)
    new = make_bundle_segment(old, [(1, 0)], 21)
    assert new.helices[-1].lattice_frame_id == old.lattice_frames[0].id
    assert new.cluster_transforms == old.cluster_transforms
    assert len(lattice_plane_context(new, 'XY')['cells']) == 2


@pytest.mark.parametrize('reason', ['ambiguous', 'moved', 'nested', 'off-grid', 'wrong-plane'])
def test_unproven_sources_are_not_inferred(reason):
    d = mixed_part()
    if reason == 'ambiguous':
        d = d.copy_with(lattice_frames=[*d.lattice_frames, d.lattice_frames[0].model_copy(update={'id':'other'})],
            helices=[*d.helices, d.helices[0].model_copy(update={'id':'other', 'lattice_frame_id':'other'})])
    elif reason == 'moved':
        d.cluster_transforms[-1].translation = [10, 0, 0]
    elif reason == 'nested':
        d.cluster_transforms[-1].parent_cluster_id = d.cluster_transforms[0].id
    elif reason == 'off-grid':
        for h in d.helices[8:]: h.axis_start.x += .01
    else:
        d.lattice_frames[0].plane = 'XZ'
    repaired = repair_lattice_frame_membership(d)
    assert all(h.lattice_frame_id is None for h in repaired.helices[8:10])
    assert repaired == d


def test_raw_history_parsing_preserves_metadata_but_editor_import_repairs():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state
    old = mixed_part()
    assert Design.from_json(old.to_json()) == old
    response = TestClient(app).post('/api/design/import', json={'content': old.to_json()})
    assert response.status_code == 200, response.text
    loaded = state.get_or_404()
    assert len(lattice_plane_context(loaded, 'XY')['cells']) == 10
    assert loaded.cluster_transforms == old.cluster_transforms
    assert loaded.deformations == old.deformations
