#!/usr/bin/env python3
"""
exp29 — MD structure-prep relaxation harness.

Goal: find a preparation recipe that lets a strained design (forced ligation +
2xT inserted bases) survive the ENM-release ladder without the WC health gate
collapsing.  Drives the *real* production prep/health code paths
(``prepare_mgh_slow_release`` + ``run_health_check``) but with a SHORT,
fully-parameterised ladder so a whole cycle finishes in minutes on the 2hb test
design instead of hours on the 6hb production design.

One invocation == one "cycle" == one prep recipe.  It:
  1. loads a .nadoc design,
  2. prepares the solvated package (GROMACS) with a chosen ``minimize_steps``,
  3. runs the ENM minimisation (declash auto-enabled for extra-base designs),
  4. rebuilds the declashed references (mirrors the runner),
  5. runs each k-ladder stage for ``stage_ns`` and records the C1'/WC health
     numbers after every stage — WITHOUT stopping on a failed gate, so we see
     the full degradation curve, not just the first failure.

Results land in ``runs/<label>/cycle_result.json`` and a one-line row is
appended to ``RESULTS.tsv`` next to this script.

Usage:
  python run_cycle.py --label baseline_min4800 --minimize-steps 4800
  python run_cycle.py --label longmin_50k     --minimize-steps 50000 --stage-ns 0.3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core.models import Design  # noqa: E402
from backend.core.md_protocols import (  # noqa: E402
    SegmentSpec,
    _segment_conf,
    _round_up_to_cycle,
    parse_box_from_namd_conf,
    prepare_mgh_slow_release,
    rebuild_declashed_references,
)
from backend.core.md_health import run_health_check  # noqa: E402
from backend.core.namd_runner import find_namd  # noqa: E402

HERE = Path(__file__).resolve().parent


def _expand_helix_spacing(design: "Design", scale: float) -> "Design":
    """Lateral (inter-helix) expansion of a Design — GEOMETRIC layer only.

    Mirrors the frontend 'Q' quick-expand (`scene/expanded_spacing.js`
    `_computeOffsets`): each helix is translated radially outward from the
    centroid of all helix lateral positions to `scale`× its current distance,
    leaving axis-parallel positions and ALL topology (strands, crossovers,
    extra_bases, forced ligations) untouched. `scale=1.0` is a no-op; `scale=1.1`
    is +10% inter-helix spacing ("slight"). Tests whether giving the bundle more
    room relieves the global melt (vs the salt arm's electrostatic screening).
    """
    if scale == 1.0 or not design.helices:
        return design
    d = design.model_copy(deep=True)
    h0 = d.helices[0]
    dx = abs(h0.axis_end.x - h0.axis_start.x)
    dy = abs(h0.axis_end.y - h0.axis_start.y)
    dz = abs(h0.axis_end.z - h0.axis_start.z)
    axis = "Z" if (dz >= dx and dz >= dy) else ("Y" if (dy >= dx and dy >= dz) else "X")
    # lateral coords = the two axes perpendicular to the helix axis
    lat = {"Z": ("x", "y"), "Y": ("x", "z"), "X": ("y", "z")}[axis]
    cu = sum(getattr(h.axis_start, lat[0]) for h in d.helices) / len(d.helices)
    cv = sum(getattr(h.axis_start, lat[1]) for h in d.helices) / len(d.helices)
    for h in d.helices:
        du = (getattr(h.axis_start, lat[0]) - cu) * (scale - 1.0)
        dv = (getattr(h.axis_start, lat[1]) - cv) * (scale - 1.0)
        for ep in (h.axis_start, h.axis_end):  # same lateral shift to both ⇒ rigid translate
            setattr(ep, lat[0], getattr(ep, lat[0]) + du)
            setattr(ep, lat[1], getattr(ep, lat[1]) + dv)
    print(f"[expand] axis={axis} scale={scale:.3f} "
          f"({len(d.helices)} helices translated laterally; topology preserved)",
          flush=True)
    return d


def _parse_k_ladder(text: str) -> list[float | None]:
    out: list[float | None] = []
    for tok in text.split(","):
        tok = tok.strip()
        if not tok:
            continue
        v = float(tok)
        out.append(None if v == 0.0 else v)
    return out


def _ensure_enm_files_for_ladder(
    package_dir: Path, name_stem: str, k_ladder: list[float | None]
) -> list[str]:
    """Generate any missing intermediate-k ENM extraBonds file for the ladder.

    Production prep (``write_aksimentiev_enm_files``) only writes files for the
    canonical scales (0.5, 0.1, 0.01).  But the base-ring bond list + equilibrium
    lengths are computed ONCE and are k-INDEPENDENT — only column 3 (the
    force-constant scale) differs between files.  So a file for any intermediate k
    (0.3, 0.05, …) is byte-for-byte what production would emit for that scale: the
    same bond list with column 3 rewritten.  We derive missing files from an
    existing on-disk file so we pick up the post-declash (ss-excluded) bond list.
    Must be called AFTER ``rebuild_declashed_references``.
    """
    existing = sorted(package_dir.glob(f"{name_stem}_k*.enm.extra"))
    ref = next((p for p in existing if "declash" not in p.name), None)
    if ref is None:
        return []
    records: list[tuple[int, int, float]] = []
    for line in ref.read_text().splitlines():
        parts = line.split()
        if len(parts) != 5 or parts[0] != "bond":
            continue
        records.append((int(parts[1]), int(parts[2]), float(parts[4])))
    created: list[str] = []
    for k in k_ladder:
        if k is None:
            continue
        path = package_dir / f"{name_stem}_k{k:g}.enm.extra"
        if path.exists():
            continue
        k_text = f"{k:.6g}"
        with path.open("w") as fh:
            for a, b, dist in records:
                fh.write(f"bond{a:10d}{b:10d}{k_text:>10s}{dist:10.3g}\n")
        created.append(path.name)
    return created


def _run_namd(namd_bin: str, conf_stem: str, package_dir: Path, log: Path,
              threads: int, devices: str) -> tuple[int, float]:
    cmd = [namd_bin, f"+p{threads}", "+setcpuaffinity", "+devices", devices,
           f"{conf_stem}.conf"]
    t0 = time.time()
    with log.open("w") as fh:
        rc = subprocess.run(cmd, cwd=str(package_dir), stdout=fh,
                            stderr=subprocess.STDOUT).returncode
    return rc, time.time() - t0


def _ns_per_day_from_log(log: Path) -> float | None:
    try:
        for line in reversed(log.read_text(errors="replace").splitlines()):
            if "Benchmark time:" in line and "days/ns" in line:
                parts = line.split()
                i = parts.index("days/ns") - 1
                days_per_ns = float(parts[i])
                return 1.0 / days_per_ns if days_per_ns else None
    except (OSError, ValueError, IndexError):
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", default=str(REPO / "workspace" / "2hb_2xT.nadoc"))
    ap.add_argument("--label", required=True, help="short cycle name, used for run dir + log row")
    ap.add_argument("--minimize-steps", type=int, default=4800)
    ap.add_argument("--stage-ns", type=float, default=0.3,
                    help="ns to run at each k-ladder stage (short for fast cycles)")
    ap.add_argument("--k-ladder", default="0.5,0.1,0.01,0",
                    help="comma list of ENM k values; 0 == unrestrained handoff")
    ap.add_argument("--equil-ns", type=float, default=0.0,
                    help="extra ns to hold at the FIRST k before stepping down "
                         "(tests 'longer settle before release')")
    ap.add_argument("--ion-conc-mM", type=float, default=0.0,
                    help="added NaCl (monovalent) concentration; default 0.0 keeps "
                         "the 12.5 mM Mg origami buffer. Tests electrostatic "
                         "screening as a melt driver (Cycle-4 salt arm).")
    ap.add_argument("--expand-scale", type=float, default=1.0,
                    help="lateral inter-helix expansion (GEOMETRIC only, topology "
                         "preserved); 1.0=none, 1.1=+10%% 'slight'. Mirrors the "
                         "frontend 'Q' quick-expand. Tests whether more bundle room "
                         "relieves the global melt.")
    ap.add_argument("--threads", type=int, default=16,
                    help="NAMD +p worker threads. Default 16 = all physical cores "
                         "of the Ryzen 9 9950X (16C/32T); +setcpuaffinity binds one "
                         "thread per core (no SMT contention) to maximise ns/day.")
    ap.add_argument("--devices", default="0")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    design_path = Path(args.design)
    design = Design.model_validate_json(design_path.read_text())
    design = _expand_helix_spacing(design, args.expand_scale)
    k_ladder = _parse_k_ladder(args.k_ladder)

    run_dir = HERE / "runs" / args.label
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[cycle:{args.label}] design={design_path.name} "
          f"minimize_steps={args.minimize_steps} stage_ns={args.stage_ns} "
          f"equil_ns={args.equil_ns} ion_conc_mM={args.ion_conc_mM} "
          f"expand_scale={args.expand_scale} k_ladder={args.k_ladder}", flush=True)

    namd_bin = find_namd()

    # ── 1. Prepare package (GROMACS solvation + declash ENM + min conf) ─────────
    t_prep0 = time.time()
    package_subdir, name_stem, _segs = prepare_mgh_slow_release(
        design, run_dir, minimize_steps=args.minimize_steps,
        ion_conc_mM=args.ion_conc_mM,
    )
    package_dir = run_dir / package_subdir
    prep_s = time.time() - t_prep0
    manifest = json.loads((package_dir / "manifest.json").read_text())
    declash = bool(manifest.get("declash"))
    min_name = manifest["minimization"]["name"]
    box = parse_box_from_namd_conf((package_dir / "namd.conf").read_text())
    print(f"[cycle:{args.label}] prepared in {prep_s:.0f}s; name_stem={name_stem} "
          f"declash={declash} n_unpaired_excluded={manifest.get('n_unpaired_excluded')}",
          flush=True)

    soft = declash
    dt_fs = 1.0 if soft else 2.0

    # ── 2. Minimisation ─────────────────────────────────────────────────────────
    t0 = time.time()
    rc, _ = _run_namd(namd_bin, min_name, package_dir,
                      package_dir / f"{min_name}.log", args.threads, args.devices)
    min_s = time.time() - t0
    if rc != 0:
        print(f"[cycle:{args.label}] MINIMISATION FAILED rc={rc}", flush=True)
        return 1
    print(f"[cycle:{args.label}] minimisation done in {min_s:.0f}s "
          f"({args.minimize_steps} steps)", flush=True)

    # ── 3. Declash reference rebuild (mirror the runner) ────────────────────────
    if declash:
        report = rebuild_declashed_references(
            package_dir, name_stem, package_dir / "output" / f"{min_name}.coor")
        print(f"[cycle:{args.label}] declash rebuild: {report}", flush=True)

    # ── 3b. Ensure ENM files exist for every intermediate k in the ladder ────────
    created = _ensure_enm_files_for_ladder(package_dir, name_stem, k_ladder)
    if created:
        print(f"[cycle:{args.label}] generated {len(created)} intermediate-k ENM "
              f"file(s): {', '.join(created)}", flush=True)

    # ── 4. k-ladder stages with health after each ───────────────────────────────
    stages: list[dict] = []
    previous = min_name
    for i, k in enumerate(k_ladder):
        stage_ns = args.stage_ns + (args.equil_ns if i == 0 else 0.0)
        steps = _round_up_to_cycle(max(120, int(stage_ns * 1e6 / dt_fs)))
        klabel = "k0" if k is None else f"k{k:g}".replace(".", "p")
        seg_name = f"{name_stem}_s{i + 1:02d}_{klabel}"
        spec = SegmentSpec(
            name=seg_name,
            stage=f"300K NPT {'k=0' if k is None else f'ENM k={k}'}",
            percent=100.0,
            steps=steps,
            temp=300.0,
            damping=5.0,
            scale=k,
            npt=True,
            previous=previous,
            reinit=False,
            dcd_freq=max(1200, steps // 20),
            min_wc_ref_relative=0.75 if k is None else 0.80,
            extra_bonds_file=None if k is None else f"{name_stem}_k{k:g}.enm.extra",
            soft=soft,
        )
        (package_dir / f"{seg_name}.conf").write_text(
            _segment_conf(spec, name_stem, box, False))

        t0 = time.time()
        rc, _ = _run_namd(namd_bin, seg_name, package_dir,
                          package_dir / f"{seg_name}.log", args.threads, args.devices)
        wall_s = time.time() - t0
        nspd = _ns_per_day_from_log(package_dir / f"{seg_name}.log")
        rec = {"stage": i + 1, "k": k, "label": klabel, "ns": round(stage_ns, 3),
               "steps": steps, "wall_s": round(wall_s, 1), "ns_per_day": nspd,
               "namd_rc": rc}
        if rc != 0:
            rec.update({"crashed": True})
            stages.append(rec)
            print(f"[cycle:{args.label}] stage {i + 1} {klabel}: NAMD CRASHED rc={rc} "
                  f"(see {seg_name}.log)", flush=True)
            break
        h = run_health_check(package_dir, seg_name, name_stem,
                             min_c1_paired=0.90,
                             min_wc_ref_relative=spec.min_wc_ref_relative)
        rec.update({
            "c1_paired": round(h.c1_paired_fraction or 0.0, 4),
            "c1_mean_ang": round(h.c1_mean_ang or 0.0, 3),
            "wc_ref_relative": round(h.wc_ref_relative_fraction or 0.0, 4),
            "wc_mean_hbond_ang": round(h.wc_mean_hbond_ang or 0.0, 3),
            "passed": bool(h.passed),
            "reason": h.reason or h.error or "",
        })
        stages.append(rec)
        print(f"[cycle:{args.label}] stage {i + 1} {klabel}: "
              f"C1'={rec['c1_paired'] * 100:.1f}% WC={rec['wc_ref_relative'] * 100:.1f}% "
              f"passed={rec['passed']} ({wall_s:.0f}s, {nspd or 0:.0f} ns/day)", flush=True)
        previous = seg_name

    # ── 5. Persist results ──────────────────────────────────────────────────────
    result = {
        "label": args.label,
        "design": design_path.name,
        "minimize_steps": args.minimize_steps,
        "stage_ns": args.stage_ns,
        "equil_ns": args.equil_ns,
        "k_ladder": args.k_ladder,
        "declash": declash,
        "soft_integrator": soft,
        "dt_fs": dt_fs,
        "prep_s": round(prep_s, 1),
        "min_s": round(min_s, 1),
        "first_fail_stage": next((s["stage"] for s in stages
                                  if not s.get("passed", False)), None),
        "all_passed": all(s.get("passed", False) for s in stages) and len(stages) == len(k_ladder),
        "notes": args.notes,
        "stages": stages,
    }
    (run_dir / "cycle_result.json").write_text(json.dumps(result, indent=2) + "\n")

    # Append a compact TSV row for cross-cycle comparison.
    tsv = HERE / "RESULTS.tsv"
    if not tsv.exists():
        tsv.write_text("label\tmin_steps\tstage_ns\tequil_ns\tk_ladder\t"
                       "first_fail\tall_passed\tper_stage_C1%_WC%\tnotes\n")
    per_stage = " | ".join(
        f"{s['label']}:{s.get('c1_paired', 0) * 100:.0f}/{s.get('wc_ref_relative', 0) * 100:.0f}"
        + ("CRASH" if s.get("crashed") else "")
        for s in stages)
    with tsv.open("a") as fh:
        fh.write(f"{args.label}\t{args.minimize_steps}\t{args.stage_ns}\t{args.equil_ns}\t"
                 f"{args.k_ladder}\t{result['first_fail_stage']}\t{result['all_passed']}\t"
                 f"{per_stage}\t{args.notes}\n")

    print(f"[cycle:{args.label}] DONE  all_passed={result['all_passed']} "
          f"first_fail_stage={result['first_fail_stage']}", flush=True)
    print(f"[cycle:{args.label}] {per_stage}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
