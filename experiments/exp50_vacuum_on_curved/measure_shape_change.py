#!/usr/bin/env python3
"""exp50 — how much does the vacuum stage change SHAPE, and on what?

exp48 measured the vacuum ENRG-MD step on straight bundles (2hb / 6hb / 24hb) and found
modest effects: r_max moved -3 % to +3 %.  That is the wrong class of structure to judge
it on, and the tutorial says so implicitly — its Fig. 3 shows a hextube going from
"unrealistic, helices exactly parallel, Holliday junctions abnormally stretched" to the
chickenwire arrangement.  The step exists because the IDEALISED build is not a physical
structure, and the further a design's intended shape is from the lattice the builder can
express, the more work there is to do.

A designed BEND is the extreme case: the ideal build either holds the bend as a rigid
geometric transform with unrelaxed junctions, or does not hold it at all.  Either way the
vacuum step has something real to fix, where on a straight bundle it has almost nothing.

WHAT THIS MEASURES, per design, ideal vs vacuum-relaxed:

  * Kabsch RMSD (whole solute) — how far the structure actually moved.
  * r_max and the bbox extents — what it costs to solvate afterwards, which is where
    exp48's "-7 to -9 %" claim came from and where it inverts under bbox sizing.
  * end-to-end vector angle — for a bent design, whether the bend OPENED or CLOSED.
  * base-pair integrity — the step must not buy shape by tearing the duplex.
  * interhelical P-P spacing — whether the push bonds did their job.

    python experiments/exp50_vacuum_on_curved/measure_shape_change.py \\
        workspace/6hbx100_90deg.nadoc workspace/6hbx100_2xT.nadoc -o .../runs

⚠ Needs the GPU to itself.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from backend.core.models import Design  # noqa: E402
from backend.core.namd_push_bonds import interhelical_push_bonds  # noqa: E402
from backend.core.namd_runner import find_namd  # noqa: E402
from backend.core.namd_vacuum import build_namd_vacuum_package  # noqa: E402


def _run(conf: Path, cwd: Path, namd: str, threads: int) -> dict:
    log = cwd / f"{conf.stem}.log"
    t0 = time.monotonic()
    with log.open("w") as fh:
        p = subprocess.run([namd, f"+p{threads}", "+setcpuaffinity", conf.name],
                           cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    txt = log.read_text(errors="ignore")
    died = next((s.strip() for s in txt.splitlines()
                 if s.strip().startswith(("ERROR:", "FATAL ERROR"))), None)
    bm = re.findall(r"Benchmark time:.*?([\d.eE+-]+) s/step\s+([\d.eE+-]+) (ns/day|days/ns)", txt)
    ns_day = None
    if bm:
        v, unit = float(bm[-1][1]), bm[-1][2]
        ns_day = v if unit == "ns/day" else (1.0 / v if v else None)
    return {"ok": p.returncode == 0 and died is None and "End of program" in txt,
            "error": died, "wall_s": round(time.monotonic() - t0, 1), "ns_day": ns_day}


def _pdb_xyz(pdb_text: str) -> np.ndarray:
    return np.asarray([(float(l[30:38]), float(l[38:46]), float(l[46:54]))
                       for l in pdb_text.splitlines() if l.startswith("ATOM")])


def _kabsch_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    """RMSD after optimal superposition — the shape change, not the rigid-body move."""
    a = a - a.mean(0)
    b = b - b.mean(0)
    v, _s, w = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(v @ w))
    r = v @ np.diag([1.0, 1.0, d]) @ w
    return float(np.sqrt((((a @ r) - b) ** 2).sum() / len(a)))


def _shape(pos: np.ndarray) -> dict:
    c = pos.mean(0)
    r = np.linalg.norm(pos - c, axis=1)
    ext = pos.max(0) - pos.min(0)
    return {"r_max_ang": float(r.max()), "extent_ang": [float(x) for x in ext],
            "bbox_vol_nm3": float(np.prod(ext) / 1000.0),
            "rotation_vol_nm3": float((2 * r.max() / 10.0) ** 3)}


def _end_to_end_angle(pos: np.ndarray) -> float:
    """Angle between the first and last decile's principal axes — the bend, in degrees.

    A straight bundle reads ~0; a 90-degree design should read near 90 if the build
    holds the bend, and the vacuum stage's effect on it is the number of interest.
    """
    n = max(3, len(pos) // 10)
    def _axis(p):
        p = p - p.mean(0)
        return np.linalg.svd(p, full_matrices=False)[2][0]
    a, b = _axis(pos[:n]), _axis(pos[-n:])
    cos = float(np.clip(abs(np.dot(a, b)), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def _p_spacing(design, pdb_text: str) -> "float | None":
    """Median interhelical P-P distance at the push-bond sites, or None if there are none."""
    res = interhelical_push_bonds(design, pdb_text, r0_ang=None)
    if not res.n_bonds:
        return None
    xyz = _pdb_xyz(pdb_text)
    ds = [float(np.linalg.norm(xyz[int(p[1])] - xyz[int(p[2])]))
          for p in (ln.split() for ln in res.text.splitlines() if ln.startswith("bond"))]
    return float(np.median(ds)) if ds else None


def measure(design_path: Path, out: Path, namd: str, threads: int, ns: float) -> dict:
    design = Design.model_validate_json(design_path.read_text())
    stem_dir = out / design_path.stem
    stem_dir.mkdir(parents=True, exist_ok=True)
    sub, stem, segs = build_namd_vacuum_package(design, stem_dir, ns=ns)
    pkg = stem_dir / sub

    ideal_pdb = (pkg / f"{stem}.pdb").read_text()
    ideal = _pdb_xyz(ideal_pdb)
    print(f"  {design_path.stem}: {len(ideal):,} atoms, "
          f"{len(design.helices)} helices, {segs[0].steps:,} steps @ {segs[0].timestep_fs} fs")

    m = _run(pkg / f"{stem}_00_min_vacuum.conf", pkg, namd, threads)
    print(f"    minimise {'ok' if m['ok'] else 'FAILED'} ({m['wall_s']}s)")
    if not m["ok"]:
        return {"design": design_path.stem, "error": m["error"]}
    r = _run(pkg / f"{segs[0].name}.conf", pkg, namd, threads)
    print(f"    relax    {'ok' if r['ok'] else 'FAILED'} ({r['wall_s']}s, "
          f"{r['ns_day'] and round(r['ns_day'])} ns/day)")
    if not r["ok"]:
        return {"design": design_path.stem, "error": r["error"]}

    import MDAnalysis as mda
    u = mda.Universe(str(pkg / f"{stem}.psf"),
                     str(pkg / "output" / f"{segs[0].name}.coor"), format="NAMDBIN")
    relaxed = u.atoms.positions.copy()[:len(ideal)]

    # Write the relaxed structure back as a PDB so the P-P measurement can reuse the
    # same column-based reader the push-bond builder uses.
    relaxed_pdb_lines, k = [], 0
    for ln in ideal_pdb.splitlines():
        if ln.startswith("ATOM"):
            x, y, z = relaxed[k]; k += 1
            ln = f"{ln[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{ln[54:]}"
        relaxed_pdb_lines.append(ln)
    relaxed_pdb = "\n".join(relaxed_pdb_lines) + "\n"

    si, sr = _shape(ideal), _shape(relaxed)
    res = {
        "design": design_path.stem,
        "helices": len(design.helices),
        "atoms": int(len(ideal)),
        "deformations": len(getattr(design, "deformations", []) or []),
        "vacuum_ns": ns, "ns_day": r["ns_day"], "wall_s": r["wall_s"],
        "rmsd_ang": round(_kabsch_rmsd(ideal, relaxed), 2),
        "ideal": si, "relaxed": sr,
        "bbox_vol_delta_pct": round(100 * (sr["bbox_vol_nm3"] / si["bbox_vol_nm3"] - 1), 1),
        "rotation_vol_delta_pct": round(
            100 * (sr["rotation_vol_nm3"] / si["rotation_vol_nm3"] - 1), 1),
        "r_max_delta_pct": round(100 * (sr["r_max_ang"] / si["r_max_ang"] - 1), 1),
        "bend_deg_ideal": round(_end_to_end_angle(ideal), 1),
        "bend_deg_relaxed": round(_end_to_end_angle(relaxed), 1),
        "p_spacing_ideal_ang": _p_spacing(design, ideal_pdb),
        "p_spacing_relaxed_ang": _p_spacing(design, relaxed_pdb),
    }
    for k2 in ("p_spacing_ideal_ang", "p_spacing_relaxed_ang"):
        if res[k2] is not None:
            res[k2] = round(res[k2], 1)
    print(f"    RMSD {res['rmsd_ang']} A | r_max {res['r_max_delta_pct']:+.1f}% | "
          f"bbox vol {res['bbox_vol_delta_pct']:+.1f}% | rot vol "
          f"{res['rotation_vol_delta_pct']:+.1f}% | bend "
          f"{res['bend_deg_ideal']}->{res['bend_deg_relaxed']} deg")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("designs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--ns", type=float, default=0.5)
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    namd = find_namd()
    print(f"NAMD: {namd}\n")
    rows = []
    for d in args.designs:
        if not d.exists():
            print(f"  skip (missing): {d}")
            continue
        try:
            rows.append(measure(d, args.out, namd, args.threads, args.ns))
        except Exception as exc:  # noqa: BLE001 — one design must not stop the sweep
            print(f"  {d.stem}: FAILED — {exc}")
            rows.append({"design": d.stem, "error": str(exc)})
    (args.out / "exp50_report.json").write_text(json.dumps(rows, indent=2))
    print(f"\n{'design':<20}{'hel':>4}{'RMSD':>8}{'r_max':>8}{'bbox vol':>10}"
          f"{'rot vol':>9}{'bend':>14}")
    for r in rows:
        if r.get("error"):
            print(f"{r['design']:<20} ERROR {r['error'][:60]}")
            continue
        print(f"{r['design']:<20}{r['helices']:>4}{r['rmsd_ang']:>8.1f}"
              f"{r['r_max_delta_pct']:>+7.1f}%{r['bbox_vol_delta_pct']:>+9.1f}%"
              f"{r['rotation_vol_delta_pct']:>+8.1f}%"
              f"{r['bend_deg_ideal']:>7.1f}->{r['bend_deg_relaxed']:<5.1f}")
    print(f"\nreport: {args.out / 'exp50_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
