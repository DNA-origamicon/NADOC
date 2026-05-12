"""ssDNA freely-jointed chain (FJC) lookup.

Loads ``backend/data/ssdna_fjc_lookup.json`` (pre-computed by
``scripts/generate_ssdna_fjc_lookup.py``) once at module import time and
exposes per-length lookups for radius of gyration, end-to-end distance,
and the canonical bead positions.

Schema (post bin-based redesign)
--------------------------------
Each entry exposes:

  • ``r_ee_bin_edges_nm`` / ``rg_bin_edges_nm`` — HIST_BINS+1 floats.
  • ``bins`` — HIST_BINS items, each:
      { count, rep_r_ee_nm, rep_rg_nm, rep_positions, rg_subcounts }
    Non-empty bins carry ``rep_positions`` (the canonical-frame chain).
    ``rg_subcounts[k]`` is the count of samples in this R_ee bin whose
    Rg fell into Rg bin ``k`` — used by the frontend to re-compute the
    Rg distribution when the user crops the R_ee range.

Callers usually identify a configuration by ``bin_index`` ∈ [0, HIST_BINS-1].
``bin_positions(n_bp, bin_index)`` returns positions for that bin (or for
the nearest non-empty bin when ``bin_index`` falls in an empty cell).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

_LOOKUP_PATH = Path(__file__).resolve().parents[1] / "data" / "ssdna_fjc_lookup.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    with _LOOKUP_PATH.open() as fh:
        return json.load(fh)


def dump_all() -> dict:
    """Return the raw lookup payload (metadata + entries).

    Used by the ``GET /api/ssdna-fjc-lookup`` endpoint so the frontend can
    fetch the table once and render ss-linker bridges in their natural
    FJC shape without round-tripping per-design.
    """
    return _load()


def metadata() -> dict:
    return dict(_load()["metadata"])


def supported_range() -> tuple[int, int]:
    md = metadata()
    lo, hi = md["bp_range"]
    return int(lo), int(hi)


def has_entry(n_bp: int) -> bool:
    return str(int(n_bp)) in _load()["entries"]


def entry(n_bp: int) -> dict:
    """Return the lookup entry for ``n_bp`` (fresh copy)."""
    if n_bp < 1:
        raise ValueError(f"n_bp must be >= 1, got {n_bp}")
    key = str(int(n_bp))
    entries = _load()["entries"]
    if key not in entries:
        lo, hi = supported_range()
        raise ValueError(
            f"ssDNA FJC lookup has no entry for n_bp={n_bp}; "
            f"table covers {lo}..{hi}. Regenerate "
            "scripts/generate_ssdna_fjc_lookup.py to extend the range."
        )
    return dict(entries[key])


def num_bins(n_bp: int) -> int:
    return len(entry(n_bp)["bins"])


def _resolve_bin(n_bp: int, bin_index: int) -> tuple[int, dict]:
    """Return (resolved_index, bin_payload) for the nearest non-empty bin
    to ``bin_index``. Raises if no bin in the entry is occupied."""
    bins = entry(n_bp)["bins"]
    if not bins:
        raise ValueError(f"FJC entry n_bp={n_bp} has no bins")
    n = len(bins)
    raw = int(bin_index) % n
    if bins[raw]["count"] > 0 and bins[raw].get("rep_positions") is not None:
        return raw, bins[raw]
    # Walk outward until we find a populated bin.
    for d in range(1, n + 1):
        for cand in (raw - d, raw + d):
            if 0 <= cand < n and bins[cand]["count"] > 0 and bins[cand].get("rep_positions") is not None:
                return cand, bins[cand]
    raise ValueError(f"FJC entry n_bp={n_bp} has no occupied bins")


def bin_positions(n_bp: int, bin_index: int) -> np.ndarray:
    """Return ``(n_bp, 3)`` canonical positions for the chosen bin (or the
    nearest non-empty bin)."""
    _idx, b = _resolve_bin(n_bp, bin_index)
    pos = np.asarray(b["rep_positions"], dtype=float)
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise ValueError(f"FJC bin n_bp={n_bp}, bin={bin_index} has malformed positions {pos.shape}")
    return pos


def bin_r_ee(n_bp: int, bin_index: int) -> float:
    _idx, b = _resolve_bin(n_bp, bin_index)
    return float(b["rep_r_ee_nm"])


def bin_rg(n_bp: int, bin_index: int) -> float:
    _idx, b = _resolve_bin(n_bp, bin_index)
    return float(b["rep_rg_nm"])


def resolve_bin_index(n_bp: int, bin_index: int) -> int:
    """Resolve an arbitrary ``bin_index`` to the actual non-empty bin used
    by the lookup (skipping empties via nearest-non-empty walk)."""
    idx, _ = _resolve_bin(n_bp, bin_index)
    return idx


def default_bin_index(n_bp: int) -> int:
    """Bin whose midpoint R_ee is closest to the ensemble mean. Used as the
    initial selection for a freshly relaxed linker."""
    e = entry(n_bp)
    mean = float(e.get("r_ee_mean_nm", 0.0))
    edges = e["r_ee_bin_edges_nm"]
    midpoints = [0.5 * (edges[k] + edges[k + 1]) for k in range(len(edges) - 1)]
    if not midpoints:
        return 0
    target_idx = int(np.argmin([abs(m - mean) for m in midpoints]))
    idx, _ = _resolve_bin(n_bp, target_idx)
    return idx


def transform_to_chord(
    positions: np.ndarray,
    anchor_a: np.ndarray,
    anchor_b: np.ndarray,
) -> np.ndarray:
    """Anisotropically stretch + rotate + translate canonical positions onto
    the live chord A→B. ``positions[0]`` lands at ``anchor_a``; the last
    bead lies along the chord at the canonical R_ee distance.
    """
    a = np.asarray(anchor_a, dtype=float)
    b = np.asarray(anchor_b, dtype=float)
    chord = b - a
    cl = float(np.linalg.norm(chord))
    if cl < 1e-9:
        return positions + a

    target = chord / cl
    src = np.array([1.0, 0.0, 0.0])
    s = float(np.linalg.norm(np.cross(src, target)))
    c = float(np.dot(src, target))
    if s < 1e-12:
        if c > 0:
            return positions + a
        rot = np.diag([-1.0, -1.0, 1.0])
        return positions @ rot.T + a

    axis = np.cross(src, target) / s
    K = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )
    rot = np.eye(3) + s * K + (1 - c) * (K @ K)
    return positions @ rot.T + a
