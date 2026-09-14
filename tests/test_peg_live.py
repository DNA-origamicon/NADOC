"""PEG Live staging, routing and process lifecycle; physics runs are explicitly slow."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import shutil

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import routes_oxdna_live as routes
from backend.physics.oxdna_peg_live import (
    PegLiveStepper, peg_frame_builder, validate_peg_continuation,
)


@pytest.fixture
def prepared(tmp_path):
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import write_configuration, write_topology
    from backend.physics.oxdna_surface_strands import CaptureSpec, append_capture_strands
    from scripts.create_peg_surface_review import make_review_design
    design = make_review_design()
    setup = deepcopy(design.metadata.peg_surface)
    setup['surface']['position_nm'] = -20
    top, conf = tmp_path / 'topology.top', tmp_path / 'conf.dat'
    write_topology(design, top)
    write_configuration(design, _geometry_for_design(design), conf)
    spec = setup['surface_strands']
    built = append_capture_strands(top, conf, CaptureSpec.from_payload(spec), setup['surface'])
    traps = [p for p, _xyz in built['trap_anchors']]
    spec['built'] = {'n_beads': built['n_beads'], 'trap_particles': traps,
                     'terminal_particles': [p + spec['segments'] for p in traps]}
    return design, setup, top, conf


def stage(prepared, tmp_path, field=None):
    design, setup, top, conf = prepared
    spec = setup['surface_strands']
    rd = tmp_path / 'live'
    info, backend = routes._prepare_live_rundir(design, conf, rd,
        field=field, wall=setup['surface'], anchors=setup['anchors'],
        anchor_stiff=1000, steps=10, backend='CPU',
        capture_particles=spec['built']['trap_particles'],
        field_exclude_trailing=spec['built']['n_beads'] if field else 0,
        peg_spec=spec, topology_path=top)
    return rd, info, backend


def test_staging_preserves_peg_topology_parameters_and_traps(prepared, tmp_path):
    rd, info, backend = stage(prepared, tmp_path)
    design, setup, top, conf = prepared
    assert (rd / 'topology.top').read_bytes() == top.read_bytes()
    assert (rd / 'conf.dat').read_bytes() == conf.read_bytes()
    assert backend == 'CPU' and info['has_forces']
    for name in ('input', 'input_cpu'):
        inp = (rd / name).read_text()
        assert 'interaction_type = DNA2PEG' in inp
        assert 'dt = 0.001' in inp
        assert 'peg_bond_length' in inp
    text = (rd / 'field_forces.txt').read_text()
    for particle in setup['surface_strands']['built']['trap_particles']:
        assert f'particle = {particle}\n' in text
    assert 'type = string' not in text


def test_signed_terminal_field_excludes_neutral_peg(prepared, tmp_path):
    prepared[1]['surface_strands']['terminalChargeE'] = -.5
    rd, _, _ = stage(prepared, tmp_path, {'field_V_per_m': 1e6,
        'dna_effective_charge_e': -.25, 'dir': [0, 1, 0]})
    text = (rd / 'field_forces.txt').read_text()
    blocks = [b for b in text.split('}') if 'type = string' in b]
    assert len(blocks) == 5  # grouped DNA + four terminals
    terminals = prepared[1]['surface_strands']['built']['terminal_particles']
    for particle in terminals:
        assert any(f'particle = {particle}\n' in b for b in blocks)
    for p in range(32, 68):
        if p not in terminals:
            assert not any(f'particle = {p}\n' in b for b in blocks)


def test_frame_keeps_dna_indices_and_peg_cm_in_surface_frame(prepared, tmp_path):
    design, setup, _, conf = prepared
    rd, _, _ = stage(prepared, tmp_path)
    shutil.copyfile(conf, rd / 'last_conf.dat')
    spec = setup['surface_strands']
    stepper = PegLiveStepper(rd, backend='CPU', spec=spec)
    frame = peg_frame_builder(design, spec)(SimpleNamespace(stepper=stepper))
    rows = np.loadtxt(conf, skiprows=3)
    assert len(frame) == 68
    dna = stepper.configuration(design)
    assert len(dna) == 32
    assert np.allclose(next(iter(dna.values()))['backbone_position'], rows[0, :3] * .8518)
    peg = [p for p in frame if p['helix_id'].startswith('cap')]
    assert len(peg) == 36
    assert np.allclose(peg[0]['cm_position'], rows[32, :3] * .8518)
    assert peg[0]['backbone_position'] == peg[0]['cm_position']
    assert peg[-1]['bp_index'] == 1003008


def test_continuation_rejects_changed_coating_or_missing_particles(prepared):
    _, setup, top, _ = prepared
    spec = setup['surface_strands']
    validate_peg_continuation(spec, {'enabled': True}, top)
    with pytest.raises(ValueError, match='segments differs'):
        validate_peg_continuation(spec, {'segments': 12}, top)
    with pytest.raises(ValueError, match='built coating'):
        validate_peg_continuation({**spec, 'built': {}}, None, top)


def test_live_route_uses_peg_without_stock_oxpy_and_cleans_failed_staging(prepared, tmp_path, monkeypatch):
    from backend.core.oxdna_job import OxdnaStatus
    design, setup, top, conf = prepared
    parent = SimpleNamespace(run_config=setup, status=OxdnaStatus.queued,
                             job_dir=lambda ws: tmp_path)
    monkeypatch.setattr(routes, '_load_job', lambda _: parent)
    monkeypatch.setattr(routes, '_assert_job_current', lambda _: None)
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes, '_load_snapshot_design', lambda _: design)
    monkeypatch.setattr(routes, '_latest_relaxed_conf', lambda *args: (conf, None))
    monkeypatch.setattr(routes, 'is_running', lambda _: False)
    monkeypatch.setattr(routes, 'oxpy_live_available', lambda: {'available': False, 'reason': 'stock unavailable'})
    monkeypatch.setattr('backend.physics.oxdna_peg_live.peg_live_available',
                        lambda: {'available': True, 'reason': 'ready'})
    captured = {}
    def fail_stage(*args, **kwargs):
        captured.update(kwargs)
        raise ValueError('staging failure')
    monkeypatch.setattr(routes, '_build_live_engine', fail_stage)
    request = routes.LiveStartRequest(job_id='peg', surface=setup['surface'],
        surface_strands={'enabled': True, 'subjectToField': True},
        field={'field_pN': 1, 'dir': [0, 1, 0]})
    with pytest.raises(ValueError, match='staging failure'):
        asyncio.run(routes.start_oxdna_live(request))
    assert captured['peg_spec'] == setup['surface_strands']
    assert captured['topology_path'] == top
    assert captured['field_exclude_trailing'] == 36
    assert list((tmp_path / 'live_sessions').iterdir()) == []


def test_resolve_physical_field_and_refuse_legacy_update(monkeypatch):
    request = routes.LiveStartRequest(job_id='peg', field={'field_V_per_m': 1e6, 'dir': [0, 1, 0]})
    field, force, *_ = routes._resolve_live_elements(request)
    assert field['field_V_per_m'] == 1e6 and force > 0
    monkeypatch.setattr(routes, 'get_session', lambda _: SimpleNamespace(physical_field=True))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.update_oxdna_live_field('peg', routes.LiveFieldRequest(field_pN=1, dir=[0, 1, 0])))
    assert exc.value.status_code == 409


@pytest.mark.slow
@pytest.mark.parametrize('backend', ['CPU', 'CUDA'])
def test_real_peg_worker_bursts_and_stops(prepared, tmp_path, backend):
    """Opt-in integration: run only in a user-opened test session."""
    from backend.physics.oxdna_peg_live import peg_live_available
    if not peg_live_available()['available']:
        pytest.skip('Build PEG Live bindings first')
    design, setup, _, _ = prepared
    rd, _, _ = stage(prepared, tmp_path)
    if backend == 'CUDA':
        text = (rd / 'input').read_text().replace('backend = CPU', 'backend = CUDA')
        (rd / 'input').write_text(text)
    with PegLiveStepper(rd, backend=backend, spec=setup['surface_strands']) as stepper:
        pid = stepper._process.pid
        stepper.run(5)
        stepper.run(5)
        assert stepper._process.pid == pid
        assert len(stepper.configuration(design)) == 32
        frame = peg_frame_builder(design, setup['surface_strands'])(SimpleNamespace(stepper=stepper))
        assert len(frame) == 68
        assert np.isfinite([p['cm_position'] for p in frame]).all()
    assert stepper._process is None


@pytest.mark.parametrize('backend', ['CPU', 'CUDA'])
def test_worker_transport_is_persistent_and_tears_down(prepared, tmp_path, monkeypatch, backend):
    """Real subprocess/protocol with a fake oxpy module; no molecular simulation."""
    package = tmp_path / 'bindings' / 'oxpy'
    package.mkdir(parents=True)
    (package / 'core.so').touch()
    (package / '__init__.py').write_text('''
from pathlib import Path
from types import SimpleNamespace
class Context:
    def __enter__(self): return self
    def __exit__(self, *args): pass
class InputFile(dict):
    def init_from_filename(self, path):
        for line in Path(path).read_text().splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                self[key.strip()] = value.strip()
class OxpyManager:
    def __init__(self, inp):
        if inp['backend'] == 'CUDA': raise RuntimeError('mock CUDA unavailable')
        self.inp, self.steps = inp, 0
        print('native-style log must not corrupt protocol')
    def config_info(self): return SimpleNamespace(forces=[])
    def run(self, steps, **kwargs): self.steps += steps
    def print_configuration(self):
        rows = Path(self.inp['conf_file']).read_text().splitlines()
        rows[0] = f't = {self.steps}'
        Path(self.inp['lastconf_file']).write_text('\\n'.join(rows) + '\\n')
''')
    monkeypatch.setenv('NADOC_PEG_OXPY_PATH', str(package.parent))
    rd, _, _ = stage(prepared, tmp_path)
    if backend == 'CUDA':
        (rd / 'input').write_text((rd / 'input').read_text().replace('backend = CPU', 'backend = CUDA'))
    with PegLiveStepper(rd, backend=backend, spec=prepared[1]['surface_strands']) as stepper:
        assert stepper.active_backend == 'CPU'
        assert stepper.fell_back == (backend == 'CUDA')
        proc = stepper._process
        stepper.run(3)
        stepper.run(7)
        stepper.set_field(.1, [0, 1, 0])
        assert (rd / 'last_conf.dat').read_text().startswith('t = 10\n')
        assert len(stepper.configuration(prepared[0])) == 32
        assert stepper.snapshot_seed().read_bytes() == (rd / 'last_conf.dat').read_bytes()
        assert stepper._process.pid == proc.pid
    assert proc.poll() == 0
    assert stepper._process is None
    with PegLiveStepper(rd, backend=backend, spec=prepared[1]['surface_strands']) as stopped:
        child = stopped._process
        stopped.cancel()
    assert child.poll() is not None


def test_start_and_reconfigure_keep_topology_and_current_pose(prepared, tmp_path, monkeypatch):
    from backend.core.oxdna_job import OxdnaStatus
    design, setup, top, conf = prepared
    parent = SimpleNamespace(run_config=setup, status=OxdnaStatus.queued, job_dir=lambda _: tmp_path)
    monkeypatch.setattr(routes, '_load_job', lambda _: parent)
    monkeypatch.setattr(routes, '_assert_job_current', lambda _: None)
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes, '_load_snapshot_design', lambda _: design)
    monkeypatch.setattr(routes, '_latest_relaxed_conf', lambda *args: (conf, None))
    monkeypatch.setattr(routes, 'is_running', lambda _: False)
    monkeypatch.setattr('backend.physics.oxdna_peg_live.peg_live_available',
                        lambda: {'available': True, 'reason': 'ready'})
    monkeypatch.setattr(routes.LiveSession, 'start', lambda self: None)  # no simulation
    sessions = []
    monkeypatch.setattr(routes, 'register', sessions.append)
    monkeypatch.setattr(routes, 'stop_all', lambda: None)
    original_design = design.model_dump_json()
    start = asyncio.run(routes.start_oxdna_live(routes.LiveStartRequest(job_id='peg',
        surface=setup['surface'], anchors=setup['anchors'], surface_strands=setup['surface_strands'])))
    live = sessions[0]
    assert start['session_id'] == live.session_id
    assert isinstance(live._session.stepper, PegLiveStepper)
    assert (live.rundir / 'topology.top').read_bytes() == top.read_bytes()
    # Stand in for the worker's snapshot of its current pose; no engine is opened.
    current = conf.read_text().replace('t = 0', 't = 123')
    (live.rundir / 'reconfig_seed.dat').write_text(current)
    monkeypatch.setattr(routes, 'get_session', lambda _: live)
    response = asyncio.run(routes.reconfigure_oxdna_live(live.session_id,
        routes.LiveReconfigureRequest(surface=setup['surface'], anchors=setup['anchors'],
            field={'field_V_per_m': 1e6, 'dir': [0, 1, 0]},
            surface_strands=setup['surface_strands'])))
    assert response == {'ok': True}
    rebuilt, _ = live._pending_reconfig[0]()
    assert rebuilt.stepper.physical
    assert (live.rundir / 'conf.dat').read_text() == current
    assert (live.rundir / 'topology.top').read_bytes() == top.read_bytes()
    assert design.model_dump_json() == original_design
    live.stop()
    assert not live.rundir.exists()


def test_stop_during_reconfigure_does_not_open_replacement_worker():
    from backend.core.oxdna_live_runner import LiveSession
    from tests.test_oxdna_live_session import _FakeEngine
    original, replacement = _FakeEngine(), _FakeEngine()
    live = LiveSession('stop-race', original, frame_builder=lambda _: [],
                       field_oxdna=0, field_dir=[0, 1, 0])
    def rebuild():
        live.stop()
        return replacement, lambda _: []
    live.reconfigure(rebuild)
    live._apply_pending_reconfig()
    assert original.exited
    assert not replacement.entered
    assert not replacement.runs
