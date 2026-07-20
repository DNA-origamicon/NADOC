"""Does an ATOMISTIC local propagator beat classical MD at ORIGAMI scale? — cost model.

The central strategic question for the propagator project (user, 2026-07-19):
*at sufficiently large scale, does a fully-atomistic learned propagator run faster
than conventional MD?*  This module makes that question quantitative and honest,
so it can be answered with numbers instead of hope.

Two per-step costs, compared as a function of system size N (atoms):

  NAMD (classical, per native 2 fs step) = a*N   (bonded + real-space non-bonded,
        neighbour-list; O(N))  +  b*N*log2(N)   (PME / global electrostatics; the
        term a local-cutoff propagator AVOIDS).  Fit from measured NAMD points.

  Local GNN propagator (per predicted step) = c*N   (radius-cutoff message passing,
        fixed neighbours/atom → strictly O(N); NO PME).  ``c`` depends on model
        accuracy tier (hidden width × layers) and is measured by gnn.speed_benchmark.

The propagator may also (i) take a larger step than native MD (``step_mult`` k: one
predicted step replaces k native steps — FlashMD-style, capped by the aliasing wall),
and (ii) run inside an uncertainty-gated HYBRID where only a fraction ``hybrid_frac``
f of atoms still need full MD each step.  Effective speedup vs pure MD:

    speedup(N) = MD_cost(N) * k  /  ( GNN_cost(N) + f * MD_cost(N) )

The crossover N* is where speedup crosses 1.  This module reports N* for each
accuracy tier and lever setting, and whether N* is within reach of real origami
(6hb ~10^4-10^5 atoms solvated; large origami 10^5-10^6).

IMPORTANT — honesty about inputs:
- NAMD point(s) and GNN tier coefficients are MEASURED on THIS machine (RTX 2080
  SUPER, NAMD3 CUDA); provenance in ``MEASURED_*`` below.  A single NAMD point cannot
  separate the a*N and b*N*log2(N) terms — with one point we assume the literature
  PME/real-space split (``DEFAULT_PME_FRACTION``); a SECOND measured point (e.g. the
  6hb reference run) is fitted exactly when present in ``namd_points``.
- Per-step atomistic-vs-classical is known-hard (accurate NNPs run MD 10-100x slower
  than classical FF).  The model does not assume a win; it reports where, if anywhere,
  one exists under stated levers.  numpy-only; the live GNN benchmark is optional.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ── MEASURED anchors (this machine) ──────────────────────────────────────────
# NAMD full step (force + PME + integrate), solvated 20 bp duplex, RTX 2080 SUPER,
# 16 CPU + standard CUDA offload, PME grid 32x32x64.  Job f6b191b31c33.
MEASURED_NAMD_MS_PER_STEP = 7.5
MEASURED_NAMD_N = 17_827

# GNN forward-pass per-step cost, measured by gnn.speed_benchmark on the same GPU
# (radius cutoff 5 A, no PME).  Coefficient c = ms/step / N, in ms/atom, per tier.
# Derived from the 2026-07-18 optimization sweep at N=5000 (see the topic-file
# handoff "GNN SPEED BENCHMARK"): ms/step = ratio x NAMD_per_4fs_step_scaled(5000).
# Kept as {tier: measured ms/step at N=5000} so the linear coefficient is explicit
# and refreshable by ``refresh_gnn_tiers`` when the GPU is free.
MEASURED_GNN_MS_AT_5000 = {
    "h128_L3": 47.0,   # accuracy-capable reference (26x NAMD-per-4fs @ N=17827)
    "h64_L2": 17.6,    # 4.8x NAMD-per-4fs @ N=5000
    "h32_L2": 9.9,     # 2.7x
    "h32_L1": 5.1,     # 1.4x
    "h16_L1": 3.3,     # 0.9x — break-even-sized, too small to be accurate
}
GNN_BENCH_N = 5000

# Literature split of a classical-MD step between PME (global, O(N log N)) and the
# rest (bonded + real-space non-bonded + integrate, O(N)) for a solvated biomolecular
# system with standard PME.  ~0.3-0.5 of wall time is PME at these sizes; 0.4 is a
# defensible midpoint used ONLY when a single NAMD point is available.
DEFAULT_PME_FRACTION = 0.40

# Per-step NAMD benchmarks MINED from existing job logs on THIS machine (1 socket x
# 6 cores x 2 PU).  (N atoms, ms/step, note).  CONFOUNDED — different CPU-core counts
# and integration MODE per run, so NOT a clean scaling series; use for sanity only,
# and prefer a controlled same-mode/same-CPU pair (the 6hb reference run) for the fit.
# The load-bearing observation: 12.6x more atoms (17.8k -> 225k) barely changed
# per-step time in GPU-RESIDENT mode (6.1 -> 8.6 ms) -> the single-GPU per-step cost
# is NEAR-FLAT / weakly-scaling in this range (the 2080 is underused at 18k, near
# saturation at 225k).  => there is essentially NO single-GPU O(N log N) PME wall for
# an atomistic propagator to undercut below ~2.5e5 atoms.  The genuine "avoid PME" win
# regime is MULTI-GPU / multi-node at >=1e6 atoms where PME all-to-all comms collapse
# MD strong-scaling — out of reach of this 8 GB single GPU.
MINED_NAMD_POINTS = [
    (17_827, 6.1, "16 CPU, standard CUDA offload, 2 fs (dbd8ad3b7d4f duplex)"),
    (225_504, 8.6, "4 CPU, GPU-RESIDENT (CUDASOAintegrate), 4 fs (a81b371be69d 6hb)"),
    (197_107, 20.0, "6 CPU, standard CUDA offload, 2 fs (8553cf4fa9a0 6hbx100)"),
]

ORIGAMI_SCALES = {
    "6hb_short_solvated (~7e4)": 70_000,
    "6hb_100bp_solvated (~2.2e5)": 225_000,
    "mid_origami (~5e5)": 500_000,
    "large_origami (~1e6)": 1_000_000,
    "very_large (~4e6)": 4_000_000,
}


@dataclass
class NamdModel:
    """NAMD per-step cost: c0 (fixed GPU/launch overhead) + a*N (O(N)) +
    b*N*log2(N) (PME).  ``c0`` matters in the MEASURED single-GPU regime, where the
    card is below saturation and per-step time is overhead-dominated + sub-linear;
    the b term matters only in the asymptotic saturated / multi-node regime."""
    a: float   # ms per atom (O(N) part)
    b: float   # ms per atom-log2N (PME part)
    provenance: str = ""
    c0: float = 0.0   # fixed per-step overhead (ms), independent of N

    def cost_ms(self, n):
        n = np.asarray(n, dtype=float)
        return self.c0 + self.a * n + self.b * n * np.log2(np.maximum(n, 2.0))


def fit_namd(namd_points: list[tuple[int, float]] | None = None,
             pme_fraction: float = DEFAULT_PME_FRACTION) -> NamdModel:
    """Fit the two-term NAMD cost law.

    - >=2 measured (N, ms) points → least-squares fit of (a, b) exactly (this is the
      rigorous path; drop the 6hb reference point in here).
    - 1 point (default) → split it by ``pme_fraction`` into O(N) and O(N log N) terms
      (assumption, not a fit — flagged in provenance).
    """
    pts = list(namd_points or [(MEASURED_NAMD_N, MEASURED_NAMD_MS_PER_STEP)])
    if len(pts) >= 2:
        N = np.array([p[0] for p in pts], float)
        y = np.array([p[1] for p in pts], float)
        X = np.stack([N, N * np.log2(np.maximum(N, 2.0))], axis=1)
        (a, b), *_ = np.linalg.lstsq(X, y, rcond=None)
        return NamdModel(float(a), float(b),
                         f"fit of {len(pts)} measured points: {pts}")
    n0, y0 = pts[0]
    l0 = np.log2(max(n0, 2))
    b = pme_fraction * y0 / (n0 * l0)          # PME share → b*N*log2N
    a = (1 - pme_fraction) * y0 / n0           # rest → a*N
    return NamdModel(float(a), float(b),
                     f"single point {pts[0]} split by pme_fraction={pme_fraction} "
                     f"(ASSUMED, not fitted — add a 2nd point for a real fit)")


# Controlled scaling series on THIS machine (16 CPU, standard CUDA offload, propagator-
# reference protocol — SAME config across sizes, so a clean fit).  Grown as new runs land.
CONTROLLED_NAMD_POINTS = [
    (17_827, 6.5),    # solvated 20 bp duplex (dbd8ad3b7d4f; f6b191b31c33 gave 7.5)
    (136_413, 13.5),  # solvated 21 bp 6hb, job f716e1f42b9b (this session)
]


def fit_namd_overhead(points: list[tuple[int, float]] | None = None) -> NamdModel:
    """Fit MD/step = c0 + a*N (fixed overhead + linear) — the correct form in the
    MEASURED single-GPU-below-saturation regime, where per-step time is sub-linear
    in N (the two-term PME fit gives a spurious NEGATIVE b there).  >=2 points."""
    pts = list(points or CONTROLLED_NAMD_POINTS)
    N = np.array([p[0] for p in pts], float)
    y = np.array([p[1] for p in pts], float)
    X = np.stack([np.ones_like(N), N], axis=1)
    (c0, a), *_ = np.linalg.lstsq(X, y, rcond=None)
    return NamdModel(float(a), 0.0,
                     f"overhead+linear fit of {len(pts)} controlled points {pts}: "
                     f"c0={c0:.2f} ms fixed + a={a:.3e} ms/atom (single-GPU regime)",
                     c0=float(c0))


def gnn_coeff(tier: str, ms_at_bench: dict | None = None) -> float:
    """Per-atom GNN cost c (ms/atom) for an accuracy tier, from the measured ms/step
    at the benchmark size (strictly linear: local cutoff → fixed neighbours/atom)."""
    ms_at_bench = ms_at_bench or MEASURED_GNN_MS_AT_5000
    return ms_at_bench[tier] / GNN_BENCH_N


def speedup(n, namd: NamdModel, tier: str, *, step_mult: float = 1.0,
            hybrid_frac: float = 0.0, ms_at_bench: dict | None = None):
    """Effective wall-clock speedup of the propagator vs pure MD at size ``n``.

    step_mult k: one predicted step replaces k native MD steps (larger stride).
    hybrid_frac f: fraction of atoms still needing full MD each step (uncertainty
    gate).  speedup = MD*k / (GNN + f*MD).  >1 means the propagator is faster.
    """
    n = np.asarray(n, dtype=float)
    md = namd.cost_ms(n)
    gnn = gnn_coeff(tier, ms_at_bench) * n
    return md * step_mult / (gnn + hybrid_frac * md)


def crossover_n(namd: NamdModel, tier: str, *, step_mult: float = 1.0,
                hybrid_frac: float = 0.0, ms_at_bench: dict | None = None,
                lo: float = 1e3, hi: float = 1e9) -> float | None:
    """Smallest N where speedup>=1 (the propagator starts winning), or None if it
    never wins below ``hi``.  Monotone in N when PME>0, so bisect."""
    def f(n):
        return speedup(n, namd, tier, step_mult=step_mult,
                       hybrid_frac=hybrid_frac, ms_at_bench=ms_at_bench) - 1.0
    if f(hi) < 0:
        return None                # never catches up in the searched range
    if f(lo) >= 0:
        return lo                  # already winning at the low end
    for _ in range(80):
        mid = np.sqrt(lo * hi)     # geometric bisection (log-scale search)
        if f(mid) >= 0:
            hi = mid
        else:
            lo = mid
    return float(np.sqrt(lo * hi))


def refresh_gnn_tiers(sizes=(2000, 5000, 10000), device="cuda") -> dict:
    """Re-measure GNN ms/step for each tier on THIS GPU (optional; needs torch + a
    free GPU).  Returns {tier: ms at GNN_BENCH_N} by fitting the measured points to
    c*N and evaluating at GNN_BENCH_N — refreshes MEASURED_GNN_MS_AT_5000."""
    from backend.ml.propagator.gnn import speed_benchmark  # noqa: PLC0415
    tiers = {"h128_L3": (128, 3), "h64_L2": (64, 2), "h32_L2": (32, 2),
             "h32_L1": (32, 1), "h16_L1": (16, 1)}
    out = {}
    for tier, (h, L) in tiers.items():
        rows = speed_benchmark(sizes=sizes, hidden=h, n_layers=L, device=device)
        if not rows:
            continue
        N = np.array([r["n"] for r in rows], float)
        ms = np.array([r["gnn_ms"] for r in rows], float)
        c = float((ms * N).sum() / (N * N).sum())     # least-squares slope through 0
        out[tier] = c * GNN_BENCH_N
    return out


def report(namd_points: list[tuple[int, float]] | None = None,
           levers=None, ms_at_bench: dict | None = None,
           namd: NamdModel | None = None) -> dict:
    """Print + return the full crossover analysis across accuracy tiers and lever
    settings.  ``levers`` = list of (label, step_mult, hybrid_frac).  Pass ``namd`` to
    use a specific NAMD model (e.g. ``fit_namd_overhead()`` — the correct single-GPU
    form); otherwise the PME two-term model is fitted from ``namd_points``."""
    namd = namd or fit_namd(namd_points)
    levers = levers or [
        ("per-step, no hybrid (k=1, f=0)", 1.0, 0.0),
        ("larger step k=4 (aliasing-limited)", 4.0, 0.0),
        ("hybrid f=0.1 (10% atoms full-MD)", 1.0, 0.10),
        ("k=4 + hybrid f=0.1 (realistic best)", 4.0, 0.10),
    ]
    print("=" * 78)
    print("ATOMISTIC PROPAGATOR vs CLASSICAL MD — per-step cost crossover analysis")
    print("=" * 78)
    print(f"NAMD model: {namd.provenance}")
    print(f"  a={namd.a:.3e} ms/atom (O(N))  b={namd.b:.3e} ms/atom-log2N (PME)")
    mb = ms_at_bench or MEASURED_GNN_MS_AT_5000
    print(f"GNN tiers (ms/step @ N={GNN_BENCH_N}): "
          + ", ".join(f"{k}={v:.1f}" for k, v in mb.items()))
    print(f"  accuracy note: h16_L1 is break-even-sized but too small to be a stable/"
          f"accurate propagator; accuracy-capable ~ h64_L2..h128_L3.")
    out = {"namd": namd.provenance, "tiers": {}}
    for label, k, f in levers:
        print(f"\n--- lever: {label} ---")
        print(f"{'tier':>9} {'crossover N*':>14} {'within origami?':>18} "
              f"{'speedup@1e6':>12}")
        out["tiers"][label] = {}
        for tier in mb:
            nstar = crossover_n(namd, tier, step_mult=k, hybrid_frac=f,
                                ms_at_bench=ms_at_bench)
            s1e6 = float(speedup(1e6, namd, tier, step_mult=k, hybrid_frac=f,
                                 ms_at_bench=ms_at_bench))
            within = ("never <1e9" if nstar is None
                      else ("YES <=1e5" if nstar <= 1e5
                            else ("at ~%.0e" % nstar if nstar <= 1e7 else "only >1e7")))
            ns = "never" if nstar is None else f"{nstar:.2e}"
            print(f"{tier:>9} {ns:>14} {within:>18} {s1e6:>12.2f}")
            out["tiers"][label][tier] = {"crossover_n": nstar, "speedup_1e6": s1e6}
    # origami-scale speedup table for the accuracy-capable tier
    print(f"\n--- speedup by origami scale (tier h64_L2, accuracy-capable-ish) ---")
    print(f"{'scale':>28} {'N':>10} " + " ".join(f"{lab.split(' ')[0]:>10}"
          for lab, _, _ in levers))
    for scale, n in ORIGAMI_SCALES.items():
        row = [f"{scale:>28} {n:>10}"]
        for _, k, f in levers:
            row.append(f"{speedup(n, namd, 'h64_L2', step_mult=k, hybrid_frac=f, ms_at_bench=ms_at_bench):>10.2f}")
        print(" ".join(row))
    return out


def save_report(path: str | Path, **kw) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report(**kw), indent=2, default=str))
    return path
