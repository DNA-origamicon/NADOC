"""Pre-compute the ssDNA freely-jointed-chain (FJC) lookup table.

Run once; output is committed at ``backend/data/ssdna_fjc_lookup.json`` and
loaded at runtime by ``backend.core.ssdna_fjc`` for the ss-linker relax
operation. Deterministic — uses ``numpy.random.default_rng(SEED)`` and the
same SEED reproduces the same configurations bit-for-bit.

Model
-----
Each entry covers an ssDNA segment of ``n_bp`` nucleotides. The polymer is
modelled as a 3D FJC with rigid Kuhn segments under two physical
constraints that mimic a linker sitting between two origami bodies:

  • SLAB CONSTRAINT (perpendicular to chord):
      Two parallel walls at x = 0 (anchor A's body) and x = D (anchor B's
      body), with D = KUHN_LENGTH_NM * sqrt(N_kuhn). Every bead must
      satisfy 0 <= x_i <= D.

  • SELF-AVOIDANCE (SAW):
      Pairwise center-to-center distance >= SAW_RADIUS_NM for every non-
      adjacent pair (|i - j| >= 2).

Per length, three configurations are emitted at three Rg targets within
the constrained ensemble:

  • "Rg - σ" — chain with Rg ≈ mean(Rg) − std(Rg)   (compact realisation)
  • "Rg"     — chain with Rg ≈ mean(Rg)             (typical realisation)
  • "Rg + σ" — chain with Rg ≈ mean(Rg) + std(Rg)   (extended realisation)

Each target is matched within RG_TOLERANCE_FRAC (default 1%); when no
sample passes the band, the closest available is used and ``rg_error_pct``
flags the miss in the JSON.

Sampling is vectorised — all SAMPLES chains per length are generated as a
single NumPy batch, then interpolation, canonicalisation, slab check, and
SAW check are run vectorised (the SAW check is chunked to bound memory).

Two-stage regeneration policy
-----------------------------
The generator updates lengths 1..``MAX_NEW_ALGORITHM_BP`` (currently 35)
with the new algorithm. Lengths past that bound are **preserved verbatim
from the existing JSON** so the user can review the new short-chain data
without invalidating the long-chain entries that already shipped. Re-run
with a larger ``MAX_NEW_ALGORITHM_BP`` to extend coverage.

Canonical frame
---------------
  positions[0]    = (0, 0, 0)
  positions[-1]   = (R_ee, 0, 0)   with R_ee <= D = b * sqrt(N_kuhn)

Usage
-----
    python scripts/generate_ssdna_fjc_lookup.py

Writes ``backend/data/ssdna_fjc_lookup.json``. Re-run to regenerate.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# ── Parameters ────────────────────────────────────────────────────────────────
KUHN_LENGTH_NM        = 1.5
CONTOUR_PER_NT_NM     = 0.59
BP_RANGE              = range(1, 101)          # inclusive 1..100
BATCH_SIZE            = 20_000                 # per-batch FJC samples (vectorised)
TARGET_N_BOTH_OK      = 3_000                  # accumulate this many slab+SAW samples per length
MAX_TOTAL_SAMPLES     = 2_000_000              # safety cap when acceptance is very low
SAW_BATCH             = 5_000                  # SAW pairwise distance chunk
SAW_RADIUS_NM         = 0.6                    # min center-to-center for |i-j| >= 2
SEED                  = 20260511
MAX_NEW_ALGORITHM_BP  = 35                     # apply new algorithm to n_bp <= this
HIST_BINS             = 40                     # bins for both R_ee and Rg histograms

OUT_PATH = Path(__file__).resolve().parents[1] / "backend" / "data" / "ssdna_fjc_lookup.json"


# ── Vectorised primitives ────────────────────────────────────────────────────
def _random_unit_vectors_batch(n_samples: int, n_kuhn: int, rng: np.random.Generator) -> np.ndarray:
    """Sample (n_samples, n_kuhn, 3) of uniform unit vectors on the 3-sphere."""
    v = rng.standard_normal(size=(n_samples, n_kuhn, 3))
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _fjc_polylines_batch(n_samples: int, n_kuhn: int, b: float,
                          rng: np.random.Generator) -> np.ndarray:
    """Returns ``(n_samples, n_kuhn + 1, 3)`` cumulative positions per chain."""
    segs = _random_unit_vectors_batch(n_samples, n_kuhn, rng) * b
    out = np.zeros((n_samples, n_kuhn + 1, 3), dtype=float)
    np.cumsum(segs, axis=1, out=out[:, 1:])
    return out


def _interpolate_polylines_batch(poly: np.ndarray, n_bp: int, b: float) -> np.ndarray:
    """Interpolate every chain to ``n_bp`` evenly-spaced arc-length points.

    Every Kuhn segment has length ``b``, so the segment containing a target
    arc length and the fraction within it are the same for all chains — we
    compute them once and fancy-index the whole batch.
    """
    n_samples, n_vertices, _ = poly.shape
    n_kuhn = n_vertices - 1
    if n_bp < 2:
        return poly[:, :1, :]
    total = n_kuhn * b
    arc = np.linspace(0.0, total, n_bp)
    seg_idx = np.minimum((arc / b).astype(int), n_kuhn - 1)
    frac = (arc / b) - seg_idx
    # Last target sits exactly at total → seg_idx = n_kuhn - 1, frac = 1.0.
    poly_start = poly[:, seg_idx, :]               # (n_samples, n_bp, 3)
    poly_end   = poly[:, seg_idx + 1, :]
    return poly_start + frac[None, :, None] * (poly_end - poly_start)


def _canonicalise_batch(points: np.ndarray) -> np.ndarray:
    """Translate each chain so its first bead is at the origin, then rotate
    so its last bead lies on +x. Vectorised Rodrigues' formula."""
    n_samples, n_bp, _ = points.shape
    if n_bp < 2:
        return points - points[:, :1, :]

    translated = points - points[:, :1, :]
    end = translated[:, -1, :]                          # (n_samples, 3)
    r = np.linalg.norm(end, axis=1)                     # (n_samples,)
    safe = r > 1e-9
    end_dir = np.where(safe[:, None], end / np.maximum(r[:, None], 1e-12),
                       np.array([1.0, 0.0, 0.0]))       # (n_samples, 3)

    target = np.array([1.0, 0.0, 0.0])
    axis = np.cross(end_dir, target, axis=-1)           # (n_samples, 3)
    sin_a = np.linalg.norm(axis, axis=-1)               # (n_samples,)
    cos_a = end_dir @ target                            # (n_samples,)

    # Identity by default (zero rotation when already aligned).
    R = np.broadcast_to(np.eye(3), (n_samples, 3, 3)).copy()

    # General path: axis well-defined.
    gen = sin_a >= 1e-12
    if np.any(gen):
        ax = axis[gen] / sin_a[gen, None]              # (k, 3) unit axis
        x, y, z = ax[:, 0], ax[:, 1], ax[:, 2]
        s = sin_a[gen]
        c = cos_a[gen]
        C = 1.0 - c
        Rgen = np.empty((ax.shape[0], 3, 3), dtype=float)
        Rgen[:, 0, 0] = c + x * x * C
        Rgen[:, 0, 1] = x * y * C - z * s
        Rgen[:, 0, 2] = x * z * C + y * s
        Rgen[:, 1, 0] = y * x * C + z * s
        Rgen[:, 1, 1] = c + y * y * C
        Rgen[:, 1, 2] = y * z * C - x * s
        Rgen[:, 2, 0] = z * x * C - y * s
        Rgen[:, 2, 1] = z * y * C + x * s
        Rgen[:, 2, 2] = c + z * z * C
        R[gen] = Rgen

    # Antiparallel: 180° around Y so +x → -x. Numpy `where` would be awkward;
    # detect explicitly. (cos < 0 and sin ≈ 0 is the antiparallel signature.)
    antipar = (~gen) & (cos_a < 0)
    if np.any(antipar):
        R[antipar] = np.diag([-1.0, 1.0, -1.0])

    return np.einsum("sij,snj->sni", R, translated)


