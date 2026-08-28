"""Learned cluster throughput store (Phase 5 of alpine-cluster-submission).

The Phase-2 resource recommender guesses ns/day from system size on the first run
per (GPU resource, size) — a deliberately conservative guess.  This module remembers
the *measured* throughput of completed remote runs, keyed by ``(cluster, partition,
GRES, size-bucket)``, so a MIG slice never inherits whole-GPU performance.

A small JSON file in the workspace (``cluster_throughput.json``).  Each key maps to
a running mean ns/day + sample count.  Reads are best-effort (a missing/corrupt
store just means "no learned value yet"); writes are atomic (temp + rename) so a
concurrent read never sees a torn file.

The bucketing + running-mean update are pure and unit-tested; the file IO wraps them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE_NAME = "cluster_throughput.json"

# Size-bucket edges (atoms).  A run's throughput is grouped with same-scale systems
# so a 120k-atom estimate learns from a prior 150k-atom run but not a 2M one.
_BUCKET_EDGES = (50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000)


def size_bucket(n_atoms: int) -> str:
    """Coarse size bucket label for ``n_atoms`` (e.g. ``"100000-200000"``)."""
    n = max(1, int(n_atoms))
    lo = 0
    for edge in _BUCKET_EDGES:
        if n < edge:
            return f"{lo}-{edge}"
        lo = edge
    return f"{lo}+"


def _key(
    cluster: str, partition: str, n_atoms: int, gres_type: str | None = None
) -> str:
    resource = f"{partition}/{gres_type}" if gres_type else partition
    return f"{cluster or '?'}:{resource or '?'}:{size_bucket(n_atoms)}"


def update_record(prev: dict | None, ns_per_day: float) -> dict:
    """Fold a new measurement into a running-mean record (pure).

    A simple sample mean: ``mean' = (mean*n + x) / (n+1)``.  First sample seeds it.
    """
    x = float(ns_per_day)
    if not prev or not prev.get("n_samples"):
        return {"ns_per_day": round(x, 4), "n_samples": 1}
    n = int(prev["n_samples"])
    mean = float(prev.get("ns_per_day", x))
    new_mean = (mean * n + x) / (n + 1)
    return {"ns_per_day": round(new_mean, 4), "n_samples": n + 1}


def _store_path(workspace_dir: Path) -> Path:
    return Path(workspace_dir) / _STORE_NAME


def _load(workspace_dir: Path) -> dict:
    path = _store_path(workspace_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def lookup_throughput(
    workspace_dir: Path,
    *,
    cluster: str,
    partition: str,
    n_atoms: int,
    gres_type: str | None = None,
) -> float | None:
    """Learned mean ns/day for this exact resource and size bucket, or ``None``."""
    rec = _load(workspace_dir).get(_key(cluster, partition, n_atoms, gres_type))
    if isinstance(rec, dict):
        v = rec.get("ns_per_day")
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def record_throughput(
    workspace_dir: Path,
    *,
    cluster: str,
    partition: str,
    n_atoms: int,
    ns_per_day: float,
    gres_type: str | None = None,
) -> None:
    """Fold a completed remote run's measured throughput into the store.

    Best-effort: a bad ``ns_per_day`` or an IO error is logged and dropped — learning
    must never break a completing job's bookkeeping.
    """
    if not (isinstance(ns_per_day, (int, float)) and ns_per_day > 0):
        return
    try:
        store = _load(workspace_dir)
        key = _key(cluster, partition, n_atoms, gres_type)
        store[key] = update_record(store.get(key), float(ns_per_day))
        path = _store_path(workspace_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, indent=2, sort_keys=True))
        tmp.replace(path)
        logger.info(
            "recorded throughput %s → %.2f ns/day (n=%d)",
            key,
            store[key]["ns_per_day"],
            store[key]["n_samples"],
        )
    except OSError as exc:
        logger.warning("could not record cluster throughput: %s", exc)
