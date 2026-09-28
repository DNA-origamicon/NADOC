import json
import shlex
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api import state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.api.vr_view_volumes import VolumeBinding
from backend.core.models import Design, ViewVolume


def test_native_controls_reload_and_desktop_feed(tmp_path):
    design = _demo_design()
    design.view_volumes = [ViewVolume(id='desktop', name='Desktop hex', shape='hexagonal', min_corner=(-2,-2,-3), max_corner=(2,2,3), rotation=(0,0,2**-.5,2**-.5))]
    state.set_design(design)
    rotation = np.array([[0,-1,0],[1,0,0],[0,0,1]])
    binding = VolumeBinding(tmp_path/'events', rotation)
    feed = tmp_path/'events.volumes-state'
    fields = shlex.split(feed.read_text().splitlines()[1])
    assert fields[:5] == ['desktop','Desktop hex','1','1','6']
    assert np.allclose(np.array(fields[18:21], float), [-2,0,-3])
    operations = [dict(sequence=1,action='create',id='native',shape='box',center=[-4,2,6],radius=3)]
    pending = tmp_path/'events.volumes-pending'
    pending.write_text(json.dumps(operations)); binding.consume()
    native = state.get_or_404().view_volumes[1]
    assert native.min_corner == (-1,1,3)
    assert native.max_corner == (5,7,9)
    revision = state.revision(); binding.consume()
    assert state.revision() == revision  # replay is acknowledged, never re-applied
    operations += [dict(sequence=2,action='outline',id='native',value=False),dict(sequence=3,action='enabled',id='native',value=False)]
    pending.write_text(json.dumps(operations)); binding.consume()
    part = tmp_path/'shared-volumes.nadoc'
    part.write_text(state.get_or_404().to_json())
    restored = Design.from_json(part.read_text())
    assert not restored.view_volumes[1].enabled
    assert not restored.view_volumes[1].outline_visible
    state.set_design(restored)
    # Desktop field edits preserve native switches and unrelated records.
    client = TestClient(app)
    response = client.patch('/api/design/view-volumes',json={'document_id':design.id,'patches':{'native':{'name':'Renamed'}}})
    assert response.status_code == 200
    binding.consume()
    assert 'Renamed' in feed.read_text()
    assert not state.get_or_404().view_volumes[1].enabled
    operations += [dict(sequence=4,action='delete',id='native')]
    pending.write_text(json.dumps(operations)); binding.consume()
    assert [v.id for v in state.get_or_404().view_volumes] == ['desktop']
    assert feed.read_text().startswith('NADOC_VOLUMES_3 4 1')


def test_binding_rejects_replacement_document_and_invalid_batch(tmp_path):
    design = _demo_design(); state.set_design(design)
    binding = VolumeBinding(tmp_path/'events', np.eye(3))
    pending = tmp_path/'events.volumes-pending'
    pending.write_text(json.dumps([dict(sequence=1,action='create',id='bad',shape='box',center=[0,0,float('nan')],radius=3)]))
    with pytest.raises(ValueError): binding.consume()
    assert not state.get_or_404().view_volumes
    pending.unlink()
    other = _demo_design(); other.id = 'replacement'; state.set_design(other)
    with pytest.raises(ValueError,match='no longer active'): binding.consume()
    client = TestClient(app)
    assert client.patch('/api/design/view-volumes', json={'document_id':design.id}).status_code == 409
    assert client.get('/api/design/view-volumes',params={'document_id':design.id}).status_code == 409


def test_native_transform_reverses_launch_rotation_and_preserves_metadata(tmp_path):
    from scipy.spatial.transform import Rotation
    design = _demo_design()
    design.view_volumes = [ViewVolume(id='v', name='Desktop name', shape='hexagonal', min_corner=(-1,-1,-2), max_corner=(1,1,2), enabled=False, outline_visible=True, coloring='base')]
    state.set_design(design)
    launch = Rotation.from_euler('xyz', [25,-30,42], degrees=True).as_matrix()
    binding = VolumeBinding(tmp_path/'events', launch)
    center = np.array([5., -8., 12.]); half = np.array([3.,3.,7.])
    rotation = Rotation.from_euler('xyz', [60,10,-20], degrees=True)
    op = dict(sequence=1, action='transform', id='v', center=(launch @ center).tolist(), half=half.tolist(), rotation=Rotation.from_matrix(launch @ rotation.as_matrix()).as_quat().tolist())
    pending = tmp_path/'events.volumes-pending'; pending.write_text(json.dumps([op])); binding.consume()
    volume = state.get_or_404().view_volumes[0]
    assert np.allclose(volume.min_corner, center-half)
    assert np.allclose(volume.max_corner, center+half)
    assert np.allclose(Rotation.from_quat(volume.rotation).as_matrix(), rotation.as_matrix())
    assert volume.name == 'Desktop name' and volume.coloring == 'base' and not volume.enabled
    fields = shlex.split((tmp_path/'events.volumes-state').read_text().splitlines()[1])
    assert np.allclose(np.array(fields[8:11], float), launch @ center)
    assert np.allclose(np.array(fields[11:14], float), half)
    assert np.allclose(Rotation.from_quat(np.array(fields[14:18], float)).as_matrix(), launch @ rotation.as_matrix())
    saved = tmp_path/'moved.nadoc'; saved.write_text(state.get_or_404().to_json())
    assert Design.from_json(saved.read_text()).view_volumes == state.get_or_404().view_volumes
    revision = state.revision(); binding.consume(); assert state.revision() == revision
    for field, bad in [('half', [0,3,7]), ('rotation', [0,0,0,0]), ('center', [float('nan'),0,0])]:
        pending.write_text(json.dumps([{**op, 'sequence':2, field:bad}]))
        with pytest.raises(ValueError, match='Invalid volume transform'): binding.consume()
        assert state.get_or_404().view_volumes[0] == volume
    # A remote deletion wins over a delayed motion update.
    state.get_or_404().view_volumes = []
    pending.write_text(json.dumps([{**op, 'sequence':2}])); binding.consume()
    assert not state.get_or_404().view_volumes


def test_representation_feed_tracks_desktop_style_without_geometry_mutation(tmp_path):
    design = _demo_design()
    design.view_volumes = [ViewVolume(id='focus', min_corner=(-2,-2,-3), max_corner=(2,2,3), representation='beads', coloring='base', opacity=.6)]
    state.set_design(design)
    before = [h.model_dump() for h in design.helices]
    binding = VolumeBinding(tmp_path/'events', np.eye(3))
    fields = shlex.split((tmp_path/'events.volumes-state').read_text().splitlines()[1])
    assert fields[5:8] == ['beads', 'base', '0.6']
    client = TestClient(app)
    assert client.patch('/api/design/view-volumes', json={'document_id':design.id,'patches':{'focus':{'representation':'cylinders'}}}).status_code == 200
    binding.consume()
    fields = shlex.split((tmp_path/'events.volumes-state').read_text().splitlines()[1])
    assert fields[5:8] == ['cylinders','base','0.6']
    assert [h.model_dump() for h in state.get_or_404().helices] == before