def _slab_ok_batch(points: np.ndarray, D: float, eps: float = 1e-6) -> np.ndarray:
    x = points[:, :, 0]
    return np.all((x >= -eps) & (x <= D + eps), axis=1)


def _saw_ok_batch(points: np.ndarray, min_dist: float, eps: float = 1e-5,
                   chunk: int = SAW_BATCH) -> np.ndarray:
    """Vectorised SAW check, chunked so the (S, n, n) pairwise tensor fits."""
    n_samples, n_bp, _ = points.shape
    if n_bp < 3:
        return np.ones(n_samples, dtype=bool)
    idx = np.arange(n_bp)
    band = np.abs(np.subtract.outer(idx, idx)) >= 2     # (n_bp, n_bp)
    thresh2 = (min_dist - eps) ** 2

    out = np.empty(n_samples, dtype=bool)
    for start in range(0, n_samples, chunk):
        stop = min(start + chunk, n_samples)
        chunked = points[start:stop]                    # (k, n_bp, 3)
        diff = chunked[:, :, None, :] - chunked[:, None, :, :]
        d2 = np.einsum("snmd,snmd->snm", diff, diff)
        # mask non-adjacent pairs; ignore the band by replacing with +inf.
        d2_band = np.where(band, d2, np.inf)
        min_d2 = d2_band.min(axis=(1, 2))               # (k,)
        out[start:stop] = min_d2 >= thresh2
    return out


