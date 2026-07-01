"""exp33 — atomistic-MD validation of oxDNA twist (3 structures).

Does oxDNA's twist prediction hold under FULL atomistic MD?  For each of three designs — the
analytical baseline (period 48), the exp31 incremental-best (222 skips, the flat one), and the
exp32 profile-guided converged design — this:

  1. Builds the design and SEEDS the atomistic model from that design's oxDNA-relaxed mean
     (so a FEW-NS atomistic run is meaningful — it asks whether CHARMM holds oxDNA's structure,
     not a multi-week from-ideal equilibration).
  2. Solvates with a 1.0 nm carved water shell (~1.1M atoms → fits the 12 GB GPU) + Mg/NaCl.
  3. Runs the proven equilibrium-aware NAMD ladder (reused from scripts/run_18hb.py), capped to
     ~`--prod-ns` of production.
  4. Extracts the per-nucleotide mean structure from the trajectory and measures its twist
     profile, then COMPARES to the oxDNA twist profile (overlay PNG + RMSD).
  5. Archives the (large) MD job folder to the external drive and frees disk.

Disk-budgeted: refuses to start a structure if root free-space would drop below `--min-free-gb`
(default 15); archives each finished job so the next has room.  Resume-safe (skips completed
structures in results.json).  Designed to be fired by the exp32-completion trigger.

  python run.py                 # full run (3 structures)
  python run.py --prep-only     # solvate + show the segment ladder, no MD (feasibility)
  python run.py --smoke         # tiny steps end-to-end (validate run + extraction)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import shutil
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "exp31_skip_twist_curvature_sweep"))  # profile + base builders

from backend.api.headless_oxdna_build import read_flexibility_map  # noqa: E402
from backend.api.skip_twist_tuning import (  # noqa: E402
    build_explicit_skip_from_design, build_sq_skip_design, core_reference_geometry, square_cells)
from backend.core import job_archive  # noqa: E402
from backend.core.atomistic import build_atomistic_model  # noqa: E402
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job  # noqa: E402
from backend.core.md_protocols import (  # noqa: E402
    EQUILIBRIUM_AWARE_PROTOCOL, prepare_equilibrium_aware_namd)
from backend.core.namd_runner import reconcile_job_status, run_job  # noqa: E402
from backend.core.oxdna_health import (  # noqa: E402
    _filter_to_reference_core, measure_bundle_twist, measure_bundle_twist_profile)
from backend.core.skip_sweep_strategies import baseline_skips  # noqa: E402

import md_compare  # noqa: E402  (sibling: extraction + comparison plot)

EXP31 = HERE.parent / "exp31_skip_twist_curvature_sweep"
EXP32 = HERE.parent / "exp32_profile_guided_refine"
OX_WS = EXP31 / "ws"               # archive-aware: oxDNA means resolve from the archive index
ARCHIVE = "/media/jojo/Archive/NADOC_archive/exp33_md_twist_validation"
RESULTS = HERE / "results" / "results.json"
WS = HERE / "ws"                    # MD workspace (md_jobs/ live here)


def _free_gb() -> float:
    return shutil.disk_usage(ROOT).free / 1e9


def _dirkey(v):
    return getattr(v, "value", v)


def _oxdna_override(ox_job_id: str) -> dict:
    """{(helix_id, bp_index, direction): xyz nm} from an oxDNA job's pooled mean (the seed)."""
    mean = read_flexibility_map(ox_job_id, OX_WS)
    return {(p["helix_id"], int(p["bp_index"]), _dirkey(p["direction"])):
            np.asarray(p["backbone_position"], float) for p in mean.get("positions", [])}


def structures(bare):
    """The 3 structures: (name, design, oxdna_seed_job, oxdna_profile_csv).  exp32-converged is
    read from exp32's last completed round at call time."""
    specs = []
    # 1) analytical baseline
    specs.append(("baseline_p48", build_sq_skip_design(square_cells(3, 6), 400, 48),
                  "d66341b955ba", EXP31 / "results/profiles/uniform_d+0.csv"))
    # 2) exp31 incremental-best (222 skips, the flat one)
    r31 = json.loads((EXP31 / "results/results.json").read_text())
    inc = next(x for x in r31 if x["strategy"] == "incremental" and x["delta"] == 4
               and x.get("status") == "ok")
    specs.append(("incremental_222", build_explicit_skip_from_design(bare, inc["skips"]),
                  inc["job_id"], EXP31 / "results/profiles/incremental_d+4.csv"))
    # 3) exp32 converged (last completed round)
    f32 = EXP32 / "results/results.json"
    if f32.exists():
        r32 = [x for x in json.loads(f32.read_text()) if x.get("status") == "ok"]
        if r32:
            last = max(r32, key=lambda x: x["round"])
            specs.append(("exp32_converged", build_explicit_skip_from_design(bare, last["skips"]),
                          last["job_id"], EXP32 / f"results/profiles/round_{last['round']}.csv"))
    return specs


