"""Membership reads must never inspect artifacts or reconcile running jobs."""
import json

from backend.core.sim_job_snapshot import read_snapshot


def test_all_engines_archives_and_deletion(tmp_path):
    for engine in ('oxdna', 'lammps', 'mrdna', 'cando', 'snupi', 'blade', 'md'):
        folder = tmp_path / f'{engine}_jobs' / engine
        folder.mkdir(parents=True)
        (folder / 'job.json').write_text(json.dumps({
            'job_id': engine, 'status': 'completed', 'design_source_path': 'part.nadoc',
            'health_samples': [1, 2, 3],
        }))
    md = tmp_path / 'md_jobs'
    (md / '.archive_index.json').write_text(json.dumps({'archived': '/unmounted/archive'}))
    (md / '.archive_metadata').mkdir()
    (md / '.archive_metadata' / 'archived.json').write_text(json.dumps({
        'job_id': 'archived', 'archived': True, 'status': 'completed',
    }))
    rows = read_snapshot(tmp_path)
    assert len(rows) == 8
    assert {r['engine'] for r in rows} == {'oxdna', 'lammps', 'mrdna', 'cando', 'snupi', 'blade', 'namd'}
    assert all('health_samples' not in r for r in rows)
    (md / 'md' / 'job.json').write_text(json.dumps({'job_id': 'md', 'status': 'failed'}))
    assert next(r for r in read_snapshot(tmp_path) if r['job_id'] == 'md')['status'] == 'failed'
    (md / 'md' / 'job.json').unlink()
    assert len(read_snapshot(tmp_path)) == 7


def test_snapshot_route_skips_reconciliation_and_publication(tmp_path, monkeypatch):
    import asyncio
    from backend.api.routes_simulate import list_simulate_jobs
    from backend.core.simulation_runtime import use_workspace
    from backend.core.project_artifacts import ProjectArtifactCatalog
    from backend.api import state
    from types import SimpleNamespace

    publications = []

    def forbidden(*args, **kwargs):
        publications.append(args)
        raise AssertionError('snapshot must not publish or reconcile jobs')

    monkeypatch.setattr(ProjectArtifactCatalog, 'publish_local_jobs', forbidden)
    monkeypatch.setattr(state, 'get_or_404', lambda: SimpleNamespace(id='snapshot-test'))
    folder = tmp_path / 'md_jobs' / 'one'
    folder.mkdir(parents=True)
    (folder / 'job.json').write_text(json.dumps({
        'job_id': 'one', 'status': 'running', 'design_source_path': 'part.nadoc',
    }))
    with use_workspace(tmp_path):
        rows = asyncio.run(list_simulate_jobs('part.nadoc', snapshot=True))
        assert [r['job_id'] for r in rows] == ['one']
        assert asyncio.run(list_simulate_jobs('other.nadoc', snapshot=True)) == []
    assert publications == []
