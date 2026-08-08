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


# ── heavy-simulation detection (resource guard) ────────────────────────────────
# Is a NAMD / oxDNA / mrDNA(ARBD) / GROMACS job already chewing this machine's
# GPU/CPU?  Used by the test suite (tests/conftest.py) to SKIP its own heavy tests
# rather than pile on and time out.  Kept here because it's the resource-detection
# module, and the app could reuse it (e.g. warn before launching another job).

# comm (process name) substrings for the local simulation engines.  namd3/namd2
# → "namd"; the oxDNA binary → "oxDNA"; mrDNA runs via the ARBD engine → "arbd";
# GROMACS → "gmx".  Matched against process NAMES (not full cmdlines), so a test
# file path merely containing "oxdna" never trips it.
#
# CASE-INSENSITIVELY (`pgrep -i`) — this is load-bearing, do not drop the -i.  A running
# NAMD renames its comm to "NAMD masterPe" (capitals, with a space), so the case-sensitive
# match silently NEVER fired for NAMD: heavy tests happily ran alongside a live production
# job and then failed on GPU/pinned-host contention (cudaHostAlloc in reallocate_host_T),
# which reads like a code bug but is just the guard not working.  Match comm, not cmdline:
# `pgrep -f` would match the pytest process itself (its argv contains "namd").
_SIM_PROC_PATTERN = "namd|oxDNA|arbd|gmx"
_RE_PGREP_L = re.compile(r"^\s*\d+\s+(\S+)")  # "1234 namd3" → name


def parse_pgrep_l(text: str) -> list[str]:
    """PURE.  Parse ``pgrep -l`` output ('pid name' lines) → sorted unique names."""
    names: set[str] = set()
    for line in text.splitlines():
        m = _RE_PGREP_L.match(line)
        if m:
            names.add(m.group(1))
    return sorted(names)


def parse_gpu_utilization(text: str) -> list[int]:
    """PURE.  Parse ``--query-gpu=utilization.gpu`` CSV (one % per GPU) → ints."""
    vals: list[int] = []
    for line in text.splitlines():
        s = line.strip().rstrip("%").strip()
        if s.isdigit():
            vals.append(int(s))
    return vals


def assess_heavy_sim(
    sim_procs: list[str], gpu_utils: list[int], gpu_threshold: int = 85
) -> tuple[bool, str]:
    """PURE.  Decide from the two signals whether a heavy sim is running.

    Process-name match is authoritative.  GPU utilization is a high-threshold
    backstop for oxpy-in-python CUDA runs that have no distinct binary name (the
    threshold is deliberately high so an idle desktop GPU / remote-desktop process
    never trips it)."""
    if sim_procs:
        return True, f"simulation process(es) running: {', '.join(sim_procs)}"
    busy = [u for u in gpu_utils if u >= gpu_threshold]
    if busy:
        return (
            True,
            f"GPU utilization {max(busy)}% >= {gpu_threshold}% (likely a GPU sim)",
        )
    return False, ""


def _capture(cmd: list[str]) -> str | None:
    """Run ``cmd`` and return stdout, or None on any failure (missing binary,
    timeout, non-zero exit is tolerated — callers treat None as 'no signal')."""
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def heavy_sim_running(gpu_threshold: int = 85) -> tuple[bool, str]:
    """Is a NAMD/oxDNA/mrDNA(ARBD)/GROMACS job running on THIS machine right now?

    Returns ``(running, reason)``.  FAIL-OPEN: any detection error degrades to
    ``(False, "")`` so a probe glitch never spuriously reports a sim and masks
    test results.  ``pgrep`` exit 1 (no match) yields empty output → not running.
    """
    # -r DRST: only LIVE run-states (running/sleeping/stopped) — never Z (zombie).  The
    # test suite leaves `[arbd] <defunct>` children behind; a plain pgrep matches those
    # and the guard then reports a "running sim" forever, silently skipping every heavy
    # test on an idle machine.  A defunct process is not a running simulation.
    pgrep_out = _capture(["pgrep", "-r", "DRST", "-il", _SIM_PROC_PATTERN])
    sim_procs = parse_pgrep_l(pgrep_out) if pgrep_out else []
    gpu_out = _capture(
        ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"]
    )
    gpu_utils = parse_gpu_utilization(gpu_out) if gpu_out else []
    return assess_heavy_sim(sim_procs, gpu_utils, gpu_threshold)


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
