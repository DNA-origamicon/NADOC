"""exp40 (G3) — asymmetric cross-sections: the twist↔bend coupling stress test.

An asymmetric section (L / triangle / notched block) has an OFF-CENTER neutral axis, so a UNIFORM
skip density induces BOTH twist and bend — the coupling a 1-D (twist-only) objective ignores.  This:
  1. builds each section, ROUTING-AUDITS it (single scaffold, no across-hollow xovers, full mesh) and
     SKIPS any that are mis-routed (per the G2 caution — auto_scaffold/autostaple are unvalidated here);
  2. runs the CURRENT square autorefine (`fem_refine`, twist-only) and measures the residual BEND it
     leaves (the failure mode);
  3. runs the COUPLED (twist,bend) Jacobian solve (multi-skip probe for a clean bend row) and shows it
     nulls BOTH — proving the coupled objective is necessary for asymmetric sections.

Linear FEM oracle.  Run: PYTHONPATH=. uv run python experiments/exp40_asymmetric_coupling/g3.py
"""
from __future__ import annotations

import json
import os

import numpy as np

from backend.api import headless_build as hb
from backend.api import state as ds
from backend.core.models import LatticeType
from backend.core import cando_autorefine as car
from backend.physics.fem_solver import predict_shape, build_fem_mesh
from backend.core.oxdna_health import measure_bundle_twist, measure_bundle_arc_bend
from backend.core.validator import validate_design
from backend.core.crossover_positions import extract_crossovers_from_strands

SQ = LatticeType.SQUARE
LEN = 160
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RES, exist_ok=True)

# Asymmetric square-lattice cross-sections (off-center centroid).
def Lshape():   # 4x4 corner L: full left column + full bottom row
    return sorted(set([(r, 0) for r in range(4)] + [(3, c) for c in range(4)]))
def triangle():  # staircase right triangle
    return [(r, c) for r in range(4) for c in range(r + 1)]
def notch():    # solid 4x4 minus the top-right 2x2 corner
    return [(r, c) for r in range(4) for c in range(4) if not (r < 2 and c >= 2)]

SECTIONS = [("L_4x4", Lshape()), ("triangle", triangle()), ("notch_4x4", notch())]


def build(cells, name):
    with hb.scratch_session(SQ):
        hb.create_bundle(cells, LEN, lattice=SQ, name=name)
        hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
        return ds.get_or_404().model_copy(deep=True)


def audit(d):
    flags = []
    scaffolds = [s for s in d.strands if s.is_scaffold]
    scaf_h = {dm.helix_id for s in scaffolds for dm in s.domains}
    if len(scaffolds) != 1:
        flags.append(f"scaffold not single ({len(scaffolds)})")
    if len(scaf_h) != len(d.helices):
        flags.append(f"scaffold misses {len(d.helices)-len(scaf_h)} helices")
    gp = {h.id: h.grid_pos for h in d.helices}
    xos, _ = extract_crossovers_from_strands(d.strands, d.helices, d.lattice_type)
    nonadj = sum(1 for xo in xos if gp.get(xo.half_a.helix_id) and gp.get(xo.half_b.helix_id)
                 and abs(gp[xo.half_a.helix_id][0]-gp[xo.half_b.helix_id][0])
                 + abs(gp[xo.half_a.helix_id][1]-gp[xo.half_b.helix_id][1]) != 1)
    if nonadj:
        flags.append(f"{nonadj} non-adjacent crossovers")
    if len(build_fem_mesh(d).nodes) < 0.5 * len(d.helices) * LEN:
        flags.append("under-paired mesh")
    return flags, len(scaffolds), nonadj


def measure(d):
    shape = predict_shape(d, nonlinear=False, with_rmsf=False)
    ck = {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}
    core = [p for p in shape["positions"] if (p["helix_id"], int(p["bp_index"])) in ck]
    tw = float(measure_bundle_twist(core))
    try:
        bd = float(measure_bundle_arc_bend(core))
    except Exception:
        bd = float("nan")
    return tw, bd


