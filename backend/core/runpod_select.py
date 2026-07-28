"""Value-ranked, availability-aware, build-aware GPU selection for RunPod NAMD jobs.

This is the bridge the ad-hoc launchers kept missing (see REFERENCE_RUNPOD_RUNBOOK §7-8). It
fuses the three things that must ALL be right before renting, and that this session got wrong:

  1. **The NAMD BUILD's arch set.** A card outside it rents fine and dies at step 0 with
     "no kernel image is available". The Dec-2025 GIT build is sm_50..sm_90 (NO sm_120, so the
     RTX 5090 cannot run it); the multi-arch 3.0.2 tar is sm_80/89/90/120.
  2. **LIVE availability + price** — `runpod_preflight.fetch_gpu_stock` (GraphQL), not a pinned
     table. `recommend_gpus` uses pinned prices and no stock filter; this consumes the live data.
  3. **$/ns VALUE.** A small box on an H100 is ~5x worse $/ns than on a 4090 — its horsepower is
     wasted below a few M atoms. Ranking by a per-arch rate estimate is what keeps a small job on
     a cheap card and reserves H100/H200 for the huge boxes where they win.

The rate estimate is deliberately CONSERVATIVE (slower end of measured) so a pre-rent $/ns figure
never over-promises; the on-pod preflight bench refines it to the real pod (per-pod rate varies
~1.5x even on the same card model — RUNBOOK §7).

Pure functions (`select_cards`, `estimate_rate`) are unit-tested; `pick_cards` is the thin async
wrapper that fetches live stock and calls them.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.core.runpod_script import GPU_TYPES, GpuType, fits_on

# NAMD build -> the CUDA compute-caps its binary actually carries. A card whose sm is not in the
# set dies at step 0. Keep in lockstep with the packaged binaries.
BUILD_ARCHS: dict[str, frozenset[str]] = {
    # ~/Applications/NAMD_Git-2025-12-04 (sparse-cell GPU-resident capable). NO sm_120.
    "git": frozenset({"sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_89", "sm_90"}),
    # nadoc_bench_pkg/namd_cuda.tar.gz (3.0.2p1 multi-arch). Has sm_120; NOT sparse-resident.
    "release": frozenset({"sm_80", "sm_89", "sm_90", "sm_120"}),
}

# GPU-RESIDENT ms/step per MILLION atoms, by arch (timestep-independent — per-step force cost).
# Conservative (slower observed) so $/ns estimates don't over-promise. Offload ~2.6x these.
# Sources: RUNBOOK §1 (1.94M RTX PRO 4500), §7 (1.31M 4090 14.3-21.5 ms), fullbox bench
# (11.3M: H200 86ms, H100 SXM 93ms, H100 PCIe 123ms).
_MS_PER_STEP_PER_MATOM: dict[str, float] = {
    "sm_90": 10.0,    # H100 / H200 (measured 7.6-10.9 @ 11.3M)
    "sm_89": 15.0,    # RTX 4090 / 6000 Ada / L40S — Ada (measured 10.9-16.4 @ 1.31M)
    "sm_120": 14.0,   # Blackwell PRO 4500/5000/6000 (measured 13.6 @ 1.94M)
    "sm_80": 12.0,    # A100
    "sm_86": 24.0,    # A6000 / 3090 — Ampere is genuinely ~1.6x slower than Ada (RUNBOOK §7:
                      # the A6000 that silently degraded the run)
    "sm_75": 30.0,    # Turing
}
_OFFLOAD_PENALTY = 2.6
# "balanced" ranking excludes any card slower than this fraction of the FASTEST available card's
# ns/day, then picks cheapest $/ns among the rest — so "cheap" can never mean "glacially slow"
# (RUNBOOK §7 two-axis rule). 0.6 keeps the 4090 sweet spot and drops slow Ampere on a small box.
_SPEED_FLOOR_FRAC = 0.6

# Card table: GPU_TYPES (the pinned value cards) augmented with the high-end (H100/H200) and the
# cheap Ampere fallbacks the pinned table omits, so selection sees the whole landscape. Prices are
# INDICATIVE only — overridden by live `fetch_gpu_stock` prices whenever present. sm gates arch.
_EXTRA_CARDS = (
    GpuType("NVIDIA H100 80GB HBM3", "H100 SXM", 81_920, 2.99, "sm_90"),
    GpuType("NVIDIA H100 PCIe", "H100 PCIe", 81_920, 2.89, "sm_90"),
    GpuType("NVIDIA H200", "H200 SXM", 143_360, 4.39, "sm_90"),
    GpuType("NVIDIA L40S", "L40S", 49_152, 0.99, "sm_89"),
    GpuType("NVIDIA RTX A6000", "RTX A6000", 49_152, 0.53, "sm_86"),
    GpuType("NVIDIA GeForce RTX 3090", "RTX 3090", 24_576, 0.22, "sm_86"),
)
CARDS: tuple[GpuType, ...] = tuple({g.key: g for g in (*GPU_TYPES, *_EXTRA_CARDS)}.values())


# ── Learned per-arch rate registry ───────────────────────────────────────────────────────────
# The static table above is a conservative PRIOR. Each ACCEPTED run (post-reroll, so slow-pod
# outliers are already filtered out) folds its real ms/step in here; future $/ns estimates use the
# running mean once an arch has ≥ _MIN_LEARN_SAMPLES. Same running-mean persistence as
# cluster_throughput.py, keyed by GPU arch. Stored as RESIDENT ms/step per Matom (timestep- and
# box-size-independent), so one number per arch generalises across jobs.
DEFAULT_RATES_PATH = Path("/media/jojo/Archive/nadoc_bench_campaign/gpu_rates.json")
_MIN_LEARN_SAMPLES = 2


def load_rate_registry(path: Path = DEFAULT_RATES_PATH) -> dict:
    """Load the learned ``{arch: {ms_per_matom, n, updated}}`` store; ``{}`` on missing/corrupt."""
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return {}


def record_rate(sm: str, n_atoms: int, ms_step: float, *,
                path: Path = DEFAULT_RATES_PATH) -> None:
    """Fold one accepted resident run's ms/step into the running mean for its arch. Resilient —
    never raises (a stats write must not crash a paid run)."""
    try:
        if not sm or n_atoms <= 0 or ms_step <= 0:
            return
        per = ms_step / (n_atoms / 1e6)
        reg = load_rate_registry(path)
        row = reg.get(sm) or {"ms_per_matom": 0.0, "n": 0}
        n, mean = int(row.get("n", 0)), float(row.get("ms_per_matom", 0.0))
        row["ms_per_matom"] = (mean * n + per) / (n + 1)
        row["n"] = n + 1
        row["updated"] = int(time.time())
        reg[sm] = row
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(reg, indent=2, sort_keys=True))
        os.replace(tmp, p)          # atomic
    except Exception:  # noqa: BLE001
        pass


def ms_per_matom(sm: str, *, registry: Optional[dict] = None,
                 min_samples: int = _MIN_LEARN_SAMPLES) -> Optional[float]:
    """Learned ms/step-per-Matom for an arch (enough samples) else the static prior."""
    if registry:
        row = registry.get(sm)
        if row and int(row.get("n", 0)) >= min_samples and row.get("ms_per_matom"):
            return float(row["ms_per_matom"])
    return _MS_PER_STEP_PER_MATOM.get(sm)


@dataclass(frozen=True)
class Candidate:
    """One rankable card: identity + live economics + a pre-rent value estimate."""
    key: str
    label: str
    sm: str
    vram_mb: int
    usd_per_hour: float          # LIVE price if known, else the indicative table price
    live_price: bool             # True => usd_per_hour came from fetch_gpu_stock
    available: Optional[bool]    # None => stock unknown (proceed, RunPod will 500 if truly out)
    ns_day_est: float
    usd_per_ns_est: float


def estimate_rate(sm: str, n_atoms: int, usd_per_hour: float, *,
                  timestep_fs: float = 4.0, resident: bool = True,
                  registry: Optional[dict] = None) -> Optional[dict]:
    """Pre-rent ms/step, ns/day and $/ns for a card+system. None if the arch is unknown.

    Uses the LEARNED per-arch rate if ``registry`` supplies enough samples, else the conservative
    static prior. The on-pod bench is still the ground truth (and feeds ``record_rate``). Offload
    multiplies ms/step by ~2.6x (a different, slower code path)."""
    base = ms_per_matom(sm, registry=registry)
    if base is None or not usd_per_hour or usd_per_hour <= 0 or n_atoms <= 0:
        return None
    ms_step = base * (n_atoms / 1e6) * (1.0 if resident else _OFFLOAD_PENALTY)
    ns_day = timestep_fs * 1e-6 / (ms_step / 1000.0) * 86_400.0
    usd_per_ns = usd_per_hour * 24.0 / ns_day if ns_day > 0 else float("inf")
    return {"ms_step": ms_step, "ns_day": ns_day, "usd_per_ns": usd_per_ns}


def select_cards(n_atoms: int, *, build: str, resident: bool = True, timestep_fs: float = 4.0,
                 stock: Optional[dict] = None, max_usd_per_hour: Optional[float] = None,
                 prefer: str = "balanced", registry: Optional[dict] = None,
                 cards: tuple[GpuType, ...] = CARDS) -> list[Candidate]:
    """Rank the arch-compatible, VRAM-fitting, in-stock cards (best first).

    Filters, each a step-0-or-worse failure if skipped:
      - ``sm in BUILD_ARCHS[build]``   — else "no kernel image", dies at step 0
      - ``fits_on`` (VRAM, resident-aware) — else OOM
      - in stock (when live ``stock`` is given; unknown stock is NOT excluded — a global
        "out" can still have regional capacity, and RunPod 500s cleanly if truly none)
      - ``usd_per_hour <= max_usd_per_hour`` (live price if known)

    ``prefer`` sets the sort (the two-axis rule, RUNBOOK §7):
      - ``"balanced"`` (default): among cards within ``_SPEED_FLOOR_FRAC`` of the FASTEST card's
        ns/day, cheapest $/ns — the 4090 sweet spot (fast enough AND cheap); a slow-but-cheap 3090
        can't win, an over-priced H100 can't either.
      - ``"value"``: pure cheapest $/ns (may pick a slow cheap card).
      - ``"speed"``: pure highest ns/day (may pick an expensive card).
    Pre-rent estimates are CONSERVATIVE and refined by the on-pod bench — the launcher rents the
    top card, measures the real rate, and re-plans from THAT (never a prior pod's number).
    """
    archs = BUILD_ARCHS.get(build)
    if archs is None:
        raise ValueError(f"unknown build {build!r}; known: {sorted(BUILD_ARCHS)}")
    out: list[Candidate] = []
    for g in cards:
        if g.sm not in archs:
            continue
        if not fits_on(g, n_atoms, gpu_resident=resident):
            continue
        live = (stock or {}).get(g.key) or {}
        price = live.get("on_demand") or g.usd_per_hour
        if max_usd_per_hour is not None and price and price > max_usd_per_hour:
            continue
        available = None
        if stock is not None:
            # in stock only if we have a row AND its stock field is a real level
            available = bool(live) and str(live.get("stock") or "").strip().lower() not in (
                "", "none", "null")
            if not available:
                continue
        est = estimate_rate(g.sm, n_atoms, price, timestep_fs=timestep_fs, resident=resident,
                            registry=registry)
        out.append(Candidate(
            key=g.key, label=g.label, sm=g.sm, vram_mb=g.vram_mb,
            usd_per_hour=float(price), live_price=bool(live.get("on_demand")),
            available=available,
            ns_day_est=(est or {}).get("ns_day", 0.0),
            usd_per_ns_est=(est or {}).get("usd_per_ns", float("inf")),
        ))
    if prefer == "speed":
        out.sort(key=lambda c: (-c.ns_day_est, c.usd_per_ns_est))
        return out
    if prefer == "balanced":
        best_ns = max((c.ns_day_est for c in out), default=0.0)
        floor = best_ns * _SPEED_FLOOR_FRAC
        fast = [c for c in out if c.ns_day_est >= floor and c.ns_day_est > 0]
        pool = fast or out          # if nothing has a rate estimate, fall back to the whole set
        pool.sort(key=lambda c: (c.usd_per_ns_est, c.usd_per_hour))
        return pool
    # "value": best $/ns first; unknown-rate cards (inf) sink, then by price
    out.sort(key=lambda c: (c.usd_per_ns_est, c.usd_per_hour))
    return out


def same_tier(cands: list[Candidate], *, factor: float = 1.5) -> list[Candidate]:
    """Trim a ranked list to same-VALUE-tier cards (within ``factor`` of the best $/ns).

    RUNBOOK §7: a fallback to a poor-value card silently degrades the run (the A6000 that was 4x
    worse). The launcher's gpuTypeIds fallback list should be same-tier only — retry for a good
    card rather than rent a bad one."""
    if not cands:
        return cands
    best = cands[0].usd_per_ns_est
    if best == float("inf"):
        return cands[:1]
    return [c for c in cands if c.usd_per_ns_est <= best * factor]


async def pick_cards(api_key: str, n_atoms: int, *, build: str, resident: bool = True,
                     timestep_fs: float = 4.0, max_usd_per_hour: Optional[float] = None,
                     max_fallbacks: int = 4) -> list[Candidate]:
    """Live wrapper: fetch current RunPod stock/prices, value-rank, return a FALLBACK LIST.

    Returns the balanced pool (RUNBOOK §7 two-axis: cards within the speed floor, cheapest $/ns
    first) capped at ``max_fallbacks`` — the best value card preferred, with FAST alternatives
    behind it (RunPod rents the first available). The speed floor already drops slow cards (the
    A6000 trap), so a pricier-but-fast fallback is safe now that the launcher forces 4 fs.

    Never raises on a stock-fetch failure — degrades to indicative prices with stock unknown (a
    Cloudflare/GraphQL hiccup falls back to pinned-table behaviour, not a dead launch)."""
    from backend.core.runpod_preflight import fetch_gpu_stock
    try:
        stock = await fetch_gpu_stock(api_key)
    except Exception:
        stock = None
    ranked = select_cards(n_atoms, build=build, resident=resident, timestep_fs=timestep_fs,
                          stock=stock, max_usd_per_hour=max_usd_per_hour, prefer="balanced",
                          registry=load_rate_registry())
    return ranked[:max_fallbacks]


def gpu_options(n_atoms: int, *, build: str = "release", relax_ns: float = 19.2,
                resident: bool = True, timestep_fs: float = 4.0, stock: Optional[dict] = None,
                registry: Optional[dict] = None, prefer: str = "balanced") -> list[dict]:
    """Ranked, JSON-ready GPU options for the cluster-card picker: each row carries price,
    estimated **relax wall-clock**, and **estimated cost** for a job's relaxation ladder.

    Fuses ``select_cards`` (arch/VRAM/value ranking with live stock + learned rates) with the
    relax ladder length ``relax_ns`` (default the 4×4.8 = 19.2 ns mgh/aksimentiev ladder):
      relax_hours = relax_ns / ns_day * 24 ;  est_cost = relax_ns * $/ns.
    Pure given ``stock`` + ``registry`` — the route supplies live stock (fetch_gpu_stock) and
    the learned registry. Best-value in-stock card first."""
    cards = select_cards(n_atoms, build=build, resident=resident, timestep_fs=timestep_fs,
                         stock=stock, prefer=prefer, registry=registry)
    rows: list[dict] = []
    for c in cards:
        relax_h = (relax_ns / c.ns_day_est * 24.0) if c.ns_day_est > 0 else None
        cost = (relax_ns * c.usd_per_ns_est
                if c.usd_per_ns_est not in (0.0, float("inf")) else None)
        rows.append({
            "key": c.key, "label": c.label, "sm": c.sm,
            "vram_gb": round(c.vram_mb / 1024),
            "usd_per_hour": round(c.usd_per_hour, 2),
            "live_price": c.live_price,
            "available": c.available,          # True / False / None (stock unknown)
            "ns_day": round(c.ns_day_est, 1),
            "relax_hours": round(relax_h, 1) if relax_h else None,
            "est_cost": round(cost, 2) if cost else None,
        })
    return rows
