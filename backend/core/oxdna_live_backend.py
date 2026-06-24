"""Backend selection for in-process oxpy LIVE sessions (CPU vs CUDA).

The CUDA-built oxpy is a *superset*: one library runs ``backend = CPU`` and
``backend = CUDA``, chosen per run by the input file (see
``memory/project_oxpy_binding_patch.md``).  Stage-2 benchmarks show CUDA wins at
every practical design size on a discrete GPU (oxDNA's CPU backend is
single-threaded), so a live session **prefers CUDA whenever a usable GPU is
present** and uses CPU otherwise.

Two distinct fallbacks, by design:

* **No GPU on this machine** → :func:`preferred_backend` returns ``"CPU"`` up
  front.  The GPU-presence probe (``nvidia-smi`` via :func:`engines.gpu_info`) is
  machine-level and cached for the process — it does not change mid-session.
* **GPU present but this design won't fit (out of memory) / CUDA init fails** →
  handled per-session at engine-open time by the stepper, which retries on CPU and
  flags the fallback so the UI can alert the user.  This is design-specific, so it
  is NOT cached as "no GPU".
"""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_gpu_present: bool | None = None   # tri-state: None = not yet probed


def _default_probe() -> bool:
    from backend.core.engines import gpu_info

    return bool(gpu_info().get("present"))


def gpu_present(*, probe=None) -> bool:
    """Whether this machine has a usable CUDA GPU (cached for the process).

    ``probe`` is an injection seam for tests (a zero-arg ``() -> bool``); in
    production it defaults to the ``nvidia-smi``-backed :func:`engines.gpu_info`.
    The first call probes and caches; later calls return the cached value.
    """
    global _gpu_present
    with _LOCK:
        if _gpu_present is None:
            _gpu_present = bool((probe or _default_probe)())
        return _gpu_present


def preferred_backend(*, probe=None) -> str:
    """``"CUDA"`` when a GPU is present, else ``"CPU"`` — the backend a new live
    session is staged with (a per-design GPU OOM still falls back to CPU later)."""
    return "CUDA" if gpu_present(probe=probe) else "CPU"


def reset_cache() -> None:
    """Forget the cached GPU probe (tests; or after a hardware/driver change)."""
    global _gpu_present
    with _LOCK:
        _gpu_present = None
