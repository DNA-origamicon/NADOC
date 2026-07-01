#!/usr/bin/env python3
"""Cross-engine check: does mrdna (CG/ARBD) reproduce oxDNA's global twist + twist
PROFILE for the exp31 3x6x400 square-lattice skip designs?

Apples-to-apples by construction:
  * SAME designs — rebuilt from the EXACT per-point skip patterns oxDNA stored in
    results/results.json (`skips: {helix:[bp]}`), so only the relaxation engine differs.
  * SAME metrics — feeds mrdna's relaxed positions through exp31's own
    measure_bundle_twist + compute_twist_profile (via core_reference_geometry +
    _filter_to_reference_core), the identical scoring oxDNA went through.

CRITICAL: mrdna's default CG bead model is generated *without twist*. To let
skip-induced over/under-wind express as global twist we pass coarse_local_twist=True.
Without it mrdna trivially relaxes to ~0 twist (a known CG-twist-coupling limitation).

Usage:
    uv run python experiments/exp31_skip_twist_curvature_sweep/mrdna_compare.py
    uv run python .../mrdna_compare.py --points uniform:0,uniform:-2,uniform:2
    uv run python .../mrdna_compare.py --coarse-steps 500000 --fine-steps 200000
    uv run python .../mrdna_compare.py --no-twist     # ablation: CG without local twist
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from glob import glob

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.skip_twist_tuning import (  # noqa: E402
    build_explicit_skip_from_design, build_sq_skip_design, core_reference_geometry, square_cells,
)
from backend.core.mrdna_bridge import (  # noqa: E402
    mrdna_model_from_nadoc, mrdna_tool_path, nuc_pos_override_from_arbd_strands,
)

# The real multi-stage driver (coarse→fine, honours step counts + coarse_local_twist).
# NOTE: model.simulate() is a SINGLE-stage ArbdModel method whose coarse_steps/fine_steps
# kwargs are silently swallowed → it runs default steps (the ~7s "relaxation" bug). Always
# use multiresolution_simulation for a controlled relaxation.
sys.path.insert(0, mrdna_tool_path())
from mrdna.simulate import multiresolution_simulation  # noqa: E402
from backend.core.oxdna_health import (  # noqa: E402
    _filter_to_reference_core, measure_bundle_curvature, measure_bundle_twist,
)

sys.path.insert(0, str(HERE))
import profile as twist_profile_mod  # noqa: E402

RESULTS_JSON = HERE / "results" / "results.json"
OXDNA_PROFILE_DIR = HERE / "results" / "profiles"
OUT_DIR = HERE / "results" / "mrdna"
LENGTH = 400
CELLS = square_cells(3, 6)


def _oxdna_points() -> dict:
    """(strategy, delta) -> oxDNA record (has skips, twist_diff, curvature_diff, _twist_profile via csv)."""
    recs = json.loads(RESULTS_JSON.read_text())
    out = {}
    for r in recs:
        if r.get("status") == "ok" and "skips" in r:
            out[(r["strategy"], int(r["delta"]))] = r
    return out


def _override_to_core_positions(override: dict) -> list:
    """Bridge dict {(h,bp,dir): nm-array} -> the list-of-dicts schema the metrics read."""
    return [
        {"helix_id": h, "bp_index": int(bp), "direction": d,
         "backbone_position": [float(x) for x in pos]}
        for (h, bp, d), pos in override.items()
    ]


def _find_fine(tmp: pathlib.Path, stem: str):
    """Fine CG stage = the largest stage that HAS a matching DCD. multiresolution
    also writes an atomistic stage (stem-3, ~30x more atoms) with NO trajectory; the
    DCD-match requirement excludes it (else psf↔dcd atom counts mismatch on read-back)."""
    dcd_stems = {pathlib.Path(d).stem: d for d in glob(str(tmp / "output" / "*.dcd"))}
    best, best_n = None, -1
    for psf in sorted(glob(str(tmp / f"{stem}*.psf"))):
        s = pathlib.Path(psf).stem
        if s not in dcd_stems:        # atomistic stage (no DCD) → skip
            continue
        # NATOM from the PSF header (cheaper than counting PDB ATOM lines)
        try:
            natom = next(int(ln.split()[0]) for ln in pathlib.Path(psf).read_text().splitlines()
                         if "!NATOM" in ln)
        except StopIteration:
            continue
        if natom >= best_n:           # >= so the LAST (final) fine stage wins the tie
            best_n, best = natom, psf
    if best is None:
        return None, None
    return best, dcd_stems[pathlib.Path(best).stem]


def run_mrdna_point(bare_base, skips_by_helix: dict, coarse_steps: int, fine_steps: int,
                    local_twist: bool):
    """Build the skip design, relax with mrdna, return (twist_sim, twist_diff, curv_sim,
    prof, prof_max, n_core, wall_s)."""
    import tempfile
    design = build_explicit_skip_from_design(bare_base, skips_by_helix)
    ref = core_reference_geometry(design)

    with tempfile.TemporaryDirectory(prefix="/tmp/mrdna_cmp_") as d:
        tmp = pathlib.Path(d)
        stem = "cmp"
        model = mrdna_model_from_nadoc(design)
        t0 = time.time()
        # redirect ARBD's fd-level flood to a log
        import os
        so, se = os.dup(1), os.dup(2)
        lf = os.open(str(tmp / "arbd.log"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        try:
            os.dup2(lf, 1); os.dup2(lf, 2)
            multiresolution_simulation(
                model, stem, directory=str(tmp),
                coarse_steps=int(coarse_steps), fine_steps=int(fine_steps),
                coarse_output_period=max(1, int(coarse_steps) // 10),
                fine_output_period=max(1, int(fine_steps) // 10),
                coarse_local_twist=bool(local_twist))
        finally:
            os.dup2(so, 1); os.dup2(se, 2); os.close(lf); os.close(so); os.close(se)
        wall = time.time() - t0

        psf, dcd = _find_fine(tmp, stem)
        if psf is None:
            return None
        override = nuc_pos_override_from_arbd_strands(design, psf, dcd, frame=-1, sigma_nt=1.5)

    core_positions = _override_to_core_positions(override)
    core = _filter_to_reference_core(core_positions, ref)
    twist_sim = measure_bundle_twist(core)
    twist_ana = measure_bundle_twist(ref)
    curv_sim = measure_bundle_curvature(core)
    prof = twist_profile_mod.compute_twist_profile(core, ref, length_bp=LENGTH)
    prof_max = max((abs(p["cum_twist_diff"]) for p in prof), default=0.0)
    return {
        "twist_sim": round(twist_sim, 2), "twist_analytic": round(twist_ana, 2),
        "twist_diff": round(twist_sim - twist_ana, 2),
        "curv_sim": round(curv_sim, 4), "prof_max": round(prof_max, 2),
        "n_core": len(core), "wall_s": round(wall, 1), "_prof": prof,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="uniform:0,uniform:-2,uniform:2",
                    help="comma list of strategy:delta to compare (must exist in oxDNA results)")
    ap.add_argument("--coarse-steps", type=int, default=300_000)
    ap.add_argument("--fine-steps", type=int, default=100_000)
    ap.add_argument("--no-twist", action="store_true",
                    help="ablation: build CG model WITHOUT local twist (expect ~0 twist)")
    args = ap.parse_args()

    try:
        sys.path.insert(0, mrdna_tool_path())
        import mrdna  # noqa: F401
    except ImportError:
        print("mrdna not importable — run ./scripts/setup-mrdna.sh"); return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ox = _oxdna_points()
    want = []
    for tok in args.points.split(","):
        strat, delta = tok.split(":")
        want.append((strat.strip(), int(delta)))

    bare_base = build_sq_skip_design(CELLS, LENGTH, None)
    print(f"mrdna vs oxDNA — 3x6x400 SQ  |  coarse={args.coarse_steps} fine={args.fine_steps} "
          f"local_twist={not args.no_twist}\n")
    hdr = f"{'point':16s} {'skips':>6s} | {'oxDNA twist':>11s} {'mrdna twist':>11s} " \
          f"{'Δ':>7s} | {'oxDNA pmax':>10s} {'mrdna pmax':>10s} | {'mrdna curv':>10s} {'wall':>6s}"
    print(hdr); print("-" * len(hdr))

    rows = []
    for (strat, delta) in want:
        rec = ox.get((strat, delta))
        if rec is None:
            print(f"{strat}:{delta:<+d}  — no oxDNA point, skipping"); continue
        skips = {h: list(v) for h, v in rec["skips"].items()}
        res = run_mrdna_point(bare_base, skips, args.coarse_steps, args.fine_steps,
                              local_twist=not args.no_twist)
        if res is None:
            print(f"{strat}:{delta:<+d}  — mrdna produced no fine stage"); continue
        label = f"{strat}_d{delta:+d}"
        twist_profile_mod.save_profile_csv(res["_prof"], OUT_DIR / f"{label}.csv")
        ox_twist = rec.get("twist_diff")
        ox_pmax = rec.get("twist_profile_max", "—")
        print(f"{label:16s} {sum(len(v) for v in skips.values()):>6d} | "
              f"{ox_twist:>11} {res['twist_diff']:>11} "
              f"{res['twist_diff'] - (ox_twist or 0):>+7.1f} | "
              f"{str(ox_pmax):>10} {res['prof_max']:>10} | "
              f"{res['curv_sim']:>10} {res['wall_s']:>5}s")
        rows.append({"point": label, "skips": sum(len(v) for v in skips.values()),
                     "ox_twist_diff": ox_twist, "mrdna_twist_diff": res["twist_diff"],
                     "ox_prof_max": ox_pmax, "mrdna_prof_max": res["prof_max"],
                     "mrdna_curv": res["curv_sim"], "wall_s": res["wall_s"]})

    (OUT_DIR / "compare.json").write_text(json.dumps(rows, indent=2))
    print(f"\nmrdna profiles → {OUT_DIR}/  (oxDNA profiles in {OXDNA_PROFILE_DIR}/)")
    print(f"summary → {OUT_DIR}/compare.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
