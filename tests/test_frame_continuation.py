"""Blunt-end continuation must address a frame, not a globally unique cell."""
import math
import pytest
from backend.core.models import Design
from backend.core.lattice_frames import append_independent_bundle
from backend.core.lattice import make_bundle_continuation, bundle_continuation_conflicts
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.cadnano import export_cadnano


@pytest.mark.parametrize('plane', ['XY','XZ','YZ'])
@pytest.mark.parametrize('sign', [-1,1])
def test_rotated_frame_continuation_preserves_identity_and_other_frame(plane, sign):
    d = append_independent_bundle(Design(),[[0,0]],42,plane=plane,
        translation_nm=[12,-4,8], rotation_xyzw=[0,math.sin(.3),0,math.cos(.3)])
    d = append_independent_bundle(d,[[0,0]],84,plane=plane,translation_nm=[30,0,0])
    before = d.to_json(); frame_id = d.lattice_frames[0].id
    offset = 42*BDNA_RISE_PER_BP if sign>0 else 0
    assert bundle_continuation_conflicts(d,[(0,0)],sign*21,plane,offset,frame_id) == []
    # The other frame actually overlaps that interval in local coordinates.
    if sign>0:
        assert bundle_continuation_conflicts(d,[(0,0)],21,plane,offset)
    result = make_bundle_continuation(d,[(0,0)],sign*21,plane,offset,
        extend_inplace=True,source_frame_id=frame_id)
    assert d.to_json() == before
    assert result.helices[1] == d.helices[1]
    assert result.lattice_frames == d.lattice_frames
    assert result.cluster_transforms == d.cluster_transforms
    h = result.helices[0]
    assert h.id == d.helices[0].id
    assert h.grid_pos == (0,0) and h.lattice_frame_id == frame_id
    assert h.length_bp == 63 and h.bp_start == (-21 if sign<0 else 0)
    restored = Design.model_validate_json(result.to_json())
    assert restored.helices == result.helices
    assert len(export_cadnano(restored)['vstrands']) == 2
    untouched = {s.id for s in d.strands if all(dm.helix_id==d.helices[1].id for dm in s.domains)}
    assert [s for s in result.strands if s.id in untouched] == [s for s in d.strands if s.id in untouched]


def test_invalid_frame_or_plane_cannot_fall_back_to_another_frame():
    d = append_independent_bundle(Design(),[[0,0]],42)
    for frame,plane in [('missing','XY'),(d.lattice_frames[0].id,'XZ')]:
        with pytest.raises(ValueError):
            make_bundle_continuation(d,[(0,0)],21,plane,42*BDNA_RISE_PER_BP,
                extend_inplace=True,source_frame_id=frame)
