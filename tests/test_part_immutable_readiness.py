"""Native strict readiness parity, honest evidence and owned read lifecycle."""
import json
from multiprocessing.shared_memory import SharedMemory
from threading import Event

from fastapi import HTTPException
import pytest

from backend.api import assembly, state, routes_design_readiness as ordinary
from backend.api import part_immutable_display_reads as reads
from backend.api import part_readiness_evidence as evidence
from backend.api import part_immutable_revision as revisions
from backend.api import part_strict_geometry_http as geometry
from backend.api import part_publication_policy as policy
from tests.test_part_immutable_geometry_host import document as document, saved, available
from tests.test_part_strict_deformation_preview_http import client as client, enabled as enabled
from tests.test_design_readiness import save_job
from tests.deformation_history_app import fixture

PATH = '/api/design/readiness'


def install(document, kind):
    design = fixture(kind)
    document[1].design = revisions.prepare_geometry_revision(design)
    document[1].revision = 7
    document[1].redo.append(document[1].design)
    return design


def context(document):
    return geometry.capture_context(document[0], policy.resolve(document[0]).generation, recovering=False)


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('kind', ['bend', 'twist'])
@pytest.mark.parametrize('job', ['absent', 'current', 'stale', 'unknown', 'archive', 'revision', 'parent'])
def test_real_http_readiness_matches_ordinary_report(document, client, tmp_path, monkeypatch, kind, job):
    design = install(document, kind)
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    if job == 'current': save_job(tmp_path, design)
    elif job == 'stale':
        from backend.core.oxdna_staleness import design_build_fingerprint
        save_job(tmp_path, design, snapshot=False,
                 design_fingerprint=design_build_fingerprint(design).split(':', 1)[0] + ':stale')
    elif job == 'unknown': save_job(tmp_path, design, snapshot=False, design_fingerprint=None)
    elif job == 'archive':
        archived = save_job(tmp_path, design, folder='archive', snapshot=False)
        root = tmp_path / 'cando_jobs';root.mkdir()
        (root / '.archive_index.json').write_text(json.dumps({'fine': str(archived)}))
    elif job == 'revision':
        from backend.core.project_revisions import ProjectRevisionStore
        revision = ProjectRevisionStore(tmp_path).commit(design, loadout_id='test', loadout_name='Test',
            parent_revision_id=None, expected_head=None)
        save_job(tmp_path, design, folder='lammps_jobs', snapshot=False, design_fingerprint=None,
                 design_revision_id=revision.revision_id, steps=100)
    elif job == 'parent':
        save_job(tmp_path, design, folder='md_jobs', job_id='parent', status='prepared', design_fingerprint=None)
        save_job(tmp_path, design, folder='md_jobs', job_id='production', snapshot=False,
            design_fingerprint=None, parent_job_id='parent', run_kind='production',
            segments=[{'status': 'done', 'steps': 10, 'name': 'production', 'stage': 'production'}])
    before, disk = saved(document[1]), files(tmp_path)
    monkeypatch.setattr(state, 'get_design_with_revision', lambda: (design, 7))
    expected = ordinary.get_design_readiness()
    monkeypatch.setattr(reads, '_decoded_exact', lambda *a: pytest.fail('Parent decoded'))
    monkeypatch.setattr(geometry.publication, 'issue', lambda *a, **k: pytest.fail('Read issued permit'))
    result = client.get(PATH)
    assert result.status_code == 200, result.text
    assert result.json() == expected
    assert result.json()['available'] and result.json()['context'] == 'part'
    assert result.json()['simulation']['complete'] == (job in {'current','archive','revision','parent'})
    if job == 'stale': assert result.json()['simulation']['stale_runs'] == 1
    if job == 'unknown': assert result.json()['simulation']['unknown_runs'] == 1
    assert saved(document[1]) == before and files(tmp_path) == disk
    available()


