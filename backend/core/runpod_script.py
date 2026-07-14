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

# The relaxation early-stop accelerator is IDENTICAL on a pod and on a cluster node:
# the same stdlib evaluator reads the same NAMD log and the same copy-forward bridge
# fakes up the skipped chunks' checkpoints. Import the emitters rather than copying
# them — the bridge bash is the subtle half (explicit names, never a glob, so `_p50`
# can't sweep `_p100`), and a second copy would drift out of lockstep with the tests
# that pin it.
from backend.core.slurm_script import (
    _DEFAULT_EARLY_STOP_MIN_K,
    _chain_scales,
    _early_stop_block,
    _early_stop_eligible,
    _stage_last_chunk_index,
)

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


# ⚠️ A CARD OUTSIDE THESE ARCHS RENTS FINE AND DIES AT STEP 0:
#
#     FATAL ERROR: CUDA error cudaMemcpyToSymbol(constExclusions, ...) in
#     CudaComputeNonbondedKernel.cu, bindExclusions ... no kernel image is available
#
# Offering a card the binary cannot run is not a fallback, it is a guaranteed BILLING
# failure. So GPU selection MUST be filtered by architecture.
#
# The volume's binary (/workspace/namd/3.0.2p1-cuda-a80/namd3, built 2026-07-14 by
# experiments/exp43_runpod_bench/build_namd_multiarch.py) covers:
#     sm_80   Ampere    (A100)
#     sm_89   Ada       (4090, L4, L40S, RTX 6000 Ada)
#     sm_90   Hopper    (H100, H200)
#     sm_120  Blackwell (RTX PRO 4500/5000/6000, RTX 50-series)
# ...plus a compute_120 PTX fallback. STILL EXCLUDED: sm_86 (A6000/3090) and sm_100 (B200 —
# "Blackwell", but a DATACENTER arch, not sm_120; that is the trap).
#
# ⚠️ **`cuobjdump --list-elf` CANNOT tell you the coverage.** It reports the identical
# sm_50..sm_120 union for the OLD 2-arch binary and this 4-arch one, because it shows
# NAMD's kernels UNIONED with the bundled NVIDIA libs (cuFFT etc.). The old binary was
# PROVEN to fail on an A100 despite cuobjdump listing sm_80. **The only proof is running
# the card** — which costs ~$0.12 and five minutes.
#
# To widen further: rebuild with more `-gencode` arches (build_namd_multiarch.py) and add
# them here.
NAMD_BUILD_ARCHS: tuple[str, ...] = ("sm_80", "sm_89", "sm_90", "sm_120")

# A hard price ceiling. Without one, "fall back to whatever is available" quietly rents an
# H100 to relax a 225k-atom duplex.
DEFAULT_MAX_USD_PER_HOUR = 1.00

