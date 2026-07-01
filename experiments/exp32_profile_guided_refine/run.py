"""exp32 — profile-guided adaptive skip refinement (3×6×400 SQ).

exp31 verdict: residual twist is back-loaded, uniform density can't flatten it, deviation-field
placement is worst, incremental-gap placement is the one that drives a region to zero.  This
experiment closes the loop: start from the analytical baseline, read the twist PROFILE, and each
round add/remove deletions in the over-/under-wound axial SEGMENTS via incremental-gap, driving
the whole profile to flat-zero.  Per-segment UNDERDAMPED secant (gain>1, overshoot to bracket
zero fast); add AND remove; stop at max|profile| < --tol (default 5°) or --max-rounds (default 8).

Reuses exp31's `run.measure` (relax + 8M production → twist profile, curvature, health, archive)
and `backend.core.profile_guided_refine` (the controller).  One iterative refinement, not a grid.

  python run.py --backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import sys
import time
from argparse import Namespace

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent / "exp31_skip_twist_curvature_sweep"))  # reuse run.measure

import run as R  # noqa: E402  (exp31 driver: measure / Cfg / build helpers / archive)

from backend.core import profile_guided_refine as PGR  # noqa: E402

import plot32 as plot  # noqa: E402  (sibling; unique name to avoid exp31's plot on sys.path)

RESULTS_DIR = HERE / "results"
RESULTS_JSON = RESULTS_DIR / "results.json"
PROFILE_DIR = RESULTS_DIR / "profiles"
CURRENT_JSON = RESULTS_DIR / "current.json"
MONITOR_LOG = HERE / "MONITOR_LOG.md"
ARCHIVE = "/media/jojo/Archive/NADOC_archive/exp32_profile_guided_refine"


def _log(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not MONITOR_LOG.exists():
        MONITOR_LOG.write_text("# exp32 driver log\n\n| time | event |\n|---|---|\n")
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | {msg} |\n")


def _write_current(rnd, total, cfg, job_id, ws) -> None:
    steps = cfg.prod_steps * cfg.n_prod
    CURRENT_JSON.write_text(json.dumps({
        "strategy": "profile_refine", "delta": rnd, "total_skips": total, "job_id": job_id,
        "workspace": ws, "host": socket.gethostname(),
        "production_total_steps": steps, "steps_per_s": cfg.steps_per_s,
        "expected_wall_s": (steps / cfg.steps_per_s) if cfg.steps_per_s else None,
        "started_at": time.time()}, indent=2))


def _save(records) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(records, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="CUDA"); ap.add_argument("--device", default="0")
    ap.add_argument("--skip-benchmark", action="store_true", default=True)
    ap.add_argument("--steps-per-s", type=float, default=2551.7)
    ap.add_argument("--tol", type=float, default=5.0, help="converge when max|cumulative twist| < tol (deg)")
    ap.add_argument("--max-rounds", type=int, default=8)
    ap.add_argument("--gain", type=float, default=1.3, help=">1 underdamps (overshoot to bracket zero)")
    ap.add_argument("--n-bins", type=int, default=6,
                    help="axial segments for the controller (coarse: each must accrue ≳34°/deletion)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Borrow exp31's Cfg for the sim settings (3×6×400, 8M production, CUDA, archive).
    cfg = R.Cfg(Namespace(dry_run=args.dry_run, steps=4, backend=args.backend, device=args.device,
                          skip_benchmark=True, steps_per_s=args.steps_per_s,
                          archive_root=ARCHIVE, no_archive=False, workspace=None))
    ws = str(HERE / ("ws_dry" if args.dry_run else "ws"))
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[exp32] building bare base + bin layout ({args.n_bins} segments)…", flush=True)
    bare = R.build_sq_skip_design(cfg.cells, cfg.length, None)
    _edges, per_helix_bins = PGR.bin_layout(bare, args.n_bins)

    records = json.loads(RESULTS_JSON.read_text()) if RESULTS_JSON.exists() else []
    # Resume: reconstruct skips + secant history from the last (and prior) recorded rounds.
    if records:
        last = records[-1]
        skips = {h: list(v) for h, v in last["skips"].items()}
        prev_counts = records[-2]["bin_counts"] if len(records) >= 2 else None
        prev_lt = records[-2]["bin_local_twist"] if len(records) >= 2 else None
        start_round = last["round"] + 1
    else:
        skips = R.baseline_skips(bare, skip_period=cfg.baseline_period)   # analytical start
        prev_counts = prev_lt = None
        start_round = 0
    _log(f"start: tol={args.tol}° max_rounds={args.max_rounds} gain={args.gain} "
         f"n_bins={args.n_bins} resume_round={start_round}")

    for rnd in range(start_round, args.max_rounds + 1):
        total = sum(len(v) for v in skips.values())
        _log(f"ROUND {rnd} START ({total} skips)")
        _write_current(rnd, total, cfg, None, ws)
        t0 = time.monotonic()
        design = R.build_explicit_skip_from_design(bare, skips)
        rec = R.measure(design, ws, cfg,
                        on_job_id=lambda jid: _write_current(rnd, total, cfg, jid, ws))
        prof = rec.pop("_twist_profile", None)
        curv = rec.pop("_curvature_profile", None)
        if rec.get("status") != "ok" or prof is None:
            _log(f"ROUND {rnd} FAILED status={rec.get('status')} — stopping")
            rec.update({"round": rnd, "total_skips": total,
                        "skips": {h: sorted(v) for h, v in skips.items()}})
            records.append(rec); _save(records); break

        lt = PGR.local_twist_per_bin(prof, args.n_bins)
        cur_counts = PGR.counts_per_bin(skips, per_helix_bins)
        rec.update({"round": rnd, "total_skips": total,
                    "skips": {h: sorted(v) for h, v in skips.items()},
                    "bin_counts": cur_counts, "bin_local_twist": [round(x, 2) for x in lt],
                    "wall_s": round(time.monotonic() - t0, 1)})
        records.append(rec); _save(records)
        plot.save_profile(prof, PROFILE_DIR / f"round_{rnd}.csv", "cum_twist_diff")
        if curv:
            plot.save_profile(curv, PROFILE_DIR / f"curv_round_{rnd}.csv", "cum_curv_diff")
        plot.regenerate()
        R._archive_run(rec.get("job_id"), ws, cfg)
        flat = rec.get("twist_profile_max")
        _log(f"ROUND {rnd} DONE flat(max|prof|)={flat}° twist={rec.get('twist_diff')}° "
             f"curv={rec.get('curvature_diff')} healthy={rec.get('healthy')} ({rec.get('wall_s')}s)")

        if flat is not None and flat < args.tol:
            _log(f"CONVERGED at round {rnd}: max|profile|={flat}° < {args.tol}°"); break
        if rnd >= args.max_rounds:
            _log(f"max-rounds {args.max_rounds} reached (max|profile|={flat}°)"); break

        target = PGR.secant_targets(prev_counts, prev_lt, cur_counts, lt, gain=args.gain)
        skips = PGR.plan_edits(skips, per_helix_bins, target, min_spacing=4)
        prev_counts, prev_lt = cur_counts, lt

    CURRENT_JSON.write_text(json.dumps({"job_id": None, "idle": True}))
    (RESULTS_DIR / "COMPLETE").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    print("[exp32] done.", flush=True)


if __name__ == "__main__":
    main()
