"""exp35 — validate the equilibration-fixed autorefine with post-transient analysis.

exp34 (conclusion.md, LESSONS A8) found the 3×6×400 square bundle's global twist has a
~5M-step EQUILIBRATION transient (the built/over-wound seed unwinding).  The stock relax
``equil_steps`` was 100k (~50× too short), so the MEASURED production started badly
unequilibrated and read a biased, drifting twist — the ±9° "noise" that derailed exp31/exp32.

The fix (landed): ``autorefine_sq_design`` now defaults ``equilibration_steps = 10_000_000``.
This experiment validates it on real CUDA in three escalating modes:

  --mode proxy     (2×3×40, ~min)  step 1: autorefine completes/converges with the new default;
                                   per-iteration production is measurable via read_twist_series.
  --mode residual  (3×6×400)       step 2 (the crux): build d+4 = 222 skips, relax with the NEW
                                   10M equil, run a measured 16M production, then
                                   production_twist_series + detect_equilibration.
                                     PASS = burn-in t0 ≲ 1M steps, the per-frame trace is flat
                                            from the start, and the whole-production mean (what
                                            the secant steers on) agrees with the equilibrated
                                            mean within ~2°; equilibrated d+4 twist ≈ 0 ± 2°.
                                     FAIL = residual transient survives the dt handoff → a
                                            burn-in DISCARD in the measurement is needed.
  --mode e2e       (3×6×400)       step 3: full autorefine from the analytical seed converges to
                                   ~222 skips with steering twist ≈ 0; each iteration is
                                   equilibrated (read_twist_series per iteration job).

Reuses exp31 ``run.measure`` / ``Cfg`` / build helpers, exp34 ``plot34``, and the
``read_twist_series`` / ``production_twist_series`` / ``detect_equilibration`` tooling
(do NOT rebuild).  Three-Layer Law: only skip TOPOLOGY is tuned; relaxed coords are read to
score, never written back.

Usage:
  python run.py --mode dry                                     # CPU wiring smoke (no GPU)
  python run.py --mode proxy    --backend CUDA --device 0
  python run.py --mode residual --backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7
  python run.py --mode e2e      --backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7
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
# exp34 first, then exp31 — so `import run` resolves to exp31's driver (both dirs have run.py),
# while `import plot34` (unique to exp34) is still found further down the path.
sys.path.insert(0, str(HERE.parent / "exp34_finetune_validation"))
sys.path.insert(0, str(HERE.parent / "exp31_skip_twist_curvature_sweep"))

import run as R  # noqa: E402  (exp31 driver: Cfg, measure, _archive_run, _health_check)

from backend.api.headless_oxdna_build import (  # noqa: E402
    STANDARD_RELAX_PARAMS, read_twist_series,
)
from backend.api.skip_twist_tuning import (  # noqa: E402
    autorefine_sq_design, build_explicit_skip_from_design, build_sq_skip_design,
    core_reference_geometry, square_cells,
)
from backend.core.models import Design  # noqa: E402
from backend.core.oxdna_health import detect_equilibration  # noqa: E402
from backend.core.skip_sweep_strategies import baseline_skips, place_incremental  # noqa: E402

import plot34 as plot  # noqa: E402  (exp34 plotting: save_twistseries_png)

RESULTS_DIR = HERE / "results"
PROFILE_DIR = RESULTS_DIR / "profiles"
PNG_DIR = PROFILE_DIR / "png"
CURRENT_JSON = RESULTS_DIR / "current.json"
MONITOR_LOG = HERE / "MONITOR_LOG.md"
ARCHIVE = pathlib.Path("/media/jojo/Archive/NADOC_archive/exp35_autorefine_equilibration_test")

# plot34 reads/writes under exp34's results dir; point it at ours so PNGs land here.
plot.RESULTS_DIR = RESULTS_DIR
plot.PROFILE_DIR = PROFILE_DIR
plot.PNG_DIR = PNG_DIR

STEPS_PER_FRAME = 20_000  # 2M round, print_conf_interval = steps//100 = 20k → frame spacing


def _log(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not MONITOR_LOG.exists():
        MONITOR_LOG.write_text("# exp35 driver log\n\n| time | event |\n|---|---|\n")
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | {msg} |\n")


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def _write_current(d: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    d = {**d, "host": socket.gethostname()}
    CURRENT_JSON.write_text(json.dumps(d, indent=2))


def _make_cfg(args, *, dry: bool, equil_steps: int, prod_steps: int, n_prod: int) -> R.Cfg:
    """An exp31 ``Cfg`` with the equilibration / production overrides this experiment needs."""
    cfg = R.Cfg(Namespace(
        dry_run=dry, steps=4, backend=args.backend, device=args.device,
        skip_benchmark=True, steps_per_s=args.steps_per_s,
        archive_root=None, no_archive=True, workspace=None))
    cfg.skip_benchmark = True              # exp35 never runs the proxy benchmark (forces backend)
    cfg.relax = {**STANDARD_RELAX_PARAMS, "equil_steps": equil_steps}
    cfg.prod_steps, cfg.n_prod = prod_steps, n_prod
    cfg.archive_root = None
    return cfg


# ── d+4 design (222 skips) — the residual-transient + e2e target ──────────────────
def _build_d4():
    """3×6×400 seamless square bundle at incremental delta +4 over the period-48 baseline
    (= 222 skips), the exp34c net-twist-zero design."""
    bare = build_sq_skip_design(square_cells(3, 6), 400, None)
    base = baseline_skips(bare, skip_period=48)
    d4 = place_incremental(bare, base, 4)
    total = sum(len(v) for v in d4.values())
    design = build_explicit_skip_from_design(bare, d4)
    return bare, design, d4, total


# ── twist-series record + verdict ────────────────────────────────────────────────
def _series_record(label: str, skips: int, ts: dict, *, twist_on_avg=None, wall_s=None) -> dict:
    eq = ts.get("equilibrated") or {}
    eqs = {k: _r(v) for k, v in (eq.get("stats") or {}).items()}
    raw = {k: _r(v) for k, v in (ts.get("stats") or {}).items()}
    return {
        "label": label, "total_skips": skips, "status": "ok",
        "n_frames": ts.get("n_frames"), "wall_s": wall_s,
        "twist_series": {
            "mean": raw.get("mean"), "std": raw.get("std"), "sem": raw.get("sem"),
            "tau_int": raw.get("tau_int"), "n_eff": raw.get("n_eff"),
            "twist_on_mean_structure": ts.get("twist_on_mean_structure"),
            "twist_on_avg_structure": _r(twist_on_avg) if twist_on_avg is not None else None,
            "n_frames": ts.get("n_frames")},
        "equilibrated": {
            "t0_frames": eq.get("t0"), "mean": eqs.get("mean"), "sem": eqs.get("sem"),
            "std": eqs.get("std"), "tau_int": eqs.get("tau_int"), "n_eff": eqs.get("n_eff")},
    }


def _residual_verdict(rec: dict) -> dict:
    """PASS/FAIL on the step-2 residual-transient criteria (PROMPT)."""
    eq = rec["equilibrated"]
    raw = rec["twist_series"]
    t0_frames = eq["t0_frames"] or 0
    t0_steps = t0_frames * STEPS_PER_FRAME
    whole_mean = raw["mean"]
    eq_mean = eq["mean"]
    c_t0 = t0_steps <= 1_000_000                               # burn-in ≲ 1M steps
    c_agree = (whole_mean is not None and eq_mean is not None
               and abs(whole_mean - eq_mean) <= 2.0)           # whole-mean ≈ equilibrated
    c_zero = eq_mean is not None and abs(eq_mean) <= 2.0       # d+4 equilibrated ≈ 0 ± 2°
    passed = bool(c_t0 and c_agree and c_zero)
    # Three outcomes, not two.  The PROMPT anticipated PASS (all three) and a "residual
    # transient" FAIL (t0 ≫ 1M, whole-mean biased).  The DATA showed a THIRD case:
    # t0≈0 + whole==eq (the equil-lengthening DID remove the fast +90° ramp) BUT the
    # equilibrated value is NOT ~0.  A burn-in DISCARD cannot help that — there is no
    # transient left in-window to trim; the miss is the slow twist relaxation being slower
    # than the whole production, so detect_equilibration falsely reads t0=0 ("flat") on a
    # value that is still gliding.  Name it explicitly so the record isn't misleading.
    if passed:
        interp = ("PASS — equil-lengthening makes the measured production post-transient; the "
                  "whole-production mean the secant steers on equals the equilibrated twist, "
                  "and d+4 equilibrates to ~0.")
    elif c_t0 and c_agree and not c_zero:
        interp = (
            f"FAIL (not a measurement/burn-in problem) — the equil fix WORKED: t0≈0, the trace "
            f"is flat from the start, and whole-prod mean == equilibrated mean ({whole_mean}°). "
            f"But d+4 equilibrates to {eq_mean}° ≠ 0 (reproduces the OLD under-equilibrated +17°, "
            f"CONTRADICTS exp34c's warm-started −0.6°).  A burn-in DISCARD is a no-op here (t0=0). "
            f"The slow +90°→equilibrium twist glide is longer than this 26M-step run, so "
            f"detect_equilibration can't see it in a 16M window; 10M equil removes the fast ramp "
            f"but not the slow relaxation. Fix = MUCH longer equilibration (or a long-run "
            f"convergence check), not trimming.")
    else:
        interp = (
            "FAIL — a residual transient survives the equil→production dt handoff (t0 ≫ 1M and/or "
            "whole-mean biased vs equilibrated); implement burn-in discard in the measurement "
            "(steer on detect_equilibration-trimmed twist).")
    return {
        "passed": passed,
        "t0_frames": t0_frames, "t0_steps": t0_steps,
        "whole_production_mean_deg": whole_mean, "equilibrated_mean_deg": eq_mean,
        "whole_minus_equilibrated_deg": _r(abs(whole_mean - eq_mean))
        if (whole_mean is not None and eq_mean is not None) else None,
        "criteria": {"t0_le_1M_steps": c_t0, "whole_vs_eq_within_2deg": c_agree,
                     "equilibrated_within_2deg_of_zero": c_zero},
        "interpretation": interp,
    }


# ── modes ─────────────────────────────────────────────────────────────────────────
def mode_dry(args) -> None:
    """CPU wiring smoke: tiny 2×3×40 d+4-ish design, short relax + 2×short production, then
    read_twist_series + production_twist_series + detect_equilibration.  Proves the WHOLE
    measurement chain returns a per-frame series + a t0 — no GPU, no autorefine loop."""
    _log("DRY smoke start (CPU)")
    ws = str(HERE / "ws_dry")
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    bare = build_sq_skip_design(square_cells(2, 3), 40, None)
    base = baseline_skips(bare, skip_period=8)
    d4 = place_incremental(bare, base, 1)
    design = build_explicit_skip_from_design(bare, d4)
    cfg = _make_cfg(args, dry=True, equil_steps=200, prod_steps=20_000, n_prod=3)
    cfg.backend = "CPU"
    rec = R.measure(design, ws, cfg)
    if rec.get("status") != "ok":
        _log(f"DRY measure status={rec.get('status')}")
        print(f"[exp35:dry] FAILED measure: {rec.get('status')}")
        return
    ts = read_twist_series(rec["job_id"], ws, design, core_reference_geometry(design))
    ok = bool(ts.get("ready") and ts.get("twist_per_frame") and ts.get("equilibrated"))
    print(f"[exp35:dry] ready={ts.get('ready')} n_frames={ts.get('n_frames')} "
          f"stats_mean={(ts.get('stats') or {}).get('mean')} "
          f"t0={ (ts.get('equilibrated') or {}).get('t0')}  -> wiring {'OK' if ok else 'BROKEN'}")
    _log(f"DRY smoke {'OK' if ok else 'BROKEN'}: n_frames={ts.get('n_frames')} "
         f"t0={(ts.get('equilibrated') or {}).get('t0')}")


def _read_iter_series(jobs: list[str], ws: str, design, ref, *, tag: str) -> list[dict]:
    """read_twist_series + detect_equilibration on each captured iteration job that still
    exists on disk; returns lightweight per-iteration records (saves the full series JSON)."""
    out = []
    for i, jid in enumerate(jobs):
        try:
            ts = read_twist_series(jid, ws, design, ref)
        except Exception as e:  # noqa: BLE001
            _log(f"{tag} iter{i} series error {e}")
            continue
        if not ts.get("ready"):
            continue
        (PROFILE_DIR / f"twistseries_{tag}_iter{i}.json").write_text(json.dumps(ts))
        rec = _series_record(f"{tag}_iter{i}", 0, ts)
        out.append({"iter": i, "job_id": jid, **rec["equilibrated"],
                    "whole_mean": rec["twist_series"]["mean"],
                    "n_frames": ts.get("n_frames")})
        try:
            plot.save_twistseries_png(rec)
        except Exception as e:  # noqa: BLE001
            _log(f"{tag} iter{i} plot warn {e}")
    return out


def mode_proxy(args) -> None:
    """Step 1 — proxy autorefine (2×3×40) with the new long-equil default (scaled down for the
    proxy), confirming the loop completes + converges and each iteration's production is
    measurable via read_twist_series."""
    _log("PROXY autorefine start (2×3×40)")
    ws = str(HERE / "ws_proxy")
    if pathlib.Path(ws).exists():
        shutil.rmtree(ws, ignore_errors=True)
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    bare = build_sq_skip_design(square_cells(2, 3), 40, None)
    jobs: list[str] = []
    t0 = time.monotonic()
    _write_current({"mode": "proxy", "phase": "running", "started_at": t0})

    def on_job(job):
        jid = getattr(job, "job_id", job)   # autorefine's on_job passes an OxdnaJob, not an id
        if jid and jid not in jobs:
            jobs.append(jid)
        _write_current({"mode": "proxy", "phase": "running", "current_job": jid,
                        "n_jobs": len(jobs), "started_at": t0})

    def on_progress(ev):
        _log(f"proxy progress {ev.get('phase')} period={ev.get('period')}")

    # Proxy-scaled: a real >0 equil to exercise the path, but not 10M (the 10M default is
    # separately unit-pinned; the proxy validates WIRING + convergence, not the transient).
    result = autorefine_sq_design(
        bare, ws, backend=args.backend, device=args.device,
        on_job=on_job, on_progress=on_progress,
        initial_period=8, max_iterations=3, min_confidence=80, baseline_min_confidence=40,
        production_steps=40_000, screen_steps=20_000, max_production_rounds=3,
        equilibration_steps=50_000,
        mc_steps=100, md_relax_steps=2_000, min_bp_retained=0.0, max_relax_retries=0,
        timeout=3600.0)
    wall = round(time.monotonic() - t0, 1)
    ref = core_reference_geometry(build_sq_skip_design(square_cells(2, 3), 40, None))
    iters = _read_iter_series(jobs, ws, bare, ref, tag="proxy")
    out = {
        "mode": "proxy", "status": result.get("status"),
        "converged_period": result.get("converged_period"),
        "primary_metric": result.get("primary_metric"),
        "before": result.get("before"), "after": result.get("after"),
        "n_iterations": len(result.get("iterations") or []),
        "n_jobs_captured": len(jobs),
        "iteration_series": iters,
        "per_iter_measurable": all(it.get("n_frames") for it in iters) and bool(iters),
        "wall_s": wall,
    }
    (RESULTS_DIR / "proxy_result.json").write_text(json.dumps(out, indent=2))
    _write_current({"mode": "proxy", "idle": True})
    _log(f"PROXY done status={out['status']} period={out['converged_period']} "
         f"iters={out['n_iterations']} measurable={out['per_iter_measurable']} [{wall}s]")
    print(f"[exp35:proxy] status={out['status']} converged_period={out['converged_period']} "
          f"per_iter_measurable={out['per_iter_measurable']}  (results/proxy_result.json)")


def mode_residual(args) -> None:
    """Step 2 (the crux) — build d+4 (222 skips), one relax with the NEW 10M equil, a measured
    16M production, then production_twist_series + detect_equilibration → PASS/FAIL verdict."""
    ws = str(HERE / "ws_residual")
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    res_path = RESULTS_DIR / "residual_result.json"
    if res_path.exists():
        prev = json.loads(res_path.read_text())
        if prev.get("status") == "ok":
            print(f"[exp35:residual] already done (status ok) — see {res_path}")
            return

    bare, design, d4, total = _build_d4()
    _log(f"RESIDUAL start: d+4 = {total} skips (3×6×400), equil={args.equil_steps:,} "
         f"prod={args.prod_steps:,}×{args.n_prod} ({args.prod_steps*args.n_prod:,} steps)")
    cfg = _make_cfg(args, dry=False, equil_steps=args.equil_steps,
                    prod_steps=args.prod_steps, n_prod=args.n_prod)
    cfg.backend, cfg.device, cfg.steps_per_s = args.backend, args.device, args.steps_per_s
    cfg.timeout = 12 * 3600.0

    t0 = time.monotonic()
    _write_current({"mode": "residual", "phase": "relax+production", "total_skips": total,
                    "equil_steps": args.equil_steps,
                    "production_total_steps": args.prod_steps * args.n_prod,
                    "steps_per_s": args.steps_per_s, "started_at": time.time(),
                    "expected_wall_s": ((args.equil_steps + args.prod_steps * args.n_prod)
                                        / args.steps_per_s if args.steps_per_s else None)})

    def on_job(jid):
        _write_current({"mode": "residual", "phase": "relax+production", "total_skips": total,
                        "job_id": jid, "equil_steps": args.equil_steps,
                        "production_total_steps": args.prod_steps * args.n_prod,
                        "steps_per_s": args.steps_per_s, "started_at": time.time()})

    rec = R.measure(design, ws, cfg, on_job_id=on_job)
    wall = round(time.monotonic() - t0, 1)
    if rec.get("status") != "ok":
        out = {"mode": "residual", "status": rec.get("status"), "job_id": rec.get("job_id"),
               "total_skips": total, "wall_s": wall}
        res_path.write_text(json.dumps(out, indent=2))
        _write_current({"mode": "residual", "idle": True})
        _log(f"RESIDUAL FAILED measure status={rec.get('status')} [{wall}s]")
        print(f"[exp35:residual] measure FAILED: {rec.get('status')}")
        return

    ref = core_reference_geometry(design)
    ts = read_twist_series(rec["job_id"], ws, design, ref)
    if not ts.get("ready"):
        out = {"mode": "residual", "status": "series_failed", "job_id": rec.get("job_id"),
               "total_skips": total, "wall_s": wall, "reason": ts.get("reason")}
        res_path.write_text(json.dumps(out, indent=2))
        _write_current({"mode": "residual", "idle": True})
        _log(f"RESIDUAL series_failed: {ts.get('reason')}")
        return

    (PROFILE_DIR / "twistseries_residual_d+4.json").write_text(json.dumps(ts))
    srec = _series_record("residual_d+4", total, ts, twist_on_avg=rec.get("twist_diff"),
                          wall_s=wall)
    verdict = _residual_verdict(srec)
    out = {"mode": "residual", "status": "ok", "job_id": rec.get("job_id"),
           "total_skips": total, "wall_s": wall,
           "measure": {k: rec.get(k) for k in
                       ("twist_diff", "twist_profile_max", "curvature_diff", "bend_diff",
                        "dev_max", "dev_mean", "n_frames", "healthy", "bp_retained",
                        "fene_safe", "max_backbone_stretch_nm")},
           "twist_series": srec["twist_series"], "equilibrated": srec["equilibrated"],
           "verdict": verdict}
    res_path.write_text(json.dumps(out, indent=2))
    try:
        plot.save_twistseries_png(srec)
    except Exception as e:  # noqa: BLE001
        _log(f"RESIDUAL plot warn {e}")
    # archive the heavy job folder off-disk (metrics already saved)
    _archive(rec.get("job_id"), ws)
    _write_current({"mode": "residual", "idle": True})
    eq = srec["equilibrated"]
    _log(f"RESIDUAL {'PASS' if verdict['passed'] else 'FAIL'}: "
         f"t0={verdict['t0_steps']/1e6:.2f}M  whole={verdict['whole_production_mean_deg']}° "
         f"eq={eq['mean']}±{eq['sem']}°  N_eff={eq['n_eff']} [{wall}s]")
    print(f"[exp35:residual] {'PASS' if verdict['passed'] else 'FAIL'}  "
          f"t0={verdict['t0_steps']/1e6:.2f}M steps  whole={verdict['whole_production_mean_deg']}°  "
          f"equilibrated={eq['mean']}±{eq['sem']}°  (results/residual_result.json)")


def mode_design(args) -> None:
    """Load a user `.nadoc` (as-is: its own manual skips + assigned sequences) and run the
    residual-style equilibrated-twist measurement on it — one relax with the shipped 10M equil,
    a measured 16M production, then production_twist_series + detect_equilibration.  Reports the
    same three-criterion twist verdict (here 'equilibrated ≈ 0' asks whether the traditional
    manual-skip pattern nulls the global twist)."""
    import pathlib as _pl
    src = _pl.Path(args.nadoc)
    design = Design.model_validate_json(src.read_text())
    stem = src.stem
    tot_skips = sum(sum(1 for ls in h.loop_skips if ls.delta <= -1) for h in design.helices)
    ws = str(HERE / f"ws_design_{stem}")
    _pl.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    res_path = RESULTS_DIR / f"design_{stem}_result.json"
    if res_path.exists() and json.loads(res_path.read_text()).get("status") == "ok":
        print(f"[exp35:design] already done — see {res_path}")
        return

    _log(f"DESIGN start: {stem} ({tot_skips} skips, {len(design.helices)} helices), "
         f"equil={args.equil_steps:,} prod={args.prod_steps:,}×{args.n_prod}")
    cfg = _make_cfg(args, dry=False, equil_steps=args.equil_steps,
                    prod_steps=args.prod_steps, n_prod=args.n_prod)
    cfg.backend, cfg.device, cfg.steps_per_s = args.backend, args.device, args.steps_per_s
    cfg.timeout = 12 * 3600.0
    t0 = time.monotonic()
    _write_current({"mode": "design", "design": stem, "phase": "relax+production",
                    "total_skips": tot_skips, "equil_steps": args.equil_steps,
                    "production_total_steps": args.prod_steps * args.n_prod,
                    "steps_per_s": args.steps_per_s, "started_at": time.time()})

    def on_job(jid):
        _write_current({"mode": "design", "design": stem, "phase": "relax+production",
                        "total_skips": tot_skips, "job_id": jid,
                        "production_total_steps": args.prod_steps * args.n_prod,
                        "steps_per_s": args.steps_per_s, "started_at": time.time()})

    rec = R.measure(design, ws, cfg, on_job_id=on_job)
    wall = round(time.monotonic() - t0, 1)
    if rec.get("status") != "ok":
        res_path.write_text(json.dumps({"mode": "design", "design": stem,
                                        "status": rec.get("status"), "job_id": rec.get("job_id"),
                                        "total_skips": tot_skips, "wall_s": wall}, indent=2))
        _write_current({"mode": "design", "idle": True})
        _log(f"DESIGN {stem} FAILED measure status={rec.get('status')}")
        print(f"[exp35:design] measure FAILED: {rec.get('status')}")
        return

    ref = core_reference_geometry(design)
    ts = read_twist_series(rec["job_id"], ws, design, ref)
    label = f"design_{stem}"
    if not ts.get("ready"):
        res_path.write_text(json.dumps({"mode": "design", "design": stem, "status": "series_failed",
                                        "job_id": rec.get("job_id"), "reason": ts.get("reason"),
                                        "total_skips": tot_skips, "wall_s": wall}, indent=2))
        _write_current({"mode": "design", "idle": True})
        _log(f"DESIGN {stem} series_failed: {ts.get('reason')}")
        return
    (PROFILE_DIR / f"twistseries_{label}.json").write_text(json.dumps(ts))
    srec = _series_record(label, tot_skips, ts, twist_on_avg=rec.get("twist_diff"), wall_s=wall)
    verdict = _residual_verdict(srec)
    out = {"mode": "design", "design": stem, "status": "ok", "job_id": rec.get("job_id"),
           "total_skips": tot_skips, "wall_s": wall,
           "measure": {k: rec.get(k) for k in
                       ("twist_diff", "twist_profile_max", "curvature_diff", "bend_diff",
                        "dev_max", "dev_mean", "n_frames", "healthy", "bp_retained",
                        "fene_safe", "max_backbone_stretch_nm")},
           "twist_series": srec["twist_series"], "equilibrated": srec["equilibrated"],
           "verdict": verdict}
    res_path.write_text(json.dumps(out, indent=2))
    try:
        srec_png = dict(srec); srec_png["label"] = label
        plot.save_twistseries_png(srec_png)
    except Exception as e:  # noqa: BLE001
        _log(f"DESIGN {stem} plot warn {e}")
    _archive(rec.get("job_id"), ws)
    _write_current({"mode": "design", "idle": True})
    eq = srec["equilibrated"]
    _log(f"DESIGN {stem} done: {tot_skips} skips  whole={verdict['whole_production_mean_deg']}° "
         f"eq={eq['mean']}±{eq['sem']}°  t0={verdict['t0_steps']/1e6:.2f}M  N_eff={eq['n_eff']} [{wall}s]")
    print(f"[exp35:design] {stem}: {tot_skips} skips  equilibrated twist={eq['mean']}±{eq['sem']}°  "
          f"whole={verdict['whole_production_mean_deg']}°  t0={verdict['t0_steps']/1e6:.2f}M  "
          f"(results/design_{stem}_result.json)")


def mode_e2e(args) -> None:
    """Step 3 — full fixed autorefine from the analytical seed on 3×6×400.  PASS = converges to
    ~222 skips (d+4) with steering twist within tol of 0, and each iteration's production is
    equilibrated (read_twist_series per captured iteration job)."""
    ws = str(HERE / "ws_e2e")
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    bare = build_sq_skip_design(square_cells(3, 6), 400, None)
    jobs: list[str] = []
    t0 = time.monotonic()
    _log("E2E autorefine start (3×6×400, analytical seed)")
    _write_current({"mode": "e2e", "phase": "running", "started_at": time.time(),
                    "steps_per_s": args.steps_per_s})

    def on_job(job):
        jid = getattr(job, "job_id", job)   # autorefine's on_job passes an OxdnaJob, not an id
        if jid and jid not in jobs:
            jobs.append(jid)
        _write_current({"mode": "e2e", "phase": "running", "current_job": jid,
                        "n_jobs": len(jobs), "started_at": time.time(),
                        "steps_per_s": args.steps_per_s})

    def on_progress(ev):
        _log(f"e2e progress {ev.get('phase')} period={ev.get('period')} "
             f"twist={ev.get('global_twist_deg') or ev.get('measured')}")

    result = autorefine_sq_design(
        bare, ws, backend=args.backend, device=args.device,
        on_job=on_job, on_progress=on_progress,
        equilibration_steps=args.equil_steps,
        production_steps=args.prod_steps, screen_steps=2_000_000,
        min_confidence=400, max_iterations=6, max_production_rounds=6,
        timeout=14400.0)
    wall = round(time.monotonic() - t0, 1)

    converged_period = result.get("converged_period")
    converged_skips = result.get("converged_skips")
    # count the skips of the converged uniform period for the "~222" check
    n_skips = None
    if converged_skips:
        n_skips = sum(len(v) for v in converged_skips.values())
    elif converged_period:
        try:
            n_skips = sum(len(v) for v in baseline_skips(bare, skip_period=converged_period).values())
        except Exception:  # noqa: BLE001
            n_skips = None

    ref = core_reference_geometry(bare)
    iters = _read_iter_series(jobs, ws, bare, ref, tag="e2e")
    after = result.get("after") or {}
    twist_after = after.get("global_twist_deg")
    out = {
        "mode": "e2e", "status": result.get("status"),
        "converged_period": converged_period, "converged_skips_total": n_skips,
        "primary_metric": result.get("primary_metric"),
        "before": result.get("before"), "after": after,
        "iterations": result.get("iterations"),
        "iteration_series": iters,
        "all_iters_equilibrated": bool(iters) and all(
            (it.get("t0_frames") or 0) * STEPS_PER_FRAME <= 1_000_000 for it in iters),
        "converged_twist_deg": twist_after,
        "pass": (n_skips is not None and 210 <= n_skips <= 234
                 and twist_after is not None and abs(twist_after) <= 5.0),
        "wall_s": wall,
    }
    (RESULTS_DIR / "e2e_result.json").write_text(json.dumps(out, indent=2))
    _write_current({"mode": "e2e", "idle": True})
    _log(f"E2E done status={out['status']} period={converged_period} skips={n_skips} "
         f"twist={twist_after}° pass={out['pass']} [{wall}s]")
    print(f"[exp35:e2e] status={out['status']} converged_period={converged_period} "
          f"skips={n_skips} twist={twist_after}° PASS={out['pass']}  (results/e2e_result.json)")


def _archive(job_id: str | None, ws: str) -> None:
    if not job_id:
        return
    try:
        from backend.core import job_archive
        from backend.core.oxdna_job import OxdnaJob
        if not ARCHIVE.parent.exists():
            _log(f"archive mount {ARCHIVE.parent} missing — keeping {job_id} in ws")
            return
        job = OxdnaJob.load(job_id, pathlib.Path(ws))
        dest = job_archive.archive_job(job, pathlib.Path(ws), "oxdna_jobs", ARCHIVE)
        _log(f"archived {job_id} → {dest}")
    except Exception as e:  # noqa: BLE001
        _log(f"ARCHIVE FAILED {job_id}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["dry", "proxy", "residual", "e2e", "design"])
    ap.add_argument("--nadoc", default=None, help="path to a .nadoc for --mode design")
    ap.add_argument("--backend", default="CUDA")
    ap.add_argument("--device", default="0")
    ap.add_argument("--skip-benchmark", action="store_true")
    ap.add_argument("--steps-per-s", type=float, default=2551.7)
    ap.add_argument("--equil-steps", type=int, default=10_000_000)
    ap.add_argument("--prod-steps", type=int, default=2_000_000)
    ap.add_argument("--n-prod", type=int, default=8, help="production rounds (residual mode)")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    {"dry": mode_dry, "proxy": mode_proxy, "residual": mode_residual, "e2e": mode_e2e,
     "design": mode_design}[args.mode](args)


if __name__ == "__main__":
    main()
