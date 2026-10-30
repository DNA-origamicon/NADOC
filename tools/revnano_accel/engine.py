"""Bounded-memory adapter for pinned REVNANO 1.1 (Shirt-Ediss, 2020–2023).
Pass 1 remains upstream and sequential; Pass 2 uses a fixed footprint snapshot.
No routing thresholds, tie ordering or scientific error policy are changed.
"""
from collections import OrderedDict
from collections.abc import MutableMapping
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import multiprocessing as mp
import os
import pickle
import resource
import sys
import time


def limit_memory(mib):
    """Linux address-space ceiling, not an RSS estimate; fail rather than prune."""
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    value = int(mib * 1024**2)
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    # Lowering RLIMIT_AS does not reclaim already allocated address space.
    current = int(Path('/proc/self/statm').read_text().split()[0]) * os.sysconf('SC_PAGE_SIZE')
    if current > value:
        raise MemoryError(f'Existing address space {current / 1024**2:.1f} MiB exceeds requested limit {value / 1024**2:.1f} MiB')
    resource.setrlimit(resource.RLIMIT_AS, (value, hard))


def atomic_pickle(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as f:
        pickle.dump(value, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temporary, path)


class TreeStore(MutableMapping):
    """Mutable trees persisted on eviction; at most one tree cached in RAM.

    REVNANO stages access one mutable tree at a time. Do not use this mapping
    for clients retaining and mutating an evicted tree reference.
    """
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.paths = {}
        self.active_key = None
        self.active_tree = None

    def flush(self):
        if self.active_key is not None:
            atomic_pickle(self.paths[self.active_key], self.active_tree)
            self.active_key = None
            self.active_tree = None

    def __getitem__(self, key):
        path = self.paths[key]
        if self.active_key != key:
            self.flush()
            with path.open('rb') as f:
                self.active_tree = pickle.load(f)
            self.active_key = key
        return self.active_tree

    def __setitem__(self, key, value):
        self.flush()
        path = self.directory / f'{int(key)}.pickle'
        atomic_pickle(path, value)
        self.paths[key] = path

    def register(self, key, path):
        self.paths[key] = Path(path)

    def __delitem__(self, key):
        self.flush()
        self.paths.pop(key).unlink()

    def __iter__(self):
        return iter(self.paths)

    def __len__(self):
        return len(self.paths)


def install_run_cache(max_mib):
    """Memoize sequence-only scans, with conservatively accounted byte eviction."""
    from REVNANO import dna
    original = dna.get_run
    cache = OrderedDict()
    size = 0
    stats = {'hits': 0, 'misses': 0, 'peak_bytes': 0}
    budget = int(max_mib * 1024**2)

    def cached(origami, subseq):
        nonlocal size
        key = (origami['scaffold53'], origami['scaffold_type'], subseq)
        if key in cache:
            stats['hits'] += 1
            cache.move_to_end(key)
            return cache[key][0]
        stats['misses'] += 1
        result = original(origami, subseq)
        # Count Python object payloads, deliberately overcount shared integers.
        cost = 256 + sys.getsizeof(key) + sum(sys.getsizeof(s) for s in key)
        cost += sys.getsizeof(result) + sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in result.items())
        while cache and size + cost > budget:
            _, (_, old_cost) = cache.popitem(last=False)
            size -= old_cost
        if cost <= budget:
            cache[key] = result, cost
            size += cost
            stats['peak_bytes'] = max(stats['peak_bytes'], size)
        return result

    dna.get_run = cached
    return stats


_CONTEXT = None
_WORK = None
_STATS = None


def worker_init(snapshot, directory, memory_mib, cache_mib, source):
    global _CONTEXT, _WORK, _STATS
    limit_memory(memory_mib)
    sys.path.insert(0, source)
    with open(snapshot, 'rb') as f:
        _CONTEXT = pickle.load(f)
    _WORK = Path(directory)
    _STATS = install_run_cache(cache_mib)


def build_one(task):
    """Same short-staple/retry branches as upstream stage0 Pass 2."""
    from REVNANO import srt, parameters
    staple_id, mu, sigma, beta = task
    seq = _CONTEXT['staples53'][staple_id]
    started = time.perf_counter()
    attempts = [mu - 1] if len(seq) <= parameters.SHORT_STAPLE_LEN else [mu, mu - 1]
    tree = None
    reason = None
    for minimum in attempts:
        srt.subtree_count = 0
        try:
            tree = srt.generate_staple_routing_tree(_CONTEXT, staple_id, seq, [], set(), 0, len(seq), sigma, minimum, beta)
        except ValueError:
            # Upstream terminates this staple on its MAX_SUBTREES exception.
            reason = 'upstream subtree limit'
            tree = None
            break
        root_pruned = srt.propagate_pruning_in_staple_routing_tree(tree)
        if tree is not None and not root_pruned:
            reason = None
            break
        reason = 'no route'
        tree = None
    path = _WORK / f'{staple_id}.pickle'
    atomic_pickle(path, tree)
    return {'id': staple_id, 'path': str(path), 'no_tree': tree is None,
            'reason': reason, 'seconds': time.perf_counter() - started,
            'pid': os.getpid(), 'peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            'cache': dict(_STATS)}


def parallel_builder(directory, source, workers, worker_mib, cache_mib, metrics):
    """Factory for the small upstream Pass 2 hook; bounded submission batches."""
    def build(origami, initial_trees, mu, sigma, beta):
        store = TreeStore(Path(directory) / 'trees')
        for key, tree in initial_trees.items():
            store[key] = tree
        initial_trees.clear()
        origami['staple_routing_trees'] = store
        # The snapshot contains only the frozen Pass 1 state; not accumulated trees.
        frozen = dict(origami)
        frozen['staple_routing_trees'] = None
        snapshot = Path(directory) / 'pass1.pickle'
        atomic_pickle(snapshot, frozen)
        pending = [i for i in range(origami['num_staples']) if i not in origami['staple_ids_with_1definite_route']]
        ctx = mp.get_context('spawn')
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=worker_init,
                                 initargs=(str(snapshot), str(store.directory), worker_mib, cache_mib, str(source))) as pool:
            for offset in range(0, len(pending), workers):
                batch = pending[offset:offset + workers]
                futures = [pool.submit(build_one, (i, mu, sigma, beta)) for i in batch]
                # Commit in original staple order, never completion order.
                for future in futures:
                    result = future.result()  # resource failures abort, never silently drop a staple
                    metrics.append(result)
                    store.register(result['id'], result['path'])
                    if result['no_tree']:
                        origami['staple_ids_with_no_tree'].append(result['id'])
                    print(f"Pass 2 staple {result['id']}: {result['reason'] or 'tree saved'} ({result['seconds']:.2f}s)", flush=True)
    return build
