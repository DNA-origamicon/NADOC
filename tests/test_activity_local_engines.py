"""Observation parity against native reconciliation on isolated metadata only."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from backend.core.activity_evidence_io import Evidence
from backend.core.activity_local_engines import observe_local_engine
from backend.core import oxdna_runner, lammps_runner, cando_runner, snupi_runner
from backend.core.oxdna_job import OxdnaJob, OxdnaStageStatus, OxdnaStatus
from backend.core.oxdna_protocol import OxdnaStageSpec
from backend.core.lammps_job import LammpsJob, LammpsStatus
from backend.core.cando_job import CandoJob, CandoStatus
from backend.core.snupi_job import SnupiJob, SnupiStatus

FAMILIES = {
    'oxdna': (OxdnaJob, OxdnaStatus, oxdna_runner.reconcile_oxdna_status),
    'lammps': (LammpsJob, LammpsStatus, lammps_runner.reconcile_lammps_status),
    'cando': (CandoJob, CandoStatus, cando_runner.reconcile_cando_status),
    'snupi': (SnupiJob, SnupiStatus, snupi_runner.reconcile_snupi_status),
}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'; proc.mkdir()
    for runner in (oxdna_runner, lammps_runner, cando_runner):
        monkeypatch.setattr(runner, 'is_running', lambda *a: False)
    monkeypatch.setattr(oxdna_runner, '_external_oxdna_running', lambda *a: False)
    monkeypatch.setattr(lammps_runner, '_pid_is_lammps', lambda *a: False)
    monkeypatch.setattr(snupi_runner, '_pid_alive', lambda *a: False)
    monkeypatch.setattr(oxdna_runner, '_load_snapshot_design', lambda *a: pytest.fail('Design load'))
    return tmp_path, proc


def job_for(engine, root, state='running'):
    model, status, _ = FAMILIES[engine]
    job = model(job_id='isolated', design_name='Test', status=status(state), created_at=0)
    job.job_dir(root).mkdir(parents=True)
    if engine == 'oxdna':
        job.stages = [OxdnaStageStatus('stage', 'production', 1000, 'running')]
        spec = OxdnaStageSpec('stage', 'production', 'MD', 1000, 'CPU')
        (job.job_dir(root) / 'stages_spec.json').write_text(json.dumps([asdict(spec)]))
        job.stage_dir(root, 'stage').mkdir()
    return job


def observe(engine, job, scene):
    root, proc = scene; before = snapshot(root); saved = deepcopy(job)
    result = observe_local_engine(engine, job, root, Evidence(proc))
    assert snapshot(root) == before and job == saved
    assert not list(root.rglob('.runtime.lock'))
    return result


@pytest.mark.parametrize('engine', FAMILIES)
@pytest.mark.parametrize('state', ['running', 'queued', 'completed', 'preparing'])
def test_native_empty_output_and_nonrunning_parity(scene, engine, state):
    root, _ = scene; job = job_for(engine, root, state)
    result = observe(engine, job, scene)
    if state == 'preparing':
        assert result.assessment.action == 'unknown' and result.reason == 'separate_owner'
    else:
        assert result.assessment.action == ('stopped' if state == 'running' else 'unchanged')
    native = FAMILIES[engine][2](deepcopy(job), root)
    assert native.status.value == ('stopped' if state == 'running' else state)


@pytest.mark.parametrize('engine', ['cando', 'snupi'])
def test_cached_completion_matches_native_without_mutation(scene, engine):
    root, _ = scene; job = job_for(engine, root)
    (job.job_dir(root) / 'display.json').write_text('not parsed by native')
    assert observe(engine, job, scene).assessment.action == 'completed_cache'
    assert FAMILIES[engine][2](deepcopy(job), root).status.value == 'completed'


@pytest.mark.parametrize('mode,action', [
    ('complete', 'completed_outputs'), ('resume', 'completed_outputs'),
    ('diverged', 'unchanged'), ('partial', 'unchanged'),
    ('failed', 'stopped'), ('done', 'completed_outputs'),
])
def test_oxdna_stage_and_resume_predicates_match_native(scene, mode, action):
    root, _ = scene; state = 'stopped' if mode in ('resume', 'diverged', 'partial') else 'running'
    job = job_for('oxdna', root, state); directory = job.stage_dir(root, 'stage')
    (directory / 'last_conf.dat').write_text('existence is the native predicate')
    lines = 100 if mode in ('complete', 'failed') else 41
    (directory / 'energy.dat').write_text('0\n' * lines)
    if state == 'stopped':
        (directory / 'energy.r1.dat').write_text('0\n' * 61)
        if mode != 'partial': (directory / 'oxdna.log').write_text('END OF THE SIMULATION, everything went OK!')
        if mode == 'diverged': (directory / 'error_conf.dat').write_text('diverged')
    if mode == 'failed': job.stages[0].status = 'failed'
    if mode == 'done': job.stages[0].status = 'done'
    assert observe('oxdna', job, scene).assessment.action == action
    native = FAMILIES['oxdna'][2](deepcopy(job), root)
    assert native.status.value == ('completed' if action == 'completed_outputs' else 'stopped')


@pytest.mark.parametrize('engine', ['oxdna', 'lammps', 'snupi'])
def test_native_external_process_rule(scene, engine, monkeypatch):
    root, proc = scene; job = job_for(engine, root)
    process = proc / '321'; process.mkdir()
    command = b'oxDNA\0' + str(job.job_dir(root)).encode() if engine == 'oxdna' else b'lmp\0input' if engine == 'lammps' else b'python\0worker'
    (process / 'cmdline').write_bytes(command); (process / 'cwd').symlink_to(root)
    if engine == 'lammps':
        job.lammps_pid = 321; monkeypatch.setattr(lammps_runner, '_pid_is_lammps', lambda pid: pid == 321)
    elif engine == 'snupi':
        job.pid = 321; monkeypatch.setattr(snupi_runner, '_pid_alive', lambda pid: pid == 321)
    else: monkeypatch.setattr(oxdna_runner, '_external_oxdna_running', lambda *a: True)
    assert observe(engine, job, scene).assessment.action == 'live'
    assert FAMILIES[engine][2](deepcopy(job), root).status.value == 'running'


def test_snupi_known_runtime_does_not_trust_old_pid(scene):
    root, proc = scene; job = job_for('snupi', root); job.pid = 321
    process = proc / '321'; process.mkdir(); (process / 'cmdline').write_bytes(b'python')
    (job.job_dir(root) / '.runtime.json').write_text('{}')
    assert observe('snupi', job, scene).assessment.action == 'stopped'
    assert snupi_runner.reconcile_snupi_status(deepcopy(job), root).status.value == 'stopped'


@pytest.mark.parametrize('engine', FAMILIES)
def test_owned_runtime_precedes_output_without_inventory(scene, engine):
    import fcntl
    root, proc = scene; job = job_for(engine, root); proc.rmdir()
    lock = job.job_dir(root) / '.runtime.lock'; lock.touch()
    before = snapshot(root); saved = deepcopy(job)
    with lock.open('rb') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = observe_local_engine(engine, job, root, Evidence(proc))
    assert result.assessment.action == 'live' and snapshot(root) == before and job == saved


@pytest.mark.parametrize('fault', ['specs', 'stage_count', 'bytes', 'work', 'deadline', 'energy', 'permission', 'attempt_entries'])
def test_oxdna_unknown_bounds_never_become_stopped(scene, monkeypatch, fault):
    from backend.core import activity_evidence_io as io
    root, proc = scene; job = job_for('oxdna', root); evidence = Evidence(proc)
    directory = job.stage_dir(root, 'stage'); (directory / 'last_conf.dat').touch()
    if fault == 'specs': (job.job_dir(root) / 'stages_spec.json').unlink()
    if fault == 'stage_count': job.stages *= 129
    if fault == 'bytes': evidence.remaining = 0
    if fault == 'work': evidence.work = 0
    if fault == 'deadline': evidence.deadline = 0
    if fault == 'energy': (directory / 'energy.dat').write_bytes(b'0' * (io.MAX_TEXT + 1))
    if fault == 'permission':
        original = evidence.open_regular
        def unreadable(path, *a):
            if Path(path).name == 'stages_spec.json': raise PermissionError('isolated')
            return original(path, *a)
        monkeypatch.setattr(evidence, 'open_regular', unreadable)
    if fault == 'attempt_entries':
        job.status = OxdnaStatus.stopped; monkeypatch.setattr(io, 'MAX_ENTRIES', 2)
        (directory / 'oxdna.log').write_text('END OF THE SIMULATION, everything went OK!')
        for i in range(3): (directory / f'energy.r{i}.dat').touch()
    before = snapshot(root); saved = deepcopy(job)
    result = observe_local_engine('oxdna', job, root, evidence)
    assert result.assessment.action == 'unknown' and result.reason
    assert snapshot(root) == before and job == saved


def test_one_process_inventory_for_all_process_families(scene, monkeypatch):
    from backend.core import activity_evidence_io as io
    root, proc = scene; calls = []; original = io.os.scandir
    def scan(path):
        if Path(path) == proc: calls.append(path)
        return original(path)
    monkeypatch.setattr(io.os, 'scandir', scan)
    evidence = Evidence(proc)
    for engine in FAMILIES:
        job = job_for(engine, root)
        if engine == 'lammps': job.lammps_pid = 321
        if engine == 'snupi': job.pid = 321
        assert observe_local_engine(engine, job, root, evidence).assessment.action == 'stopped'
    assert len(calls) == 1


@pytest.mark.parametrize('engine', ['lammps', 'snupi'])
def test_incomplete_inventory_cannot_hide_recorded_pid(scene, engine):
    root, proc = scene; job = job_for(engine, root); proc.rmdir()
    if engine == 'lammps': job.lammps_pid = 321
    else: job.pid = 321
    result = observe(engine, job, scene)
    assert result.assessment.action == 'unknown' and result.assessment.missing == 'live'


def test_lammps_recycled_pid_is_not_live(scene):
    root, proc = scene; job = job_for('lammps', root); job.lammps_pid = 321
    process = proc / '321'; process.mkdir(); (process / 'cmdline').write_bytes(b'python\0worker')
    assert observe('lammps', job, scene).assessment.action == 'stopped'


@pytest.mark.parametrize('engine', ['oxdna', 'lammps', 'cando'])
def test_native_registry_handle_precedes_missing_inventory(scene, engine, monkeypatch):
    from types import SimpleNamespace
    from backend.core import simulation_runtime as runtime
    root, proc = scene; job = job_for(engine, root); proc.rmdir()
    runner = {'oxdna': oxdna_runner, 'lammps': lammps_runner, 'cando': cando_runner}[engine]
    with runtime.use_workspace(root):
        monkeypatch.setitem(runner._RUNNING, job.job_id, SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True)))
        assert observe(engine, job, scene).assessment.action == 'live'
        # Remove while the same workspace scope is active (monkeypatch teardown
        # outside that scope must not leave a scoped fake owner behind).
        del runner._RUNNING[job.job_id]


@pytest.mark.parametrize('engine', ['lammps', 'snupi'])
def test_pid_lookup_cannot_use_inventory_after_work_exhaustion(scene, engine, monkeypatch):
    root, proc = scene; job = job_for(engine, root); evidence = Evidence(proc)
    if engine == 'lammps': job.lammps_pid = 321
    else: job.pid = 321
    def exhausted():
        evidence.process_ids.add(321)
        evidence.process_commands[321] = b'lmp'
        evidence.work = -1
        return []
    monkeypatch.setattr(evidence, 'processes', exhausted)
    result = observe_local_engine(engine, job, root, evidence)
    assert result.assessment.action == 'unknown' and result.reason == 'work_budget'
