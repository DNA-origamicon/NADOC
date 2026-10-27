"""Starting-frame previews use frozen job inputs, never another job's latest frame."""
import asyncio
import json
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core.md_import import resolve_md_config
from backend.core.md_starting_structure import starting_structure_display


def package(tmp_path, binary=True):
    (tmp_path / 'dna.psf').write_text('PSF\n')
    (tmp_path / 'dna.pdb').write_text(
        f"{'ATOM      1  P    DA A   1':<30}{1.:8.3f}{2.:8.3f}{3.:8.3f}  1.00  0.00           P  \nEND\n")
    (tmp_path / 'start.conf').write_text(
        'structure dna.psf\ncoordinates dna.pdb\n' +
        ('binCoordinates equilibrated.coor\nextendedSystem equilibrated.xsc\n' if binary else ''))
    (tmp_path / 'equilibrated.coor').write_bytes(struct.pack('<i3d', 1, 8., 9., 10.))
    (tmp_path / 'equilibrated.xsc').write_text('0 40 0 0 0 50 0 0 0 60 20 25 30\n')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'name_stem': 'dna', 'minimization': {'name': 'start'},
                                    'segments': [], 'box_ang': [40, 50, 60]}))
    return manifest


@pytest.mark.parametrize('binary,expected', [(True, [8, 9, 10]), (False, [1, 2, 3])])
def test_preview_reads_actual_start_and_does_not_create_results(tmp_path, binary, expected):
    from MDAnalysis.coordinates.DCD import DCDReader
    manifest = package(tmp_path, binary)
    before = manifest.read_bytes()
    display = starting_structure_display(manifest)
    source = resolve_md_config(display)
    with DCDReader(str(source.trajectory_path)) as reader:
        assert len(reader) == 1
        np.testing.assert_allclose(reader.ts.positions[0], expected)
        np.testing.assert_allclose(reader.ts.dimensions, [40, 50, 60, 90, 90, 90])
    assert not (tmp_path / 'output').exists()
    assert manifest.read_bytes() == before
    from backend.core.md_executor import stage_plan
    assert not any('.nadoc-analysis' in relative for _, relative in stage_plan(tmp_path))
    with pytest.raises(ValueError, match='No DCD'):
        resolve_md_config(manifest)
    stamp = source.trajectory_path.stat().st_mtime_ns
    assert starting_structure_display(manifest) == display
    assert source.trajectory_path.stat().st_mtime_ns == stamp
    if binary:
        (tmp_path / 'equilibrated.coor').write_bytes(struct.pack('<i3d', 1, 11., 12., 13.))
        assert starting_structure_display(manifest) != display


def test_missing_checkpoint_never_falls_back_to_unrelaxed_pdb(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / 'equilibrated.coor').unlink()
    assert starting_structure_display(manifest) is None


def test_md_metadata_exposes_preview_separately_then_prefers_simulation(tmp_path, monkeypatch):
    from backend.api import routes_md as routes
    from backend.core.md_job import MdStatus
    package(tmp_path)
    job = SimpleNamespace(job_id='child', status=MdStatus.queued, prep_params={},
                          execution_target='local', live_frame=None, package_dir=lambda _: tmp_path)
    monkeypatch.setattr(routes, '_load_job', lambda _: job)
    monkeypatch.setattr(routes, 'root_relaxation', lambda _: job)
    monkeypatch.setattr(routes, '_production_ready_checkpoint', lambda _: (None, None, '', ''))
    monkeypatch.setattr(routes, '_completed_production_checkpoint', lambda _: (None, None, ''))
    monkeypatch.setattr(routes, '_latest_display_segment', lambda _: (None, None))
    meta = asyncio.run(routes.get_md_job_display('child'))
    assert meta['starting_structure_config']
    assert meta['ready'] is False
    assert meta['trajectory_path'] is None
    assert meta['production_ready'] is False
    # A newly opened DCD with only its header is still an unrun display.
    from backend.core.dcd_fast import read_layout
    preview_dcd = resolve_md_config(meta['starting_structure_config']).trajectory_path
    output = tmp_path / 'real.dcd'
    output.write_bytes(preview_dcd.read_bytes()[:read_layout(preview_dcd).header_bytes])
    monkeypatch.setattr(routes, '_latest_display_segment', lambda _: ('production', output))
    assert asyncio.run(routes.get_md_job_display('child'))['starting_structure_config']
    output.write_bytes(preview_dcd.read_bytes())
    monkeypatch.setattr(routes, '_latest_display_segment', lambda _: ('production', tmp_path / 'real.dcd'))
    meta = asyncio.run(routes.get_md_job_display('child'))
    assert meta['starting_structure_config'] is None
    assert meta['ready'] is True


pytest_plugins = ['tests.md_trajectory_fixture']


def test_starting_structure_streams_through_real_md_viewer(generated_md):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    fixture = generated_md
    (fixture.folder / 'start.conf').write_text(
        f'structure {fixture.psf.name}\ncoordinates {fixture.ref.name}\n')
    manifest = fixture.folder / 'manifest.json'
    manifest.write_text(json.dumps({'name_stem': fixture.psf.stem,
                                    'minimization': {'name': 'start'}, 'box_ang': [200, 200, 200]}))
    preview = starting_structure_display(manifest)
    with TestClient(app).websocket_connect('/ws/md-run') as ws:
        ws.send_json({'action': 'load', 'config_path': str(preview), 'mode': 'nadoc',
                      'design': fixture.design.model_dump(mode='json')})
        while True:
            message = ws.receive_json()
            assert message['type'] != 'error', message
            if message['type'] == 'ready':
                assert message['n_frames'] == 1
                break
        ws.send_json({'action': 'get_latest'})
        frame = ws.receive_json()
        assert frame['type'] == 'frame', frame
        assert frame['positions']
        assert all(np.isfinite([p['x'], p['y'], p['z']]).all() for p in frame['positions'])


def test_new_segment_header_keeps_previous_simulation_frame(tmp_path):
    from backend.api.routes_md import _latest_display_segment
    from backend.core.dcd_fast import read_layout
    source = resolve_md_config(starting_structure_display(package(tmp_path))).trajectory_path
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'relax.dcd').write_bytes(source.read_bytes())
    (output / 'production.dcd').write_bytes(source.read_bytes()[:read_layout(source).header_bytes])
    job = SimpleNamespace(package_dir=lambda _: tmp_path, current_segment_idx=1,
                          segments=[SimpleNamespace(name='relax'), SimpleNamespace(name='production')])
    assert _latest_display_segment(job) == ('relax', output / 'relax.dcd')
    from backend.core.md_import import _latest_existing_dcd
    assert _latest_existing_dcd(tmp_path, ['relax', 'production']) == (
        (output / 'relax.dcd').resolve(), 'relax')
