"""Is a Holliday junction's two crossover strands wound through one another?

## Why this module exists at all

The obvious measure — the Gauss linking number — is a topological invariant only for
CLOSED curves.  Crossover backbones are OPEN arcs, so every answer depends on how you
close them, and five different closures each produced a confident wrong answer:

1. straight chord across the connector window: correct on an ideal build, but on a
   thermalised frame the chord sweeps across the partner and flips the verdict by +/-1
   with ZERO integrality residual.  Measured on a real 2hb_2xT run: +1 -> 0 -> -1 across
   three stages while nothing physical moved.
2. straight chord across WHOLE strands: a staple's 3'/5' ends abut at a nick, so the
   5.5 A closing chord passed 0.16 A from the partner — degenerate.
3. closure "at infinity" along a common direction: the two far-field closure loops
   interlock each other, reporting a clean junction as linked.
4. average crossing number: confounded by arc length; across designs it gave a false
   positive, and within one design it did not discriminate at all.
5. net Lk on whole staples: cancels a "winds in and back out" pair of wraps.

Mathematically, two open chains are never *linked* — they can always be pulled apart.  So
any boolean verdict is a MODELLING CHOICE about a bounded window, not a theorem, and this
module says so in its own output rather than asserting a false invariant.

## The two channels

**PCS — projected crossing number (primary, closure-free).**  Project the two open arcs
along many directions; in each view count SIGNED crossings of one arc over the other.
Nothing is closed, nothing is added, so none of the five artefacts above can arise.  The
verdict statistic is ``f_hi``, the fraction of views showing two or more crossings:
measured 0.000-0.016 clean vs 0.453-0.562 wound, and stable under rotation.  (The modal
crossing number is NOT used for the verdict — it flips between 1 and 2 on a wound
junction depending on orientation.)

**Duplex clamp (confirming, canonically closed).**  A crossover strand's two ends sit on
OPPOSITE helices at the SAME bp, so closing it is a rung across a base pair -- a real
feature of the duplex, k bp away from the junction.  Both strands close by the same rule
and their rungs sit on opposite sides of the junction.  Unlike an arbitrary chord this
converges: sweeping k gives 0.79, 0.82, 0.87, 0.93, 0.99 on a wound junction and
-0.20 ... -0.01 on a clean one.  **That convergence is a built-in falsification test** —
a value that does not settle means the measurement is not to be trusted, which is exactly
the check every earlier attempt lacked.

The channels share no machinery (signed diagram crossings of open arcs vs a solid-angle
integral over a closed 2-component link), so their agreement is real evidence.  When they
DISAGREE the verdict is ``ambiguous`` — reported, never silently resolved.  Quietly
picking one channel is what produced three false alarms during development.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

SCHEMA = "nadoc.junction_winding.v1"

# Verdict wording — deliberately about a bounded window, never "the strands are linked".
_WORDING = {
    "wound": "wound through, relative to a bounded junction window",
    "clean": "not wound within the junction window",
    "ambiguous": "channels disagree - no verdict",
}

DEFAULT_VIEWS = 64  # 256 gave identical modes and f_hi within 0.03
DEFAULT_CLAMP_K = 5  # bp of duplex buffer; the k-sweep checks convergence
_CLAMP_KS = (2, 3, 4, 5)
# The VERDICT uses f_hi, not n_mode.  Measured on real junctions across 6 orientations:
# a wound pair's modal crossing number flips between 1 and 2 (2,2,1,1,1,2) because the
# distribution straddles them ({0:1, 1:29, 2:34} over 64 views), so a rule of
# "|n_mode| >= 2" scores a wound junction CLEAN in half of all orientations.  f_hi — the
# fraction of views showing |crossings| >= 2 — is stable over the same rotations
# (0.453-0.562 wound vs 0.000-0.016 clean) and the threshold sits in the empty middle.
_PCS_F_HI_WOUND = 0.15
_LK_WOUND = 0.5
_CONVERGENCE_TOL = 0.25  # |Lk(k_max) - round(Lk(k_max))| above this = not converged


def fibonacci_directions(n: int = DEFAULT_VIEWS) -> np.ndarray:
    """``n`` near-uniform unit vectors on the sphere (deterministic)."""
    i = np.arange(n) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    theta = np.pi * (1.0 + 5.0**0.5) * i
    return np.stack(
        [np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1
    )


def signed_crossings(arc_a: np.ndarray, arc_b: np.ndarray, view: np.ndarray) -> int:
    """Signed crossings of ``arc_a`` over ``arc_b`` in the projection along ``view``."""
    v = view / np.linalg.norm(view)
    helper = np.array([1.0, 0.0, 0.0])
    if abs(float(v @ helper)) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    e1 = np.cross(v, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(v, e1)

    a2 = np.stack([arc_a @ e1, arc_a @ e2], axis=1)
    b2 = np.stack([arc_b @ e1, arc_b @ e2], axis=1)
    az, bz = arc_a @ v, arc_b @ v

    # All segment pairs at once — this runs per view, per junction pair, per frame.
    p = a2[:-1, None, :]
    r = (a2[1:] - a2[:-1])[:, None, :]
    s = b2[None, :-1, :]
    u = (b2[1:] - b2[:-1])[None, :, :]

    den = r[..., 0] * u[..., 1] - r[..., 1] * u[..., 0]
    ok = np.abs(den) > 1e-12
    safe = np.where(ok, den, 1.0)
    w = s - p
    ta = (w[..., 0] * u[..., 1] - w[..., 1] * u[..., 0]) / safe
    tb = (w[..., 0] * r[..., 1] - w[..., 1] * r[..., 0]) / safe
    hit = ok & (ta > 0.0) & (ta < 1.0) & (tb > 0.0) & (tb < 1.0)
    if not hit.any():
        return 0

    za = az[:-1, None] + ta * (az[1:] - az[:-1])[:, None]
    zb = bz[None, :-1] + tb * (bz[1:] - bz[:-1])[None, :]
    sign = np.where(den > 0, 1, -1)
    contrib = np.where(za > zb, sign, -sign)
    return int(contrib[hit].sum())


def projected_crossing_number(
    arc_a: np.ndarray, arc_b: np.ndarray, n_views: int = DEFAULT_VIEWS
) -> dict:
    """Closure-free winding signal: modal signed crossing number over many views.

    ``f_hi`` — the fraction of views showing |crossings| >= 2 — is the VERDICT statistic:
    measured 0.000-0.016 on clean junctions and 0.453-0.562 on wound ones, stable under
    rotation.  ``n_mode`` (the modal signed crossing number) is reported as a diagnostic
    only: it reads 0 when clean but flips between 1 and 2 when wound, because the
    distribution straddles those values, so it must not carry the verdict.
    """
    if len(arc_a) < 2 or len(arc_b) < 2:
        return {"n_mode": 0, "f_hi": 0.0, "n_views": 0}
    vals = np.array(
        [signed_crossings(arc_a, arc_b, v) for v in fibonacci_directions(n_views)]
    )
    mags = np.abs(vals)
    mode = int(np.bincount(mags).argmax())
    if mode == 0:
        signed = 0
    else:
        sel = vals[mags == mode]
        signed = int(np.sign(sel.sum()) * mode) if sel.sum() else mode
    return {
        "n_mode": signed,
        "f_hi": float((mags >= 2).mean()),
        "n_views": int(n_views),
    }


# ── duplex clamp ──────────────────────────────────────────────────────────────


def clamped_loop(
    residue_lookup, positions, connector, k: int, backbone: Sequence[str]
) -> Optional[np.ndarray]:
    """Close a crossover strand through the duplex at a buffer of ``k`` bp.

    Walk ``k`` bp back along the strand's own backbone on the outgoing helix, through the
    junction (and any inserts), then ``k`` bp on along the incoming helix.  The two ends
    then sit on opposite helices at the same bp, so joining them is a rung across a base
    pair — canonical, and far enough from the junction that its contribution vanishes as
    ``k`` grows.  ``residue_lookup(key) -> {atom name: row} | None``.
    """
    pts: list = []
    step_out = -1 if connector["from_dir"] == "REVERSE" else 1
    for t in range(k, -1, -1):
        d = residue_lookup(
            (
                "nt",
                connector["strand_id"],
                connector["from_helix"],
                connector["from_bp"] - step_out * t,
                connector["from_dir"],
            )
        )
        if d is None:
            return None
        pts.extend(positions[d[nm]] for nm in backbone if nm in d)

    for insert_k in range(connector.get("n_inserts", 0)):
        d = residue_lookup(("xb", connector["crossover_id"], insert_k))
        if d is not None:
            pts.extend(positions[d[nm]] for nm in backbone if nm in d)

    step_in = -1 if connector["to_dir"] == "REVERSE" else 1
    for t in range(0, k + 1):
        d = residue_lookup(
            (
                "nt",
                connector["strand_id"],
                connector["to_helix"],
                connector["to_bp"] + step_in * t,
                connector["to_dir"],
            )
        )
        if d is None:
            return None
        pts.extend(positions[d[nm]] for nm in backbone if nm in d)

    return np.asarray(pts, dtype=float)


def clamp_sweep(
    residue_lookup, positions, conn_a, conn_b, backbone, ks: Sequence[int] = _CLAMP_KS
) -> dict:
    """Duplex-clamped Lk at several buffers, plus whether it converged.

    Convergence is the self-check: a genuine invariant settles on an integer as the rung
    retreats into the duplex.  A value that never settles means the geometry is too
    degenerate to judge, and the report says so instead of rounding.
    """
    from backend.core.junction_topology import gauss_linking_number

    values: dict = {}
    for k in ks:
        la = clamped_loop(residue_lookup, positions, conn_a, k, backbone)
        lb = clamped_loop(residue_lookup, positions, conn_b, k, backbone)
        if la is None or lb is None:
            continue
        values[k] = round(float(gauss_linking_number(la, lb)), 4)
    if not values:
        return {"lk_by_k": {}, "lk": None, "converged": False, "residual": None}

    k_max = max(values)
    lk = values[k_max]
    residual = abs(lk - round(lk))
    return {
        "lk_by_k": values,
        "lk": lk,
        "k": k_max,
        "residual": round(residual, 4),
        "converged": bool(residual <= _CONVERGENCE_TOL),
    }


# ── composite verdict ─────────────────────────────────────────────────────────


def combine(pcs: dict, clamp: dict) -> dict:
    """Fuse the two channels into one verdict, refusing to guess when they disagree."""
    pcs_wound = pcs["f_hi"] >= _PCS_F_HI_WOUND
    clamp_lk = clamp.get("lk")
    clamp_known = clamp.get("converged") and clamp_lk is not None
    clamp_wound = bool(clamp_known and abs(clamp_lk) >= _LK_WOUND)

    if not clamp_known:
        # Only one channel has an opinion. Report it, flag the reduced confidence.
        verdict = "wound" if pcs_wound else "clean"
        confidence = "single-channel"
    elif pcs_wound == clamp_wound:
        verdict = "wound" if pcs_wound else "clean"
        confidence = "confirmed"
    else:
        verdict = "ambiguous"
        confidence = "channels-disagree"

    return {
        "verdict": verdict,
        "meaning": _WORDING[verdict],
        "confidence": confidence,
        "pcs": pcs,
        "clamp": clamp,
    }
