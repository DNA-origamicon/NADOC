"""Versioned job-local analysis artifacts shared by interactive and idle workers."""
from __future__ import annotations

from contextlib import nullcontext
import dataclasses
import functools
import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import tempfile

VERSION = 1
_LOG = logging.getLogger(__name__)


def _pack(value):
    if isinstance(value, dict):
        return {"dict": [[_pack(k), _pack(v)] for k, v in value.items()]}
    if isinstance(value, tuple):
        return {"tuple": [_pack(v) for v in value]}
    if isinstance(value, list):
        return [_pack(v) for v in value]
    if hasattr(value, "dtype") and hasattr(value, "shape"):
        return {"array": value.tolist(), "dtype": str(value.dtype)}
    return value


def _unpack(value):
    if isinstance(value, dict):
        if "array" in value:
            import numpy as np
            return np.asarray(value["array"], dtype=value["dtype"])
        if "dict" in value:
            return {_unpack(k): _unpack(v) for k, v in value["dict"]}
        return tuple(_unpack(v) for v in value["tuple"])
    if isinstance(value, list):
        return [_unpack(v) for v in value]
    return value


def _signature(value, paths):
    if isinstance(value, str) and len(value) < 4096 and "\n" not in value:
        try:
            if Path(value).is_file():
                value = Path(value)
        except OSError:
            pass
    if isinstance(value, Path):
        paths.append(value)
        try:
            st = value.stat()
            return [str(value.resolve()), st.st_size, st.st_mtime_ns]
        except OSError:
            return [str(value), None]
    if hasattr(value, "to_json"):
        return value.to_json()
    if dataclasses.is_dataclass(value):
        return _signature(dataclasses.asdict(value), paths)
    if isinstance(value, dict):
        return [[_signature(k, paths), _signature(v, paths)] for k, v in value.items()]
    if isinstance(value, (tuple, list)):
        return [_signature(v, paths) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def persistent_analysis(function):
    """Cache successful calculations; callbacks are deliberately not part of identity.

    File locks coalesce foreground/background work across processes. Atomic JSON writes
    survive interruption and preserve tuple-keyed average frames without executable data.
    """
    signature = inspect.signature(function)

    def entry(args, kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        paths = []
        inputs = {k: v for k, v in bound.arguments.items()
                  if k not in {"progress", "on_frame", "on_stage", "workers"}}
        fingerprint = _signature(inputs, paths)
        root = next((p for path in paths for p in path.parents
                     if (p / "job.json").is_file()), None)
        if root is None:
            return None
        # Job status is not evidence that these local files are changing (remote
        # runs and queued resumes often have stable downloaded trajectories).
        # The before/after input signature below guards publication for every state.
        key = hashlib.sha256(json.dumps([VERSION, fingerprint], sort_keys=True).encode()).hexdigest()
        return root / "analysis_cache", key, inputs, fingerprint

    def read_cached(*args, **kwargs):
        found = entry(args, kwargs)
        if found is None:
            return None
        directory, key, _, _ = found
        try:
            return _unpack(json.loads((directory / f"{function.__name__}-{key}.json").read_text()))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        import fcntl

        found = entry(args, kwargs)
        if found is None:
            return function(*args, **kwargs)
        directory, key, inputs, fingerprint = found
        try:
            directory.mkdir(exist_ok=True)
            lock = (directory / f"{function.__name__}-{key}.lock").open("a")
        except OSError as error:
            _LOG.warning("Cannot open analysis cache for %s in %s: %s",
                         function.__name__, directory, error)
            return function(*args, **kwargs)
        artifact = directory / f"{function.__name__}-{key}.json"
        # Warm reads must not interrupt unrelated backfill. On a miss, advertise
        # demand BEFORE waiting for a background-owned artifact lock.
        try:
            cached = _unpack(json.loads(artifact.read_text()))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        else:
            lock.close()
            return cached
        from backend.core import trajectory_priority as priority

        if priority.BACKFILL_PROCESS:
            demand = priority.interruptible_backfill()
        elif os.environ.get("NADOC_PRECOMPUTE_WORKER"):
            demand = nullcontext()
        else:
            demand = priority.foreground_work()
        with lock, demand:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return _unpack(json.loads(artifact.read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                pass
            result = function(*args, **kwargs)
            # Never publish a result against inputs which changed during the pass.
            if (not isinstance(result, dict) or (result.get("ready", True) or result.get("not_applicable") is True)) and _signature(inputs, []) == fingerprint:
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as out:
                        temporary = Path(out.name)
                        json.dump(_pack(result), out, separators=(",", ":"))
                    os.replace(temporary, artifact)
                except OSError as error:
                    # Viewing remains possible, but do not silently imply that a
                    # result survived disk-full/read-only/disconnected storage.
                    _LOG.warning("Could not save analysis %s in %s: %s",
                                 function.__name__, directory, error)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            return result
    wrapped.read_cached = read_cached
    return wrapped
