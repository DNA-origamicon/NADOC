"""Relaxation-stage early-stop decision (multi-criteria plateau detection).

A relaxation *stage* (e.g. an ENM-restraint rung) is split into p10/p50/p100
chunks that each re-run NAMD from the previous checkpoint. Empirically the stage
reaches its equilibrium energy AND base-pairing well before the first chunk ends
(exp36 reference bank: 18hb/3x6x200/3x4SQ settle by ~2-20% of every stage). This
module decides, at a chunk boundary, whether the stage has settled enough that the
remaining chunks are redundant and can be skipped.

The rule is MULTI-CRITERIA on purpose: energy(+volume) plateau ALONE is unsafe at
low restraint on fragile designs (base-pairing can keep degrading after energy
flattens — 2hb_noT at k=0.01). We only skip when BOTH the energy series AND the WC
base-pairing series are flat over their trailing window.

Pure functions, no I/O. Caller passes the chunk's energy frames (from
namd_metrics.parse_namd_log_frames) and the chunk's per-frame WC list (from the
health check). Default thresholds are calibrated on the exp36 bank.
"""
from __future__ import annotations
from dataclasses import dataclass
import statistics as st


@dataclass(frozen=True)
class CutoffParams:
    """Thresholds separate DRIFT (has the mean settled? — the real convergence
    signal, kept tight) from FLUCT (instantaneous thermal noise — a loose "not
    exploding" guard). Calibrated on a live FAST run (HMR + 4 fs) of 2hb_noT
    (2026-07-04): settled-stage POT fluct ~0.13%, VOL fluct ~0.24%, so the old
    single 0.1%/0.2% thresholds never fired on fast runs even when drift ~0.02%.
    A still-relaxing low-k stage there shows POT drift ~0.15%, so drift ~0.05%
    cleanly separates settled (k=0.5) from relaxing (k=0.1)."""
    window: int = 10               # trailing frames to test
    eps_pot_drift: float = 5e-4    # 0.05% mean drift = settled
    eps_pot_fluct: float = 3.5e-3  # 0.35% noise guard (fast-run thermal ~0.13%)
    eps_vol_drift: float = 3e-3    # 0.30% mean drift
    eps_vol_fluct: float = 5e-3    # 0.50% noise guard (fast-run thermal ~0.24%)
    eps_wc_drift: float = 0.02     # 2 pts mean drift
    eps_wc_fluct: float = 0.05     # 5 pts noise guard
    min_frames: int = 20           # skip a tiny p10 chunk; judge on p50's fuller series


def _rel(a: float, b: float) -> float:
    m = (abs(a) + abs(b)) / 2 or 1.0
    return abs(a - b) / m


def _series_flat(vals: list[float], window: int, drift_eps: float,
                 fluct_eps: float, absolute: bool) -> bool:
    """True if the trailing `window` of `vals` has mean-drift < drift_eps AND
    scatter < fluct_eps. Separating the two lets a converged-but-thermally-noisy
    atomistic series read as flat.

    absolute=True compares raw differences (for WC, already a 0-1 fraction);
    absolute=False compares relative to the mean (for energy/volume)."""
    w = [v for v in vals[-window:] if v is not None]
    if len(w) < max(4, window // 2):
        return False
    lo, hi = w[: len(w) // 2], w[len(w) // 2:]
    drift = abs(st.mean(lo) - st.mean(hi))
    fluct = st.pstdev(w)
    if not absolute:
        scale = abs(st.mean(w)) or 1.0
        drift /= scale
        fluct /= scale
    return drift < drift_eps and fluct < fluct_eps


def energy_plateaued(frames: list[dict], params: CutoffParams = CutoffParams()) -> bool:
    """POTENTIAL flat over the trailing window; VOLUME too when present (NPT)."""
    if len(frames) < params.min_frames:
        return False
    pot = [f.get("POTENTIAL") for f in frames]
    if not _series_flat(pot, params.window, params.eps_pot_drift,
                        params.eps_pot_fluct, absolute=False):
        return False
    vol = [f.get("VOLUME") for f in frames]
    if any(v is not None for v in vol):
        if not _series_flat(vol, params.window, params.eps_vol_drift,
                            params.eps_vol_fluct, absolute=False):
            return False
    return True


def wc_plateaued(wc_per_frame: list[float], params: CutoffParams = CutoffParams()) -> bool:
    """WC base-pairing flat over its trailing window. Empty -> not proven -> False."""
    if not wc_per_frame:
        return False
    return _series_flat(wc_per_frame, params.window, params.eps_wc_drift,
                        params.eps_wc_fluct, absolute=True)


def should_early_stop_stage(
    frames: list[dict],
    wc_per_frame: list[float],
    params: CutoffParams = CutoffParams(),
) -> tuple[bool, dict]:
    """Decide whether the current stage has settled enough to skip its remaining
    chunks. Requires BOTH energy and WC plateau. Returns (decision, diagnostics)."""
    e = energy_plateaued(frames, params)
    w = wc_plateaued(wc_per_frame, params)
    diag = {
        "n_energy_frames": len(frames),
        "n_wc_frames": len(wc_per_frame or []),
        "energy_plateaued": e,
        "wc_plateaued": w,
    }
    return (e and w), diag
