"""Pure logic for running a NADOC NAMD segment chain on a RunPod GPU pod.

No network, no SSH, no filesystem — everything here is a pure function so the
tricky parts (idempotent resume, stall detection, GPU sizing) are unit-testable
without renting a GPU.

Companion to :mod:`backend.core.slurm_script` (the Alpine/SLURM equivalent). The
two differ in one fundamental way:

    Alpine  = a SCHEDULER. You `sbatch` a job and poll `squeue`.
    RunPod  = a MACHINE.  You rent it, run a script, and destroy it.

So instead of `#SBATCH` directives we emit a plain bash script and track a PID.
The whole segment ladder runs as ONE script on the pod (the same decision as
Alpine's single-sbatch: re-queuing per segment would stack latency), and the pod
is destroyed when it finishes.

Everything in here is calibrated against real measurements taken on a rented
RTX 4090 (32 vCPU / 16 physical cores / 131 GB RAM, NAMD 3.0.2p1, 2026-07-13):

    system            atoms     offload VRAM   resident VRAM   resident speedup
    6hb_sim_v2        225,504      854 MB         1,114 MB          3.3x
    flat_1x50       1,442,735    3,496 MB         5,016 MB          4.1x
    VoltronCore     5,656,632   12,334 MB        17,678 MB             —

The resident fit predicted 18,571 MB for VoltronCore and it measured 17,678 —
5% conservative, which is the right direction to be wrong in when sizing a card.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional, Sequence

# ── VRAM model ───────────────────────────────────────────────────────────────
# Linear fits to the three measured points above. Both are ~0.4 GB fixed overhead
# plus a per-atom slope; the offload fit reproduces all three within ~3%.
VRAM_MB_PER_MATOM_OFFLOAD = 2100.0
VRAM_MB_PER_MATOM_RESIDENT = 3212.0
VRAM_MB_FIXED = 400.0

# Leave headroom: the CUDA context, the display (if any), and NAMD's transient
# peaks during patch-grid setup all sit on top of the steady-state figure.
VRAM_SAFETY_FRACTION = 0.85


@dataclass(frozen=True)
class GpuType:
    """A RunPod GPU offering. `key` is RunPod's own id string."""

    key: str
    label: str
    vram_mb: int
    usd_per_hour: float  # indicative; RunPod's real price varies by tier + region
    sm: str  # CUDA compute capability, e.g. "sm_89"


# ⚠️ THE BINARY IS SINGLE-ARCH. `tools/namd_tilelist_fix/build_patched_namd.sh` compiles
# for ONE `sm_XX` ("restricting codegen to $SM — single arch: ~4x faster nvcc pass"), and
# the build on the network volume is **sm_89**. Running it on any other architecture dies
# instantly with:
#
#     FATAL ERROR: CUDA error cudaMemcpyToSymbol(constExclusions, ...) in
#     CudaComputeNonbondedKernel.cu, bindExclusions ... no kernel image is available
#
# This is EXACTLY the failure that wasted the first pod launch (an A100 = sm_80), and the
# same one that made the local sm_75 binary useless on the 4090. So GPU selection MUST be
# filtered by architecture — offering a card the binary cannot run on is not a fallback,
# it is a guaranteed, billing failure.
#
# To widen this list: rebuild NAMD with more `-gencode` arches and add them here.
NAMD_BUILD_ARCHS: tuple[str, ...] = ("sm_89",)

# A hard price ceiling. Without one, "fall back to whatever is available" quietly rents an
# H100 to relax a 225k-atom duplex.
DEFAULT_MAX_USD_PER_HOUR = 1.00

# Cheapest-first. Ids verified against RunPod's live gpuTypes list.
#
# Deliberately only TWO cards (user decision, 2026-07-13): both are sm_89 (so the patched
# binary runs), both are proven, and the pair covers the whole VRAM range we need —
# 24 GB holds everything up to VoltronCore's 5.66M atoms GPU-resident (17.7 GB measured),
# and the 48 GB card is the headroom.
#
# NOT offered while the binary is sm_89-only — these rent successfully and then die at
# step 0 with "no kernel image is available":
#   RTX A6000 / RTX 3090  sm_86
#   A100 80GB             sm_80
#   H100 80GB             sm_90
# L4 / L40S are sm_89 and WOULD work; excluded by choice, not by capability.
GPU_TYPES: tuple[GpuType, ...] = (
    GpuType("NVIDIA GeForce RTX 4090", "RTX 4090", 24_564, 0.34, "sm_89"),
    GpuType("NVIDIA RTX 6000 Ada Generation", "RTX 6000 Ada", 49_140, 0.74, "sm_89"),
)


