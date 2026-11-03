"""Finite native discovery/projection, no cache refresh or lifecycle effects."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from backend.core import activity_catalog as catalog
from backend.core.activity_evidence_io import Evidence


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    from backend.core import job_archive, alpine_transfer_state, alpine_restart
    proc = tmp_path / 'proc'; proc.mkdir()
    for module, name in [(job_archive, 'cache_job_metadata'), (alpine_transfer_state, 'apply_transfer_state'),
                         (alpine_restart, 'apply_acknowledgments')]:
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('Catalog entered an effect/overlay'))
    return tmp_path, proc


def metadata(engine, identifier='job', status='running', **extra):
    value = dict(job_id=identifier, design_name='Isolated', status=status, created_at=0,
                 design_source_path='isolated.nadoc')
    if engine == 'md': value.update(protocol='test', package_subdir='package', name_stem='test')
    value.update(extra)
    return value


def write(root, engine, data):
    path = root / f'{engine}_jobs' / data['job_id'] / 'job.json'
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data))
    return path


def run(scene, **kwargs):
    root, proc = scene; before = snapshot(root)
    result = catalog.activity_catalog(root, evidence=kwargs.pop('evidence', Evidence(proc)), **kwargs)
    assert snapshot(root) == before
    assert not list(root.rglob('.runtime.lock'))
    return result


def test_empty_catalog_is_complete(scene):
    assert run(scene) == {'records': [], 'issues': [], 'complete': True}


@pytest.mark.parametrize('engine,model', catalog._families())
def test_native_normalization_and_inactive_projection(scene, monkeypatch, engine, model):
    root, _ = scene; data = metadata(engine, status='queued')
    path = write(root, engine, data)
    normalized = model.from_metadata(deepcopy(data))
    # Native loading keeps its normal overlays; this test isolates normalization
    # by supplying identity overlays, not by asking the catalog to run them.
    result = run(scene)
    record = result['records'][0]
    assert result['complete'] and record['active'] is False
    assert record['summary']['status'] == normalized.status.value
    assert record['summary']['design_source_path'] == normalized.design_source_path
    assert json.loads(path.read_text()) == data
    from backend.core import alpine_transfer_state, alpine_restart
    with monkeypatch.context() as native:
        native.setattr(alpine_transfer_state, 'apply_transfer_state', lambda *a: None)
        native.setattr(alpine_restart, 'apply_acknowledgments', lambda *a: None)
        assert asdict(model.load('job', root)) == asdict(normalized)


def test_mixed_family_completion_and_unknown_are_not_omitted(scene):
    root, _ = scene
    for engine, _ in catalog._families(): write(root, engine, metadata(engine))
    for engine in ('mrdna', 'cando', 'snupi'):
        (root / f'{engine}_jobs/job/display.json').write_text('{}')
    result = run(scene); rows = {r['summary']['engine']: r for r in result['records']}
    assert len(rows) == 6 and result['complete'] is False
    assert rows['md']['active'] is None and rows['md']['action'] == 'finalization_required'
    assert rows['oxdna']['active'] is None and rows['oxdna']['action'] == 'unknown'
    for engine in ('mrdna', 'cando', 'snupi'):
        assert rows[engine]['action'] == 'completed_cache' and rows[engine]['active'] is False
    assert rows['lammps']['action'] == 'stopped' and rows['lammps']['active'] is False


def test_preparing_remote_and_source_eta_are_explicit(scene):
    root, _ = scene
    write(root, 'md', metadata('md', status='preparing', execution_target='alpine', design_source_path=None))
    write(root, 'mrdna', metadata('mrdna', status='preparing'))
    result = run(scene)
    assert not result['complete'] and len(result['records']) == 2
    for row in result['records']: assert row['active'] is None and 'separate_owner' in row['issues']
    row = next(r for r in result['records'] if r['summary']['engine'] == 'md')
    assert 'source_identity_unverified' in row['issues'] and 'accelerator_unverified' in row['issues']


def test_live_oxdna_preserves_resource_and_unqualified_eta(scene):
    root, proc = scene; path = write(root, 'oxdna', metadata('oxdna', backend='CPU'))
    process = proc / '123'; process.mkdir()
    (process / 'cmdline').write_bytes(b'oxDNA\0' + str(path.parent).encode())
    (process / 'cwd').symlink_to(root)
    result = run(scene); row = result['records'][0]
    assert row['active'] is True and row['summary']['resource_class'] == 'cpu'
    assert row['issues'] == ['eta_unverified'] and not result['complete']


@pytest.mark.parametrize('cached', [True, False])
def test_archive_index_uses_local_cache_without_external_read_or_refresh(scene, cached):
    root, _ = scene; directory = root / 'cando_jobs'; directory.mkdir()
    (directory / '.archive_index.json').write_text(json.dumps({'archived': '/unavailable/archive'}))
    if cached:
        path = directory / '.archive_metadata/archived.json'; path.parent.mkdir()
        path.write_text(json.dumps(metadata('cando', 'archived', status='completed', archived=True, archive_path='/unavailable/archive')))
    result = run(scene); row = result['records'][0]
    assert not result['complete'] and row['active'] is None and row['summary']['job_id'] == 'archived'
    assert row['issues'] == (['archive_live_unverified'] if cached else ['metadata_unavailable'])


def test_index_precedes_local_job_and_deduplicates(scene):
    root, _ = scene; write(root, 'cando', metadata('cando', status='running'))
    directory = root / 'cando_jobs'; (directory / '.archive_index.json').write_text('{"job":"/offline"}')
    cache = directory / '.archive_metadata/job.json'; cache.parent.mkdir()
    cache.write_text(json.dumps(metadata('cando', status='completed')))
    result = run(scene)
    assert len(result['records']) == 1 and result['records'][0]['summary']['status'] == 'completed'
    assert result['records'][0]['active'] is None and not result['complete']


@pytest.mark.parametrize('fault', ['malformed', 'identity', 'collection', 'text', 'nodes', 'work', 'jobs', 'output', 'permission', 'index'])
def test_refusals_cannot_claim_a_complete_empty_catalog(scene, monkeypatch, fault):
    root, proc = scene; path = write(root, 'cando', metadata('cando'))
    evidence = Evidence(proc)
    if fault == 'malformed': path.write_text('bad json')
    if fault == 'identity': path.write_text(json.dumps(metadata('cando', 'different')))
    if fault == 'collection': path.write_text(json.dumps(metadata('cando', stages=[{}]*129)))
    if fault == 'text': path.write_text('x' * 16385)
    if fault == 'nodes': monkeypatch.setattr(catalog, 'MAX_NODES', 1)
    if fault == 'work': evidence.work = 0
    if fault == 'jobs': monkeypatch.setattr(catalog, 'MAX_JOBS', 0)
    if fault == 'output': monkeypatch.setattr(catalog, 'MAX_OUTPUT_BYTES', 1)
    if fault == 'permission':
        original = evidence.open_regular
        def read(target, *a):
            if target == path: raise PermissionError('isolated')
            return original(target, *a)
        monkeypatch.setattr(evidence, 'open_regular', read)
    if fault == 'index': (path.parent.parent / '.archive_index.json').write_text('bad json')
    result = run(scene, evidence=evidence)
    assert not result['complete']
    assert result['issues'] or any(r['issues'] for r in result['records'])


def test_symlink_discovery_does_not_escape_workspace(scene):
    root, _ = scene; (root / 'cando_jobs').symlink_to('/unavailable/archive')
    result = run(scene)
    assert not result['complete'] and result['issues'][0]['reason'] == 'symlink_discovery_unqualified'


def test_shared_inventory_for_multiple_families(scene, monkeypatch):
    from backend.core import activity_evidence_io as io
    root, proc = scene
    for engine in ('md', 'oxdna', 'mrdna', 'snupi', 'lammps'):
        write(root, engine, metadata(engine, **({'pid': 123} if engine == 'snupi' else {'lammps_pid': 123} if engine == 'lammps' else {})))
    calls = []; original = io.os.scandir
    def scan(path):
        if Path(path) == proc: calls.append(path)
        return original(path)
    monkeypatch.setattr(io.os, 'scandir', scan)
    catalog.activity_catalog(root, evidence=Evidence(proc))
    assert len(calls) == 1


def test_raw_mrdna_completion_stays_visible_pending_finalization(scene):
    import struct
    root, _ = scene
    path = write(root, 'mrdna', metadata('mrdna', fine_steps=100, coarse_steps=100, output_period=50))
    output = path.parent / 'output'; output.mkdir()
    for index in range(3):
        (output / f'mrdna_relax-{index}.dcd').write_bytes(struct.pack('<i4si', 84, b'CORD', 3))
    result = run(scene); row = result['records'][0]
    assert row['action'] == 'finalization_required' and row['active'] is None
    assert 'finalization_required' in row['issues'] and not result['complete']


def test_ordinary_md_loader_still_applies_both_overlays(scene, monkeypatch):
    from backend.core import alpine_restart, alpine_transfer_state
    from backend.core.md_job import MdJob
    root, _ = scene
    write(root, 'md', metadata('md', status='queued', restart_events=[{'id': 'test'}]))
    calls = []
    monkeypatch.setattr(alpine_restart, 'apply_acknowledgments', lambda job, ws: calls.append(('restart', job.status.value)))
    monkeypatch.setattr(alpine_transfer_state, 'apply_transfer_state', lambda job, ws: calls.append(('transfer', job.status.value)))
    MdJob.load('job', root)
    assert calls == [('restart', 'queued'), ('transfer', 'queued')]
