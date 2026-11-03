"""Bounded, single-flight cache for :func:`build_atomistic_model`.

The live-MD WebSocket (``/ws/md-run`` in ``backend/api/ws.py``) rebuilds the full
all-atom model on every ``load`` message.  For a ~1 M-atom origami each build is a
multi-second, multi-GB scipy backbone minimisation.  With no cache and no
concurrency guard, rapid re-opens (representation changes, reconnects, retry
storms) piled up *dozens* of concurrent identical builds — each holding its own
multi-GB model — which exhausted host RAM (observed: one worker at ~20 GB on a
30 GB box, actively swapping, with ~20 ``build_atomistic_model`` frames live in a
single ``py-spy`` dump).

This wraps the build with two guards:

* a content-fingerprint keyed **LRU cache** — build once per design, reuse; and
* a per-fingerprint **single-flight lock** — N concurrent requests for the same
  design collapse to ONE build; the other N-1 wait on the lock and receive the
  cached result instead of each materialising their own copy.

Completed cache entries have both count and conservative byte-charge limits.
Distinct builds serialize and reserve their expected temporary allocations.
Active callers own their models independently of cache retention.

The fingerprint hashes the whole design (a superset of what
``build_atomistic_model`` actually reads): over-invalidation only costs a rebuild,
whereas serving a stale model would silently show the wrong structure — so we err
toward rebuilding.  This lives in ``backend/core`` (not the ws router) so every
caller of ``build_atomistic_model`` can opt in, and so it is unit-testable without
a WebSocket.
"""

from __future__ import annotations

import hashlib
import json
import threading
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.core.models import Design

# Live-MD viewing is normally one design at a time; keep a tiny window so a repr
# toggle back-and-forth (nadoc ↔ ballstick share one model per design) stays warm
# without letting several million-atom models accumulate.
_CACHE_MAX = 2
_CACHE_MAX_BYTES = 512 * 1024**2
_cache_charges: dict[str, int] = {}
# Also serialize different designs: an LRU bounds completed entries, not builds.
_build_lock = threading.Lock()

_cache: "OrderedDict[str, object]" = OrderedDict()
_key_locks = weakref.WeakValueDictionary()
_registry_lock = (
    threading.Lock()
)  # guards _cache + _key_locks (never held during a build)


def atomistic_fingerprint(design: "Design") -> str:
    """Stable content hash of the full design.

    A superset of the fields ``build_atomistic_model`` consumes — deliberately, so
    the cache can never return a model built from a different design.  Hashing a
    few MB of JSON is trivial next to building a million atoms.
    """
    payload = design.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_atomistic_model_cached(
    design: "Design",
    *,
    fingerprint: str | None = None,
    fast_bridges: bool = False,
    measured_positioning: bool = True,
):
    """``build_atomistic_model(design)`` with a bounded cache + single-flight build.

    Pass ``fingerprint`` if the caller already computed one (avoids re-hashing);
    it MUST be ``atomistic_fingerprint(design)`` for the same design.
    """
    from backend.core.atomistic import build_atomistic_model  # noqa: PLC0415
    from backend.core.native_full_placement import SOURCE, require_native_full_option
    require_native_full_option(measured_positioning)

    base_key = fingerprint if fingerprint is not None else atomistic_fingerprint(design)
    # Bridge construction changes coordinates, so keep exact and interpolated
    # models in distinct cache entries. The placement authority version prevents
    # reusing a cache entry produced before the single-source contract.
    key = (
        f"{base_key}:fast_bridges={int(fast_bridges)}"
        f":placement={SOURCE}"
    )

    # Fast path: already built.
    with _registry_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        key_lock = _key_locks.setdefault(key, threading.Lock())

    # Single-flight: exactly one thread builds a given key.  The others block here
    # (cheap — waiting, not building) and pick up the cached result below.  The
    # Build work runs outside the registry lock, but has its own allocation lock.
    with key_lock, _build_lock:
        with _registry_lock:
            if key in _cache:  # built by the thread that held the lock before us
                _cache.move_to_end(key)
                return _cache[key]

        from backend.core.memory_budget import reserve
        from backend.core.memory_sizes import retained_bytes
        from backend.core.sequences import strand_nucleotide_count

        nucleotides = sum(strand_nucleotide_count(s, design) for s in design.strands)
        # Heavy-atom Python models plus placement temporaries; no solvent atoms.
        allowance = 128 * 1024**2 + nucleotides * 32 * 4096
        with reserve(allowance, label='Atomistic model construction'):
            model = build_atomistic_model(
                design,
                fast_bridges=fast_bridges,
                measured_positioning=measured_positioning,
            )
            charge = int(retained_bytes(model) * 1.25)

        with _registry_lock:
            if charge > _CACHE_MAX_BYTES:
                return model  # caller owns it; don't retain an oversized cache entry
            _cache[key] = model
            _cache_charges[key] = charge
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_MAX or sum(_cache_charges.values()) > _CACHE_MAX_BYTES:
                old_key, _ = _cache.popitem(last=False)
                _cache_charges.pop(old_key, None)
        return model


def clear_atomistic_cache() -> None:
    """Drop all cached models (test hook / manual reclaim)."""
    with _registry_lock:
        _cache.clear()
        _cache_charges.clear()
        # In-flight/waiting requests still own their key locks. Removing those
        # locks here would let a new request duplicate an in-flight build.


def cache_size() -> int:
    """Number of models currently held (for tests / diagnostics)."""
    with _registry_lock:
        return len(_cache)


def cache_bytes() -> int:
    with _registry_lock:
        return sum(_cache_charges.values())


def reclaim_cache_if_low(min_free_mb: int) -> int:
    """Drop cached models when host RAM is tight; return how many were freed.

    The live-viewer models are the largest *discretionary* host allocation NADOC
    holds (up to ``_CACHE_MAX`` ~1 GB million-atom models). When free host RAM falls
    below ``min_free_mb`` — e.g. just before a NAMD segment spawns and needs to pin
    GPU staging buffers (see md_vram.FAILURE_HOST_OOM) — releasing them gives the run
    maximum headroom. On a roomy machine free RAM stays above the floor, so nothing
    is dropped and the viewer never thrashes. Best-effort: an unreadable RAM figure
    leaves the cache untouched (we don't reclaim on a guess).
    """
    from backend.core.md_vram import detect_host_ram_mb  # noqa: PLC0415 (avoid import cycle at load)

    free_mb = detect_host_ram_mb()
    if free_mb is None or free_mb >= min_free_mb:
        return 0
    n = cache_size()
    if n:
        clear_atomistic_cache()
    return n


from backend.core.memory_budget import register_reclaimer
register_reclaimer('atomistic_models', clear_atomistic_cache)