# Cheapest-first. Ids verified against RunPod's live gpuTypes list.
#
# NOT offered (the binary cannot run them — they rent fine and die at step 0):
#   RTX A6000 / RTX 3090  sm_86
#   B200                  sm_100   <- reads as "Blackwell" but is NOT sm_120. The trap.
# L4 / L40S are sm_89 and WOULD work; excluded because they are terrible value —
# MEASURED: the L4 does 131.3 ms/step = 2.6 ns/day = $3.56/ns, so 5 ns takes 46 HOURS.
# Cheap per hour, awful per nanosecond AND per day. See [[gpu-value-is-two-axes]].
#
# ⚠️ These are the **SECURE** prices, live-checked against RunPod's `gpuTypes` GraphQL
# on 2026-07-14. They MUST be, because Community cloud is excluded in code (it has no
# card in EU-RO-1, where the network volume pins us — every attempt 500'd). The table
# previously carried the COMMUNITY prices, which are roughly HALF:
#
#     card            community   SECURE (what we actually pay)
#     RTX 4090          0.34        0.69
#     RTX PRO 4500      0.34        0.74
#     RTX 6000 Ada      0.74        0.77
#     RTX PRO 5000      0.82        0.96
#
# Costing a secure-only run off community prices under-reports it by ~2.2x, which is how
# a "$5" overnight ladder quietly becomes an $11 one. `plan_execution` and
# `POST /runpod/estimate` both read these numbers, so they were both lying.
#
# ORDER = FALLBACK PRIORITY, and it stays STRICTLY CHEAPEST-FIRST (pinned by
# test_gpu_table_is_strictly_cheapest_first). RunPod takes `gpuTypeIds` as a list and
# rents the first one available, so the cheap-but-scarce card costs NOTHING to ask for:
# if the 4090 (chronically "Low" stock in EU-RO-1) isn't free, RunPod simply falls
# through to the PRO 4500 and we pay $0.05/hr more. Asking cheapest-first is therefore
# strictly better than pre-emptively conceding the nickel.
#
# The PRO 4500 used to head this list because at the COMMUNITY price the two TIED at
# $0.34 — and at equal cost its 32 GB and HIGH stock made it the obvious tiebreak. The
# real prices break that tie, so the ordering reverts to the invariant.
GPU_TYPES: tuple[GpuType, ...] = (
    GpuType("NVIDIA GeForce RTX 4090", "RTX 4090", 24_564, 0.69, "sm_89"),
    GpuType("NVIDIA RTX PRO 4500 Blackwell", "RTX PRO 4500", 32_623, 0.74, "sm_120"),
    GpuType("NVIDIA RTX 6000 Ada Generation", "RTX 6000 Ada", 49_140, 0.77, "sm_89"),
    GpuType("NVIDIA RTX PRO 5000 Blackwell", "RTX PRO 5000", 49_152, 0.96, "sm_120"),
    # Ampere + the big Blackwell, unlocked by the sm_80/89/90/120 rebuild (2026-07-14).
    # MEASURED $/ns on the real 1.94M-atom system — compute does NOT scale with cost:
    #   RTX PRO 4500  $0.74  37.2 ms/step   9.3 ns/day  $1.91/ns
    #   RTX PRO 6000  $1.99  18.5 ms/step  18.6 ns/day  $2.56/ns   (2.7x price -> 2.0x speed)
    # The premium buys WALL-CLOCK, not throughput-per-dollar.
    GpuType("NVIDIA A100 80GB PCIe", "A100 PCIe", 81_920, 1.39, "sm_80"),
    GpuType("NVIDIA RTX PRO 6000 Blackwell Server Edition",
            "RTX PRO 6000", 97_887, 1.99, "sm_120"),
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

    ``GPU_TYPES`` is strictly price-ordered, so "cheapest that fits" == "first that fits".
    This is the SIZING/COSTING answer; the pod payload offers the whole tail of the list
    as fallbacks, so an unavailable cheap card degrades to the next one rather than
    failing.

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


# The spend this test is allowed to cost, in dollars. It is a BUDGET, not a duration:
# the same $15 buys 44 h on a $0.34/hr card and 6 h on a $2.39/hr one, so the wall-clock
# cap has to be derived from the rate of the pod actually rented, never hardcoded.
DEFAULT_BUDGET_USD = 15.0

# Never emit a guard shorter than this. A bogus/zero rate must not render a script that
# kills the ladder seconds after it starts.
MIN_LIFETIME_S = 900


def lifetime_for_budget(
    budget_usd: float = DEFAULT_BUDGET_USD,
    cost_per_hr: Optional[float] = None,
) -> int:
    """Seconds a pod may live before the kill-switch fires, given a dollar budget.

    ``cost_per_hr`` is the rate RunPod reports for the pod we actually got. When it is
    missing or nonsense, fall back to ``DEFAULT_MAX_USD_PER_HOUR`` — the price ceiling
    the pod was rented under, so it is the worst case it CAN be billing. Guessing high
    yields a SHORTER lifetime, which is the safe direction to be wrong in.
    """
    rate = cost_per_hr if (cost_per_hr and cost_per_hr > 0) else DEFAULT_MAX_USD_PER_HOUR
    return max(MIN_LIFETIME_S, int(budget_usd / rate * 3600))


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
    # Total steps in this segment. Needed ONLY to resume it after a cell-shrink restart:
    # the resume conf must run `total - restart_step`, not the original `run`.
    steps: int = 0


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

# The pod-side resume-conf writer (backend/core/remote_resume_conf.py, staged under this
# name). Without it a cell-shrink retry re-runs the ORIGINAL conf, restarts from the
# ORIGINAL box, and shrinks into the same wall — so "bounded retry" means "fails four
# times", not "self-heals".
RESUME_CONF_NAME = "nadoc_resume_conf.py"
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
    manifest: Optional[dict] = None,
    early_stop_relax: bool = False,
    early_stop_tier: str = "B",
    early_stop_min_k: Optional[float] = None,
    name_stem: str = "",
    health_python: str = "python3",
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

    * **Relaxation early-stop** (``early_stop_relax``) — the on-pod analogue of the
      in-sbatch accelerator, and on RunPod it is a BUDGET feature, not a nicety. The
      full 3x6x400 ladder is 9.6M steps ~= 55.7 h ~= $41 on a secure PRO 4500. It does
      not fit in a night or in a budget. With the accelerator it is ~11 h.

      After each non-final relaxation chunk, the pod evaluates whether the stage has
      plateaued and, if so, **bridges**: it copies that chunk's final ``{coor,vel,xsc}``
      onto every remaining chunk's expected names. The bridge needs no new skip logic —
      ``run_step``'s existing "``output/<name>.coor`` exists => SKIP" guard then walks
      straight past them, and the next stage's ``previous`` (which points at ``_p100``)
      finds the bridged file. The idempotent-resume trick and the early-stop trick are
      the same trick.

      **Tier matters, and Tier B cannot pay for this run.** Tier B (stdlib, energy+volume
      plateau) may only skip stages restrained at ENM ``k >= min_k`` (0.1), because below
      that base-pairing keeps degrading after the energy flattens — so k=0.01 and the
      k=0/MGHH melt always run in FULL. That caps Tier B at 5.28M steps (~$22.7): over
      budget even in its best case. Tier A adds the WC base-pairing series (an on-pod
      MDAnalysis health step), which holds the fragile stages directly and therefore makes
      EVERY relaxation chunk eligible — that is where exp36's measured 4.9x comes from.

      Tier A **fails safe to HOLD**: no ``wc.json`` (MDAnalysis missing, health step
      failed, no frames yet) => no skip => the full ladder runs. Safe for the science,
      *expensive* on a rented pod — so confirm MDAnalysis imports on the pod before
      trusting Tier A to bring a run inside budget.
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
        "  local name=$1 conf=$2 attempt=${3:-0} total=${4:-0}",
        "  if [ -f \"output/${name}.coor\" ]; then",
        '    echo "SKIP  $name (already complete)"',
        "    return 0",
        "  fi",
        "",
        "  # Resume from the segment's OWN restart files whenever they exist. TWO cases:",
        "  #",
        "  #  1. A cell-shrink RETRY. The restart files carry the SHRUNKEN cell. Re-running",
        "  #     the original conf restarts from the ORIGINAL box (its extendedSystem points",
        "  #     at the previous segment), so NAMD rebuilds the SAME patch grid, the box",
        "  #     shrinks into the SAME wall, and every retry fails identically. Measured:",
        "  #     156.6 x 89.1 x 1436.2 -> 152.0 x 86.5 x 1393.4, a uniform -3.0%.",
        "  #",
        "  #  2. A POD THAT DIED MID-SEGMENT (reclaim, host failure, an over-broad reap).",
        "  #     The idempotent skip-guard only works at SEGMENT granularity — it skips",
        "  #     steps whose .coor exists. An INCOMPLETE segment has no .coor, so without",
        "  #     this it restarts FROM ZERO. On an 800k-step production segment that threw",
        "  #     away five hours of compute. 'A reclaimed pod resumes, it does not restart'",
        "  #     was only ever true BETWEEN segments; this makes it true WITHIN one.",
        '  local runconf="$conf"',
        '  if [ -f "output/${name}.restart.xsc" ] && [ "$total" -gt 0 ]; then',
        f"    if python3 {RESUME_CONF_NAME} --seg \"$name\" --total-steps \"$total\"; then",
        '      runconf="${name}.resume.conf"',
        '      echo "RESUME $name from its own checkpoint (attempt $attempt)"',
        "    else",
        '      echo "RESUME $name FAILED to build — falling back to the original conf"',
        "    fi",
        "  fi",
        "",
        '  echo "START $name"; echo "$name" > nadoc_current',
        f"  {q(namd_bin)} +p{int(threads)} +setcpuaffinity +devices {q(devices)} "
        '"$runconf" > "${name}.log" 2>&1 &',
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
        "  local name=$1 conf=$2 total=${3:-0} attempt=0",
        f"  while [ $attempt -le {int(MAX_CELL_SHRINK_RETRIES)} ]; do",
        '    run_step "$name" "$conf" "$attempt" "$total"',
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

    tier = (early_stop_tier or "B").upper()
    if early_stop_relax and tier not in ("A", "B"):
        raise ValueError(f"early_stop_tier {tier!r} must be 'A' or 'B'")
    min_k = _DEFAULT_EARLY_STOP_MIN_K if early_stop_min_k is None else float(early_stop_min_k)

    chain = [s.name for s in steps]
    # Scales come from the manifest, positionally aligned to the chain (chain[0] is the
    # minimisation -> None). No manifest => no scales => nothing is eligible, which is
    # the fail-safe direction: run everything.
    scales = _chain_scales(manifest, chain) if (early_stop_relax and manifest) else []

    for i, step in enumerate(steps):
        kind = "minimization" if step.is_minimization else "segment"
        lines.append(f"# {kind}: {step.name}")
        lines.append(
            f'run_step_with_retries {q(step.name)} {q(step.name + ".conf")} '
            f"{int(step.steps)} || exit 1"
        )
        if scales and _early_stop_eligible(chain, scales, i, min_k, tier):
            last = _stage_last_chunk_index(chain, i)
            lines += _early_stop_block(
                step.name, chain[i + 1 : last + 1],
                tier=tier, name_stem=name_stem, health_python=health_python,
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
