"""Local-machine hardware enumeration for the simulation Benchmark feature.

The Dynamics-panel "Benchmark" button sweeps oxDNA/NAMD over the CPU thread counts
and CUDA devices this machine actually has, then stores the fastest config in the
design (keyed by hostname).  This module answers "what hardware is here?".

Kept tiny and side-effect-light: the only impurity is one ``nvidia-smi -L`` call,
and the parse of its output is split into a pure function so it is unit-testable
without a GPU.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess

# "GPU 0: NVIDIA RTX A5000 (UUID: GPU-1d2c3b4a-...)"
_RE_NVIDIA_SMI_L = re.compile(
    r"^GPU (?P<index>\d+):\s*(?P<name>.+?)\s*\(UUID:\s*(?P<uuid>GPU-[0-9a-fA-F-]+)\)"
)


def parse_nvidia_smi_l(text: str) -> list[dict]:
    """Parse ``nvidia-smi -L`` output into ``[{"index", "name", "uuid"}, ...]``.

    PURE — given the captured text, returns the device list.  Lines that don't
    match the expected shape are skipped, so partial/garbage output degrades to
    fewer (or zero) devices rather than raising.
    """
    devices: list[dict] = []
    for line in text.splitlines():
        m = _RE_NVIDIA_SMI_L.match(line.strip())
        if m:
            devices.append(
                {
                    "index": int(m.group("index")),
                    "name": m.group("name").strip(),
                    "uuid": m.group("uuid"),
                }
            )
    return devices


def enumerate_cuda_devices() -> list[dict]:
    """Return the CUDA devices visible to this machine, or ``[]`` if none / no driver.

    Absent ``nvidia-smi`` (no NVIDIA driver) → ``[]`` → the benchmark simply runs a
    CPU-only sweep.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "-L"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return parse_nvidia_smi_l(out.stdout)


def cpu_thread_ladder() -> list[int]:
    """A small, ascending, de-duplicated ladder of ``+p`` thread counts to sweep.

    ``{n//4, n//2, n}`` (min 1) where ``n`` is the logical CPU count.  Gives the
    NAMD benchmark a coarse scaling curve (low / medium / all cores) without an
    exhaustive per-value sweep.
    """
    n = os.cpu_count() or 2
    candidates = {max(1, n // 4), max(1, n // 2), max(1, n)}
    return sorted(candidates)


def cpu_count() -> int:
    return os.cpu_count() or 2


def hostname() -> str:
    """The key under which this machine's benchmark result is stored in the design."""
    return socket.gethostname()
