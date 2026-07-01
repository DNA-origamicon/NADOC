"""exp34 — validate the corrected square-lattice autorefine (3×6×400 SQ).

exp31 showed placement is the lever: incremental-gap @ delta +4 (222 skips) reached net twist
−3° AND max|profile| 5° in one shot, while uniform-restagger stayed at 46°/52°.  exp32 showed a
per-segment MIMO controller diverges (LESSONS A7).  So the recommended algorithm is just the
scalar net-twist COUNT secant + INCREMENTAL-GAP placement — no per-segment optimizer.

This driver tests that, and measures the one thing exp31/exp32 never did — the per-run NOISE
FLOOR — in cheap→expensive kill-gated order:

  Gate 0  NOISE   re-sim the IDENTICAL incremental+4 design K times → σ(max|profile|), δ_min=2σ.
  Gate 1  SECANT  re-measure incremental delta +3/+4/+5 → does the net-twist-null delta coincide
                  with the flat-profile minimum, within δ_min?
  Gate 2  FINETUNE (only if Gate 1 leaves residual > δ_min) greedy ≤5 single-skip edits at the
                  worst SIGNED-local-twist site; accept iff Δmax|profile| > δ_min and |twist|≤tol.

Reuses exp31's run.measure (relax + 8M-pooled production → metrics + archive) and
backend.core.{skip_sweep_strategies, profile_guided_refine}.  Resume-safe via results.json.

  python run.py --backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import statistics
import sys
import time
from argparse import Namespace

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent / "exp31_skip_twist_curvature_sweep"))  # reuse run.measure

import run as R  # noqa: E402  (exp31 driver: measure / Cfg / build helpers / archive)

from backend.api.headless_oxdna_build import read_twist_series  # noqa: E402
from backend.api.skip_twist_tuning import core_reference_geometry  # noqa: E402
from backend.core import profile_guided_refine as PGR  # noqa: E402
from backend.core.skip_sweep_strategies import baseline_skips, place_incremental  # noqa: E402

import plot34 as plot  # noqa: E402  (sibling: per-run annotated PNGs + overview)

RESULTS_DIR = HERE / "results"
RESULTS_JSON = RESULTS_DIR / "results.json"
PROFILE_DIR = RESULTS_DIR / "profiles"
CURRENT_JSON = RESULTS_DIR / "current.json"
MONITOR_LOG = HERE / "MONITOR_LOG.md"
ARCHIVE = "/media/jojo/Archive/NADOC_archive/exp34_finetune_validation"


def _log(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not MONITOR_LOG.exists():
        MONITOR_LOG.write_text("# exp34 driver log\n\n| time | event |\n|---|---|\n")
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | {msg} |\n")


def _write_current(label, total, cfg, job_id, ws) -> None:
    steps = cfg.prod_steps * cfg.n_prod
    CURRENT_JSON.write_text(json.dumps({
        "label": label, "total_skips": total, "job_id": job_id, "workspace": ws,
        "host": socket.gethostname(), "production_total_steps": steps,
        "steps_per_s": cfg.steps_per_s,
        "expected_wall_s": (steps / cfg.steps_per_s) if cfg.steps_per_s else None,
        "started_at": time.time()}, indent=2))


def _save(records) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(records, indent=2))


def _done_labels(records) -> set[str]:
    return {r["label"] for r in records if r.get("status") == "ok"}


def _measure_one(label, skips, bare, ws, cfg, records) -> dict:
    """Build → measure one design, tag with ``label``, persist + archive.  Resume-safe."""
    total = sum(len(v) for v in skips.values())
    _log(f"{label} START ({total} skips)")
    _write_current(label, total, cfg, None, ws)
    t0 = time.monotonic()
    design = R.build_explicit_skip_from_design(bare, skips)
    rec = R.measure(design, ws, cfg, on_job_id=lambda jid: _write_current(label, total, cfg, jid, ws))
    prof = rec.pop("_twist_profile", None)
    curv = rec.pop("_curvature_profile", None)
    rec.update({"label": label, "total_skips": total,
                "skips": {h: sorted(v) for h, v in skips.items()},
                "wall_s": round(time.monotonic() - t0, 1)})
    if prof:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        (PROFILE_DIR / f"{label}.json").write_text(json.dumps(prof))
        rec["_prof_path"] = str(PROFILE_DIR / f"{label}.json")
    if curv:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        (PROFILE_DIR / f"curv_{label}.json").write_text(json.dumps(curv))
    # τ-diagnostic: per-FRAME twist series (vs twist on the time-mean structure) — reveals how
    # many effectively-independent twist samples the 8M run actually holds.  Read BEFORE archive
    # (it moves the trajectory off-disk).  Best-effort: a read failure never loses the data point.
    if rec.get("status") == "ok" and rec.get("job_id"):
        try:
            ts = read_twist_series(rec["job_id"], ws, design, core_reference_geometry(design))
            if ts.get("ready"):
                PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                (PROFILE_DIR / f"twistseries_{label}.json").write_text(json.dumps(ts))
                st = ts.get("stats") or {}
                rec["twist_series"] = {
                    "mean": st.get("mean"), "std": st.get("std"), "sem": st.get("sem"),
                    "tau_int": st.get("tau_int"), "n_eff": st.get("n_eff"),
                    "twist_on_mean_structure": ts.get("twist_on_mean_structure"),
                    "n_frames": ts.get("n_frames")}
                _log(f"{label} TWIST-SERIES mean={st.get('mean'):.1f}±{st.get('sem'):.1f}° "
                     f"(std {st.get('std'):.1f}°, τ={st.get('tau_int'):.1f}, "
                     f"N_eff={st.get('n_eff'):.1f}/{ts.get('n_frames')}) | "
                     f"on-mean-structure={ts.get('twist_on_mean_structure')}°")
        except Exception as e:                # noqa: BLE001
            _log(f"{label} TWIST-SERIES WARN {e}")
    records.append(rec); _save(records)
    try:
        plot.save_run_png(rec)            # annotated per-run PNG (twist+curv profile + WC health)
        plot.save_overview(records)       # combined twist-profile overview
    except Exception as e:                # noqa: BLE001 — never lose a sim over a plotting error
        _log(f"{label} PLOT WARN {e}")
    R._archive_run(rec.get("job_id"), ws, cfg)
    _log(f"{label} DONE status={rec.get('status')} profmax={rec.get('twist_profile_max')}° "
         f"twist={rec.get('twist_diff')}° curv={rec.get('curvature_diff')} "
         f"healthy={rec.get('healthy')} ({rec.get('wall_s')}s)")
    return rec


def _load_prof(rec) -> list[dict] | None:
    p = rec.get("_prof_path")
    if p and pathlib.Path(p).exists():
        return json.loads(pathlib.Path(p).read_text())
    return None


# ── Gate 2 helper: ONE signed-twist single-skip edit (NOT exp32's per-segment secant) ──────────
def _worst_signed_edit(skips, bare, per_helix_bins, prof, n_bins, *, min_spacing=4):
    """Propose ONE single-skip edit at the worst SIGNED-local-twist bin: ADD at the largest gap in
    the most over-wound bin (local twist > 0), or REMOVE the smallest-gap mark in the most
    under-wound bin.  Returns (new_skips, descr) or (None, None) if no legal move."""
    lt = PGR.local_twist_per_bin(prof, n_bins)
    order = sorted(range(n_bins), key=lambda i: abs(lt[i]), reverse=True)
    new = {h: list(v) for h, v in skips.items()}
    for i in order:
        over = lt[i] > 0
        # pick the helix in bin i with the most actionable site
        best = None
        for hid, bins in per_helix_bins.items():
            cand = bins[i]
            if not cand:
                continue
            present = sorted(b for b in new.get(hid, []) if cand[0] <= b <= cand[-1])
            if over:
                bp = PGR._largest_gap_free(present, cand, set(new.get(hid, [])), min_spacing)
                if bp is not None:
                    best = (hid, bp, "add", abs(lt[i])); break
            elif present:
                bp = PGR._smallest_gap_member(present, cand)
                best = (hid, bp, "remove", abs(lt[i])); break
        if best is None:
            continue
        hid, bp, op, mag = best
        if op == "add":
            new[hid] = sorted(set(new.get(hid, [])) | {bp})
        else:
            new[hid] = [b for b in new.get(hid, []) if b != bp]
            if not new[hid]:
                del new[hid]
        return new, {"helix": hid, "bp": int(bp), "op": op, "bin": i, "local_twist": round(lt[i], 1)}
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="CUDA"); ap.add_argument("--device", default="0")
    ap.add_argument("--skip-benchmark", action="store_true", default=True)
    ap.add_argument("--steps-per-s", type=float, default=2551.7)
    ap.add_argument("--converged-delta", type=int, default=4,
                    help="incremental delta/helix that nulled net twist in exp31 (222 skips)")
    ap.add_argument("--noise-reps", type=int, default=4, help="Gate 0: identical re-sims for σ")
    ap.add_argument("--n-bins", type=int, default=6, help="Gate 2 axial bins for the signed-twist proposer")
    ap.add_argument("--max-edits", type=int, default=5, help="Gate 2 fine-tune budget")
    ap.add_argument("--tol", type=float, default=5.0, help="net-twist tolerance (deg)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = R.Cfg(Namespace(dry_run=args.dry_run, steps=4, backend=args.backend, device=args.device,
                          skip_benchmark=True, steps_per_s=args.steps_per_s,
                          archive_root=ARCHIVE, no_archive=False, workspace=None))
    ws = str(HERE / ("ws_dry" if args.dry_run else "ws"))
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[exp34] building bare base + bin layout ({args.n_bins} bins)…", flush=True)
    bare = R.build_sq_skip_design(cfg.cells, cfg.length, None)
    base = baseline_skips(bare, skip_period=cfg.baseline_period)
    conv = place_incremental(bare, base, args.converged_delta)   # the incremental-converged design
    _edges, per_helix_bins = PGR.bin_layout(R.build_explicit_skip_from_design(bare, conv), args.n_bins)

    records = json.loads(RESULTS_JSON.read_text()) if RESULTS_JSON.exists() else []
    done = _done_labels(records)
    _log(f"start: conv_delta=+{args.converged_delta} noise_reps={args.noise_reps} "
         f"n_bins={args.n_bins} max_edits={args.max_edits} resume_done={len(done)}")

    # ── Gate 0 — NOISE FLOOR (keystone) ───────────────────────────────────────────────────────
    for k in range(args.noise_reps):
        lbl = f"g0_noise_rep{k}"
        if lbl not in done:
            _measure_one(lbl, conv, bare, ws, cfg, records)
    noise = [r for r in records if r.get("label", "").startswith("g0_noise") and r.get("status") == "ok"]
    pm = [r["twist_profile_max"] for r in noise]
    tw = [r["twist_diff"] for r in noise]
    sigma = statistics.pstdev(pm) if len(pm) >= 2 else float("nan")
    delta_min = 2 * sigma
    _log(f"GATE0 max|prof| mean={statistics.fmean(pm):.1f}° σ={sigma:.1f}° → δ_min={delta_min:.1f}° "
         f"| net twist mean={statistics.fmean(tw):.1f}° σ={statistics.pstdev(tw) if len(tw)>=2 else float('nan'):.1f}°")
    kill = len(pm) >= 2 and sigma >= 15.0
    if kill:
        _log("GATE0 KILL: σ(max|prof|) ≥ 15° — fine-tuning is below noise; recommend "
             "count-secant + incremental placement, NO fine-tuner. Skipping Gate 2.")

    # ── Gate 1 — does the net-twist-null delta coincide with the flat-profile minimum? ─────────
    for d in (args.converged_delta - 1, args.converged_delta, args.converged_delta + 1):
        lbl = f"g1_incr_d{d:+d}"
        if lbl not in done:
            _measure_one(lbl, place_incremental(bare, base, d), bare, ws, cfg, records)
    g1 = {r["label"]: r for r in records if r.get("label", "").startswith("g1_incr") and r.get("status") == "ok"}
    conv_rec = next((r for r in records if r.get("label") == "g0_noise_rep0" and r.get("status") == "ok"), None)
    residual = statistics.fmean(pm) if pm else None
    _log(f"GATE1 residual max|prof| at conv delta = {residual:.1f}° (δ_min={delta_min:.1f}°); "
         f"neighbors: " + ", ".join(f"{lbl}={g1[lbl]['twist_profile_max']}°/{g1[lbl]['twist_diff']}°"
                                     for lbl in sorted(g1)))
    need_finetune = (not kill) and residual is not None and residual > delta_min

    # ── Gate 2 — signed-twist greedy ≤max_edits fine-tune (conditional) ────────────────────────
    if need_finetune:
        _log(f"GATE2 residual {residual:.1f}° > δ_min {delta_min:.1f}° → running ≤{args.max_edits}-edit fine-tune")
        cur = {h: list(v) for h, v in conv.items()}
        best_pm = residual
        best_prof = _load_prof(conv_rec) if conv_rec else None
        kept = []
        for e in range(args.max_edits):
            if best_prof is None:
                _log("GATE2 no profile available — stopping"); break
            new, descr = _worst_signed_edit(cur, bare, per_helix_bins, best_prof, args.n_bins)
            if new is None:
                _log("GATE2 no legal edit — stopping"); break
            lbl = f"g2_edit{e}"
            if lbl in done:
                continue
            rec = _measure_one(lbl, new, bare, ws, cfg, records)
            if rec.get("status") != "ok":
                _log(f"GATE2 edit {e} sim failed — stopping"); break
            improved = best_pm - rec["twist_profile_max"]
            accept = improved > delta_min and abs(rec["twist_diff"]) <= args.tol
            _log(f"GATE2 edit {e} {descr} → profmax {rec['twist_profile_max']}° "
                 f"(Δ={improved:+.1f}°, need >{delta_min:.1f}°) twist={rec['twist_diff']}° "
                 f"{'ACCEPT' if accept else 'reject'}")
            if accept:
                cur, best_pm, best_prof = new, rec["twist_profile_max"], _load_prof(rec)
                kept.append({**descr, "profmax": rec["twist_profile_max"]})
        _log(f"GATE2 done: {len(kept)} edit(s) kept, final max|prof|={best_pm:.1f}° "
             f"(started {residual:.1f}°)")
        (RESULTS_DIR / "finetune_summary.json").write_text(json.dumps(
            {"kept": kept, "start_profmax": residual, "final_profmax": best_pm,
             "delta_min": delta_min}, indent=2))
    else:
        _log("GATE2 skipped (residual within noise, or Gate 0 kill) — no fine-tune warranted")

    CURRENT_JSON.write_text(json.dumps({"job_id": None, "idle": True}))
    (RESULTS_DIR / "COMPLETE").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    print("[exp34] done.", flush=True)


if __name__ == "__main__":
    main()