def test_job_completion_is_refreshed_without_design_change(document, client, tmp_path, monkeypatch):
    design = install(document, 'bend')
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    assert not client.get(PATH).json()['simulation']['complete']
    save_job(tmp_path, design, snapshot=False)
    assert client.get(PATH).json()['simulation']['complete']
    assert document[1].revision == 7


@pytest.mark.parametrize('query', ['assembly=true', 'assembly=false', 'workspace=/tmp', 'verified=true'])
def test_public_query_cannot_select_evidence_or_assembly(document, client, monkeypatch, query):
    install(document, 'bend')
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Invalid query spawned'))
    assert client.get(PATH + '?' + query).status_code == 422


def test_gate_refusal_and_no_fallback(document, client, monkeypatch):
    install(document, 'bend')
    monkeypatch.setattr(geometry.publication, 'ENABLED', False)
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Disabled read spawned'))
    assert client.get(PATH).status_code == 409


@pytest.mark.parametrize('change', ['source', 'session', 'revision', 'policy', 'cancel'])
def test_inflight_readiness_refuses_and_reaps(document, monkeypatch, tmp_path, change):
    install(document, 'bend')
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    cancelled = Event();children = []
    original = reads.DisplayReadWorker
    class Changed(original):
        def start(self):
            super().start()
            if change == 'source': document[1].design = None
            elif change == 'session': state.drop_doc(document[0])
            elif change == 'revision': document[1].revision += 1
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            else: cancelled.set()
    def worker(*args):
        child = Changed(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', worker)
    with pytest.raises(HTTPException): reads.read(context(document), 'readiness', cancelled)
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('budget', ['bytes', 'entries'])
def test_exhausted_evidence_refuses_instead_of_reporting_no_completion(document, tmp_path, monkeypatch, budget):
    design = install(document, 'bend')
    save_job(tmp_path, design)
    original = evidence.EvidenceReader
    def limited():
        reader = original()
        if budget == 'bytes': reader.remaining = 10
        else: reader.entries = 0
        return reader
    monkeypatch.setattr(evidence, 'EvidenceReader', limited)
    parts, _ = reads.worker.encode_input(reads.worker.reserve_input(document[1].design),
        {'read': 'readiness', 'design_id': design.id, 'revision': 7, 'workspace': str(tmp_path)})
    result = reads.project_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'readiness_evidence_limit'


def test_cumulative_reader_does_not_reuse_cached_evidence(tmp_path):
    path = tmp_path / 'job.json';path.write_text('{"status":"running"}')
    reader = evidence.EvidenceReader();reader.remaining = path.stat().st_size
    assert reader.read_json(path)['status'] == 'running'
    with pytest.raises(evidence.EvidenceLimit): reader.read_json(path)


def test_host_path_is_required_only_for_readiness(document):
    design = install(document, 'bend')
    for operation in ({'read': 'readiness', 'design_id': design.id, 'revision': 7},
                      {'read': 'readiness', 'design_id': design.id, 'revision': 7, 'workspace': 'relative'},
                      {'read': 'design', 'design_id': design.id, 'revision': 7, 'workspace': '/tmp'}):
        parts, _ = reads.worker.encode_input(reads.worker.reserve_input(document[1].design), operation)
        assert reads.project_payload(b''.join(parts))['result']['status'] != 'ready'


def test_http_oversized_evidence_refuses_without_writing(document, client, tmp_path, monkeypatch):
    install(document, 'twist')
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    path = tmp_path / 'cando_jobs' / 'oversized' / 'job.json'
    path.parent.mkdir(parents=True)
    with path.open('wb') as stream:
        stream.truncate(evidence.MAX_METADATA_BYTES + 1)
    before = saved(document[1]);stamp = path.stat()
    result = client.get(PATH)
    assert result.status_code == 413 and result.json()['detail']['code'] == 'readiness_evidence_limit'
    assert saved(document[1]) == before
    assert path.stat().st_size == stamp.st_size and path.stat().st_mtime_ns == stamp.st_mtime_ns
    available()