def _cap_segments(segments, prod_ns: float, smoke: bool):
    """Trim the proven ladder to ~`prod_ns` of production (2 fs dt).  Seeded from the oxDNA-relaxed
    structure, the ENM release is short; we cap each segment and put the bulk in the final one."""
    if smoke:
        for s in segments:
            s.steps = min(s.steps, 200)
        return segments
    per_cap = 100_000                       # ≤0.2 ns per equilibration segment
    final_steps = int(prod_ns * 500_000)    # 500k steps/ns at 2 fs
    for s in segments[:-1]:
        s.steps = min(s.steps, per_cap)
    segments[-1].steps = final_steps
    return segments


def _measure_md_profile(job, design):
    """Per-nucleotide mean structure from the MD trajectory → differential twist profile +
    scalar, vs the design's analytic core.  Returns (twist_diff, profile_list) or (None, None)."""
    core = md_compare.md_mean_core_positions(job, WS, design)
    if not core:
        return None, None
    ref = core_reference_geometry(design)
    core = _filter_to_reference_core(core, ref)
    tdiff = measure_bundle_twist(core) - measure_bundle_twist(ref)
    prof = md_compare.differential_profile(core, ref, length_bp=400)
    return round(tdiff, 2), prof


def run_structure(name, design, ox_job, ox_profile, args, records):
    if _free_gb() < args.min_free_gb:
        print(f"[exp33] DISK GUARD: {_free_gb():.0f} GB free < {args.min_free_gb} — stopping", flush=True)
        return False
    print(f"\n[exp33] === {name} (free {_free_gb():.0f} GB) ===", flush=True)
    t0 = time.time()
    override = _oxdna_override(ox_job)
    model = build_atomistic_model(design, nuc_pos_override=override)
    job = new_job(design_name=name, protocol=EQUILIBRIUM_AWARE_PROTOCOL, name_stem="",
                  package_subdir="", threads=16, devices="0")
    job.status = MdStatus.preparing; job.save(WS)
    print(f"[exp33] {name}: solvate+carve (1.0 nm shell) + configs…", flush=True)
    package_subdir, name_stem, segments = prepare_equilibrium_aware_namd(
        design, job.job_dir(WS), atomistic_model=model, water_shell_nm=1.0,
        ion_conc_mM=50.0, mg_conc_mM=12.5, salt_mode="custom",
        minimize_steps=2400 if args.smoke else 24_000, declash=False)
    segments = _cap_segments(segments, args.prod_ns, args.smoke)
    job.package_subdir = package_subdir; job.name_stem = name_stem
    job.segments = [MdSegmentStatus(name=s.name, stage=s.stage, percent=s.percent,
                                    steps=s.steps, status="pending") for s in segments]
    job.status = MdStatus.queued; job.save(WS)
    print(f"[exp33] {name}: {len(segments)} segments; prep {time.time()-t0:.0f}s; job {job.job_id}", flush=True)
    for s in segments:
        print(f"    {s.name:36s} steps={s.steps} ({s.stage})", flush=True)
    if args.prep_only:
        return True

    asyncio.run(run_job(job, WS))
    job = reconcile_job_status(MdJob.load(job.job_id, WS), WS)
    rec = {"name": name, "md_job": job.job_id, "ox_job": ox_job, "status": job.status.value,
           "wall_s": round(time.time() - t0, 1)}
    if job.status == MdStatus.completed:
        tdiff, prof = _measure_md_profile(job, design)
        rec["md_twist_diff"] = tdiff
        if prof:
            md_compare.save_profile(prof, HERE / f"results/md_{name}.csv")
            rmsd = md_compare.compare_and_plot(name, prof, ox_profile,
                                               HERE / f"results/compare_{name}.png")
            rec["profile_rmsd_vs_oxdna"] = rmsd
            print(f"[exp33] {name}: MD twist {tdiff}° vs oxDNA; profile RMSD {rmsd}°", flush=True)
    records.append(rec)
    (HERE / "results").mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(records, indent=2))
    # archive the heavy MD folder, free disk
    try:
        dest = job_archive.archive_job(MdJob.load(job.job_id, WS), WS, "md_jobs", pathlib.Path(ARCHIVE))
        print(f"[exp33] archived {job.job_id} → {dest}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[exp33] archive failed for {job.job_id}: {e}", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod-ns", type=float, default=3.0, help="production length per structure (ns)")
    ap.add_argument("--min-free-gb", type=float, default=15.0)
    ap.add_argument("--prep-only", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="tiny steps end-to-end (validate run+extract)")
    args = ap.parse_args()
    WS.mkdir(parents=True, exist_ok=True); (HERE / "results").mkdir(parents=True, exist_ok=True)

    bare = build_sq_skip_design(square_cells(3, 6), 400, None)
    records = json.loads(RESULTS.read_text()) if RESULTS.exists() else []
    done = {r["name"] for r in records if r.get("status") == "completed"}
    for name, design, ox_job, ox_profile in structures(bare):
        if name in done:
            print(f"[exp33] {name} already done — skip", flush=True); continue
        if not run_structure(name, design, ox_job, ox_profile, args, records):
            break
    (HERE / "results" / "COMPLETE").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    print("[exp33] done.", flush=True)


if __name__ == "__main__":
    main()
