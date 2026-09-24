import math
import numpy as np
import pytest
from backend.core.models import Design, LatticeType
from backend.core.lattice import make_bundle_design
from backend.core.lattice_frames import append_independent_bundle, lattice_address
from backend.core.deformation import deformed_helix_axes
from backend.api.crud import _origins_by_grid_pos


@pytest.mark.parametrize('lattice', list(LatticeType))
@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
def test_separate_frames_preserve_cells_topology_and_rigid_pose(lattice, plane):
    original = make_bundle_design([(0,0)], 21, lattice_type=lattice)
    saved = original.to_json()
    theta = math.radians(37)
    rotation = [0, math.sin(theta/2), 0, math.cos(theta/2)]
    candidate = append_independent_bundle(original, [[0,0]], 21, plane=plane,
                                          translation_nm=[12,-4,8], rotation_xyzw=rotation)
    assert original.to_json() == saved
    assert len(candidate.helices) == 2 and len(candidate.strands) == 4
    assert candidate.helices[0].grid_pos == candidate.helices[1].grid_pos == (0,0)
    assert lattice_address(candidate.helices[0]) != lattice_address(candidate.helices[1])
    assert _origins_by_grid_pos(original,candidate) == {}
    restored = Design.model_validate_json(candidate.to_json())
    assert restored.lattice_frames == candidate.lattice_frames
    assert restored.cluster_transforms == candidate.cluster_transforms
    assert restored.helices == candidate.helices
    axes = deformed_helix_axes(restored)
    axis = next(a for a in axes if a['helix_id']==candidate.helices[1].id)
    h = candidate.helices[1]
    matrix=np.array([[math.cos(theta),0,math.sin(theta)],[0,1,0],[-math.sin(theta),0,math.cos(theta)]])
    # Independent matrix oracle: existing geometry transform must apply once.
    for key,rest in [('start',h.axis_start),('end',h.axis_end)]:
        expected=matrix@np.array([rest.x,rest.y,rest.z])+[12,-4,8]
        np.testing.assert_allclose(axis[key],expected,atol=1e-7)


@pytest.mark.parametrize('kwargs', [{'rotation_xyzw':[0,0,0,2]}, {'translation_nm':[float('nan'),0,0]}, {'plane':'OBLIQUE'}])
def test_invalid_candidate_placement_rejected(kwargs):
    with pytest.raises(ValueError):
        append_independent_bundle(Design(), [[0,0]], 21, **kwargs)


@pytest.mark.parametrize('lattice', list(LatticeType))
def test_export_layout_separates_frames_without_changing_local_addresses(lattice):
    from backend.core.cadnano import export_cadnano
    from backend.core.lattice_frame_layout import packed_frame_cells
    design = make_bundle_design([(0,0),(0,1)],21,lattice_type=lattice)
    design = append_independent_bundle(design, [[0,0],[0,1]],21,translation_nm=[10,0,0])
    before = [h.grid_pos for h in design.helices]
    layout = packed_frame_cells(design.helices)
    assert len(set(layout.values())) == 4
    for helix in design.helices:
        row,col = layout[helix.id]
        assert (row-helix.grid_pos[0])%6 == 0 and col==helix.grid_pos[1]
    exported = export_cadnano(design)
    assert len({(v['row'],v['col']) for v in exported['vstrands']}) == 4
    assert [h.grid_pos for h in design.helices] == before
    assert export_cadnano(Design.model_validate_json(design.to_json())) == exported


def test_three_independent_frames_and_negative_bp_survive_file_roundtrip(tmp_path):
    from backend.core.cadnano import export_cadnano, check_cadnano_compatibility
    design = Design()
    for plane in ['XY','XZ','YZ']:
        design = append_independent_bundle(design, [[0,0],[0,1]], -21, plane=plane)
    path = tmp_path/'independent.nadoc'; path.write_text(design.to_json())
    loaded = Design.model_validate_json(path.read_text())
    assert len({lattice_address(h) for h in loaded.helices}) == 6
    assert all(h.bp_start == -21 for h in loaded.helices)
    assert len({(v['row'],v['col']) for v in export_cadnano(loaded)['vstrands']}) == 6
    assert any('Rigid 3D placements' in warning for warning in check_cadnano_compatibility(loaded))


