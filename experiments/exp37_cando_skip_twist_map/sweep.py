"""exp37 — CanDo-FEM skip-vs-twist landscape map for the 3x6x400 square strut.

Maps how PERTURBING the skip count around the current autorefine best-guess (the saved
``3x6x400_Sq_test.nadoc``: 10 skips/helix, 180 total, FINE FEM twist ~14°) changes the global
end-to-end twist, bend, and deviation.  Two sweeps, both around the best guess:

  * UNIFORM (diagonal) — every helix set to the same count n; the main lever to drive twist→0.
  * AXES (per-helix)   — one helix perturbed by ±δ skips, the other 17 held at best-guess; the
                          per-helix control-authority (∂twist/∂count) map ("one helix at a time").

Skip PLACEMENT is provably twist-irrelevant on the FEM oracle (probe: <0.2° across
baseline/even/front/back at fixed count), so each helix's n skips are placed EVENLY over its free
interior (off crossovers/ends), isolating COUNT as the axis.

Solver = FINE (nonlinear corotational, ~233 s/solve on this 14040-node design) per the user.  253
solves ⇒ ~16 h serial, so the sweep runs a MULTIPROCESS pool (independent solves, single-threaded
each) and is fully checkpointed + watchdog'd:
  * every solved row is appended-and-flushed to results/*.csv immediately (main process writes);
  * a resume pass skips rows already present, so a kill/restart continues where it stopped;
  * results/heartbeat.json is rewritten each completion with progress + ETA;
  * every solve is wrapped — an exception logs an error row and the pool keeps going.

BLAS is pinned to 1 thread/worker (set the env before launch: OMP_NUM_THREADS=1 etc.) so the
workers don't oversubscribe the 12 cores.

Three-Layer Law: reads topology, predicts a Physical-layer shape, writes only CSV; never mutates
the design.  Run (from repo root):
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  PYTHONPATH=. uv run python experiments/exp37_cando_skip_twist_map/sweep.py
"""
from __future__ import annotations

import csv
import json
import os
import time
import traceback
from multiprocessing import Pool

from backend.core.models import Design

# ── Config ──────────────────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
DESIGN_PATH = "workspace/3x6x400_Sq_test.nadoc"
NONLINEAR = True
N_STEPS = 20
N_WORKERS = 8                                       # 12 cores, ~2 GB/solve → 8 keeps <20 GB
# Fine (step 1) across the twist→0 crossing band (~12-13/helix), coarse in the tails.
UNIFORM_COUNTS = [4, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 24, 28, 32, 36, 40]
AXIS_DELTAS = [-8, -6, -4, -2, -1, +1, +2, +4, +6, +8, +12, +16, +20]

os.makedirs(RES, exist_ok=True)

# ── Per-worker cached state (set in the pool initializer) ────────────────────────────────────
_G: dict = {}


def _init_worker():
    from backend.core.cando_autorefine import _forbidden_bps, free_interior_candidates
    d = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())
    base_marks = {h.id: {ls.bp_index: ls.delta for ls in h.loop_skips}
                  for h in d.helices if h.loop_skips}
    forbidden, _ = _forbidden_bps(d)
    hb = {h.id: h for h in d.helices}
    free = {h.id: free_interior_candidates(d, hb[h.id], forbidden[h.id]) for h in d.helices}
    _G.update(design=d, base_marks=base_marks,
              base_count={h.id: len(base_marks.get(h.id, {})) for h in d.helices},
              free=free, helix_ids=[h.id for h in d.helices])


