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

The oracle lives in backend/core/atomistic_validation.py (reusable + unit-tested);
this is the thin CLI the `validate-atomistic` skill calls.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.api.assembly import _WORKSPACE_DIR
from backend.core.oxdna_job import OxdnaJob
from backend.core.models import Design
from backend.core.atomistic_validation import latest_job_for_design, audit_oxdna_job


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    no_align = "--no-align" in sys.argv
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

    report = audit_oxdna_job(design, job, ws, align=not no_align)
    if as_json:
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1

    if not report.get("ready"):
        print(f"job {job_id}: not ready — {report.get('reason')}")
        return 2

    _print_human(stem, report)
    return 0 if report["ok"] else 1


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
