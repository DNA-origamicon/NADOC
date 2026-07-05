"""exp38 G1 — validate the coupled (twist, bend) authority-Jacobian solve on a honeycomb bend design.

Takes an UNDER-realized 60° bend (half its loop/skips stripped → a big twist+bend residual), builds
the per-helix 2xH Jacobian J (∂twist/∂skip, ∂bend/∂skip), solves the ridge least-squares
    minₓ ‖ J·x − (twist*−twist₀, bend*−bend₀) ‖² + λ‖x‖²
for a per-helix skip-count delta x (skips x>0 / loops x<0), realizes+verifies with a real FEM solve,
and iterates twice (the linear model is approximate).  Proves the coupled solve hits BOTH targets —
where a twist-only or bend-only pass structurally cannot.  Linear FEM oracle (fast); H=6.

Run:  PYTHONPATH=. uv run python experiments/exp38_coupled_shape_jacobian/jacobian.py
"""
from __future__ import annotations

import json
import os

import numpy as np

from backend.api import headless_build as hb
from backend.api import state as ds
from backend.core.models import LatticeType, LoopSkip
from backend.core import cando_autorefine as car
from backend.physics.fem_solver import predict_shape
from backend.core.cando_deviation import compute_deviation
from backend.core.oxdna_health import measure_bundle_twist, measure_bundle_arc_bend

HC = LatticeType.HONEYCOMB
SIX_HB = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
LEN, BEND = 210, 60.0
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RES, exist_ok=True)


def measure(design):
    shape = predict_shape(design, nonlinear=False, with_rmsf=False)
    ck = {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}
    core = [p for p in shape["positions"] if (p["helix_id"], int(p["bp_index"])) in ck]
    tw = float(measure_bundle_twist(core))
    try:
        bd = float(measure_bundle_arc_bend(core))
    except Exception:
        bd = float("nan")
    dev = compute_deviation(design, shape["positions"])
    return tw, bd, dev["rmsd_nm"]


def realize(base, marks):
    return car.apply_marks(base, marks)


def add_delta(marks, hid, x, free):
    """Apply x to helix hid's mark set: x>0 → add x skips (−1) at spread free bp; x<0 → add |x|
    loops (+1).  Off crossovers/ends via `free` (already filtered)."""
    out = {h: dict(bps) for h, bps in marks.items()}
    cur = out.setdefault(hid, {})
    avail = [bp for bp in free if bp not in cur]
    picks = car._even_place(avail, abs(int(x)))
    for bp in picks:
        cur[bp] = -1 if x > 0 else +1
    if not cur:
        out.pop(hid, None)
    return out


def main():
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB, LEN, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
        hb.add_bend(0, LEN, curvature_deg_per_bp=BEND / LEN)
        hb.apply_loop_skip_deformations()
        base = ds.get_or_404().model_copy(deep=True)

    shape0 = predict_shape(base, nonlinear=False, with_rmsf=False)
    ck = car._core_keys(shape0)
    tgt = car.target_metrics(base, ck)
    tw_star = float(tgt["twist_deg"]); bd_star = float(tgt["bend_deg"])
    print(f"TARGET (intended): twist={tw_star:.2f} bend={bd_star:.2f}")

    # Under-realize: strip half the marks → a large residual for the solve to close.
    full = car.current_marks_by_helix(base)
    marks = {hid: {bp: dl for i, (bp, dl) in enumerate(sorted(bps.items())) if i % 2 == 0}
             for hid, bps in full.items()}
    helices = list(base.helices)
    forb, _ = car._forbidden_bps(base)
    free = {h.id: car.free_interior_candidates(base, h, forb[h.id]) for h in helices}

    tw0, bd0, rmsd0 = measure(realize(base, marks))
    print(f"UNDER-REALIZED baseline: twist={tw0:.2f} bend={bd0:.2f} rmsd={rmsd0:.3f} "
          f"(twist err {abs(tw0-tw_star):.2f}, bend err {abs(bd0-bd_star):.2f})")

    log = {"target": {"twist": tw_star, "bend": bd_star},
           "baseline": {"twist": tw0, "bend": bd0, "rmsd": rmsd0}, "iterations": []}

    cur_marks = marks
    cur_tw, cur_bd = tw0, bd0
    for it in range(3):
        # Build the 2xH Jacobian at the CURRENT marks (one +1 skip per helix).
        J = np.zeros((2, len(helices)))
        for j, h in enumerate(helices):
            avail = [bp for bp in free[h.id] if bp not in cur_marks.get(h.id, {})]
            if not avail:
                continue
            trial = {hh: dict(bps) for hh, bps in cur_marks.items()}
            trial.setdefault(h.id, {})[avail[len(avail) // 2]] = -1
            tw, bd, _ = measure(realize(base, trial))
            J[:, j] = [tw - cur_tw, bd - cur_bd]
        r = np.array([tw_star - cur_tw, bd_star - cur_bd])
        lam = 0.5
        x = J.T @ np.linalg.solve(J @ J.T + lam * np.eye(2), r)   # ridge min-norm
        xi = np.round(x).astype(int)
        # realize the integer per-helix deltas on top of the current marks
        trial = {hh: dict(bps) for hh, bps in cur_marks.items()}
        for j, h in enumerate(helices):
            if xi[j] != 0:
                trial = add_delta(trial, h.id, int(xi[j]), free[h.id])
        tw, bd, rmsd = measure(realize(base, trial))
        rec = {"iter": it, "x": xi.tolist(),
               "twist": tw, "bend": bd, "rmsd": rmsd,
               "twist_err": abs(tw - tw_star), "bend_err": abs(bd - bd_star)}
        log["iterations"].append(rec)
        print(f"  iter{it}: x={xi.tolist()} → twist={tw:.2f} (err {abs(tw-tw_star):.2f}) "
              f"bend={bd:.2f} (err {abs(bd-bd_star):.2f}) rmsd={rmsd:.3f}")
        # accept if it reduces the combined shape error
        if abs(tw - tw_star) + abs(bd - bd_star) < abs(cur_tw - tw_star) + abs(cur_bd - bd_star) - 1e-6:
            cur_marks, cur_tw, cur_bd = trial, tw, bd
        else:
            print("  (no improvement — stop)")
            break
        if abs(cur_tw - tw_star) < 1.0 and abs(cur_bd - bd_star) < 2.0:
            print("  within tol (twist<1°, bend<2°) — done")
            break

    log["final"] = {"twist": cur_tw, "bend": cur_bd,
                    "twist_err": abs(cur_tw - tw_star), "bend_err": abs(cur_bd - bd_star),
                    "n_marks": sum(len(v) for v in cur_marks.values())}
    json.dump(log, open(os.path.join(RES, "jacobian_validation.json"), "w"), indent=2)
    print(f"\nFINAL: twist {cur_tw:.2f}/{tw_star:.2f}  bend {cur_bd:.2f}/{bd_star:.2f}  "
          f"(from twist err {abs(tw0-tw_star):.2f}→{abs(cur_tw-tw_star):.2f}, "
          f"bend err {abs(bd0-bd_star):.2f}→{abs(cur_bd-bd_star):.2f})")


if __name__ == "__main__":
    main()
