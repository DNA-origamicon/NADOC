"""exp31 — skip count vs twist & curvature sweep (3×6×400 square-lattice bundle).

Builds a fresh 3×6×400 SQ bundle at the analytical skip baseline, then sweeps the TOTAL skip
count by ±18 (one deletion per helix) per step, ±4 steps each way, under THREE placement
strategies (uniform restagger / incremental largest-gap / deviation-guided feedback).  Each
grid point runs a full oxDNA relaxation + 8M-step production; we measure differential global
twist and integrated curvature against the design's own analytic geometry, append a record to
``results/results.json`` + ``results/results.csv``, and regenerate the live PNG.

Orchestration (matches exp30's driver + independent-monitor pattern):
  * Δ=0 is one SHARED baseline sim (all strategies coincide there).
  * "uniform" / "incremental" points are independent → run in any order.
  * "deviation" runs each ±chain in order (round N consumes round N−1's deviation field).
  * Before each sim the driver writes ``results/current.json`` (active job, expected wall-clock)
    so ``scripts/monitor_skip_sweep.py`` can catch a hung / exploded run at the 10% / 50% marks.
  * No early-reject: every healthy sim runs the full production; a sim is abandoned only if the
    relaxation or a production round comes back non-completed (the runner's explosion gate).
  * Resume-safe: completed points are reloaded from results.json and skipped; the deviation
    chain is reconstructed from stored per-point skip patterns + fields.

Usage:
  python run.py                       # full real run (benchmark → 25 sims)
  python run.py --dry-run             # tiny 2×3×40 / 50k-step smoke on CPU (end-to-end wiring)
  python run.py --backend CUDA --device 0 --skip-benchmark
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.api.headless_oxdna_build import (  # noqa: E402
    STANDARD_RELAX_PARAMS, append_production, apply_oxdna_benchmark, create_job,
    read_flexibility_map, run_oxdna_benchmark, start_relaxation, wait_for_terminal,
)
from backend.api.skip_twist_tuning import (  # noqa: E402
    build_explicit_skip_from_design, build_sq_skip_design, core_reference_geometry, square_cells,
)
from backend.core.oxdna_health import (  # noqa: E402
    _filter_to_reference_core, geometry_deviation_map, measure_bundle_bend,
    measure_bundle_curvature, measure_bundle_twist,
)
from backend.core.regional_skip_placer import aggregate_deviation_per_bp  # noqa: E402
from backend.core.skip_sweep_strategies import (  # noqa: E402
    STRATEGIES, baseline_skips, place_deviation_step, place_incremental, place_uniform,
)

HERE = pathlib.Path(__file__).parent
RESULTS_DIR = HERE / "results"
RESULTS_JSON = RESULTS_DIR / "results.json"
RESULTS_CSV = RESULTS_DIR / "results.csv"
CURRENT_JSON = RESULTS_DIR / "current.json"
MONITOR_LOG = HERE / "MONITOR_LOG.md"

import plot  # noqa: E402  (sibling module)
import profile as twist_profile_mod  # noqa: E402  (sibling module)

PROFILE_DIR = RESULTS_DIR / "profiles"

CSV_COLS = ["strategy", "delta", "total_skips", "status", "healthy", "bp_retained",
            "max_backbone_stretch_nm", "fene_safe", "twist_diff", "twist_profile_max",
            "curvature_diff", "bend_diff", "twist_sim", "twist_analytic", "curv_sim",
            "curv_analytic", "dev_max", "dev_mean", "n_frames", "wall_s", "job_id"]


# ── config ────────────────────────────────────────────────────────────────────
class Cfg:
    def __init__(self, args):
        self.dry = args.dry_run
        self.deltas = list(range(-args.steps, args.steps + 1))
        if self.dry:
            self.cells, self.length = square_cells(2, 3), 40
            self.baseline_period = 8          # dense enough for ±4 on a 40-bp proxy
            self.prod_steps, self.n_prod = 20_000, 1
            self.relax = {"mc_steps": 100, "md_relax_steps": 1000, "equil_steps": 100,
                          "min_bp_retained": 0.0, "max_relax_retries": 0}
            self.timeout = 1800.0
        else:
            self.cells, self.length = square_cells(3, 6), 400
            self.baseline_period = 48         # the published analytical seed
            self.prod_steps, self.n_prod = 2_000_000, 4    # 8M total → ~400-frame confidence
            self.relax = dict(STANDARD_RELAX_PARAMS)
            self.timeout = 6 * 3600.0
        self.backend = args.backend
        self.device = args.device
        self.skip_benchmark = args.skip_benchmark or self.dry
        # steps/s drives the monitor's 10%/50% ETA.  The benchmark's synthetic proxy fails on
        # CUDA on this host (recommends CPU by fallback), so when forcing CUDA we inject the
        # directly-measured real-scale rate via --steps-per-s instead of trusting the sweep.
        self.steps_per_s = args.steps_per_s
        # Each completed run's job folder (~2.5 GB of trajectory) is MOVED here right after
        # its metrics are extracted, so a 25-sim series doesn't fill the disk.  None disables.
        self.archive_root = None if args.no_archive else args.archive_root


# ── persistence ─────────────────────────────────────────────────────────────────
def _load_results() -> list[dict]:
    if RESULTS_JSON.exists():
        return json.loads(RESULTS_JSON.read_text() or "[]")
    return []


def _save_results(records: list[dict]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(records, indent=2))
    lines = [",".join(CSV_COLS)]
    for r in records:
        lines.append(",".join("" if r.get(c) is None else str(r.get(c)) for c in CSV_COLS))
    RESULTS_CSV.write_text("\n".join(lines) + "\n")


def _key(strategy: str, delta: int) -> str:
    return f"{strategy}:{delta}"


def _dev_to_json(dev: dict) -> list:
    return [[h, bp, v] for (h, bp), v in dev.items()]


def _dev_from_json(lst) -> dict:
    return {(h, int(bp)): float(v) for h, bp, v in (lst or [])}


def _write_current(strategy: str, delta: int, total_skips: int, cfg: Cfg,
                   job_id: str | None, ws: str) -> None:
    """Sidecar the external monitor reads to judge progress at the 10%/50% marks."""
    total_steps = cfg.prod_steps * cfg.n_prod
    eta_s = (total_steps / cfg.steps_per_s) if cfg.steps_per_s else None
    CURRENT_JSON.write_text(json.dumps({
        "strategy": strategy, "delta": delta, "total_skips": total_skips,
        "job_id": job_id, "workspace": ws, "host": socket.gethostname(),
        "production_total_steps": total_steps, "steps_per_s": cfg.steps_per_s,
        "expected_wall_s": eta_s, "started_at": time.time(),
        "started_monotonic": time.monotonic(),
    }, indent=2))


def _clear_current() -> None:
    CURRENT_JSON.write_text(json.dumps({"job_id": None, "idle": True}))


def _log_monitor(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not MONITOR_LOG.exists():
        MONITOR_LOG.write_text("# exp31 driver log\n\n| time | event |\n|---|---|\n")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {stamp} | {msg} |\n")


def _health_check(design, job, ws: str) -> dict:
    """Standard structural-integrity check on the final production frame — so we never trust a
    metric from a melted/clashed structure.  Reuses the runner's `run_oxdna_health_check`
    (bp-pair retention, FENE safety, backbone stretch, energy convergence).  Best-effort:
    `healthy=None` on read failure (don't lose the data point over a health-read hiccup)."""
    from backend.core.oxdna_health import run_oxdna_health_check
    from backend.core.oxdna_runner import find_dnanalysis
    try:
        wsp = pathlib.Path(ws)
        stage = job.stage_dir(wsp, job.stages[-1].name)
        topo = job.job_dir(wsp) / "topology.top"
        hr = run_oxdna_health_check(design, stage, kind="production", min_bp_retained=0.5,
                                    topology_path=topo, dnanalysis_bin=find_dnanalysis())
        return {"healthy": bool(hr.passed),
                "bp_retained": round(hr.bp_retained_fraction or 0.0, 3),
                "max_backbone_stretch_nm": round(hr.max_backbone_stretch or 0.0, 2),
                "fene_safe": bool(hr.fene_safe), "n_fene_over": int(hr.n_fene_over),
                "energy_converged": bool(hr.energy_converged), "health_reason": hr.reason or ""}
    except Exception as e:  # noqa: BLE001
        return {"healthy": None, "health_reason": f"health check error: {e}"}


# ── measurement (one full sim → differential twist + curvature + fields) ─────────
def measure(design, ws: str, cfg: Cfg, *, on_job_id=None) -> dict:
    """Relax + produce ``design``, then score the pooled mean against its OWN analytic
    geometry (differential twist & curvature).  Returns a record dict; status ``"ok"`` only
    if relax and every production round completed and a mean was pooled.  ``on_job_id`` is
    called with the job id the MOMENT the job is created (so the monitor sees a live job all
    through the relax, not just production)."""
    info = create_job(design, ws, autostart=False,
                      backend=cfg.backend, device=cfg.device, **cfg.relax)
    job_id = info["job_id"]
    if on_job_id:
        on_job_id(job_id)
    start_relaxation(job_id, ws)
    job = wait_for_terminal(job_id, ws, timeout=cfg.timeout)
    if job.status.value != "completed":
        return {"status": f"relax_{job.status.value}", "job_id": job_id}
    for _ in range(max(1, cfg.n_prod)):
        append_production(job_id, ws, steps=cfg.prod_steps)
        job = wait_for_terminal(job_id, ws, timeout=cfg.timeout)
        if job.status.value != "completed":
            return {"status": f"production_{job.status.value}", "job_id": job_id}

    mean = read_flexibility_map(job_id, ws)
    if not mean.get("positions"):
        return {"status": "no_mean", "job_id": job_id}
    health = _health_check(design, job, ws)   # standard structural-integrity check on final frame
    ref = core_reference_geometry(design)
    core = _filter_to_reference_core(mean["positions"], ref)
    twist_sim, twist_ana = measure_bundle_twist(core), measure_bundle_twist(ref)
    curv_sim, curv_ana = measure_bundle_curvature(core), measure_bundle_curvature(ref)
    bend_sim, bend_ana = measure_bundle_bend(core), measure_bundle_bend(ref)
    dmap = geometry_deviation_map(mean["positions"], ref)
    prof = twist_profile_mod.compute_twist_profile(core, ref, length_bp=cfg.length)
    curv_prof = twist_profile_mod.compute_curvature_profile(core, ref, length_bp=cfg.length)
    # OBJECTIVE metric: max |cumulative twist| anywhere along the profile → 0 means flat-zero
    # everywhere (a genuinely straight duplex), not just zero net/endpoint twist (which a
    # front/back-cancelling kinked profile can fake).  Equals |endpoint| for a monotonic run.
    prof_max = max((abs(p["cum_twist_diff"]) for p in prof), default=0.0)
    return {
        "status": "ok", "job_id": job_id,
        "twist_sim": round(twist_sim, 2), "twist_analytic": round(twist_ana, 2),
        "twist_diff": round(twist_sim - twist_ana, 2),
        "twist_profile_max": round(prof_max, 2),
        "curv_sim": round(curv_sim, 4), "curv_analytic": round(curv_ana, 4),
        "curvature_diff": round(curv_sim - curv_ana, 4),
        "bend_diff": round(bend_sim - bend_ana, 2),
        "dev_max": round(dmap["max_deviation"], 3), "dev_mean": round(dmap["mean_deviation"], 3),
        "n_frames": (mean.get("confidence") or {}).get("n_frames"),
        **health,
        "deviation_by_bp": _dev_to_json(aggregate_deviation_per_bp(dmap)),
        "_twist_profile": prof,        # popped + written to profiles/ by run_point (not stored in results.json)
        "_curvature_profile": curv_prof,
    }


# ── one grid point ───────────────────────────────────────────────────────────────
def run_point(strategy: str, delta: int, skips_by_helix: dict, bare_base, ws: str, cfg: Cfg,
              records: list[dict]) -> dict:
    total = sum(len(v) for v in skips_by_helix.values())
    _log_monitor(f"START {strategy} Δ={delta:+d} ({total} skips)")
    _write_current(strategy, delta, total, cfg, None, ws)
    t0 = time.monotonic()
    design = build_explicit_skip_from_design(bare_base, skips_by_helix)
    rec = measure(design, ws, cfg,
                  on_job_id=lambda jid: _write_current(strategy, delta, total, cfg, jid, ws))
    prof = rec.pop("_twist_profile", None)      # keep results.json lean; profile → its own files
    curv_prof = rec.pop("_curvature_profile", None)
    rec.update({"strategy": strategy, "delta": delta, "total_skips": total,
                "skips": {h: sorted(v) for h, v in skips_by_helix.items()},
                "wall_s": round(time.monotonic() - t0, 1)})
    records.append(rec)
    _save_results(records)
    if prof:        # save per-run profile DATA; the combined per-strategy overlay reads these
        label = twist_profile_mod.run_label(strategy, delta)
        twist_profile_mod.save_profile_csv(prof, PROFILE_DIR / f"{label}.csv")
        if curv_prof:
            twist_profile_mod.save_profile_csv(
                curv_prof, PROFILE_DIR / f"curv_{label}.csv", fields=twist_profile_mod._CURV_FIELDS)
    plot.regenerate()
    _archive_run(rec.get("job_id"), ws, cfg)   # metrics saved → move the heavy job folder off-disk
    _clear_current()
    _log_monitor(f"DONE  {strategy} Δ={delta:+d} status={rec['status']} "
                 f"healthy={rec.get('healthy')} bp_ret={rec.get('bp_retained')} "
                 f"twist={rec.get('twist_diff')} curv={rec.get('curvature_diff')} "
                 f"({rec.get('wall_s')}s)")
    return rec


def _archive_run(job_id: str | None, ws: str, cfg: Cfg) -> None:
    """Move a finished run's job folder to the archive drive (best-effort) once its metrics
    are already saved — frees ~2.5 GB/run so a long series doesn't fill the disk.  Failure is
    logged, never fatal (the monitor's disk guard catches genuine pressure)."""
    if not cfg.archive_root or not job_id:
        return
    try:
        from backend.core import job_archive
        from backend.core.oxdna_job import OxdnaJob
        job = OxdnaJob.load(job_id, pathlib.Path(ws))
        dest = job_archive.archive_job(job, pathlib.Path(ws), "oxdna_jobs",
                                       pathlib.Path(cfg.archive_root))
        _log_monitor(f"archived {job_id} → {dest}")
    except Exception as e:  # noqa: BLE001 — never let archiving kill the experiment
        _log_monitor(f"ARCHIVE FAILED for {job_id}: {e}")


def _done(records, strategy, delta):
    return next((r for r in records
                 if r.get("strategy") == strategy and r.get("delta") == delta
                 and r.get("status") == "ok"), None)


# ── main sweep ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--steps", type=int, default=4, help="± grid steps each way")
    ap.add_argument("--backend", default="CPU")
    ap.add_argument("--device", default="0")
    ap.add_argument("--skip-benchmark", action="store_true")
    ap.add_argument("--steps-per-s", type=float, default=None,
                    help="measured steps/s for the monitor ETA (use when forcing a backend)")
    ap.add_argument("--archive-root",
                    default="/media/jojo/Archive/NADOC_archive/exp31_skip_twist_curvature_sweep",
                    help="move each finished run's job folder here after metrics extraction")
    ap.add_argument("--no-archive", action="store_true",
                    help="keep all job folders in the workspace (disables archiving)")
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args()
    cfg = Cfg(args)

    ws = args.workspace or str(HERE / ("ws_dry" if cfg.dry else "ws"))
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if cfg.archive_root:
        mount = pathlib.Path(cfg.archive_root).parent
        if mount.exists():
            print(f"[exp31] archiving finished runs → {cfg.archive_root}")
        else:
            print(f"[exp31] WARNING: archive mount {mount} not present — runs will NOT be "
                  f"archived and the disk may fill. (--no-archive to silence.)")
            _log_monitor(f"WARNING archive mount missing: {mount}")
    else:
        print("[exp31] archiving DISABLED (--no-archive)")

    print(f"[exp31] building bare {len(cfg.cells)}-helix × {cfg.length}bp SQ base…")
    bare_base = build_sq_skip_design(cfg.cells, cfg.length, None)
    base = baseline_skips(bare_base, skip_period=cfg.baseline_period)
    base_total = sum(len(v) for v in base.values())
    print(f"[exp31] baseline: {base_total} skips over {len(bare_base.helices)} helices "
          f"(period {cfg.baseline_period})")

    # Benchmark first → fastest backend + steps/s for the poller ETA.
    if not cfg.skip_benchmark:
        _log_monitor("benchmark: starting hardware sweep")
        bench = run_oxdna_benchmark(bare_base, ws)
        rec = bench.get("recommendation") or {}
        cfg.backend = rec.get("backend", cfg.backend)
        cfg.device = rec.get("device", cfg.device)
        cfg.steps_per_s = rec.get("steps_per_s")
        apply_oxdna_benchmark(bare_base, rec)        # persist into metadata (record only)
        print(f"[exp31] benchmark → backend={cfg.backend} device={cfg.device} "
              f"steps/s={cfg.steps_per_s}")
        _log_monitor(f"benchmark: backend={cfg.backend} device={cfg.device} "
                     f"steps/s={cfg.steps_per_s}")

    records = _load_results()
    _log_monitor(f"sweep start: deltas={cfg.deltas} strategies={list(STRATEGIES)} "
                 f"backend={cfg.backend}")

    # 1) shared baseline (Δ=0) — one sim, copied to all three strategies' rows.
    base_rec = _done(records, "uniform", 0)
    if base_rec is None:
        base_rec = run_point("uniform", 0, base, bare_base, ws, cfg, records)
    base_dev = _dev_from_json(base_rec.get("deviation_by_bp")) if base_rec.get("status") == "ok" else {}
    for s in ("incremental", "deviation"):
        if _done(records, s, 0) is None and base_rec.get("status") == "ok":
            mirror = {**base_rec, "strategy": s}
            records.append(mirror)
    _save_results(records)
    plot.regenerate()

    # 2) uniform + incremental — independent points, both directions.
    for delta in [d for d in cfg.deltas if d != 0]:
        for strategy, place in (("uniform", place_uniform), ("incremental", place_incremental)):
            if _done(records, strategy, delta):
                continue
            run_point(strategy, delta, place(bare_base, base, delta), bare_base, ws, cfg, records)

    # 3) deviation-guided — sequential chain outward in each direction.
    for direction in (+1, -1):
        prev_skips, prev_dev = base, base_dev
        for step in range(1, max(cfg.deltas) + 1):
            delta = direction * step
            done = _done(records, "deviation", delta)
            if done:
                prev_skips = {h: v for h, v in (done.get("skips") or {}).items()}
                prev_dev = _dev_from_json(done.get("deviation_by_bp"))
                continue
            skips = place_deviation_step(bare_base, prev_skips, direction, prev_dev)
            rec = run_point("deviation", delta, skips, bare_base, ws, cfg, records)
            prev_skips = skips
            prev_dev = _dev_from_json(rec.get("deviation_by_bp")) if rec.get("status") == "ok" else prev_dev

    n_ok = sum(1 for r in records if r.get("status") == "ok")
    _log_monitor(f"sweep complete: {n_ok}/{len(records)} points ok")
    _clear_current()
    (RESULTS_DIR / "COMPLETE").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + f" {n_ok} ok\n")
    print(f"[exp31] done — {n_ok} ok points. PNG: {plot.PNG}")


if __name__ == "__main__":
    main()