def _radius_of_gyration_batch(points: np.ndarray) -> np.ndarray:
    if points.shape[1] < 2:
        return np.zeros(points.shape[0], dtype=float)
    centroid = points.mean(axis=1, keepdims=True)
    diff = points - centroid
    sq = np.einsum("snd,snd->sn", diff, diff)
    return np.sqrt(sq.mean(axis=1))


# ── Streaming bin-builder ────────────────────────────────────────────────────
def _process_batch(canon: np.ndarray, slab_ok: np.ndarray, saw_ok: np.ndarray,
                    r_ees: np.ndarray, rgs: np.ndarray,
                    r_ee_edges: np.ndarray, rg_edges: np.ndarray,
                    state: dict) -> None:
    """Update bin reps + counts + Rg subcounts from one batch.

    Pool = slab+SAW samples. Of those, only samples whose R_ee falls
    inside ``[r_ee_edges[0], r_ee_edges[-1]]`` are added to the histogram —
    out-of-range samples are dropped (NOT clipped to the edge bins) so
    bin 0 / bin HIST_BINS-1 don't pile up with tail outliers. The Rg axis
    still uses clipping for its sub-histogram since users see the Rg
    distribution only via the in-range R_ee filter.
    """
    pool = slab_ok & saw_ok
    n_pool = int(pool.sum())
    state["pool_n_total"] += n_pool
    if n_pool == 0:
        return
    pos = canon[pool]
    r = r_ees[pool]
    g = rgs[pool]
    in_range = (r >= r_ee_edges[0]) & (r <= r_ee_edges[-1])
    state["pool_n_outliers"] += int((~in_range).sum())
    if not in_range.any():
        return
    pos = pos[in_range]; r = r[in_range]; g = g[in_range]
    n_bins = len(r_ee_edges) - 1
    r_ee_idx = np.clip(np.digitize(r, r_ee_edges) - 1, 0, n_bins - 1)
    rg_idx   = np.clip(np.digitize(g, rg_edges)   - 1, 0, n_bins - 1)

    bin_count = state["bin_count"]
    bin_rep_dist = state["bin_rep_dist"]
    bin_rep_pos  = state["bin_rep_pos"]
    bin_rep_ree  = state["bin_rep_ree"]
    bin_rep_rg   = state["bin_rep_rg"]
    rg_subcounts = state["rg_subcounts"]
    midpoints    = state["midpoints"]

    for s in range(pos.shape[0]):
        k = int(r_ee_idx[s])
        bin_count[k] += 1
        rg_subcounts[k, int(rg_idx[s])] += 1
        d = abs(r[s] - midpoints[k])
        if d < bin_rep_dist[k]:
            bin_rep_dist[k] = d
            bin_rep_pos[k]  = pos[s].copy()
            bin_rep_ree[k]  = float(r[s])
            bin_rep_rg[k]   = float(g[s])

    state["binned_n"]        += int(pos.shape[0])
    state["pool_r_ee_sum"]   += float(r.sum())
    state["pool_r_ee_sumsq"] += float((r * r).sum())
    state["pool_rg_sum"]     += float(g.sum())
    state["pool_rg_sumsq"]   += float((g * g).sum())


