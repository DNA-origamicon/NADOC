"""Shared immutable implementation files and single-thread numerical identity.

Only server-owned paths are supplied by feature contracts. Hashing a numerical
runtime admits no geometry and never changes its algorithms or thread policy.
"""

from functools import lru_cache
import hashlib
from importlib import import_module
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys

from backend.core.part_command_errors import CommandContractError


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=128)
def _cached_file_digest(path, signature):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_digest(path, *, error_type=CommandContractError, label="numerical"):
    try:
        stat = path.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        result = _cached_file_digest(str(path), signature)
        after = path.stat()
        if signature != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise error_type(f"{label} engine file changed while being read", code="engine_mismatch")
        return result
    except OSError as error:
        raise error_type(f"A pinned {label} engine file is unavailable", code="engine_unavailable") from error


def numerical_libraries(*, file_digest_fn=file_digest, error_type=CommandContractError, label="numerical"):
    # Import both runtimes before reading pools: SciPy may load a different BLAS.
    for module in ("numpy", "scipy.linalg", "scipy.optimize", "scipy.spatial.transform",
                   "scipy.spatial.distance", "scipy.interpolate"):
        import_module(module)
    from threadpoolctl import threadpool_info

    libraries = []
    for pool in threadpool_info():
        if pool.get("user_api") not in {"blas", "openmp"}:
            continue
        path = Path(pool["filepath"]).resolve()
        if pool.get("num_threads") != 1:
            raise error_type(f"Native {label} execution requires one numerical thread in its worker",
                             code="runtime_mismatch")
        libraries.append({
            **{key: pool.get(key) for key in ("user_api", "internal_api", "prefix", "version",
                                              "threading_layer", "architecture")},
            "sha256": file_digest_fn(path),
        })
    if not any(pool["user_api"] == "blas" for pool in libraries):
        raise error_type(f"The installed numerical runtime is not covered by the {label} engine contract",
                         code="runtime_mismatch")
    return sorted(libraries, key=lambda item: json.dumps(item, sort_keys=True))


def runtime_fingerprint(*, libraries=None, error_type=CommandContractError):
    import numpy as np

    libraries = numerical_libraries(error_type=error_type) if libraries is None else libraries
    features = getattr(np._core._multiarray_umath, "__cpu_features__", None)
    if not isinstance(features, dict):
        raise error_type("Numerical CPU dispatch cannot be identified", code="runtime_mismatch")
    return {
        "python": {"implementation": sys.implementation.name, "version": platform.python_version()},
        "platform": {"system": platform.system(), "machine": platform.machine(),
                     "byteorder": sys.byteorder, "libc": list(platform.libc_ver())},
        "packages": {name: version(name) for name in ("numpy", "scipy", "pydantic", "pydantic-core", "threadpoolctl")},
        "cpu_features": features,
        "numpy_error_policy": np.geterr(),
        "native_threads": 1,
        "libraries": libraries,
    }
