"""Pure logic for the simulation Benchmark feature (no I/O, no subprocesses).

The Benchmark button auto-tunes oxDNA/NAMD hardware settings for the current
machine: it builds a synthetic system sized like the open design, runs a short
trial on each candidate config, and keeps the fastest.  This module owns the
*decision* parts — which configs to try, how big the synthetic system should be,
and which trial won — so they can be unit-tested without a GPU or a binary.

The runner that actually launches simulations lives in ``benchmark_runner.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Synthetic-system size caps ───────────────────────────────────────────────────
# oxDNA (coarse-grained, one bead/nucleotide) scales to large systems cheaply, so
# its cap is generous.  NAMD is all-atom + explicit solvent: solvating a system
# matched to a big origami would take many minutes and a huge water box, so its
# cap is small.  A capped proxy still preserves the *relative* ranking of configs
# (GPU-vs-CPU, thread scaling) — only the absolute throughput differs — and the
# realized proxy size is always recorded so the stored default stays auditable.
OXDNA_MAX_NT: int = 50_000
NAMD_MAX_NT: int = 4_000

# 6-helix honeycomb bundle ring (matches tests/conftest SIX_HB_CELLS) — a compact,
# fully-paired building block we scale by length to hit a target nucleotide count.
SIX_HB_CELLS: tuple[tuple[int, int], ...] = (
    (0, 0),
    (0, 1),
    (1, 0),
    (1, 1),
    (2, 0),
    (2, 1),
)


@dataclass(frozen=True)
class OxdnaTrialConfig:
    label: str
    backend: str  # "CPU" | "CUDA"
    device: str  # CUDA device index (ignored for CPU)


@dataclass(frozen=True)
class NamdTrialConfig:
    label: str
    threads: int
    devices: str  # "" = CPU-only; "0" / "0,1" = GPU list


def oxdna_config_grid(cuda_devices: list[dict]) -> list[OxdnaTrialConfig]:
    """One CPU trial plus one CUDA trial per available device.

    oxDNA's Monte-Carlo backend is CPU-only, but the benchmark uses a single short
    *MD* stage, so the CUDA configs are meaningful.
    """
    grid = [OxdnaTrialConfig(label="CPU", backend="CPU", device="0")]
    for dev in cuda_devices:
        idx = str(dev["index"])
        grid.append(
            OxdnaTrialConfig(
                label=f"CUDA:{idx} ({dev.get('name', 'GPU')})",
                backend="CUDA",
                device=idx,
            )
        )
    return grid


def namd_config_grid(
    thread_ladder: list[int],
    cuda_devices: list[dict],
) -> list[NamdTrialConfig]:
    """``thread_ladder × ({each GPU} ∪ {CPU-only})``.

    The CPU-only trial carries ``devices=""`` — the runner omits the ``+devices``
    flag entirely in that case (passing ``+devices ""`` confuses NAMD).
    """
    targets: list[tuple[str, str]] = [("", "CPU")]
    for dev in cuda_devices:
        idx = str(dev["index"])
        targets.append((idx, f"GPU:{idx}"))
    grid: list[NamdTrialConfig] = []
    for threads in thread_ladder:
        for devices, dev_label in targets:
            grid.append(
                NamdTrialConfig(
                    label=f"+p{threads} {dev_label}",
                    threads=threads,
                    devices=devices,
                )
            )
    return grid


def synthetic_bundle_plan(n_target: int, *, max_nt: int) -> dict:
    """Pick ``(cells, length_bp)`` for a synthetic 6hb whose nucleotide count ≈ N.

    A fully-paired 6-cell bundle has ``2 strands/helix`` → ``2 * n_cells * length_bp``
    nucleotides.  We clamp the target to ``max_nt`` (engine-specific) and record the
    realized proxy size and whether a cap was applied — never a silent truncation.
    Minimum ``length_bp`` of 8 keeps the structure buildable.
    """
    n_cells = len(SIX_HB_CELLS)
    capped = min(n_target, max_nt)
    length_bp = max(8, round(capped / (2 * n_cells)))
    proxy_nucleotides = 2 * n_cells * length_bp
    return {
        "cells": list(SIX_HB_CELLS),
        "length_bp": length_bp,
        "proxy_nucleotides": proxy_nucleotides,
        "requested_nucleotides": n_target,
        "capped": n_target > max_nt,
    }


def _is_valid(metric) -> bool:
    return metric is not None and metric > 0


def pick_best_oxdna(results: list[dict]) -> dict | None:
    """Winner = highest ``steps_per_s`` among non-errored trials.

    Tie-break: prefer CUDA over CPU (the GPU usually wins at full size even when a
    tiny proxy looks even).  Each result dict carries at least
    ``{backend, device, steps_per_s, error}`` (plain fields → JSON-serializable).
    """
    valid = [
        r for r in results if not r.get("error") and _is_valid(r.get("steps_per_s"))
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda r: (
            r["steps_per_s"],
            1 if r.get("backend") == "CUDA" else 0,
        ),
    )


def pick_best_namd(results: list[dict]) -> dict | None:
    """Winner = highest ``ns_per_day`` among non-errored trials.

    Tie-break: prefer GPU (non-empty ``devices``) over CPU, then *fewer* threads
    (cheaper, leaves cores free) at equal throughput.  Each result dict carries
    ``{threads, devices, ns_per_day, error}``.
    """
    valid = [
        r for r in results if not r.get("error") and _is_valid(r.get("ns_per_day"))
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda r: (
            r["ns_per_day"],
            1 if r.get("devices") else 0,
            -r.get("threads", 0),
        ),
    )


def resolve_oxdna_relax_config(hw) -> dict:
    """Map a stored per-machine benchmark result → the oxDNA relaxation ``{backend,
    device}`` a run should use.

    The Benchmark button writes the fastest discovered config into
    ``Design.metadata.hardware_defaults[hostname]`` (a ``HardwareBenchmark``); this is
    the *read* side that turns it into the backend/device a relaxation feeds to oxDNA.
    Falls back to the safe, portable ``CPU``/``"0"`` default when no oxDNA result has
    been benchmarked on this machine (``hw`` is ``None`` or carries no ``oxdna`` slot) —
    so a headless iterate-until-met loop runs on the fastest discovered backend when one
    exists and a plain CPU run otherwise.

    PURE: no I/O and no hostname lookup — the caller selects the per-machine slot and
    hands it in (``None`` for "nothing benchmarked here yet").
    """
    oxdna = getattr(hw, "oxdna", None) if hw is not None else None
    if oxdna is None:
        return {"backend": "CPU", "device": "0"}
    return {"backend": oxdna.backend, "device": oxdna.device}


def extrapolate_note(proxy_n: int, real_n: int, *, capped: bool) -> str:
    """Honest one-line caveat surfaced in the API + panel (no-silent-caps rule)."""
    if not capped or proxy_n >= real_n:
        return (
            f"Ranking and throughput measured on a {proxy_n}-nt synthetic proxy "
            f"(your design is {real_n} nt)."
        )
    return (
        f"Config *ranking* measured on a capped {proxy_n}-nt synthetic proxy; your "
        f"{real_n}-nt design is larger, so absolute throughput will be lower and a "
        f"GPU's lead may be wider than shown."
    )
