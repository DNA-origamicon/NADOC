from backend.core.models import Design
from backend.core.lattice import make_bundle_segment
from backend.core.vr_empty_scene import empty_authoring_scene
from backend.api import routes_vr


def test_new_document_has_explicit_empty_contract_without_fake_geometry():
    design = Design()
    scene = empty_authoring_scene(design)
    assert scene.startswith('NADOCVR 14 full strand\n')
    assert 'Q empty_authoring\n' in scene
    assert 'F XY HONEYCOMB' in scene
    assert not any(line.startswith(('P ', 'C ', 'B ', 'H ')) for line in scene.splitlines())
    assert design.helices == [] and design.strands == []


def test_nonempty_document_does_not_bypass_geometry():
    design = make_bundle_segment(Design(), [(0, 0)], 21)
    assert empty_authoring_scene(design) is None


def test_streaming_and_string_empty_snapshot_match(monkeypatch):
    monkeypatch.setattr(routes_vr.design_state, 'get_or_404', lambda: Design())
    body = routes_vr.VRLaunchRequest()
    text = routes_vr._snapshot(body)
    lines = []
    assert routes_vr._snapshot(body, line_writer=lines.append) is None
    assert text == '\n'.join(lines)+'\n'
