#!/usr/bin/env python
"""Audit the atomistic ball-and-stick / VDW display of an oxDNA job's relaxed frame.

Every bond (stick) and atom (sphere) the oxDNA-display toggle would draw is measured
and flagged — invalid bonds (broken rigidity / over-stretched backbone / non-finite),
bonds the renderer HIDES (too long to draw but still present), clashes, and stranded
atoms.  Read-only.

    uv run python scripts/audit_atomistic.py                       # 6hb_sim_tests, latest job
    uv run python scripts/audit_atomistic.py 18hb2                 # another design stem
    uv run python scripts/audit_atomistic.py 6hb_sim_tests <job_id>
    uv run python scripts/audit_atomistic.py --json               # machine-readable
    uv run python scripts/audit_atomistic.py --trajectory          # audit View-trajectory frames
    uv run python scripts/audit_atomistic.py 6hb_sim_tests <job> --trajectory --json

``--trajectory`` audits a SAMPLING of the View-trajectory scrub (whole lineage), not
just the single relaxed frame — proving the forward/reverse-phase + closure + identity
invariants hold on every frame.  The oracle lives in
backend/core/atomistic_validation.py (reusable + unit-tested); this is the thin CLI the
`validate-atomistic` skill calls.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.api.assembly import _WORKSPACE_DIR
from backend.core.oxdna_job import OxdnaJob
from backend.core.models import Design
from backend.core.atomistic_validation import (
    latest_job_for_design, audit_oxdna_job, audit_trajectory_frames)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    no_align = "--no-align" in sys.argv
    trajectory = "--trajectory" in sys.argv
    stem = args[0] if args else "6hb_sim_tests"
    job_id = args[1] if len(args) > 1 else None
    ws = Path(_WORKSPACE_DIR)

    if job_id is None:
        job_id = latest_job_for_design(stem, ws)
        if job_id is None:
            print(f"No relaxed oxDNA job found for '{stem}' in {ws/'oxdna_jobs'}")
            return 2
    job = OxdnaJob.load(job_id, ws)
    snap = job.job_dir(ws) / "design.json"
    design = Design.model_validate_json(snap.read_text())

    if trajectory:
        return _run_trajectory(stem, job, design, ws, as_json)

    report = audit_oxdna_job(design, job, ws, align=not no_align)
    if as_json:
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1

    if not report.get("ready"):
        print(f"job {job_id}: not ready — {report.get('reason')}")
        return 2

    _print_human(stem, report)
    return 0 if report["ok"] else 1


def _run_trajectory(stem: str, job, design, ws: Path, as_json: bool) -> int:
    """Audit a sampling of the composite View-trajectory frames (whole lineage)."""
    from backend.api.routes_oxdna import _composite_inputs
    design, stages, ref = _composite_inputs(job)
    if not stages:
        print(f"job {job.job_id}: no trajectory yet")
        return 2
    report = audit_trajectory_frames(design, stages, ref)
    report["job_id"] = job.job_id
    if as_json:
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1
    if not report.get("ready"):
        print(f"job {job.job_id}: not ready — {report.get('reason')}")
        return 2
    _print_trajectory(stem, report)
    return 0 if report["ok"] else 1


def _print_trajectory(stem: str, r: dict) -> None:
    s = r["summary"]
    print(f"=== trajectory display audit · {stem} · job {r['job_id']} ===")
    print(f"composite frames={r['n_frames']}  audited={s['n_audited']} {r['audited_frames']}")
    print(f"VERDICT: {'ALL FRAMES SOUND' if r['ok'] else 'REGRESSION'}  "
          f"(invariants_ok={s['all_invariants_ok']}, identity_preserved={s['identity_preserved']})")
    rng = s["wc_c1c1_median_range"]
    print(f"  WC C1'-C1' median range: {rng[0]}–{rng[1]} nm [B-DNA ~1.05]")
    print(f"  max rigid-stamp violations: {s['max_rigid_stamp_violations']}  "
          f"any wc-collapsed: {s['any_wc_collapsed']}  "
          f"any forward/reverse-imbalanced: {s['any_wc_helix_imbalanced']}  "
          f"any over-stretched: {s['any_over_stretched']}  max clashes: {s['max_clashes']}")
    if s["failed_frames"]:
        print(f"  FAILED frames: {s['failed_frames']}")
    print("\nper frame:")
    for f in r["frames"]:
        flag = "OK " if f["invariants_ok"] else "BAD"
        print(f"  [{flag}] frame {f['frame']:4d}  WC={f['wc_c1c1_median']} nm  "
              f"stampΔ={f['rigid_stamp_max_dev_nm']*10:.3f}Å  "
              f"stamp_viol={f['n_rigid_stamp_violations']}  invalid={f['n_invalid_bonds']}  "
              f"clash={f['n_clashes']}  fwd/rev_imbal={f['wc_helix_imbalanced']}")


def _print_human(stem: str, r: dict) -> None:
    print(f"=== atomistic display audit · {stem} · job {r['job_id']} · stage {r['stage_name']} ===")
    print(f"atoms={r['n_atoms']}  bonds={r['n_bonds']}  "
          f"VERDICT: {'OK' if r['ok'] else 'INVALID'}")
    print("\nbond lengths by class (nm):")
    for cls, s in r["by_class"].items():
        if s["count"]:
            print(f"  {cls:9s} n={s['count']:5d}  min={s['min']:.3f}  "
                  f"mean={s['mean']:.3f}  max={s['max']:.3f}")
    print(f"\nrigid-frame stamp: max Δ vs template = "
          f"{r['rigid_stamp_max_dev_nm']*10:.4f} Å over RIGID bonds  "
          f"({r['n_rigid_stamp_violations']} violations — "
          f"{'STAMP OK' if r['n_rigid_stamp_violations'] == 0 else 'PLACER BUG'})")
    bg = r["base_geometry"]
    wc, st = bg["wc_c1c1"], bg["stacking_c1c1"]
    print("\ninter-base geometry (C1'-C1'):")
    print(f"  WC pairs   median={wc['median']} nm  (n={wc['count']}) [B-DNA ~1.05]  "
          f"{'COLLAPSED — bases crushed onto partners' if bg['wc_collapsed'] else 'OK'}")
    print(f"    by helix lattice dir: FORWARD={bg['wc_c1c1_forward_helix_median']} "
          f"REVERSE={bg['wc_c1c1_reverse_helix_median']} nm  "
          f"{'IMBALANCED — forward/reverse phase bug' if bg['wc_helix_imbalanced'] else 'balanced'}")
    print(f"  stacking   median={st['median']} nm  (n={st['count']}) [B-DNA ~0.5-0.7]")
    print(f"\ninvalid bonds: {r['n_invalid_bonds']}")
    for b in r["invalid_bonds"][:25]:
        print(f"  #{b['serials']} {b['atoms']} {b['class']} "
              f"L={b['length_nm']} nm — {b['reason']}")
    if r["n_invalid_bonds"] > 25:
        print(f"  … +{r['n_invalid_bonds']-25} more")
    print(f"\nhidden by renderer (>{r['thresholds']['render_hide_nm']} nm — drawn as nothing): "
          f"{r['n_hidden_by_renderer']}")
    for b in r["hidden_by_renderer"][:15]:
        print(f"  #{b['serials']} {b['atoms']} {b['class']} L={b['length_nm']} nm")
    if r["n_hidden_by_renderer"] > 15:
        print(f"  … +{r['n_hidden_by_renderer']-15} more")
    print(f"\nclashes (<{r['thresholds']['clash_nm']} nm): {len(r['clashes'])}")
    for c in r["clashes"][:10]:
        print(f"  #{c['serials']} d={c['distance_nm']} nm")
    print(f"\nbad/stranded atoms: {len(r['bad_atoms'])}")
    for a in r["bad_atoms"][:10]:
        print(f"  #{a['serial']} {a['name']} {a['site']} — {a['reason']}")


if __name__ == "__main__":
    sys.exit(main())
