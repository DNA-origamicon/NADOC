"""exp34c — burn-in / equilibration validation across d+x, WARM-STARTED from existing runs.

The 80M run (run_longrun.py) showed the 3×6×400 square bundle's global twist has a ~8M-step
EQUILIBRATION transient, after which it decorrelates fast (τ≈1 frame).  This validates that
across skip counts and builds the EQUILIBRATED twist-vs-count curve — cheaply, by CONTINUING the
already-simulated Gate runs instead of cold-rebuilding:

  d+3 (204 skips): warm-start from g1_incr_d+3   job 5627e9498f00  (+16M production)
  d+4 (222 skips): warm-start from g0_noise_rep3  job 162d32982388  (+16M production)
  d+5 (240 skips): REUSE the 80M run's per-frame series (no new sim)

Each warm-start = copy the archived job back, clear its archived flag, `append_production` more
2M rounds (continues the trajectory from its last frame — same 20k-step frame spacing as the
original), then `read_twist_series` over the full pooled trajectory and `detect_equilibration` to
split off the burn-in.  The archive copy is left intact; the working copy is deleted after metrics
are extracted (disk-bounded — one design resident at a time).

  python run_burnin.py --backend CUDA --device 0 --append-rounds 8
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import socket
import sys
import time
from argparse import Namespace

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent / "exp31_skip_twist_curvature_sweep"))

import run as R  # noqa: E402

from backend.api.headless_oxdna_build import (  # noqa: E402
    append_production, read_twist_series, wait_for_terminal,
)
from backend.api.skip_twist_tuning import core_reference_geometry  # noqa: E402
from backend.core.models import Design  # noqa: E402
from backend.core.oxdna_health import detect_equilibration  # noqa: E402

import plot34 as plot  # noqa: E402

RESULTS_DIR = HERE / "results"
PROFILE_DIR = RESULTS_DIR / "profiles"
CURRENT_JSON = RESULTS_DIR / "current.json"
RESULT_JSON = RESULTS_DIR / "burnin_results.json"
MONITOR_LOG = HERE / "MONITOR_LOG.md"
ARCHIVE = pathlib.Path("/media/jojo/Archive/NADOC_archive/exp34_finetune_validation")
WS = HERE / "ws_burnin"

# d+x → (skips, warm-start source job, existing-series reuse path)
TARGETS = [
    {"label": "burnin_d+3", "delta": 3, "skips": 204, "src_job": "5627e9498f00", "reuse": None},
    {"label": "burnin_d+4", "delta": 4, "skips": 222, "src_job": "162d32982388", "reuse": None},
    {"label": "burnin_d+5", "delta": 5, "skips": 240, "src_job": None,
     "reuse": "twistseries_longrun_d+5_80M.json"},
]


def _log(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | {msg} |\n")


def _warm_restore(job_id: str) -> bool:
    """Copy an archived job back into WS and clear its archived flag so it can be appended to.
    Leaves the archive copy intact (we delete the working copy after, not the archive)."""
    src = ARCHIVE / job_id
    dest = WS / "oxdna_jobs" / job_id
    if dest.exists():
        return True
    if not src.exists():
        _log(f"WARM-RESTORE MISSING archive {src}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    jf = dest / "job.json"
    d = json.loads(jf.read_text())
    d["archived"] = False
    d["archive_path"] = None
    jf.write_text(json.dumps(d, indent=2))
    return True


def _emit_record(records, rec):
    records.append(rec)
    RESULT_JSON.write_text(json.dumps(records, indent=2))


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def _series_to_record(label, skips, delta, ts, n_frames, wall_s=None):
    eq = ts.get("equilibrated") or {}
    eqs = {k: _r(v) for k, v in (eq.get("stats") or {}).items()}
    raw = {k: _r(v) for k, v in (ts.get("stats") or {}).items()}
    return {
        "label": label, "total_skips": skips, "delta": delta, "status": "ok",
        "n_frames": n_frames, "wall_s": wall_s,
        "twist_series": {  # full-series (raw) for the panel
            "mean": raw.get("mean"), "std": raw.get("std"), "sem": raw.get("sem"),
            "tau_int": raw.get("tau_int"), "n_eff": raw.get("n_eff"),
            "twist_on_mean_structure": ts.get("twist_on_mean_structure"), "n_frames": n_frames},
        "equilibrated": {  # post-burn-in (the trustworthy number)
            "t0_frames": eq.get("t0"), "mean": eqs.get("mean"), "sem": eqs.get("sem"),
            "std": eqs.get("std"), "tau_int": eqs.get("tau_int"), "n_eff": eqs.get("n_eff")},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="CUDA"); ap.add_argument("--device", default="0")
    ap.add_argument("--steps-per-s", type=float, default=2551.7)
    ap.add_argument("--append-rounds", type=int, default=8, help="2M rounds to append (8 → +16M)")
    ap.add_argument("--round-steps", type=int, default=2_000_000)
    args = ap.parse_args()

    WS.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    records = json.loads(RESULT_JSON.read_text()) if RESULT_JSON.exists() else []
    done = {r["label"] for r in records}
    _log(f"BURNIN start: append_rounds={args.append_rounds} (+{args.append_rounds*args.round_steps/1e6:.0f}M) "
         f"resume_done={sorted(done)}")

    for tgt in TARGETS:
        label = tgt["label"]
        if label in done:
            continue

        if tgt["reuse"]:                                   # d+5 — reuse the 80M series, no sim
            p = PROFILE_DIR / tgt["reuse"]
            if not p.exists():
                _log(f"{label} REUSE MISSING {p} — skipping"); continue
            ts = json.loads(p.read_text())
            ts["equilibrated"] = detect_equilibration(ts["twist_per_frame"])
            (PROFILE_DIR / f"twistseries_{label}.json").write_text(json.dumps(ts))
            rec = _series_to_record(label, tgt["skips"], tgt["delta"], ts, ts.get("n_frames"))
            _emit_record(records, rec)
            eq = rec["equilibrated"]
            _log(f"{label} REUSE 80M: equilibrated twist={eq['mean']:.1f}±{eq['sem']:.1f}° "
                 f"(burn-in t0={eq['t0_frames']}f, N_eff={eq['n_eff']:.0f})")
            try:
                plot.save_twistseries_png(rec)
            except Exception as e:  # noqa: BLE001
                _log(f"{label} PLOT WARN {e}")
            continue

        # warm-started designs (d+3, d+4)
        job_id = tgt["src_job"]
        _log(f"{label} START warm-restore job {job_id} (+{args.append_rounds} rounds)")
        CURRENT_JSON.write_text(json.dumps({"label": label, "total_skips": tgt["skips"],
                                            "job_id": job_id, "workspace": str(WS),
                                            "host": socket.gethostname(),
                                            "started_at": time.time()}, indent=2))
        if not _warm_restore(job_id):
            _emit_record(records, {"label": label, "status": "restore_failed", "src_job": job_id})
            continue
        jd = WS / "oxdna_jobs" / job_id
        design = Design.model_validate_json((jd / "design.json").read_text())
        t0 = time.monotonic()
        failed = False
        for i in range(args.append_rounds):
            append_production(job_id, str(WS), steps=args.round_steps)
            job = wait_for_terminal(job_id, str(WS), timeout=3600.0)  # block until the round ends
            CURRENT_JSON.write_text(json.dumps({"label": label, "total_skips": tgt["skips"],
                                                "job_id": job_id, "round": i + 1,
                                                "append_rounds": args.append_rounds,
                                                "workspace": str(WS),
                                                "started_at": t0}, indent=2))
            if job.status.value != "completed":
                _log(f"{label} round {i+1} {job.status.value} — stopping appends, measuring what exists")
                failed = True
                break
        ts = read_twist_series(job_id, str(WS), design, core_reference_geometry(design))
        wall = round(time.monotonic() - t0, 1)
        if not ts.get("ready"):
            _emit_record(records, {"label": label, "status": "series_failed", "src_job": job_id})
            shutil.rmtree(jd, ignore_errors=True)
            continue
        (PROFILE_DIR / f"twistseries_{label}.json").write_text(json.dumps(ts))
        rec = _series_to_record(label, tgt["skips"], tgt["delta"], ts, ts.get("n_frames"), wall)
        _emit_record(records, rec)
        eq = rec["equilibrated"]
        _log(f"{label} DONE: full-series mean={rec['twist_series']['mean']:.1f}° "
             f"→ EQUILIBRATED twist={eq['mean']:.1f}±{eq['sem']:.1f}° (burn-in t0={eq['t0_frames']}f"
             f"={(eq['t0_frames'] or 0)*args.round_steps/100/1e6:.1f}M, τ={eq['tau_int']:.1f}, "
             f"N_eff={eq['n_eff']:.0f}/{ts.get('n_frames')}) [{wall}s]")
        try:
            plot.save_twistseries_png(rec)
        except Exception as e:  # noqa: BLE001
            _log(f"{label} PLOT WARN {e}")
        shutil.rmtree(jd, ignore_errors=True)              # free disk; archive copy stays intact

    # equilibrated twist-vs-count summary
    try:
        _summary_plot(records)
    except Exception as e:  # noqa: BLE001
        _log(f"SUMMARY PLOT WARN {e}")
    CURRENT_JSON.write_text(json.dumps({"job_id": None, "idle": True}))
    (RESULTS_DIR / "BURNIN_COMPLETE").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    _log("BURNIN COMPLETE")
    print("[exp34c] done.")


def _summary_plot(records) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts = sorted([r for r in records if r.get("status") == "ok" and r.get("equilibrated", {}).get("mean") is not None],
                 key=lambda r: r["total_skips"])
    if not pts:
        return
    xs = [r["total_skips"] for r in pts]
    eqm = [r["equilibrated"]["mean"] for r in pts]
    eqe = [r["equilibrated"]["sem"] or 0 for r in pts]
    rawm = [r["twist_series"]["mean"] for r in pts]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.axhline(0, color="#444", lw=0.8, ls="--", label="twist-zero target")
    ax.errorbar(xs, eqm, yerr=eqe, fmt="-o", color="#1b7837", capsize=4, lw=1.8,
                label="EQUILIBRATED twist (burn-in discarded) ± SEM")
    ax.plot(xs, rawm, "s--", color="#b2182b", alpha=0.6, label="full-series mean (incl. transient — biased)")
    for r in pts:
        ax.annotate(r["label"].replace("burnin_", ""), (r["total_skips"], r["equilibrated"]["mean"]),
                    textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.set_xlabel("total skips"); ax.set_ylabel("equilibrated net twist (deg)")
    ax.set_title("exp34c — equilibrated twist vs skip count (warm-started, burn-in discarded)")
    ax.grid(alpha=0.25); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(RESULTS_DIR / "equilibrated_twist_vs_count.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