def required_vram_mb(n_atoms: int, *, gpu_resident: bool) -> float:
    """Steady-state VRAM for an ``n_atoms`` system, from the measured fits."""
    matoms = n_atoms / 1_000_000.0
    slope = VRAM_MB_PER_MATOM_RESIDENT if gpu_resident else VRAM_MB_PER_MATOM_OFFLOAD
    return VRAM_MB_FIXED + slope * matoms


def fits_on(gpu: GpuType, n_atoms: int, *, gpu_resident: bool) -> bool:
    return required_vram_mb(n_atoms, gpu_resident=gpu_resident) <= (
        gpu.vram_mb * VRAM_SAFETY_FRACTION
    )


def recommend_gpu(
    n_atoms: int,
    *,
    gpu_resident: bool = True,
    candidates: Sequence[GpuType] = GPU_TYPES,
) -> Optional[GpuType]:
    """Cheapest GPU that can hold this system, or None if nothing fits.

    GPU-resident is worth 3.3-4.1x, so it is the DEFAULT and we size for it. If the
    system is too big to be resident anywhere affordable, the caller should retry
    with ``gpu_resident=False`` — a bigger system in offload mode on a small card
    still beats not running.
    """
    for gpu in candidates:
        if fits_on(gpu, n_atoms, gpu_resident=gpu_resident):
            return gpu
    return None


def recommend_gpus(
    n_atoms: int,
    *,
    gpu_resident: bool = True,
    candidates: Sequence[GpuType] = GPU_TYPES,
    archs: Sequence[str] = NAMD_BUILD_ARCHS,
    max_usd_per_hour: float = DEFAULT_MAX_USD_PER_HOUR,
) -> list[GpuType]:
    """Every GPU that can RUN this job, cheapest first.

    Three filters, and dropping any one of them has already cost real money:

    * **VRAM** — from the measured model.
    * **Architecture** — the NAMD build on the volume is single-arch (sm_89). A card of
      any other arch rents successfully and then dies at step 0 with "no kernel image is
      available". An A100 fallback did exactly this.
    * **Price ceiling** — otherwise "whatever is available" rents an H100 for a duplex.

    The result is handed to RunPod as ``gpuTypeIds``, which is a PRIORITY LIST: a network
    volume pins the pod to its datacenter (ours: EU-RO-1) and a single named card is
    regularly unavailable there (``500 "There are no instances currently available"``), so
    offering several turns a hard failure into a success.
    """
    return [
        g
        for g in candidates
        if fits_on(g, n_atoms, gpu_resident=gpu_resident)
        and g.sm in archs
        and g.usd_per_hour <= max_usd_per_hour
    ]


def plan_execution(n_atoms: int) -> dict:
    """Decide GPU + execution mode for a system. The whole sizing policy, one call.

    ``gpu`` is the preferred (cheapest) card; ``gpus`` is the full fallback list to hand
    to RunPod as a priority order.
    """
    gpus = recommend_gpus(n_atoms, gpu_resident=True)
    if gpus:
        return {
            "gpu": gpus[0],
            "gpus": gpus,
            "gpu_resident": True,
            "reason": f"fits GPU-resident on {gpus[0].label} (3-4x faster than offload)",
        }
    gpus = recommend_gpus(n_atoms, gpu_resident=False)
    if gpus:
        return {
            "gpu": gpus[0],
            "gpus": gpus,
            "gpu_resident": False,
            "reason": (
                f"too large for GPU-resident anywhere; {gpus[0].label} in CUDA offload mode"
            ),
        }
    biggest = max((g.vram_mb for g in GPU_TYPES), default=0)
    return {
        "gpu": None,
        "gpus": [],
        "gpu_resident": False,
        "reason": (
            f"{n_atoms:,} atoms needs "
            f"{required_vram_mb(n_atoms, gpu_resident=False) / 1024:.1f} GB; the largest "
            f"GPU offered has {biggest / 1024:.0f} GB. Carve the water shell or use GBIS."
        ),
    }


# NAMD stops scaling long before it runs out of cores when there is ONE GPU: past this
# many PEs the extra threads add synchronisation cost and nothing else. Measured on the
# 4090 pod: +p8 42.98, +p16 41.38, +p32 18.85 ns/day. A 128-vCPU machine would otherwise
# get +p64, which is far off the end of that curve.
MAX_NAMD_THREADS = 16


