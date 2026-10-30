"""Current document I/O and picker costs on disposable Archive fixtures.

Run under validation_guard with Archive TMPDIR and isolated NADOC_WORKSPACE.
No app lifespan or user document services are started.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import statistics
import tempfile
import time


def measure(fn, repeats=7):
    samples = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return dict(median_ms=statistics.median(samples), samples_ms=samples), result


def main():
    archive = Path('/media/jojo/Archive')
    scratch = Path(os.environ['TMPDIR']).resolve()
    assert archive.is_mount() and scratch.is_relative_to(archive)
    assert os.environ.get('NADOC_VALIDATION_SCOPE') == '1'
    assert Path(os.environ['NADOC_WORKSPACE']).resolve().is_relative_to(scratch)
    from backend.api import routes_fs, state
    from backend.core.lattice import make_bundle_design
    from backend.core.models import Design, SnapshotLogEntry
    from backend.core.project_revisions import ProjectRevisionStore

    rows = []
    with tempfile.TemporaryDirectory(prefix='docs-', dir=scratch) as directory:
        root = Path(directory)
        for count in (100, 1000, 10000):
            folder = root / f'picker-{count}'
            folder.mkdir()
            for index in range(count):
                child = folder / f'entry-{index:05d}'
                if index % 10 == 0:
                    child.mkdir()
                else:
                    child.touch()
            timing, result = measure(lambda: routes_fs._list_dir(folder))
            assert [entry['name'] for entry in result['entries']] == [f'entry-{i:05d}' for i in range(0, count, 10)]
            rows.append(dict(operation='directory_picker', entries=count, **timing))
        for history in (0, 100, 1000):
            design = make_bundle_design([(i, 0) for i in range(24)], length_bp=84)
            body, size = state.encode_design_snapshot(design)
            design.feature_log = [SnapshotLogEntry(op_kind='nick', label='Synthetic recovery state', params={}, design_snapshot_gz_b64=body, snapshot_size_bytes=size, post_state_gz_b64=body, post_state_size_bytes=size) for _ in range(history)]
            timing, serialized = measure(design.to_json)
            rows.append(dict(operation='portable_json_encode', history=history, bytes=len(serialized.encode()), **timing))
            timing, restored = measure(lambda: Design.from_json(serialized))
            assert restored.model_dump(mode='json') == design.model_dump(mode='json')
            rows.append(dict(operation='portable_json_decode', history=history, **timing))
            store = ProjectRevisionStore(root / f'revisions-{history}')
            head = None
            def commit():
                nonlocal head
                design.metadata.name = f'Benchmark revision {head}'
                revision = store.commit(design, loadout_id='benchmark', loadout_name='Benchmark', parent_revision_id=head, expected_head=head)
                head = revision.revision_id
                return revision
            timing, revision = measure(commit)
            rows.append(dict(operation='revision_commit_unique_snapshot', history=history, **timing))
            timing, loaded = measure(lambda: store.load_design(design.id, revision.revision_id))
            expected = design.model_copy(update={'loadouts': [], 'active_loadout_id': None, 'last_editable_loadout_id': None})
            assert loaded.model_dump(mode='json') == expected.model_dump(mode='json')
            rows.append(dict(operation='revision_load', history=history, **timing))
    sources = ['backend/api/routes_fs.py', 'backend/core/models.py', 'backend/core/project_revisions.py', 'backend/core/part_document_io.py']
    print(json.dumps(dict(scope='Warm component screening, GC enabled; Archive filesystem, no HTTP/rendering. Seven sequential samples including first call. Revision commits change snapshots each time; portable encoding is CPU only.', source_sha256={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}, cases=rows, fixture_cleanup_complete=not root.exists()), indent=2))


if __name__ == '__main__':
    main()