def _build_bin_entries(
    n_bp: int, n_kuhn: int, rng: np.random.Generator
) -> dict:
    """Adaptive streaming sampler: draws batches of BATCH_SIZE FJC chains
    until the slab+SAW pool reaches TARGET_N_BOTH_OK (or MAX_TOTAL_SAMPLES
    is hit). Maintains one rep shape per R_ee bin via online "closest to
    bin midpoint" — never holds the full sample set in memory.

    Two passes: pass 1 = a single pilot batch to set R_ee / Rg bin edges
    from the observed range; pass 2 = streaming batches that fill the
    bins until the target is reached.
    """
    D = KUHN_LENGTH_NM * np.sqrt(n_kuhn)
    rg_target_free = KUHN_LENGTH_NM * np.sqrt(n_kuhn / 6.0)
    b = KUHN_LENGTH_NM

    # ── Phase A: ranging — accumulate pool samples until percentile-based
    #    bin edges are statistically stable. The constraint-skewed distribution
    #    at long chain lengths has a long lower tail; using raw min..max would
    #    waste several bins on bins with <10 counts. We use the 0.5 / 99.5
    #    percentiles instead so the bulk of the data fills the 40 bins.
    RANGE_POOL_TARGET = 1000
    range_r_ees_list: list[np.ndarray] = []
    range_rgs_list:   list[np.ndarray] = []
    range_pool_n = 0
    range_total  = 0
    range_n_slab = 0
    range_n_saw  = 0
    while range_pool_n < RANGE_POOL_TARGET and range_total < MAX_TOTAL_SAMPLES:
        poly = _fjc_polylines_batch(BATCH_SIZE, n_kuhn, b, rng)
        interp = _interpolate_polylines_batch(poly, n_bp, b)
        canon = _canonicalise_batch(interp)
        slab_ok = _slab_ok_batch(canon, D)
        saw_ok  = _saw_ok_batch(canon, SAW_RADIUS_NM)
        pool = slab_ok & saw_ok
        range_n_slab += int(slab_ok.sum())
        range_n_saw  += int(saw_ok.sum())
        if pool.any():
            r = np.linalg.norm(canon[pool, -1, :] - canon[pool, 0, :], axis=1)
            g = _radius_of_gyration_batch(canon[pool])
            range_r_ees_list.append(r)
            range_rgs_list.append(g)
            range_pool_n += int(pool.sum())
        range_total += canon.shape[0]

    if range_pool_n >= 32:
        range_r_ees = np.concatenate(range_r_ees_list)
        range_rgs   = np.concatenate(range_rgs_list)
    else:
        # Hit the cap without enough pool samples — fall back to [0, D].
        range_r_ees = np.array([0.0, D])
        range_rgs   = np.array([0.0, D])

    def _edges_from_percentiles(values: np.ndarray) -> np.ndarray:
        """Bin edges spanning [P0.5, P99.5] of the data, clipped to >=0."""
        if values.size == 0:
            return np.linspace(0.0, D, HIST_BINS + 1)
        lo = float(np.percentile(values, 0.5))
        hi = float(np.percentile(values, 99.5))
        if hi - lo < 1e-6:
            return np.linspace(max(lo - 0.1, 0.0), hi + 0.1, HIST_BINS + 1)
        return np.linspace(max(0.0, lo), hi, HIST_BINS + 1)

    r_ee_edges = _edges_from_percentiles(range_r_ees)
    rg_edges   = _edges_from_percentiles(range_rgs)

    state = {
        "bin_count":    np.zeros(HIST_BINS, dtype=int),
        "bin_rep_dist": np.full(HIST_BINS, np.inf),
        "bin_rep_pos":  [None] * HIST_BINS,
        "bin_rep_ree":  [0.0] * HIST_BINS,
        "bin_rep_rg":   [0.0] * HIST_BINS,
        "rg_subcounts": np.zeros((HIST_BINS, HIST_BINS), dtype=int),
        "midpoints":    0.5 * (r_ee_edges[:-1] + r_ee_edges[1:]),
        "pool_n_total":    0,   # slab+SAW samples drawn (in-range + outliers)
        "pool_n_outliers": 0,   # slab+SAW samples whose R_ee fell outside the edges
        "binned_n":        0,   # slab+SAW samples actually placed in a histogram bin
        "pool_r_ee_sum":   0.0,
        "pool_r_ee_sumsq": 0.0,
        "pool_rg_sum":     0.0,
        "pool_rg_sumsq":   0.0,
    }

    # Phase A's full samples are discarded (we kept only R_ee + Rg for the
    # percentile fit; positions weren't stored). Phase B re-streams fresh
    # batches and fills the bin reps with the now-final edges. n_total /
    # n_slab_ok / n_saw_ok are credited from phase A's metrics already.
    n_total   = range_total
    n_slab_ok = range_n_slab
    n_saw_ok  = range_n_saw

    while state["binned_n"] < TARGET_N_BOTH_OK and n_total < MAX_TOTAL_SAMPLES:
        poly = _fjc_polylines_batch(BATCH_SIZE, n_kuhn, b, rng)
        interp = _interpolate_polylines_batch(poly, n_bp, b)
        canon = _canonicalise_batch(interp)
        slab_ok = _slab_ok_batch(canon, D)
        saw_ok  = _saw_ok_batch(canon, SAW_RADIUS_NM)
        rgs   = _radius_of_gyration_batch(canon)
        r_ees = np.linalg.norm(canon[:, -1, :] - canon[:, 0, :], axis=1)
        _process_batch(canon, slab_ok, saw_ok, r_ees, rgs,
                       r_ee_edges, rg_edges, state)
        n_total   += canon.shape[0]
        n_slab_ok += int(slab_ok.sum())
        n_saw_ok  += int(saw_ok.sum())

    # Sums only accumulate from in-range (binned) samples — divide by binned_n
    # to keep mean/std consistent with the histogram the user actually sees.
    pool_n = max(1, state["binned_n"])
    rg_mean   = state["pool_rg_sum"]   / pool_n
    r_ee_mean = state["pool_r_ee_sum"] / pool_n
    rg_var    = max(0.0, state["pool_rg_sumsq"]   / pool_n - rg_mean   * rg_mean)
    r_ee_var  = max(0.0, state["pool_r_ee_sumsq"] / pool_n - r_ee_mean * r_ee_mean)
    rg_std    = float(np.sqrt(rg_var))
    r_ee_std  = float(np.sqrt(r_ee_var))

    bins = []
    for k in range(HIST_BINS):
        c = int(state["bin_count"][k])
        if c > 0 and state["bin_rep_pos"][k] is not None:
            rep_pos = state["bin_rep_pos"][k]
            bins.append({
                "count": c,
                "rep_r_ee_nm": round(state["bin_rep_ree"][k], 6),
                "rep_rg_nm":   round(state["bin_rep_rg"][k],  6),
                "rep_positions": [
                    [round(float(p[0]), 6), round(float(p[1]), 6), round(float(p[2]), 6)]
                    for p in rep_pos
                ],
                "rg_subcounts": [int(x) for x in state["rg_subcounts"][k].tolist()],
            })
        else:
            bins.append({
                "count": 0,
                "rep_r_ee_nm": None,
                "rep_rg_nm": None,
                "rep_positions": None,
                "rg_subcounts": [0] * HIST_BINS,
            })

    return {
        "n_bp": n_bp,
        "n_kuhn": n_kuhn,
        "contour_nm": round(n_bp * CONTOUR_PER_NT_NM, 6),
        "wall_separation_nm": round(D, 6),
        "rg_target_unconstrained_nm": round(rg_target_free, 6),
        "rg_mean_nm": round(rg_mean, 6),
        "rg_std_nm": round(rg_std, 6),
        "r_ee_mean_nm": round(r_ee_mean, 6),
        "r_ee_std_nm": round(r_ee_std, 6),
        "saw_radius_nm": SAW_RADIUS_NM,
        "primary_constraint_tier": 0,
        "n_total":   int(n_total),
        "n_slab_ok": int(n_slab_ok),
        "n_saw_ok":  int(n_saw_ok),
        "n_both_ok":  int(state["pool_n_total"]),
        "n_binned":   int(state["binned_n"]),
        "n_outliers": int(state["pool_n_outliers"]),
        "stats_tier": 0,
        "r_ee_bin_edges_nm": [round(float(e), 4) for e in r_ee_edges.tolist()],
        "rg_bin_edges_nm":   [round(float(e), 4) for e in rg_edges.tolist()],
        "bins": bins,
    }


