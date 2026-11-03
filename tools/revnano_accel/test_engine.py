from pathlib import Path
import sys
import random
import pytest
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'.development-artifacts/revnano-gerling2018'))
from engine import TreeStore, install_run_cache


def test_disk_tree_eviction_preserves_mutations_and_iteration_order(tmp_path):
    store = TreeStore(tmp_path)
    store[3] = {(10, 2): [[], 2, False, {}]}
    store[1] = None
    store[3][(10, 2)][2] = True
    assert store[1] is None  # evicts and persists mutated tree3
    assert store[3][(10, 2)][2] is True
    assert list(store) == [3, 1]
    store[3] = None
    assert store[3] is None
    del store[1]
    assert list(store) == [3]
    store.flush()
    assert store.active_tree is None


def test_cache_exact_parity_linear_circular_and_bounded_eviction(monkeypatch):
    from REVNANO import dna
    original = dna.get_run
    # monkeypatch owns restoration even though the adapter installs the wrapper.
    monkeypatch.setattr(dna, 'get_run', original)
    stats = install_run_cache(.002)
    rng = random.Random(14)
    queries = ['','A','TTTT','ACGT','AUGC'] + [''.join(rng.choices('ACGT',k=9)) for _ in range(30)]
    for kind in ['LINEAR','CIRCULAR']:
        origami = {'scaffold53':'ATGCGATTACGGTTAAT', 'scaffold_nt':17, 'scaffold_type':kind}
        for query in queries:
            expected = original(origami,query)
            assert dna.get_run(origami,query) == expected
            assert dna.get_run(origami,query) == expected
    assert stats['hits'] > 0 and stats['misses'] > 30
    assert stats['peak_bytes'] <= .002 * 1024**2


def test_worker_memory_failure_is_not_reported_as_unroutable(monkeypatch, tmp_path):
    from REVNANO import srt
    import engine
    monkeypatch.setattr(engine, '_CONTEXT', {'staples53':['ACGTACGTACGT']})
    monkeypatch.setattr(engine, '_WORK', tmp_path)
    def fail(*args):
        raise MemoryError('test budget exhausted')
    monkeypatch.setattr(srt, 'generate_staple_routing_tree', fail)
    with pytest.raises(MemoryError):
        engine.build_one((0,6,4,.3))
    assert not list(tmp_path.glob('*.pickle'))


def test_limit_rejects_budget_below_existing_address_space_without_changing_limit():
    import resource
    from engine import limit_memory
    before = resource.getrlimit(resource.RLIMIT_AS)
    with pytest.raises(MemoryError, match='Existing address space'):
        limit_memory(1)
    assert resource.getrlimit(resource.RLIMIT_AS) == before