def test_same_frame_duplicate_segments_are_not_silently_packed():
    from backend.core.lattice_frame_layout import packed_frame_cells
    design = append_independent_bundle(Design(), [[0,0]],21)
    duplicate = design.helices[0].model_copy(update={'id':'another-segment','bp_start':21})
    with pytest.raises(ValueError,match='segment consolidation'):
        packed_frame_cells([*design.helices,duplicate])


@pytest.mark.parametrize('damage', ['missing_cluster','missing_frame','duplicate_frame'])
def test_serialized_dangling_frame_references_are_rejected(damage):
    design=append_independent_bundle(Design(),[[0,0]],21)
    raw=design.model_dump(mode='json')
    if damage=='missing_cluster': raw['cluster_transforms']=[]
    if damage=='missing_frame': raw['lattice_frames']=[]
    if damage=='duplicate_frame': raw['lattice_frames']*=2
    with pytest.raises(ValueError): Design.model_validate(raw)


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('length', [-21, 42])
def test_extend_existing_frame_preserves_pose_cells_and_roundtrip(plane, length):
    from backend.core.lattice_frames import append_frame_bundle
    from backend.core.cadnano import export_cadnano
    theta = math.radians(37)
    design = append_independent_bundle(Design(), [[0,0]], 21, plane=plane,
        translation_nm=[12,-4,8], rotation_xyzw=[0,math.sin(theta/2),0,math.cos(theta/2)])
    before = design.to_json()
    frame = design.lattice_frames[0]
    result = append_frame_bundle(design, frame.id, [[0,1],[1,0]], length, plane=plane)
    assert design.to_json() == before
    assert result.lattice_frames == design.lattice_frames
    assert result.helices[0] == design.helices[0]
    assert result.strands[:2] == design.strands
    assert {h.lattice_frame_id for h in result.helices} == {frame.id}
    assert {h.grid_pos for h in result.helices} == {(0,0),(0,1),(1,0)}
    cluster = result.cluster_transforms[0]
    assert set(cluster.helix_ids) == {h.id for h in result.helices}
    assert cluster.translation == design.cluster_transforms[0].translation
    assert cluster.rotation == design.cluster_transforms[0].rotation
    axes = {a['helix_id']:a for a in deformed_helix_axes(result)}
    matrix = np.array([[math.cos(theta),0,math.sin(theta)],[0,1,0],[-math.sin(theta),0,math.cos(theta)]])
    for h in result.helices[1:]:
        assert h.length_bp == abs(length)
        assert h.bp_start == min(0, length)
        for key, rest in [('start',h.axis_start),('end',h.axis_end)]:
            np.testing.assert_allclose(axes[h.id][key], matrix @ [rest.x,rest.y,rest.z]+[12,-4,8], atol=1e-7)
    loaded = Design.model_validate_json(result.to_json())
    assert loaded.helices == result.helices
    assert loaded.cluster_transforms == result.cluster_transforms
    assert export_cadnano(loaded) == export_cadnano(result)
    assert len(export_cadnano(loaded)['vstrands']) == 3


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('cells', [[(0,0),(0,1)], [(0,0),(0,1),(20,20)]])
def test_desktop_bundle_frame_registration_preserves_topology_and_clusters(plane, cells):
    from backend.core.cluster_autodetect import _cluster_bundle_regions, with_default_cluster
    from backend.core.lattice_frames import register_created_bundle_frames
    raw = make_bundle_design(cells,42,plane=plane)
    built = with_default_cluster(_cluster_bundle_regions(raw.copy_with(helices=[h.model_copy(update={'grid_pos':cell})
        for h,cell in zip(raw.helices,cells,strict=True)])))
    before = built.to_json()
    result = register_created_bundle_frames(built,plane,cells)
    assert built.to_json() == before
    assert result.strands == built.strands
    assert result.cluster_transforms == built.cluster_transforms
    assert len(result.lattice_frames) == len(built.cluster_transforms)
    for a,b in zip(result.helices,built.helices):
        assert a.model_dump(exclude={'lattice_frame_id'}) == b.model_dump(exclude={'lattice_frame_id'})
        frame = next(f for f in result.lattice_frames if f.id == a.lattice_frame_id)
        assert frame.plane == plane
        assert a.id in next(c for c in result.cluster_transforms if c.id == frame.placement_cluster_id).helix_ids