# ── Driver ───────────────────────────────────────────────────────────────────
def _degenerate_entry(n_bp: int) -> dict:
    """Synthesise a minimal entry for n_bp < 2 (no chain to speak of)."""
    return {
        "n_bp": n_bp,
        "n_kuhn": 0,
        "contour_nm": round(n_bp * CONTOUR_PER_NT_NM, 6),
        "wall_separation_nm": 0.0,
        "rg_target_unconstrained_nm": 0.0,
        "rg_mean_nm": 0.0,
        "rg_std_nm": 0.0,
        "r_ee_mean_nm": 0.0,
        "r_ee_std_nm": 0.0,
        "saw_radius_nm": SAW_RADIUS_NM,
        "primary_constraint_tier": 0,
        "n_total": 1, "n_slab_ok": 1, "n_saw_ok": 1, "n_both_ok": 1,
        "stats_tier": 0,
        "r_ee_bin_edges_nm": [0.0] * (HIST_BINS + 1),
        "rg_bin_edges_nm":   [0.0] * (HIST_BINS + 1),
        "bins": [
            {
                "count": 1 if k == 0 else 0,
                "rep_r_ee_nm": 0.0 if k == 0 else None,
                "rep_rg_nm":   0.0 if k == 0 else None,
                "rep_positions": [[0.0, 0.0, 0.0]] if k == 0 else None,
                "rg_subcounts": [0] * HIST_BINS,
            }
            for k in range(HIST_BINS)
        ],
    }


