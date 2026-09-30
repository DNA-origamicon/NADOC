"""Selective export preserves geometry while avoiding unrequested construction."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest

from backend.api import routes_vr as vr
from backend.api import vr_representation_loading as loading
from backend.core.vr_scene_contract import parse_scene_contract
from tests.conftest import make_minimal_design


def test_full_only_does_not_construct_atoms_or_extra_representations(monkeypatch, tmp_path):
    design = make_minimal_design(helix_length_bp=8)
    def unwanted(*args, **kwargs):
        raise AssertionError('Unrequested geometry was built')
    monkeypatch.setattr('backend.core.atomistic.build_atomistic_model', unwanted)
    monkeypatch.setattr('backend.core.vr_representation_geometry.build', unwanted)
    output = vr._snapshot(vr.VRLaunchRequest(), design_snapshot=design, representations={'full'})
    parsed = parse_scene_contract(output)
    assert set(parsed) == {'full'}
    path = tmp_path/'full.nadocvr'
    path.write_text(output)
    subprocess.run(['native/vr_viewer/build/nadoc-vr-viewer', '--validate', str(path)], check=True, capture_output=True)


@pytest.mark.parametrize('representation', ['full', 'cylinders', 'ballstick', 'stick', 'surface', 'hull-prism', 'mrdna-coarse', 'mrdna-fine', 'oxdna'])
def test_selective_export_matches_same_blocks_in_complete_snapshot(representation, tmp_path):
    design = make_minimal_design(helix_length_bp=5)
    body = vr.VRLaunchRequest(representation=representation)
    complete = parse_scene_contract(vr._snapshot(body, design_snapshot=design))
    selective = vr._snapshot(body, design_snapshot=design, representations={representation})
    parsed = parse_scene_contract(selective)
    assert set(parsed) == {representation}
    for pose in (representation,):
        assert parsed[pose] == complete[pose]
    path=tmp_path/'selected.nadocvr';path.write_text(selective)
    subprocess.run(['native/vr_viewer/build/nadoc-vr-viewer','--validate',str(path)],check=True,capture_output=True)


def test_request_protocol_and_monotonic_progress_publication(tmp_path):
    event=tmp_path/'event'
    path=Path(str(event)+'.repr-request')
    path.write_text('NADOCVR_REP_REQUEST 1 4 surface 7\n')
    request=loading.read_request(event)
    assert request == (4, 'surface', 7)
    loading.publish(event, request, 'loading', 37.456, 123, 'Exporting\nrecords')
    assert Path(str(event)+'.repr-status').read_text().splitlines()==[
        'NADOCVR_REP_STATUS 1 4 7 surface loading 37.456 123','Exporting records']
    assert Path(str(event)+'.repr-status').stat().st_mode & 0o777 == 0o600
    path.write_text('NADOCVR_REP_REQUEST 1 4 ../../other 7\n')
    assert loading.read_request(event) is None
    loading.cleanup(event)
    assert not list(tmp_path.iterdir())


def test_superseded_export_does_not_publish_ready(monkeypatch, tmp_path):
    event=tmp_path/'event';request=(1,'surface',0)
    Path(str(event)+'.repr-request').write_text('NADOCVR_REP_REQUEST 1 2 full 0\n')
    design=make_minimal_design(helix_length_bp=5)
    monkeypatch.setattr('backend.api.state.copy_doc_for_persist', lambda doc:(design,1))
    monkeypatch.setattr(vr,'_snapshot',lambda body, **kw:kw['progress'](50,'working'))
    with pytest.raises(loading.Superseded):
        loading.export_request(vr.VRLaunchRequest(),event,SimpleNamespace(poll=lambda:None),request)
    assert not Path(str(event)+'.repr-1').exists()


def test_document_change_discards_finished_representation(monkeypatch, tmp_path):
    event = tmp_path/'event'
    request = (1, 'surface', 0)
    Path(str(event)+'.repr-request').write_text('NADOCVR_REP_REQUEST 1 1 surface 0\n')
    design = make_minimal_design(helix_length_bp=5)
    monkeypatch.setattr('backend.api.state.copy_doc_for_persist', lambda doc: (design, 1))
    monkeypatch.setattr('backend.api.state.get_design_with_revision', lambda: (design, 2))
    source = tmp_path/'candidate'
    source.write_text('obsolete geometry')
    monkeypatch.setattr(vr, '_write_scene_snapshot', lambda **kw: source)
    with pytest.raises(ValueError, match='Part changed'):
        loading.export_request(vr.VRLaunchRequest(), event, SimpleNamespace(poll=lambda: None), request)
    assert not source.exists()
    assert not Path(str(event)+'.repr-1').exists()
    assert 'ready' not in Path(str(event)+'.repr-status').read_text()


def test_cylinders_use_desktop_radius_and_staple_color():
    import numpy as np
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes
    from backend.core.vr_representation_geometry import build

    design = make_minimal_design(helix_length_bp=12)
    design.strands[0].color = '#0000ff'
    design.strands[1].color = '#ff0000'
    data = build(design, _geometry_for_design(design), deformed_helix_axes(design), {'cylinders'})
    # Desktop draws one staple-domain cylinder, not an overlapping scaffold tube.
    assert len(data['cylinders']) == 1
    mesh = data['cylinders'][0]
    points = np.asarray(mesh['vertices']).reshape(-1, 3)
    assert np.max(np.linalg.norm(points[:, :2], axis=1)) == pytest.approx(1.125)
    assert mesh['palettes'][:3] == [1, 0, 0]
    assert np.linalg.norm(np.asarray(mesh['normals']).reshape(-1, 3), axis=1) == pytest.approx(np.ones(len(points)))
