"""exp41 (G4) — 1×N (single-layer) and 2×N designs: the twist-degeneracy special case.

A single row of helices is COLINEAR in cross-section, so end-to-end twist is ill-defined (no 2-D
cross-section to rotate).  This confirms:
  1. `measure_bundle_twist` is degenerate/None on 1×N (cross-section point cloud has rank 1);
  2. the CURRENT square autorefine (`fem_refine`, twist objective) therefore NO-OPS on 1×N (twist
     unmeasurable → nothing to null) — it needs a BEND-objective fallback + a degeneracy guard;
  3. bend IS well-defined and controllable on 1×N (a ribbon bends), so the fallback is viable;
  4. 2×N is the boundary — twist resolvable but small/noisy (clamp).
Every structure is routing-audited + flagged (G2 caution).

Run: PYTHONPATH=. uv run python experiments/exp41_1xN_degeneracy/g4.py
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
from backend.core.crossover_positions import extract_crossovers_from_strands

SQ = LatticeType.SQUARE
LEN = 160
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RES, exist_ok=True)

SECTIONS = [("1x4", [(0, c) for c in range(4)]),
            ("1x6", [(0, c) for c in range(6)]),
            ("1x8", [(0, c) for c in range(8)]),
            ("2x4", [(r, c) for r in range(2) for c in range(4)])]   # boundary


def build(cells, name):
    with hb.scratch_session(SQ):
        hb.create_bundle(cells, LEN, lattice=SQ, name=name)
        hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
        return ds.get_or_404().model_copy(deep=True)


def audit(d):
    flags = []
    scaffolds = [s for s in d.strands if s.is_scaffold]
    if len(scaffolds) != 1:
        flags.append(f"scaffold not single ({len(scaffolds)})")
    gp = {h.id: h.grid_pos for h in d.helices}
    xos, _ = extract_crossovers_from_strands(d.strands, d.helices, d.lattice_type)
    nonadj = sum(1 for xo in xos if gp.get(xo.half_a.helix_id) and gp.get(xo.half_b.helix_id)
                 and abs(gp[xo.half_a.helix_id][0]-gp[xo.half_b.helix_id][0])
                 + abs(gp[xo.half_a.helix_id][1]-gp[xo.half_b.helix_id][1]) != 1)
    if nonadj:
        flags.append(f"{nonadj} non-adjacent crossovers")
    return flags, len(scaffolds)


def cross_section_rank(d):
    """SVD of the centered helix (x,y) cloud → (s1, s2).  s2≈0 ⇒ colinear ⇒ twist-degenerate."""
    P = np.array([[h.axis_start.x, h.axis_start.y] for h in d.helices])
    P = P - P.mean(axis=0)
    s = np.linalg.svd(P, compute_uv=False)
    return float(s[0]), float(s[1] if len(s) > 1 else 0.0)


def main():
    out = {}
    for name, cells in SECTIONS:
        d = build(cells, name)
        flags, nscaf = audit(d)
        s1, s2 = cross_section_rank(d)
        shape = predict_shape(d, nonlinear=False, with_rmsf=False)
        ck = {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}
        core = [p for p in shape["positions"] if (p["helix_id"], int(p["bp_index"])) in ck]
        # twist: does the estimator resolve?
        try:
            tw = float(measure_bundle_twist(core)); tw_err = None
        except Exception as e:
            tw = None; tw_err = str(e)
        try:
            bd = float(measure_bundle_arc_bend(core))
        except Exception:
            bd = None
        # current autorefine behavior
        res = car.fem_refine(d, nonlinear=False)
        n_marks = sum(len(v) for v in res["converged_marks"].values())

        degenerate = s2 < 1e-6 or tw is None
        out[name] = {"n_helices": len(d.helices), "flags": flags, "scaffolds": nscaf,
                     "sv": [round(s1, 3), round(s2, 3)], "colinear": s2 < 1e-6,
                     "twist_measure": tw, "twist_error": tw_err, "bend_measure": bd,
                     "twist_degenerate": degenerate,
                     "autorefine": {"objective": res.get("objective"),
                                    "twist_before": res.get("twist_before"),
                                    "twist_after": res.get("twist_after"),
                                    "n_marks": n_marks,
                                    "note": res.get("status")}}
        print(f"{name:5s} H={len(d.helices):2d} scaf={nscaf} flags={flags or 'OK'} "
              f"sv=({s1:.2f},{s2:.2f}) colinear={s2<1e-6} "
              f"twist={'None('+ (tw_err or '')[:30]+')' if tw is None else round(tw,2)} "
              f"bend={round(bd,2) if bd is not None else None} "
              f"| autorefine: obj={res.get('objective')} marks={n_marks} "
              f"tw_before={res.get('twist_before')}")
    json.dump(out, open(os.path.join(RES, "g4_results.json"), "w"), indent=2)
    print("\nwrote g4_results.json")


if __name__ == "__main__":
    main()