def main() -> None:
    rng = np.random.default_rng(SEED)

    entries: dict[str, dict] = {}
    for n_bp in BP_RANGE:
        if n_bp < 2:
            entries[str(n_bp)] = _degenerate_entry(n_bp)
            continue
        if n_bp > MAX_NEW_ALGORITHM_BP:
            # Out-of-scope for now; emit a placeholder with empty bins so the
            # frontend can still display "no data" cleanly. (Old per-config
            # entries don't fit the new bin-based schema — regenerate on a
            # later run.)
            entries[str(n_bp)] = _degenerate_entry(n_bp) | {
                "n_bp": n_bp,
                "wall_separation_nm": round(
                    KUHN_LENGTH_NM * np.sqrt(max(1, round(n_bp * CONTOUR_PER_NT_NM / KUHN_LENGTH_NM))),
                    6,
                ),
                "contour_nm": round(n_bp * CONTOUR_PER_NT_NM, 6),
                "n_kuhn": max(1, round(n_bp * CONTOUR_PER_NT_NM / KUHN_LENGTH_NM)),
            }
            continue

        n_kuhn = max(1, round(n_bp * CONTOUR_PER_NT_NM / KUHN_LENGTH_NM))
        entry = _build_bin_entries(n_bp, n_kuhn, rng)
        entries[str(n_bp)] = entry
        n_nonempty = sum(1 for b in entry["bins"] if b["count"] > 0)
        print(f"  n_bp={n_bp:3d} (N_kuhn={n_kuhn}): "
              f"⟨R_ee⟩={entry['r_ee_mean_nm']:.2f}±{entry['r_ee_std_nm']:.2f} nm, "
              f"⟨Rg⟩={entry['rg_mean_nm']:.2f}±{entry['rg_std_nm']:.2f} nm, "
              f"{n_nonempty}/{HIST_BINS} bins occupied, "
              f"n_total={entry['n_total']}, "
              f"pool n_both_ok={entry['n_both_ok']}, "
              f"binned={entry['n_binned']}, "
              f"outliers={entry['n_outliers']}", flush=True)

    payload = {
        "metadata": {
            "kuhn_length_nm": KUHN_LENGTH_NM,
            "contour_per_nt_nm": CONTOUR_PER_NT_NM,
            "saw_radius_nm": SAW_RADIUS_NM,
            "target_n_both_ok": TARGET_N_BOTH_OK,
            "max_total_samples": MAX_TOTAL_SAMPLES,
            "batch_size": BATCH_SIZE,
            "hist_bins": HIST_BINS,
            "max_new_algorithm_bp": MAX_NEW_ALGORITHM_BP,
            "seed": SEED,
            "bp_range": [BP_RANGE.start, BP_RANGE.stop - 1],
            "constraint_tiers": {
                "0": "slab + SAW (strictest, what we want)",
                "1": "slab only (SAW infeasible at this length)",
                "2": "free FJC (both infeasible — chain too long for slab)",
            },
            "description": (
                "ssDNA freely-jointed chain lookup with slab + SAW constraints. "
                "Per n_bp, an R_ee histogram (`hist_bins` bins) is emitted with "
                "ONE representative shape per non-empty bin (`rep_positions`). "
                "Each bin also carries `rg_subcounts`: how many samples in that "
                "R_ee bin fall into each Rg bin — the frontend uses this to "
                "re-compute the Rg distribution when the user crops the R_ee "
                "range with the modal's range thumbs."
            ),
        },
        "entries": entries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    new_lengths = [k for k in entries if 2 <= int(k) <= MAX_NEW_ALGORITHM_BP]
    n_total_bins = sum(
        sum(1 for b in entries[k]["bins"] if b["count"] > 0)
        for k in new_lengths
    )
    print(f"Wrote {OUT_PATH} ({len(entries)} entries; {n_total_bins} non-empty bins "
          f"across n_bp 2..{MAX_NEW_ALGORITHM_BP}).")


if __name__ == "__main__":
    main()
