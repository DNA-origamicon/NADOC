#!/usr/bin/env python3
"""SNUPI ↔ CanDo (↔ MD) cross-comparison over qualifying designs.

Runs the SAME native FEM twice per design — ``predict_shape(material="cando")`` and
``predict_shape(material="snupi")`` — and compares them through the EXISTING cross-engine
comparison framework (`build_cando_shape_source` → `build_comparison_report`), the same one
the in-app Shape-comparison card uses.  For designs with a free (k=0) NAMD DCD on disk it
adds the MD trajectory as the gold RMSF reference (`md_rmsf` → `build_namd_shape_source`),
reproducing the P4 verdict: does SNUPI's per-bp RMSF pattern match MD better than CanDo's?

"Basic SNUPI check" = a paired duplex core with NO extra crossover bases (base SNUPI can't
predict extra-base motifs — those are the extension targets, excluded here).

RMSF is the free-free NMA (material-dependent, solve-mode-INDEPENDENT), so the fast LINEAR
solve gives the same RMSF as the nonlinear one; shape descriptors (twist/bend) come from the
same frame.  Physical-layer / display-only throughout (Three-Layer Law).

Usage:
    uv run python scripts/snupi_cross_compare.py [--nonlinear] [--only 6hbx100_noT,3x4SQ]
Writes a JSON report to experiments/exp42_snupi_cross_compare/results.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.core.models import Design                                  # noqa: E402
from backend.physics.fem_solver import predict_shape                    # noqa: E402
from backend.api.skip_twist_tuning import core_reference_geometry       # noqa: E402
from backend.core.cando_shape_source import build_cando_shape_source    # noqa: E402
from backend.core.shape_compare import build_comparison_report          # noqa: E402

WS = REPO / "workspace"
OUT_DIR = REPO / "experiments" / "exp42_snupi_cross_compare"

# ── The design battery ─────────────────────────────────────────────────────────
# md: (job_dir, name_stem, dcd_glob, design_json|None) → the free k=0 NAMD reference.
BATTERY = [
    {"name": "6hbx100_noT", "nadoc": "6hbx100_noT.nadoc", "lattice": "HC",
     "md": {"job": "892ad3d12d4f", "stem": "6hbx100_noT",
            "dcd": "6hbx100_noT_01_production_20ns_k0.dcd", "design_json": True}},
    {"name": "3x4SQ", "nadoc": "3x4SQ.nadoc", "lattice": "SQ",
     "md": {"job": "93cdbbd3a3f1", "stem": "3x4SQ",
            "dcd": "3x4SQ_18_production_5ns_k0_p100.dcd", "design_json": False}},
    {"name": "6hb_validated", "nadoc": "6hb_validated.nadoc", "lattice": "HC", "md": None},
    {"name": "2hb_noT",       "nadoc": "2hb_noT.nadoc",       "lattice": "HC", "md": None},
    {"name": "10hb",          "nadoc": "10hb.nadoc",          "lattice": "HC", "md": None},
    {"name": "18hb",          "nadoc": "18hb.nadoc",          "lattice": "HC", "md": None},
    {"name": "U6HB",          "nadoc": "U6HB.nadoc",          "lattice": "HC", "md": None},
]


def _load(nadoc: str) -> Design:
    return Design.model_validate_json((WS / nadoc).read_text())


def _rmsf_mean(result: dict) -> float | None:
    vals = [r["rmsf_nm"] for r in (result.get("rmsf") or [])]
    return round(sum(vals) / len(vals), 4) if vals else None


def _fem_source(design, result: dict, engine: str) -> dict | None:
    """A cando/snupi source bundle for build_comparison_report (engine tag overridden)."""
    if not result.get("positions"):
        return None
    ref = core_reference_geometry(design)
    bundle = build_cando_shape_source(result["positions"], ref, rmsf=result.get("rmsf"))
    bundle["engine"] = engine
    return bundle


def _md_source(entry: dict) -> tuple[dict | None, float | None]:
    """The NAMD gold RMSF/shape source from the on-disk free k=0 DCD, or (None, None)."""
    from backend.core.md_trajectory import md_rmsf
    from backend.core.namd_shape_source import build_namd_shape_source

    md = entry["md"]
    jd = WS / "md_jobs" / md["job"]
    pkg = next((jd / "package").glob("*/"), None)
    if pkg is None:
        return None, None
    psf = pkg / f"{md['stem']}.psf"
    ref_pdb = pkg / f"{md['stem']}.pdb"
    dcd = pkg / "output" / md["dcd"]
    if not (psf.exists() and ref_pdb.exists() and dcd.exists()):
        print(f"    [md] missing topology/dcd for {entry['name']}")
        return None, None
    # The MD design snapshot: the job's own design.json if present, else the live .nadoc.
    md_design = (Design.model_validate_json((jd / "design.json").read_text())
                 if md["design_json"] else _load(entry["nadoc"]))
    segments = [("prod", "md", dcd)]
    res = md_rmsf(str(psf), segments, str(ref_pdb), md_design, max_frames=150)
    if not res.get("positions"):
        print(f"    [md] md_rmsf produced no positions for {entry['name']}: {res.get('reason')}")
        return None, None
    reference = core_reference_geometry(md_design)
    src = build_namd_shape_source(res["positions"], reference, rmsf_positions=res["positions"])
    mean = round(res.get("mean_rmsf"), 4) if res.get("mean_rmsf") is not None else None
    return src, mean


def _agreement(report: dict, engine: str) -> dict:
    for row in report.get("agreement", []):
        if row["engine"] == engine:
            return row
    return {}


def run(entry: dict, *, nonlinear: bool) -> dict:
    name = entry["name"]
    print(f"[{name}] ({entry['lattice']}) loading + solving …")
    design = _load(entry["nadoc"])
    out = {"design": name, "lattice": entry["lattice"], "nadoc": entry["nadoc"]}
    try:
        t0 = time.monotonic()
        cando = predict_shape(design, nonlinear=nonlinear, with_rmsf=True, material="cando")
        snupi = predict_shape(design, nonlinear=nonlinear, with_rmsf=True, material="snupi")
        out["solve_seconds"] = round(time.monotonic() - t0, 1)
    except ValueError as exc:
        out["error"] = str(exc)
        print(f"    SKIP: {exc}")
        return out

    out["n_bp_nodes"] = len(cando.get("rmsf") or [])
    out["rmsf_mean_nm"] = {"cando": _rmsf_mean(cando), "snupi": _rmsf_mean(snupi)}

    sources = [_fem_source(design, cando, "cando"), _fem_source(design, snupi, "snupi")]
    md_mean = None
    if entry.get("md"):
        print("    computing MD RMSF (free k=0 DCD) …")
        md_src, md_mean = _md_source(entry)
        if md_src:
            sources.insert(0, md_src)
    out["rmsf_mean_nm"]["md"] = md_mean

    report = build_comparison_report([s for s in sources if s])
    out["rmsf_reference"] = report.get("references", {}).get("rmsf")

    # Agreement of each FEM material vs the RMSF reference (MD if present, else CanDo).
    ag = {}
    for eng in ("cando", "snupi"):
        row = _agreement(report, eng).get("rmsf")
        if row:
            ag[eng] = {k: (round(row[k], 4) if isinstance(row.get(k), float) else row.get(k))
                       for k in ("pearson", "spearman", "n")}
    out["rmsf_vs_reference"] = ag

    # Shape descriptors (twist/bend/…) per engine from the scalar table.
    desc = {}
    for sc in report.get("scalars", []):
        cells = sc.get("cells", {})
        desc[sc["name"]] = {e: (round(cells[e]["value"], 3) if isinstance(cells.get(e, {}).get("value"), float)
                                else cells.get(e, {}).get("value"))
                            for e in cells}
    out["shape_descriptors"] = desc
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nonlinear", action="store_true",
                    help="Fine (nonlinear) solve for shape descriptors (RMSF is identical either way)")
    ap.add_argument("--only", default=None, help="comma-separated design names to run")
    args = ap.parse_args()

    battery = BATTERY
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        battery = [e for e in battery if e["name"] in want]

    results = [run(e, nonlinear=args.nonlinear) for e in battery]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "results.json").write_text(json.dumps(
        {"solve": "nonlinear" if args.nonlinear else "linear", "results": results}, indent=2))

    # ── Summary table ──────────────────────────────────────────────────────────
    print("\n" + "=" * 92)
    print(f"{'design':<15}{'ref':<6}{'RMSF mean (nm) c/s/md':<26}"
          f"{'pearson c→ref / s→ref':<24}{'spearman c/s':<16}")
    print("-" * 92)
    for r in results:
        if r.get("error"):
            print(f"{r['design']:<15}SKIP ({r['error'][:60]})")
            continue
        rm = r["rmsf_mean_nm"]
        means = f"{rm.get('cando')}/{rm.get('snupi')}/{rm.get('md')}"
        ag = r.get("rmsf_vs_reference", {})
        pear = f"{ag.get('cando', {}).get('pearson')} / {ag.get('snupi', {}).get('pearson')}"
        spear = f"{ag.get('cando', {}).get('spearman')} / {ag.get('snupi', {}).get('spearman')}"
        print(f"{r['design']:<15}{str(r.get('rmsf_reference')):<6}{means:<26}{pear:<24}{spear:<16}")
    print("=" * 92)
    print("pearson/spearman = correlation of each FEM material's per-bp RMSF vs the reference")
    print("(reference = MD when a free k=0 DCD exists, else CanDo). Higher snupi→ref = SNUPI wins.")
    print(f"\nfull JSON → {OUT_DIR / 'results.json'}")


if __name__ == "__main__":
    main()