def namd_threads(vcpus: int, *, smt: bool = True, cap: int = MAX_NAMD_THREADS) -> int:
    """NAMD ``+p``: one PE per PHYSICAL core, capped.

    MEASURED, do not "optimise" upward: on a 32-vCPU / 16-physical-core pod, ``+p32`` ran
    at 18.85 ns/day against ``+p16``'s 41.38 — oversubscribing the hyperthreads HALVED
    throughput. RunPod advertises vCPUs (SMT threads), so halve. And cap: a big host
    (128 vCPU) would otherwise get +p64, well past where a single-GPU NAMD scales.
    """
    return max(1, min(vcpus // 2 if smt else vcpus, cap))


# ── Chain script ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChainStep:
    """One NAMD invocation in the ladder (the minimisation, or one segment)."""

    name: str  # conf/output stem, e.g. "6hb_01_300K_NPT_ENM_k0p5_p10"
    is_minimization: bool = False


STALL_TIMEOUT_S = 1800  # 30 min with no new ENERGY frame => the run is wedged

# An NPT box relaxing to equilibrium density shrinks ~3% linearly. NAMD fixes the
# patch grid at startup with only a tiny margin, so the shrink crosses the floor and
# NAMD exits: "Periodic cell has become too small for original patch grid!". This is
# NOT a blow-up (T/P/energy stay healthy) and it is SELF-HEALING: restarting from the
# checkpoint rebuilds the grid at the smaller box. It hit BOTH offload VoltronCore
# cells on the 4090. The local runner already auto-resumes it (MAX_CELL_SHRINK_RESUMES);
# a pod that treats it as fatal would burn a 25-minute minimisation for nothing.
# DO NOT "fix" this with a `margin` keyword — that crashes NAMD's GPU tile-list
# kernel on a carved box (see project_water_shell_carve).
CELL_SHRINK_PATTERN = "Periodic cell has become too small"
MAX_CELL_SHRINK_RETRIES = 4
WATCHDOG_POLL_S = 30    # how often the watchdog checks the log mtime + heartbeat


def render_chain_script(
    *,
    steps: Sequence[ChainStep],
    remote_dir: str,
    namd_bin: str,
    threads: int,
    devices: str = "0",
    stall_timeout_s: int = STALL_TIMEOUT_S,
    max_lifetime_s: Optional[int] = None,
    watchdog_poll_s: int = WATCHDOG_POLL_S,
) -> str:
    """Emit the bash script that runs the whole ladder on the pod.

    Properties that matter, each learned the hard way:

    * **Idempotent.** A step whose ``output/<name>.coor`` already exists is skipped.
      This is what makes resume-after-interruption work on a spot pod (and it is the
      same trick Alpine's sbatch uses for completed segments).

    * **Stall detection.** A NAMD minimisation on a degenerate structure NEVER exits
      — its line minimiser sits on NaN forever. One such run ate 32 threads for an
      hour before anyone noticed. We watch the log's mtime and kill the step if it
      goes quiet for ``stall_timeout_s``. Without this a wedged job bills until the
      account is empty.

    * **Never `pgrep namd3`.** NAMD renames its process to "NAMD masterPe", so
      matching by process NAME silently finds nothing and reports a running job as
      dead. We track the PID we spawned, and nothing else.

    * **A heartbeat file** so the poller can distinguish "still working" from
      "silently dead" without an SSH round-trip per segment.
    """
    q = shlex.quote
    lines: list[str] = [
        "#!/bin/bash",
        "# Generated by NADOC (backend/core/runpod_script.py). Do not edit on the pod.",
        "set -uo pipefail",  # NOT -e: a failed step must still write status + exit cleanly
        "",
        f"cd {q(remote_dir)} || exit 90",
        "mkdir -p output",
        'echo "running" > nadoc_status',
        'date +%s > nadoc_heartbeat',
        "",
    ]

    if max_lifetime_s:
        lines += [
            "# Hard kill-switch: a pod that outlives this is a billing accident.",
            f"( sleep {int(max_lifetime_s)}; echo lifetime > nadoc_status; "
            "pkill -9 -P $$ ; ) & LIFETIME_GUARD=$!",
            "",
        ]

    lines += [
        "run_step() {",
        "  local name=$1 conf=$2 attempt=${3:-0}",
        "  if [ -f \"output/${name}.coor\" ]; then",
        '    echo "SKIP  $name (already complete)"',
        "    return 0",
        "  fi",
        '  echo "START $name"; echo "$name" > nadoc_current',
        f"  {q(namd_bin)} +p{int(threads)} +setcpuaffinity +devices {q(devices)} "
        '"$conf" > "${name}.log" 2>&1 &',
        "  local pid=$!",
        "",
        "  # Watchdog: the ONLY reliable handle on NAMD is the pid we just spawned.",
        "  ( while kill -0 $pid 2>/dev/null; do",
        "      date +%s > nadoc_heartbeat",
        '      local now=$(date +%s)',
        '      local mtime=$(stat -c %Y "${name}.log" 2>/dev/null || echo $now)',
        f"      if [ $((now - mtime)) -gt {int(stall_timeout_s)} ]; then",
        '        echo "STALL $name — no log output; killing" >> nadoc_stall',
        "        kill -9 $pid 2>/dev/null",
        "        break",
        "      fi",
        f"      sleep {int(watchdog_poll_s)}",
        # >/dev/null is LOAD-BEARING, not tidiness: the watchdog subshell inherits the
        # script's stdout pipe, and its orphaned `sleep` keeps that pipe OPEN after NAMD
        # exits — so whoever reads the script's output blocks for a full poll interval
        # per step, and the job looks hung. Detach its stdio; it reports via files.
        "    done ) >/dev/null 2>&1 & local watchdog=$!",
        "",
        "  wait $pid; local rc=$?",
        "  kill $watchdog 2>/dev/null",
        "  wait $watchdog 2>/dev/null",
        "",
        "  if [ $rc -ne 0 ] || [ ! -f \"output/${name}.coor\" ]; then",
        "    # An NPT cell shrinking past its patch grid is SELF-HEALING: restart from",
        "    # the checkpoint and NAMD rebuilds the grid at the smaller box. Treating it",
        "    # as fatal would throw away a 25-minute minimisation. Bounded, so a genuinely",
        "    # broken run still terminates.",
        f'    if grep -q {q(CELL_SHRINK_PATTERN)} "${{name}}.log" 2>/dev/null '
        f"&& [ $attempt -lt {int(MAX_CELL_SHRINK_RETRIES)} ]; then",
        '      echo "SHRINK $name — cell outgrew the patch grid; restarting from checkpoint"',
        "      return 75",
        "    fi",
        '    echo "FAIL  $name (rc=$rc)"',
        '    echo "failed:$name" > nadoc_status',
        "    return 1",
        "  fi",
        '  echo "DONE  $name"',
        "  return 0",
        "}",
        "",
        "run_step_with_retries() {",
        "  local name=$1 conf=$2 attempt=0",
        f"  while [ $attempt -le {int(MAX_CELL_SHRINK_RETRIES)} ]; do",
        "    run_step \"$name\" \"$conf\" \"$attempt\"",
        "    local rc=$?",
        "    [ $rc -eq 0 ] && return 0",
        "    [ $rc -ne 75 ] && return 1",
        "    attempt=$((attempt + 1))",
        "  done",
        '  echo "failed:$name" > nadoc_status',
        "  return 1",
        "}",
        "",
    ]

    for step in steps:
        kind = "minimization" if step.is_minimization else "segment"
        lines.append(f"# {kind}: {step.name}")
        lines.append(
            f'run_step_with_retries {q(step.name)} {q(step.name + ".conf")} || exit 1'
        )

    lines += [
        "",
        'echo "completed" > nadoc_status',
        "date +%s > nadoc_heartbeat",
        "exit 0",
    ]
    return "\n".join(lines) + "\n"


# ── Status parsing (what the poller reads back) ───────────────────────────────


def parse_status_file(text: str) -> dict:
    """Parse the pod's ``nadoc_status`` sentinel.

    ``running`` | ``completed`` | ``failed:<segment>`` | ``lifetime``
    """
    s = (text or "").strip()
    if s.startswith("failed:"):
        return {"state": "failed", "segment": s.split(":", 1)[1] or None}
    if s in {"running", "completed", "lifetime"}:
        return {"state": s, "segment": None}
    return {"state": "unknown", "segment": None}


def heartbeat_is_stale(heartbeat_epoch: Optional[int], now_epoch: int,
                       *, tolerance_s: int = 300) -> bool:
    """True when the pod stopped writing its heartbeat — the run is dead or the pod
    was reclaimed (which, on an interruptible pod, is a NORMAL event: resume it)."""
    if heartbeat_epoch is None:
        return True
    return (now_epoch - heartbeat_epoch) > tolerance_s


def completed_steps(listing: str) -> set[str]:
    """Names of steps already finished, from an ``ls output/*.coor`` listing.

    This is how resume decides what to skip — and it is deliberately the SAME
    mechanism the Alpine executor uses (``poll_remote_progress``), so both remote
    backends agree on what "done" means.
    """
    done: set[str] = set()
    for raw in (listing or "").splitlines():
        name = raw.strip().rsplit("/", 1)[-1]
        if name.endswith(".coor"):
            done.add(name[: -len(".coor")])
    return done


def next_step(steps: Sequence[ChainStep], done: set[str]) -> Optional[ChainStep]:
    """First step not yet complete, or None when the whole ladder is done."""
    for step in steps:
        if step.name not in done:
            return step
    return None
