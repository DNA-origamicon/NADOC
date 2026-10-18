"""Incremental recipe replay: a bounded cache of executed command results (R1).

Replay is deterministic in its inputs: the explicit recipe root plus each
command's exact parameters. A *full key* hash-chains all of them, so a hit returns
exactly what re-execution would produce.

Bend/Twist edits are geometry-only. A ``deformation`` command changes only
``Design.deformations``, and the commands in ``DEFORMATION_INDEPENDENT`` neither
read deformations nor change them (they pass them through). For those commands a
second *topology key* chains every input except deformation commands. A topology
hit is the cached output with the current input's deformations substituted, which
is what re-execution would produce. Both invariants are asserted by
tests/test_part_replay_cache.py; add a kind to the set only with such a test.

Only results that took at least ``MIN_CACHE_SECONDS`` are stored (cheap commands
are faster to re-run than to copy). Stored and returned values are deep copies,
so callers and executors may mutate them freely. The cache is process-local and
never persisted: it is an optimization, never an authority.
"""

from collections import OrderedDict
import hashlib
import json
from threading import Lock
from time import monotonic

CACHE_VERSION = 1
MIN_CACHE_SECONDS = 0.02
MAX_ENTRIES = 32

DEFORMATION_INDEPENDENT = frozenset({
    "auto-scaffold-seamless", "auto-scaffold-seamed", "auto-scaffold-matched",
    "full-autostaple", "auto-break", "auto-merge", "auto-crossover",
})

_lock = Lock()
_entries = OrderedDict()
stats = {"full_hits": 0, "topology_hits": 0, "misses": 0, "stored": 0}


def _hash(*parts):
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _get(key):
    with _lock:
        value = _entries.get(key)
        if value is not None:
            _entries.move_to_end(key)
        return value


def _put(key, value):
    with _lock:
        _entries[key] = value
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear():
    with _lock:
        _entries.clear()
        for name in stats:
            stats[name] = 0


class ReplayChain:
    """Sequential replay position. Call ``run`` once per command, in recipe order,
    always passing the previous result (or the root design first)."""

    def __init__(self, root=None, input_sources=None, *, position=None):
        if position is not None:
            self.full, self.topology = position
        else:
            seed = _hash("root", CACHE_VERSION,
                         root.model_dump(mode="json") if root is not None else None,
                         dict(input_sources or {}))
            self.full = self.topology = seed

    @classmethod
    def for_design(cls, design):
        return cls(design.recipe_root, design.input_sources)

    def position(self):
        return (self.full, self.topology)

    def run(self, executor, kind, design, params):
        full = _hash(self.full, kind, params)
        if kind == "deformation":
            topology = self.topology  # writes deformations only
        elif kind in DEFORMATION_INDEPENDENT:
            topology = _hash(self.topology, kind, params)
        else:
            # Output topology may depend on deformation geometry from here on.
            topology = _hash("full", full)
        result = None
        cached = _get(("full", full))
        if cached is not None:
            result = cached.model_copy(deep=True)
            stats["full_hits"] += 1
        elif kind in DEFORMATION_INDEPENDENT and (cached := _get(("topology", topology))) is not None:
            result = cached.model_copy(deep=True).copy_with(
                deformations=[op.model_copy(deep=True) for op in design.deformations])
            stats["topology_hits"] += 1
        if result is not None:
            result = result.copy_with(id=design.id)
        else:
            started = monotonic()
            result = executor(kind, design, params)  # failures propagate, never cached
            stats["misses"] += 1
            if monotonic() - started >= MIN_CACHE_SECONDS:
                stored = result.model_copy(deep=True)
                _put(("full", full), stored)
                if kind in DEFORMATION_INDEPENDENT:
                    _put(("topology", topology), stored)
                stats["stored"] += 1
        self.full, self.topology = full, topology
        return result

    def wrap(self, executor):
        """An ``executor(kind, design, params)`` that advances this chain."""
        def run(kind, design, params):
            return self.run(executor, kind, design, params)
        run.chain = self
        return run
