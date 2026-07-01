#!/usr/bin/env python3
"""Nick-artifact test: does LIGATING the staple nicks collapse oxDNA's +51deg residual
global twist on the period-48 3x6x400 SQ baseline?

Hypothesis (from the counting audit): oxDNA demands ~2x the literature skip density
(period 24 vs the canonical 48) because oxDNA2's residual +1.3deg/step NICK overtwist
accumulates over the design's ~112 mid-helix nicks into spurious global twist that the
skip loop then over-cancels. If so, ligating the nicks (restoring the backbone bonds —
geometry UNCHANGED, only topology differs) should drop the +51deg toward the real residual.

A/B is maximally clean: the oxDNA .dat config is byte-identical (ligation doesn't move any
nucleotide); only the .top strand assignment + n3/n5 bonds at the 112 co-linear nicks change.

Compares against the stored NICKED baseline (results.json uniform d+0 = +51.4deg,
profile in results/profiles/uniform_d+0.csv). Same relax + 8M production protocol.
Saves results/mrdna/../ligation/ligation_twist_compare.png on finish.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from backend.core.models import Direction  # noqa: E402
from backend.api.skip_twist_tuning import (  # noqa: E402
    build_sq_skip_design, square_cells, build_explicit_skip_from_design,
)
from backend.api.headless_oxdna_build import STANDARD_RELAX_PARAMS  # noqa: E402
from backend.core.skip_sweep_strategies import baseline_skips  # noqa: E402
from backend.core.lattice import _ligate  # noqa: E402
import run as exp31  # noqa: E402  (reuse exp31.measure — identical metric path)

OUT = HERE / "results" / "ligation"
OUT.mkdir(parents=True, exist_ok=True)
LENGTH = 400


def find_nicks(d):
    """Co-linear abutting strand-end pairs (s1 3' -> s2 5', same helix/dir/adjacent bp) = nicks."""
    starts = {}
    for s in d.strands:
        f = s.domains[0]
        starts.setdefault((f.helix_id, f.direction, f.start_bp), []).append(s.id)
    out = []
    for s1 in d.strands:
        dl = s1.domains[-1]
        adj = 1 if dl.direction == Direction.FORWARD else -1
        for s2id in starts.get((dl.helix_id, dl.direction, dl.end_bp + adj), []):
            if s2id != s1.id:
                out.append((s1.id, s2id))
    return out


def ligate_all_nicks(d):
    """Ligate every co-linear nick. _ligate keeps only s1's sequence, so re-attach the
    concatenated 5'->3' sequence (s1 then s2) onto the merged strand — preserving the
    EXACT per-nucleotide bases so the ligated .dat/sequence is identical to the nicked
    baseline and only the nick backbone bonds differ."""
    n = 0
    while n < 5000:
        nicks = find_nicks(d)
        if not nicks:
            break
        s1id, s2id = nicks[0]
        s1 = next(s for s in d.strands if s.id == s1id)
        s2 = next(s for s in d.strands if s.id == s2id)
        merged_seq = (s1.sequence or "") + (s2.sequence or "")
        d = _ligate(d, s1, s2)
        merged = next(s for s in d.strands if s.id == s1id)
        d = d.model_copy(update={"strands": [
            s.model_copy(update={"sequence": merged_seq}) if s.id == s1id else s
            for s in d.strands
        ]})
        n += 1
    return d, n


def _cfg():
    c = types.SimpleNamespace()
    c.backend = "CUDA"
    c.device = "0"
    c.relax = dict(STANDARD_RELAX_PARAMS)
    c.prod_steps, c.n_prod = 2_000_000, 4      # 8M total, matches the exp31 baseline
    c.timeout = 6 * 3600.0
    c.length = LENGTH
    return c


def main():
    t0 = time.time()
    bare = build_sq_skip_design(square_cells(3, 6), LENGTH, None)
    nicked = build_explicit_skip_from_design(bare, baseline_skips(bare, skip_period=48))
    ligated, n_lig = ligate_all_nicks(nicked)
    print(f"[setup] nicked strands={len(nicked.strands)} -> ligated strands={len(ligated.strands)} "
          f"({n_lig} nicks ligated)", flush=True)

    ws = str(OUT / "ws")
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)
    cfg = _cfg()

    print(f"[run] relaxing + producing LIGATED design (8M prod, CUDA)...", flush=True)
    rec = exp31.measure(ligated, ws, cfg)
    prof = rec.pop("_twist_profile", None)
    rec["wall_s"] = round(time.time() - t0, 1)
    print(f"[done] status={rec.get('status')} twist_diff={rec.get('twist_diff')} "
          f"prof_max={rec.get('twist_profile_max')} curv_diff={rec.get('curvature_diff')} "
          f"wall={rec['wall_s']}s", flush=True)

    # stored NICKED baseline
    recs = json.load(open(HERE / "results" / "results.json"))
    base = next(r for r in recs if r["strategy"] == "uniform" and r["delta"] == 0)

    summary = {
        "nicked_baseline": {"twist_diff": base["twist_diff"], "curv_diff": base.get("curvature_diff"),
                             "n_nicks": len(nicked.strands)},
        "ligated": {"twist_diff": rec.get("twist_diff"), "curv_diff": rec.get("curvature_diff"),
                    "prof_max": rec.get("twist_profile_max"), "status": rec.get("status"),
                    "n_strands": len(ligated.strands), "n_ligations": n_lig},
        "verdict": None,
    }
    if rec.get("twist_diff") is not None:
        drop = base["twist_diff"] - rec["twist_diff"]
        frac = drop / base["twist_diff"] if base["twist_diff"] else 0
        summary["verdict"] = (f"twist {base['twist_diff']:+.1f} -> {rec['twist_diff']:+.1f} "
                              f"({100*frac:.0f}% removed by ligation)")
    (OUT / "ligation_summary.json").write_text(json.dumps(summary, indent=2))
    print("[verdict]", summary["verdict"], flush=True)

    # PNG overlay: nicked baseline profile vs ligated profile
    try:
        import csv
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        bp = list(csv.DictReader(open(HERE / "results" / "profiles" / "uniform_d+0.csv")))
        bx = [float(r["position_bp"]) for r in bp]; by = [float(r["cum_twist_diff"]) for r in bp]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(bx, by, "-o", ms=3, color="C3",
                label=f"NICKED (period-48, 152 strands)  end {by[-1]:+.1f}°")
        if prof:
            lx = [p["position_bp"] for p in prof]; ly = [p["cum_twist_diff"] for p in prof]
            ax.plot(lx, ly, "-s", ms=3, color="C0",
                    label=f"LIGATED ({n_lig} nicks removed)  end {ly[-1]:+.1f}°")
        ax.axhline(0, color="k", lw=0.5, alpha=0.5)
        ax.set_xlabel("position along bundle (bp, axis-projected)")
        ax.set_ylabel("cumulative twist diff (sim − analytic, deg)")
        ax.set_title("Nick-artifact test: 3×6×400 SQ period-48 baseline\n"
                     "does ligating staple nicks collapse oxDNA's global twist?")
        ax.legend()
        fig.tight_layout()
        png = OUT / "ligation_twist_compare.png"
        fig.savefig(png, dpi=120)
        print(f"[png] {png}", flush=True)
    except Exception as exc:
        print(f"[png] failed: {exc}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
