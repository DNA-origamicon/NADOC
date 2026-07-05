"""exp39 (G2) — per-helix twist/bend authority vs cross-section geometry for SQUARE tubes.

Maps whether per-helix authority (∂twist/∂skip, ∂bend/∂skip) is PREDICTABLE from geometry (each
helix's moment arm r_h about the bundle centroid, the helix count N, the diameter D) — if it is, the
generalized autorefine can SEED its authority Jacobian analytically and skip the O(H) in-loop probe.

Structures: hollow square tubes (perimeter ring) d=3,4,5,6 + solid squares d=2,3,4 for contrast.
**Every tube is ROUTING-AUDITED** (single scaffold covering all helices; crossovers only between
adjacent helices — no across-hollow links; full duplex coverage) and FLAGGED if anything is off —
the hollow auto-scaffold/autostaple path is not otherwise validated (user caution).  Note: basic
autostaple places some staple nicks ON crossovers on ALL square bundles (solid included) — a known
general realizer limitation, flagged but not hollow-specific.

Linear FEM oracle (fast); per-helix single-skip probe.  Parallel across (tube, helix).
Run:  OMP_NUM_THREADS=1 ... PYTHONPATH=. uv run python experiments/exp39_hollow_tube_authority/sweep.py
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from multiprocessing import Pool

from backend.api import headless_build as hb
from backend.api import state as ds
from backend.core.models import LatticeType
from backend.core import cando_autorefine as car

SQ = LatticeType.SQUARE
LEN = 168
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RES, exist_ok=True)


def hollow(D):
    return [(r, c) for r in range(D) for c in range(D) if r in (0, D - 1) or c in (0, D - 1)]


def solid(D):
    return [(r, c) for r in range(D) for c in range(D)]


TUBES = [
    ("hollow_d3", hollow(3), 3, True), ("hollow_d4", hollow(4), 4, True),
    ("hollow_d5", hollow(5), 5, True), ("hollow_d6", hollow(6), 6, True),
    ("solid_d2", solid(2), 2, False), ("solid_d3", solid(3), 3, False),
    ("solid_d4", solid(4), 4, False),
]

_CACHE: dict = {}


def _build(name, cells):
    if name not in _CACHE:
        with hb.scratch_session(SQ):
            hb.create_bundle(cells, LEN, lattice=SQ, name=name)
            hb.auto_scaffold(seamless=False); hb.auto_crossover(); hb.auto_break()
            _CACHE[name] = ds.get_or_404().model_copy(deep=True)
    return _CACHE[name]


def _measure(design):
    from backend.physics.fem_solver import predict_shape
    from backend.core.oxdna_health import measure_bundle_twist, measure_bundle_arc_bend
    shape = predict_shape(design, nonlinear=False, with_rmsf=False)
    ck = {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}
    core = [p for p in shape["positions"] if (p["helix_id"], int(p["bp_index"])) in ck]
    tw = float(measure_bundle_twist(core))
    try:
        bd = float(measure_bundle_arc_bend(core))
    except Exception:
        bd = float("nan")
    return tw, bd


def audit(name, cells, D, is_hollow):
    """Routing correctness for one tube — returns (design, flags, info). No FEM."""
    from backend.core.validator import validate_design
    from backend.core.crossover_positions import extract_crossovers_from_strands
    from backend.physics.fem_solver import build_fem_mesh
    d = _build(name, cells)
    flags = []
    scaffolds = [s for s in d.strands if s.is_scaffold]
    scaf_h = {dm.helix_id for s in scaffolds for dm in s.domains}
    if len(scaffolds) != 1:
        flags.append(f"scaffold not single ({len(scaffolds)})")
    if len(scaf_h) != len(d.helices):
        flags.append(f"scaffold misses {len(d.helices)-len(scaf_h)} helices")
    gp = {h.id: h.grid_pos for h in d.helices}
    xos, _ = extract_crossovers_from_strands(d.strands, d.helices, d.lattice_type)
    nonadj = sum(1 for xo in xos
                 if gp.get(xo.half_a.helix_id) and gp.get(xo.half_b.helix_id)
                 and abs(gp[xo.half_a.helix_id][0] - gp[xo.half_b.helix_id][0])
                 + abs(gp[xo.half_a.helix_id][1] - gp[xo.half_b.helix_id][1]) != 1)
    if nonadj:
        flags.append(f"{nonadj} non-adjacent crossovers (across hollow!)")
    mesh = build_fem_mesh(d)
    if len(mesh.nodes) < 0.5 * len(d.helices) * LEN:
        flags.append(f"under-paired mesh {len(mesh.nodes)}")
    errs = [r.message for r in validate_design(d).results if not r.ok]
    nick_xo = sum(1 for e in errs if "nicked at crossover" in e)
    info = {"n_helices": len(d.helices), "n_crossovers": len(xos),
            "mesh_nodes": len(mesh.nodes), "nick_on_xo_error": bool(nick_xo),
            "nonadjacent_xo": nonadj, "scaffolds": len(scaffolds)}
    return d, flags, info


def helix_moment_arm(design, hid):
    xs = [(h.axis_start.x, h.axis_start.y) for h in design.helices]
    cx = sum(x for x, _ in xs) / len(xs)
    cy = sum(y for _, y in xs) / len(xs)
    h = next(h for h in design.helices if h.id == hid)
    return math.hypot(h.axis_start.x - cx, h.axis_start.y - cy)


def _task(t):
    """(name, cells, helix_id | None) → measure baseline (None) or single-skip authority."""
    name, cells, hid = t
    d = _build(name, cells)
    if hid is None:
        tw, bd = _measure(d)
        return {"name": name, "helix": None, "twist": tw, "bend": bd}
    forb, _ = car._forbidden_bps(d)
    helix = next(h for h in d.helices if h.id == hid)
    free = car.free_interior_candidates(d, helix, forb[hid])
    if not free:
        return {"name": name, "helix": hid, "twist": None, "bend": None, "r": None}
    marks = car.current_marks_by_helix(d)
    m = {h: dict(bps) for h, bps in marks.items()}
    m.setdefault(hid, {})[free[len(free) // 2]] = -1
    tw, bd = _measure(car.apply_marks(d, m))
    return {"name": name, "helix": hid, "twist": tw, "bend": bd,
            "r": helix_moment_arm(d, hid)}


def main():
    # ── Routing audit pass (main process, no FEM) — FLAG every tube ──────────────────────────
    audits = {}
    print("=== ROUTING AUDIT ===")
    for name, cells, D, is_hollow in TUBES:
        _, flags, info = audit(name, cells, D, is_hollow)
        audits[name] = {"D": D, "hollow": is_hollow, "flags": flags, **info}
        tag = "OK" if not flags else "FLAGS: " + "; ".join(flags)
        print(f"  {name:11s} H={info['n_helices']:2d} xo={info['n_crossovers']:3d} "
              f"mesh={info['mesh_nodes']:4d} scaffold={info['scaffolds']} "
              f"nonadj_xo={info['nonadjacent_xo']} nick@xo={info['nick_on_xo_error']}  {tag}")
    json.dump(audits, open(os.path.join(RES, "routing_audit.json"), "w"), indent=2)

    # ── Baselines + per-helix probes (parallel FEM) ─────────────────────────────────────────
    baseline_tasks = [(name, cells, None) for name, cells, _, _ in TUBES]
    probe_tasks = [(name, cells, h.id)
                   for name, cells, _, _ in TUBES
                   for h in _build(name, cells).helices]
    print(f"\n=== FEM: {len(baseline_tasks)} baselines + {len(probe_tasks)} helix probes ===")

    with Pool(8) as pool:
        base = {r["name"]: r for r in pool.map(_task, baseline_tasks)}
        results = pool.map(_task, probe_tasks)

    rows = []
    for r in results:
        b = base[r["name"]]
        if r["twist"] is None or b["twist"] is None:
            continue
        a = audits[r["name"]]
        rows.append({
            "tube": r["name"], "D": a["D"], "hollow": a["hollow"], "n_helices": a["n_helices"],
            "helix": r["helix"], "r_nm": round(r["r"], 3) if r["r"] else None,
            "dtwist_per_skip": round(r["twist"] - b["twist"], 4),
            "dbend_per_skip": round(r["bend"] - b["bend"], 4),
            "flags": ";".join(a["flags"]),
        })
    with open(os.path.join(RES, "authority.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote authority.csv ({len(rows)} rows)")


if __name__ == "__main__":
    main()
