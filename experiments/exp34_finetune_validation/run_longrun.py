"""exp34b — 80M long-run sampling diagnostic (3×6×400 SQ, delta +5 = 240 skips).

exp34 Gate 0 found the global twist is a SLOW mode: an 8M run holds only N_eff≈4 independent
twist samples (τ_int≈100 frames), so every evaluation carries ±9°.  This run answers the single
question that decides the fix: does a 10× LONGER run raise N_eff proportionally (≈40 → "run
longer" works) or does the slow mode stay frozen (N_eff≈4 → only independent seeds help)?

ONE run at delta +5 (the Gate-1 net-twist-zero winner): relax + 80M production (8×10M rounds,
~800 frames spaced 100k steps so τ_phys≈2M steps is well resolved), then the per-frame twist
diagnostic + annotated PNG.  ~9 h on a 3080 Ti; job folder ~5 GB (archived after).

  python run_longrun.py --backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7
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
sys.path.insert(0, str(HERE.parent / "exp31_skip_twist_curvature_sweep"))

import run as R  # noqa: E402

from backend.api.headless_oxdna_build import read_twist_series  # noqa: E402
from backend.api.skip_twist_tuning import core_reference_geometry  # noqa: E402
from backend.core.skip_sweep_strategies import baseline_skips, place_incremental  # noqa: E402

import plot34 as plot  # noqa: E402

RESULTS_DIR = HERE / "results"
PROFILE_DIR = RESULTS_DIR / "profiles"
CURRENT_JSON = RESULTS_DIR / "current.json"
RESULT_JSON = RESULTS_DIR / "longrun_result.json"
MONITOR_LOG = HERE / "MONITOR_LOG.md"
ARCHIVE = "/media/jojo/Archive/NADOC_archive/exp34_finetune_validation"
LABEL = "longrun_d+5_80M"


def _log(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not MONITOR_LOG.exists():
        MONITOR_LOG.write_text("# exp34 driver log\n\n| time | event |\n|---|---|\n")
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | {msg} |\n")


def _write_current(cfg, job_id, ws) -> None:
    steps = cfg.prod_steps * cfg.n_prod
    CURRENT_JSON.write_text(json.dumps({
        "label": LABEL, "total_skips": 240, "job_id": job_id, "workspace": ws,
        "host": socket.gethostname(), "production_total_steps": steps,
        "steps_per_s": cfg.steps_per_s,
        "expected_wall_s": (steps / cfg.steps_per_s) if cfg.steps_per_s else None,
        "started_at": time.time()}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="CUDA"); ap.add_argument("--device", default="0")
    ap.add_argument("--skip-benchmark", action="store_true", default=True)
    ap.add_argument("--steps-per-s", type=float, default=2551.7)
    ap.add_argument("--delta", type=int, default=5, help="incremental delta/helix (Gate-1 net-zero winner)")
    ap.add_argument("--prod-steps", type=int, default=10_000_000)
    ap.add_argument("--n-prod", type=int, default=8, help="rounds → total = prod_steps·n_prod (default 80M)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = R.Cfg(Namespace(dry_run=args.dry_run, steps=4, backend=args.backend, device=args.device,
                          skip_benchmark=True, steps_per_s=args.steps_per_s,
                          archive_root=ARCHIVE, no_archive=False, workspace=None))
    if not args.dry_run:                      # override exp31's 8M default → long run
        cfg.prod_steps, cfg.n_prod = args.prod_steps, args.n_prod
    ws = str(HERE / ("ws_longrun_dry" if args.dry_run else "ws_longrun"))
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if RESULT_JSON.exists():
        _log(f"{LABEL}: result already present — nothing to do (delete to re-run)")
        print("[exp34b] already done."); return

    total_steps = cfg.prod_steps * cfg.n_prod
    _log(f"{LABEL} START: delta +{args.delta} (240 skips), production {total_steps:,} steps "
         f"({cfg.n_prod}×{cfg.prod_steps:,}), eta ~{total_steps/cfg.steps_per_s/3600:.1f}h")
    _write_current(cfg, None, ws)

    bare = R.build_sq_skip_design(cfg.cells, cfg.length, None)
    base = baseline_skips(bare, skip_period=cfg.baseline_period)
    skips = place_incremental(bare, base, args.delta)
    design = R.build_explicit_skip_from_design(bare, skips)

    t0 = time.monotonic()
    rec = R.measure(design, ws, cfg, on_job_id=lambda jid: _write_current(cfg, jid, ws))
    prof = rec.pop("_twist_profile", None)
    curv = rec.pop("_curvature_profile", None)
    rec.update({"label": LABEL, "total_skips": 240, "delta": args.delta,
                "production_total_steps": total_steps,
                "skips": {h: sorted(v) for h, v in skips.items()},
                "wall_s": round(time.monotonic() - t0, 1)})
    if prof:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        (PROFILE_DIR / f"{LABEL}.json").write_text(json.dumps(prof))
        rec["_prof_path"] = str(PROFILE_DIR / f"{LABEL}.json")
    if curv:
        (PROFILE_DIR / f"curv_{LABEL}.json").write_text(json.dumps(curv))

    if rec.get("status") == "ok" and rec.get("job_id"):
        try:
            ts = read_twist_series(rec["job_id"], ws, design, core_reference_geometry(design))
            if ts.get("ready"):
                (PROFILE_DIR / f"twistseries_{LABEL}.json").write_text(json.dumps(ts))
                st = ts.get("stats") or {}
                rec["twist_series"] = {
                    "mean": st.get("mean"), "std": st.get("std"), "sem": st.get("sem"),
                    "tau_int": st.get("tau_int"), "n_eff": st.get("n_eff"),
                    "twist_on_mean_structure": ts.get("twist_on_mean_structure"),
                    "n_frames": ts.get("n_frames")}
                _log(f"{LABEL} TWIST-SERIES mean={st.get('mean'):.1f}±{st.get('sem'):.1f}° "
                     f"std={st.get('std'):.1f}° τ={st.get('tau_int'):.1f} "
                     f"N_eff={st.get('n_eff'):.1f}/{ts.get('n_frames')} | "
                     f"VERDICT: {'run-longer WORKS (N_eff scaled)' if (st.get('n_eff') or 0) > 20 else 'FROZEN — need seeds'}")
        except Exception as e:                # noqa: BLE001
            _log(f"{LABEL} TWIST-SERIES WARN {e}")

    RESULT_JSON.write_text(json.dumps(rec, indent=2))
    try:
        plot.save_run_png(rec)
    except Exception as e:                    # noqa: BLE001
        _log(f"{LABEL} PLOT WARN {e}")
    R._archive_run(rec.get("job_id"), ws, cfg)
    _log(f"{LABEL} DONE status={rec.get('status')} profmax={rec.get('twist_profile_max')}° "
         f"twist={rec.get('twist_diff')}° healthy={rec.get('healthy')} ({rec.get('wall_s')}s)")
    CURRENT_JSON.write_text(json.dumps({"job_id": None, "idle": True}))
    print("[exp34b] done.")


if __name__ == "__main__":
    main()
