"""Isolated evidence acquisition: no user processes, simulations or reconciliation."""
from copy import deepcopy
import os
from pathlib import Path
import struct

import pytest

from backend.core import activity_evidence_io as io, mrdna_runner, namd_runner
from backend.core.activity_observation import observe_mrdna, observe_namd
from backend.core.md_job import MdJob, MdStatus, MdSegmentStatus
from backend.core.mrdna_job import MrdnaJob, MrdnaStatus


@pytest.fixture
def scene(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'; proc.mkdir()
    job = MdJob(job_id='isolated', design_name='Test', protocol='test', status=MdStatus.running,
        created_at=0, package_subdir='package', name_stem='test')
    job.segments = [MdSegmentStatus(name='segment', stage='production', percent=100, steps=100)]
    job.package_dir(tmp_path).joinpath('output').mkdir(parents=True)
    mr = MrdnaJob(job_id='isolated', design_name='Test', status=MrdnaStatus.running, created_at=0,
        coarse_steps=100, fine_steps=100, output_period=50)
    mr.job_dir(tmp_path).joinpath('output').mkdir(parents=True)
    for runner, names in ((namd_runner, ('_finish_job', 'run_health_check', '_append_metrics_jsonl')),
                          (mrdna_runner, ('_load_snapshot_design', '_finalize_outputs'))):
        for name in names:
            monkeypatch.setattr(runner, name, lambda *a, **k: pytest.fail('Effect entered'))
    return tmp_path, proc, job, mr


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def observe(scene, engine):
    root, proc, job, mr = scene
    before = files(root); model = job if engine == 'namd' else mr; saved = deepcopy(model)
    result = (observe_namd if engine == 'namd' else observe_mrdna)(model, root, io.Evidence(proc))
    assert files(root) == before and model == saved
    assert not list(root.rglob('.runtime.lock'))
    return result


@pytest.mark.parametrize('state,action', [
    ('fresh', 'resume_unstarted_segment'), ('log', 'failed_without_checkpoint'),
    ('resume_log', 'failed_without_checkpoint'), ('checkpoint', 'resume_checkpoint'),
    ('min', 'resume_minimization'), ('complete', 'segment_finalization_required'),
    ('no_segment', 'finalization_required'), ('queued', 'unchanged'),
    ('malformed', 'resume_unstarted_segment'),
])
def test_namd_native_evidence_and_no_effects(scene, state, action):
    root, _, job, _ = scene; package = job.package_dir(root); output = package / 'output'
    if state == 'log': (package / 'segment.log').touch()
    if state == 'resume_log': (package / 'segment.resume2.log').touch()
    if state == 'checkpoint':
        (output / 'segment.restart.xsc').write_text('# comment\n100 0 0\n')
        assert namd_runner._read_xsc_step(output / 'segment.restart.xsc') == 100
    if state == 'min': (package / 'manifest.json').write_text('{"minimization":{"name":"min"}}')
    if state == 'malformed':
        (package / 'manifest.json').write_text('bad json')
        (output / 'segment.restart.xsc').write_text('invalid step')
    if state == 'complete':
        for ext in ('coor', 'vel', 'xsc'): (output / f'segment.{ext}').touch()
        assert namd_runner._segment_outputs_complete(output, 'segment')
    if state == 'no_segment': job.segments = []
    if state == 'queued': job.status = MdStatus.queued
    result = observe(scene, 'namd')
    assert result.assessment.action == action and result.reason is None


@pytest.mark.parametrize('state,action', [('missing', 'stopped'), ('partial', 'stopped'),
    ('raw', 'finalization_required'), ('cache', 'completed_cache'), ('queued', 'unchanged')])
def test_mrdna_native_headers_and_no_effects(scene, state, action):
    root, _, _, job = scene; directory = job.job_dir(root)
    if state in ('partial', 'raw'):
        for index in range(3):
            path = directory / 'output' / f'mrdna_relax-{index}.dcd'
            path.write_bytes(struct.pack('<i4si', 84, b'CORD', 3 if state == 'raw' else 2))
        assert mrdna_runner._multiresolution_progress(job, root)[0] == (.99 if state == 'raw' else 1/6)
    if state == 'cache': (directory / 'display.json').write_text('not parsed')
    if state == 'queued': job.status = MrdnaStatus.queued
    result = observe(scene, 'mrdna')
    assert result.assessment.action == action and result.reason is None


@pytest.mark.parametrize('engine,command,cwd', [
    ('namd', b'namd3\0segment.resume2.conf\0', 'elsewhere'),
    ('namd', b'namd3\0min.conf\0', 'package'),
    ('mrdna', b'arbd\0relative.conf\0', 'mrdna'),
])
def test_live_priority_native_process_predicates(scene, engine, command, cwd):
    root, proc, job, mr = scene; process = proc / '123'; process.mkdir()
    (process / 'cmdline').write_bytes(command)
    target = job.package_dir(root) if cwd == 'package' else mr.job_dir(root) if cwd == 'mrdna' else root
    (process / 'cwd').symlink_to(target)
    assert observe(scene, engine).assessment.action == 'live'


def test_one_inventory_across_engines_and_shell_not_segment(scene, monkeypatch):
    root, proc, job, mr = scene; process = proc / '123'; process.mkdir()
    (process / 'cmdline').write_bytes(b'bash\0-c\0namd3 segment.conf\0')
    (process / 'cwd').symlink_to(root)
    calls = []; original = os.scandir
    def scandir(path):
        if Path(path) == proc: calls.append(path)
        return original(path)
    monkeypatch.setattr(io.os, 'scandir', scandir)
    evidence = io.Evidence(proc)
    assert observe_namd(job, root, evidence).assessment.action == 'resume_unstarted_segment'
    assert observe_mrdna(mr, root, evidence).assessment.action == 'stopped'
    assert len(calls) == 1


@pytest.mark.parametrize('failure', ['oversize', 'fifo', 'permission', 'bytes', 'work', 'deadline', 'entries', 'process', 'segments', 'nested', 'owner'])
def test_unknown_evidence_is_not_inactive(scene, monkeypatch, failure):
    root, proc, job, _ = scene; evidence = io.Evidence(proc)
    manifest = job.package_dir(root) / 'manifest.json'
    if failure == 'oversize': manifest.write_bytes(b'x' * (io.MAX_TEXT + 1))
    if failure == 'fifo': os.mkfifo(manifest)
    if failure == 'permission':
        original = evidence.open_regular
        def unreadable(path, *a):
            if Path(path) == manifest: raise PermissionError('isolated')
            return original(path, *a)
        monkeypatch.setattr(evidence, 'open_regular', unreadable)
    if failure == 'bytes': evidence.remaining = 0
    if failure == 'work': evidence.work = 0
    if failure == 'deadline': evidence.deadline = 0
    if failure == 'entries':
        monkeypatch.setattr(io, 'MAX_ENTRIES', 1)
        for i in range(2): (proc / str(i)).mkdir()
    if failure == 'process':
        process = proc / '123'; process.mkdir(); (process / 'cmdline').write_bytes(b'x' * (io.MAX_COMMAND + 1))
    if failure == 'segments': job.segments *= 129
    if failure == 'nested': manifest.write_text('[' * 2000 + '0' + ']' * 2000)
    if failure == 'owner': job.execution_target = 'runpod'
    result = observe_namd(job, root, evidence)
    assert result.assessment.action == 'unknown' and result.assessment.missing and result.reason
    assert not list(root.rglob('.runtime.lock'))


def test_large_trajectory_only_reads_header(scene):
    root, proc, _, job = scene
    for index in range(3):
        with (job.job_dir(root) / 'output' / f'mrdna_relax-{index}.dcd').open('wb') as stream:
            stream.write(struct.pack('<i4si', 84, b'CORD', 3)); stream.truncate(100_000_000)
    evidence = io.Evidence(proc)
    assert observe_mrdna(job, root, evidence).assessment.action == 'finalization_required'
    assert evidence.remaining == io.MAX_METADATA_BYTES - 36


@pytest.mark.parametrize('engine', ['namd', 'mrdna'])
def test_missing_process_inventory_is_unknown(scene, engine):
    root, proc, job, mr = scene; proc.rmdir()
    result = (observe_namd if engine == 'namd' else observe_mrdna)(job if engine == 'namd' else mr, root, io.Evidence(proc))
    assert result.assessment.action == 'unknown' and result.assessment.missing == 'live'


@pytest.mark.parametrize('engine', ['namd', 'mrdna'])
def test_existing_runtime_owner_has_priority_without_process_scan(scene, engine):
    import fcntl
    root, proc, job, mr = scene; model = job if engine == 'namd' else mr
    lock = model.job_dir(root) / '.runtime.lock'; lock.touch()
    before = files(root); saved = deepcopy(model)
    proc.rmdir()
    with lock.open('rb') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = (observe_namd if engine == 'namd' else observe_mrdna)(model, root, io.Evidence(proc))
    assert result.assessment.action == 'live'
    assert files(root) == before and model == saved


@pytest.mark.parametrize('fault', ['header_permission', 'invalid_steps', 'preparing', 'archive', 'lock_pipe'])
def test_mrdna_unavailable_is_explicit(scene, monkeypatch, fault):
    root, proc, _, job = scene; evidence = io.Evidence(proc)
    if fault == 'header_permission':
        original = evidence.open_regular
        def read(path, *a):
            if Path(path).suffix == '.dcd': raise PermissionError('isolated')
            return original(path, *a)
        monkeypatch.setattr(evidence, 'open_regular', read)
    if fault == 'invalid_steps': job.output_period = 0
    if fault == 'preparing': job.status = MrdnaStatus.preparing
    if fault == 'archive': job.archived = True
    if fault == 'lock_pipe': os.mkfifo(job.job_dir(root) / '.runtime.lock')
    result = observe_mrdna(job, root, evidence)
    assert result.assessment.action == 'unknown' and result.reason


def test_manifest_string_brackets_do_not_count_as_nesting(scene):
    import json
    root, _, job, _ = scene
    (job.package_dir(root) / 'manifest.json').write_text(json.dumps({'note': '["' * 100, 'minimization': {'name': 'min'}}))
    assert observe(scene, 'namd').assessment.action == 'resume_minimization'


def test_invalid_manifest_encoding_is_unknown(scene):
    root, _, job, _ = scene
    (job.package_dir(root) / 'manifest.json').write_bytes(b'{"minimization":{"name":"\xff"}}')
    result = observe(scene, 'namd')
    assert result.assessment.action == 'unknown' and result.reason == 'unreadable_encoding'