def even_place(free, n):
    """n evenly-spaced bp from the sorted free-interior list (placement is twist-irrelevant;
    even spacing just makes it deterministic)."""
    free = sorted(free)
    if n <= 0 or not free:
        return []
    if n >= len(free):
        return list(free)
    idx = [round(i * (len(free) - 1) / (n - 1)) if n > 1 else (len(free) // 2) for i in range(n)]
    return sorted({free[i] for i in idx})


def measure(design, marks):
    """One FINE FEM solve on ``design`` carrying ``marks`` → twist / bend / deviation."""
    from backend.physics.fem_solver import predict_shape
    from backend.core.cando_deviation import compute_deviation
    from backend.core.oxdna_health import measure_bundle_twist, measure_bundle_arc_bend
    from backend.core.cando_autorefine import apply_marks
    t0 = time.time()
    dd = apply_marks(design, marks)
    shape = predict_shape(dd, nonlinear=NONLINEAR, n_steps=N_STEPS, with_rmsf=False)
    ck = {(a["helix_id"], int(a["bp_index"])) for a in shape.get("axis", [])}
    core = [p for p in shape["positions"] if (p["helix_id"], int(p["bp_index"])) in ck]
    tw = measure_bundle_twist(core)
    try:
        bd = float(measure_bundle_arc_bend(core))
    except Exception:  # noqa: BLE001
        bd = None
    dev = compute_deviation(dd, shape["positions"])
    return {"twist_deg": round(tw, 3), "bend_deg": (round(bd, 3) if bd is not None else None),
            "rmsd_nm": round(dev["rmsd_nm"], 4), "dev_max_nm": round(dev["max_deviation"], 4),
            "dev_mean_nm": round(dev["mean_deviation"], 4), "n_core": len(core),
            "solve_s": round(time.time() - t0, 1)}


def _run_task(task):
    """Worker entry: build marks for the task from cached globals, solve, return a result row.
    Never raises — a failed solve returns an error row (watchdog)."""
    try:
        d, base_marks, free = _G["design"], _G["base_marks"], _G["free"]
        if task["sweep"] == "uniform":
            n = task["count"]
            marks = {hid: {bp: -1 for bp in even_place(free[hid], n)} for hid in _G["helix_ids"]}
        else:
            hid = task["helix"]
            marks = {k: dict(v) for k, v in base_marks.items()}
            placed = even_place(free[hid], task["count"])
            if placed:
                marks[hid] = {bp: -1 for bp in placed}
            else:
                marks.pop(hid, None)
        marks = {k: v for k, v in marks.items() if v}
        m = measure(d, marks)
        return {**task, "total_skips": sum(len(v) for v in marks.values()), "error": "", **m}
    except Exception:  # noqa: BLE001 — watchdog
        return {**task, "total_skips": "", "twist_deg": "", "bend_deg": "", "rmsd_nm": "",
                "dev_max_nm": "", "dev_mean_nm": "", "n_core": "", "solve_s": "",
                "error": traceback.format_exc().splitlines()[-1]}


def load_done(path, keycols):
    done = set()
    if os.path.isfile(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("error"):
                    continue
                done.add(tuple(str(row[k]) for k in keycols))
    return done


def append_row(path, header, row):
    new = not os.path.isfile(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def main():
    d = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())
    base_count = {h.id: len(h.loop_skips) for h in d.helices}
    helix_ids = [h.id for h in d.helices]
    from backend.core.cando_autorefine import _forbidden_bps, free_interior_candidates
    forbidden, _ = _forbidden_bps(d)
    hb = {h.id: h for h in d.helices}
    free = {h.id: free_interior_candidates(d, hb[h.id], forbidden[h.id]) for h in d.helices}

    json.dump({"design": DESIGN_PATH, "n_helices": len(d.helices),
               "helix_length_bp": {h.id: h.length_bp for h in d.helices},
               "base_count": base_count, "total_base_skips": sum(base_count.values()),
               "nonlinear": NONLINEAR, "n_steps": N_STEPS, "n_workers": N_WORKERS,
               "uniform_counts": UNIFORM_COUNTS, "axis_deltas": AXIS_DELTAS,
               "free_candidates": {k: len(v) for k, v in free.items()}},
              open(os.path.join(RES, "metadata.json"), "w"), indent=2)

    u_path = os.path.join(RES, "uniform.csv")
    a_path = os.path.join(RES, "axes.csv")
    u_header = ["sweep", "count", "total_skips", "twist_deg", "bend_deg", "rmsd_nm",
                "dev_max_nm", "dev_mean_nm", "n_core", "solve_s", "error"]
    a_header = ["sweep", "helix", "delta", "count", "total_skips", "twist_deg", "bend_deg",
                "rmsd_nm", "dev_max_nm", "dev_mean_nm", "n_core", "solve_s", "error"]
    u_done = load_done(u_path, ["count"])
    a_done = load_done(a_path, ["helix", "delta"])

    # Build the task list (uniform first — the twist→0 crossing is the headline), skip done.
    tasks = []
    for n in UNIFORM_COUNTS:
        if (str(n),) not in u_done:
            tasks.append({"sweep": "uniform", "count": n})
    for hid in helix_ids:
        for delta in AXIS_DELTAS:
            n = base_count[hid] + delta
            if n < 0 or (hid, str(delta)) in a_done:
                continue
            tasks.append({"sweep": "axis", "helix": hid, "delta": delta, "count": n})

    total = len(tasks)
    print(f"exp37 sweep: {total} FINE solves on {N_WORKERS} workers "
          f"(~{total * 233 / N_WORKERS / 3600:.1f} h wall). Resuming skips "
          f"{len(u_done) + len(a_done)} done.")
    if not total:
        print("nothing to do — all rows present.")
        return

    t_start = time.time()
    i = 0
    with Pool(N_WORKERS, initializer=_init_worker) as pool:
        for res in pool.imap_unordered(_run_task, tasks):
            i += 1
            if res["sweep"] == "uniform":
                append_row(u_path, u_header, res)
            else:
                append_row(a_path, a_header, res)
            elapsed = time.time() - t_start
            rate = elapsed / i
            hb_ = {"done": i, "total": total, "elapsed_s": round(elapsed),
                   "eta_s": round(rate * (total - i)), "ts": time.time(),
                   "last": {k: res.get(k) for k in ("sweep", "helix", "count",
                            "twist_deg", "rmsd_nm", "error")}}
            json.dump(hb_, open(os.path.join(RES, "heartbeat.json"), "w"), indent=2)
            tag = res.get("helix", "unif")
            print(f"[{i}/{total}] {res['sweep']} {tag} count={res.get('count')} "
                  f"twist={res.get('twist_deg')} rmsd={res.get('rmsd_nm')} "
                  f"eta={rate*(total-i)/3600:.1f}h {res.get('error','')}")

    print("SWEEP COMPLETE", round(time.time() - t_start), "s")


if __name__ == "__main__":
    main()
