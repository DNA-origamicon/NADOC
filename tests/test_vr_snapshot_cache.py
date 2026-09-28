"""Cache correctness without geometry generation, GPU allocation or SteamVR."""
from unittest.mock import Mock

import pytest
from tools.vr_workflows import snapshot_cache as cache


def producer(raw, destination):
    destination.write_bytes(b'NADOCVR snapshot '+raw)


def test_reset_reuses_identical_content_and_edits_invalidate(tmp_path):
    build = Mock(side_effect=producer)
    def run(raw, version='exporter-v1'):
        output = tmp_path/('run-'+str(len(list(tmp_path.glob('run-*')))))
        result = cache.prepare(raw, output, build, cache=tmp_path/'cache', fingerprint=version)
        assert output.read_bytes() == b'NADOCVR snapshot '+raw
        return result
    assert not run(b'original')['cache_hit']
    assert run(b'original')['cache_hit']
    assert build.call_count == 1
    assert not run(b'unsaved edit')['cache_hit']
    assert not run(b'unsaved edit', 'exporter-v2')['cache_hit']
    assert len(list((tmp_path/'cache').glob('*.nadocvr'))) == 2
    # Run evidence remains readable after its cached entry was evicted.
    assert (tmp_path/'run-0').read_bytes() == b'NADOCVR snapshot original'


def test_corruption_and_interrupted_export_cannot_be_cache_hits(tmp_path):
    directory = tmp_path/'cache'
    build = Mock(side_effect=producer)
    cache.prepare(b'design', tmp_path/'first', build, cache=directory, fingerprint='v1')
    snapshot = next(directory.glob('*.nadocvr'))
    snapshot.write_bytes(b'X'*snapshot.stat().st_size)
    assert not cache.prepare(b'design', tmp_path/'second', build, cache=directory, fingerprint='v1')['cache_hit']
    def fail(raw, output):
        output.write_bytes(b'partial')
        raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError, match='interrupted'):
        cache.prepare(b'new', tmp_path/'failed', fail, cache=directory, fingerprint='v1')
    assert not list(directory.glob('.pending-*'))
    assert not (tmp_path/'failed').exists()
    assert not cache.prepare(b'new', tmp_path/'retry', build, cache=directory, fingerprint='v1')['cache_hit']


def test_byte_budget_and_no_cache_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, 'MAX_BYTES', 30)
    directory = tmp_path/'cache'
    for i in range(3):
        cache.prepare(str(i).encode(), tmp_path/str(i), producer, cache=directory, fingerprint='v1')
    assert sum(p.stat().st_size for p in directory.glob('*.nadocvr')) <= 30
    build = Mock(side_effect=producer)
    result = cache.prepare(b'new', tmp_path/'uncached', build, cache=tmp_path/'unused', enabled=False)
    assert not result['cache_enabled'] and not result['cache_hit']
    assert not (tmp_path/'unused').exists()


def test_exporter_fingerprint_tracks_code_templates_and_dependencies(tmp_path):
    (tmp_path/'backend/core').mkdir(parents=True)
    code = tmp_path/'backend/core/geometry.py'
    code.write_text('first')
    first = cache.exporter_fingerprint(tmp_path)
    code.write_text('second')
    assert cache.exporter_fingerprint(tmp_path) != first
    second = cache.exporter_fingerprint(tmp_path)
    (tmp_path/'uv.lock').write_text('new dependencies')
    assert cache.exporter_fingerprint(tmp_path) != second


def test_concurrent_launches_publish_one_complete_export(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    build = Mock(side_effect=producer)
    def run(index):
        return cache.prepare(b'same', tmp_path/str(index), build,
                             cache=tmp_path/'cache', fingerprint='v1')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r['cache_hit'] for r in results) == [False, True]
    assert build.call_count == 1
    assert (tmp_path/'0').read_bytes() == (tmp_path/'1').read_bytes()
    with pytest.raises(FileExistsError):
        run(0)
