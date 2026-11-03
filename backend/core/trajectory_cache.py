"""Versioned job-local analysis artifacts shared by interactive and idle workers."""
from __future__ import annotations

from contextlib import nullcontext
import base64
import io
import dataclasses
import functools
import hashlib
import inspect
import json
import logging
import math
import os
from pathlib import Path
import tempfile

VERSION = 2
_LOG = logging.getLogger(__name__)


_TAG = '$nadoc_cache'


def _array_packet(value, kind):
    import numpy as np

    out = io.BytesIO()
    np.save(out, value, allow_pickle=False)
    return {_TAG: kind, 'data': base64.b64encode(out.getbuffer()).decode('ascii')}


def _read_array_packet(data):
    """Validate byte count before NumPy can allocate from a corrupted shape."""
    import numpy as np

    stream = io.BytesIO(data)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
    elif version == (3, 0):
        # NumPy exposes no public v3 header reader. Its format is the same as
        # v2 with UTF-8 field names; bound and validate the literal before load.
        import ast
        import struct
        length = stream.read(4)
        if len(length) != 4:
            raise ValueError('Truncated cached array header')
        size, = struct.unpack('<I', length)
        if size > 10000:
            raise ValueError('Cached array header is too large')
        try:
            header = ast.literal_eval(stream.read(size).decode('utf-8'))
        except (SyntaxError, UnicodeError) as error:
            raise ValueError('Invalid cached array header') from error
        if set(header) != {'shape', 'fortran_order', 'descr'} or type(header['fortran_order']) is not bool:
            raise ValueError('Invalid cached array header')
        shape = header['shape']
        if type(shape) is not tuple or any(type(d) is not int for d in shape):
            raise ValueError('Invalid cached array shape')
        dtype = np.lib.format.descr_to_dtype(header['descr'])
    else:
        raise ValueError('Unsupported cached array version')
    if (dtype.hasobject or any(d < 0 for d in shape)
            or math.prod(shape) * dtype.itemsize != len(data) - stream.tell()):
        raise ValueError('Invalid cached array bytes or object dtype (allow_pickle=False)')
    stream.seek(0)
    return np.load(stream, allow_pickle=False)


def _pack(value):
    """Keep ordinary JSON graphs shared; encode typed values without float objects.

    The old format wrapped/copy-expanded every dictionary, including each atom.
    Large homogeneous numeric lists can use lossless binary64/int64 storage;
    decoding restores their list API. No pickle or executable deserialization.
    """
    if isinstance(value, dict):
        if _TAG in value or any(not isinstance(k, str) for k in value):
            return {_TAG: 'dict', 'items': [[_pack(k), _pack(v)] for k, v in value.items()]}
        packed = {k: _pack(v) for k, v in value.items()}
        return value if all(packed[k] is v for k, v in value.items()) else packed
    if isinstance(value, tuple):
        return {_TAG: 'tuple', 'items': [_pack(v) for v in value]}
    if isinstance(value, list):
        if len(value) >= 256 and type(value[0]) in (float, int, bool):
            kind = type(value[0])
            if all(type(v) is kind for v in value):
                import numpy as np
                # Large Python integers must never be rounded through float64.
                dtype = np.float64 if kind is float else np.bool_ if kind is bool else np.int64
                if kind is not int or all(-(2**63) <= v < 2**63 for v in value):
                    return _array_packet(np.asarray(value, dtype=dtype), 'list')
        packed = [_pack(v) for v in value]
        return value if all(a is b for a, b in zip(value, packed)) else packed
    if hasattr(value, 'dtype') and hasattr(value, 'shape'):
        if value.dtype.hasobject:
            # JSON-compatible object arrays remain data, never pickled objects.
            if value.dtype.fields:
                raise TypeError('Structured object arrays cannot be cached')
            return {_TAG: 'object_array', 'shape': list(value.shape),
                    'items': _pack(value.ravel().tolist())}
        return _array_packet(value, 'array')
    return value


def _unpack(value):
    """Decode in place so a warm read does not clone every atom dictionary."""
    if isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = _unpack(item)
    elif isinstance(value, dict):
        kind = value.get(_TAG)
        if kind in ('array', 'list'):
            data = base64.b64decode(value['data'], validate=True)
            array = _read_array_packet(data)
            return array.tolist() if kind == 'list' else array
        if kind == 'object_array':
            import numpy as np
            shape = value['shape']
            items = _unpack(value['items'])
            if any(type(d) is not int or d < 0 for d in shape) or math.prod(shape) != len(items):
                raise ValueError('Invalid cached object array shape')
            array = np.empty(shape, dtype=object)
            for i, item in enumerate(items):
                array.flat[i] = item
            return array
        if kind == 'dict':
            return {_unpack(k): _unpack(v) for k, v in value['items']}
        if kind == 'tuple':
            return tuple(_unpack(v) for v in value['items'])
        if kind is not None:
            raise ValueError('Unknown analysis cache encoding')
        for key, item in value.items():
            value[key] = _unpack(item)
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

    File locks coalesce foreground/background work across processes. Atomic compact JSON writes survive interruption, preserve typed arrays and
    tuple-keyed average frames, and never deserialize executable data.
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
        except (OSError, ValueError, KeyError, TypeError, EOFError):
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
        except (OSError, ValueError, KeyError, TypeError, EOFError):
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
            except (OSError, ValueError, KeyError, TypeError, EOFError):
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
                except (OSError, ValueError, TypeError) as error:
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