def coupled_solve(base, tw_star, bd_star, *, probe=4, iters=4, tol_tw=1.0, tol_bd=2.0):
    """Ridge least-squares on the measured 2xH (twist,bend) authority Jacobian, iterated.  Probe uses
    `probe` skips per helix (÷probe) so the bend row clears the estimator noise floor (G2 fix)."""
    helices = list(base.helices)
    forb, _ = car._forbidden_bps(base)
    free = {h.id: car.free_interior_candidates(base, h, forb[h.id]) for h in helices}
    cur = car.current_marks_by_helix(base)
    cur_tw, cur_bd = measure(car.apply_marks(base, cur))
    traj = [{"iter": -1, "twist": cur_tw, "bend": cur_bd}]
    for it in range(iters):
        J = np.zeros((2, len(helices)))
        for j, h in enumerate(helices):
            avail = [bp for bp in free[h.id] if bp not in cur.get(h.id, {})]
            picks = car._even_place(avail, probe)
            if not picks:
                continue
            trial = {k: dict(v) for k, v in cur.items()}
            trial.setdefault(h.id, {}).update({bp: -1 for bp in picks})
            tw, bd = measure(car.apply_marks(base, trial))
            J[:, j] = [(tw - cur_tw) / len(picks), (bd - cur_bd) / len(picks)]
        r = np.array([tw_star - cur_tw, bd_star - cur_bd])
        x = J.T @ np.linalg.solve(J @ J.T + 0.5 * np.eye(2), r)
        xi = np.round(x).astype(int)
        trial = {k: dict(v) for k, v in cur.items()}
        for j, h in enumerate(helices):
            n = int(xi[j])
            avail = [bp for bp in free[h.id] if bp not in trial.get(h.id, {})]
            for bp in car._even_place(avail, abs(n)):
                trial.setdefault(h.id, {})[bp] = -1 if n > 0 else +1
            if not trial.get(h.id):
                trial.pop(h.id, None)
        tw, bd = measure(car.apply_marks(base, trial))
        traj.append({"iter": it, "twist": tw, "bend": bd, "x": xi.tolist()})
        if abs(tw-tw_star)+abs(bd-bd_star) < abs(cur_tw-tw_star)+abs(cur_bd-bd_star) - 1e-6:
            cur, cur_tw, cur_bd = trial, tw, bd
        else:
            break
        if abs(cur_tw-tw_star) < tol_tw and abs(cur_bd-bd_star) < tol_bd:
            break
    return cur, cur_tw, cur_bd, traj


def main():
    out = {}
    for name, cells in SECTIONS:
        print(f"\n=== {name}: {len(cells)} helices  cells={cells}")
        d = build(cells, name)
        flags, nscaf, nonadj = audit(d)
        if flags:
            print(f"  ROUTING FLAGGED: {flags} — SKIPPING (untrusted)")
            out[name] = {"skipped": True, "flags": flags}
            continue
        print(f"  routing OK (scaffold={nscaf}, nonadj_xo={nonadj}, {len(d.helices)} helices)")

        shape0 = predict_shape(d, nonlinear=False, with_rmsf=False)
        tgt = car.target_metrics(d, car._core_keys(shape0))
        tw_star = float(tgt["twist_deg"]); bd_star = float(tgt["bend_deg"])
        tw0, bd0 = measure(d)
        print(f"  intended twist={tw_star:.2f} bend={bd_star:.2f} | bare FEM twist={tw0:.2f} bend={bd0:.2f}")

        # 1-D current square autorefine (twist-only) → residual bend
        res1d = car.fem_refine(d, nonlinear=False)
        m1 = car.apply_marks(d, {hid: {int(bp): int(dl) for bp, dl in bps.items()}
                                 for hid, bps in res1d["converged_marks"].items()})
        tw1, bd1 = measure(m1)
        print(f"  [1D twist-only]  twist={tw1:.2f} (err {abs(tw1-tw_star):.2f})  "
              f"bend={bd1:.2f} (err {abs(bd1-bd_star):.2f})  <- residual bend = the failure")

        # 2-D coupled solve → null both
        _, tw2, bd2, traj = coupled_solve(d, tw_star, bd_star)
        print(f"  [2D coupled]     twist={tw2:.2f} (err {abs(tw2-tw_star):.2f})  "
              f"bend={bd2:.2f} (err {abs(bd2-bd_star):.2f})")
        out[name] = {"n_helices": len(d.helices), "intended": {"twist": tw_star, "bend": bd_star},
                     "bare": {"twist": tw0, "bend": bd0},
                     "oneD": {"twist": tw1, "bend": bd1,
                              "twist_err": abs(tw1-tw_star), "bend_err": abs(bd1-bd_star)},
                     "twoD": {"twist": tw2, "bend": bd2,
                              "twist_err": abs(tw2-tw_star), "bend_err": abs(bd2-bd_star)},
                     "traj": traj}
    json.dump(out, open(os.path.join(RES, "g3_results.json"), "w"), indent=2)
    print("\nwrote g3_results.json")


if __name__ == "__main__":
    main()
