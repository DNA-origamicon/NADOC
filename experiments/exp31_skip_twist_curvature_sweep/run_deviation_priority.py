"""Priority run of the deviation-guided (strategy C) arm at the most back-loaded counts.

The main sweep runs C last; this bumps a focused subset forward to test whether deviation-guided
(local) placement flattens the back-loaded twist profile better than uniform at the SAME skip
count — informing whether finishing the full set is worthwhile.  Runs C(+1) (single step from the
baseline deviation field) and the C(−1)→C(−2) chain (each step consumes the prior sim's field),
i.e. the 168 / 132 / 114-skip points where uniform was 82% / 75% / 92% back-loaded.

Records into the SHARED results.json + profiles + archive via run.py's run_point, so the main
driver later SKIPS these (resume) and chains C(−3)/C(+2)… off them.  Run with the main driver
STOPPED (shares one GPU).  Usage:  python run_deviation_priority.py
"""
from __future__ import annotations

import pathlib
import sys
from argparse import Namespace

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import run as R  # noqa: E402

ARCHIVE = "/media/jojo/Archive/NADOC_archive/exp31_skip_twist_curvature_sweep"


def main() -> None:
    args = Namespace(dry_run=False, steps=4, backend="CUDA", device="0",
                     skip_benchmark=True, steps_per_s=2551.7,
                     archive_root=ARCHIVE, no_archive=False, workspace=None)
    cfg = R.Cfg(args)
    ws = str(HERE / "ws")
    pathlib.Path(ws).mkdir(parents=True, exist_ok=True)

    print("[priority-C] building bare base…", flush=True)
    bare = R.build_sq_skip_design(cfg.cells, cfg.length, None)
    base = R.baseline_skips(bare, skip_period=cfg.baseline_period)
    records = R._load_results()

    base_row = R._done(records, "uniform", 0)
    if not base_row:
        print("[priority-C] no baseline result yet — abort"); return
    base_dev = R._dev_from_json(base_row.get("deviation_by_bp"))

    # C(+1): single step from the baseline field (add one skip/helix at the deviation hotspot).
    if not R._done(records, "deviation", 1):
        skips = R.place_deviation_step(bare, base, +1, base_dev)
        R.run_point("deviation", 1, skips, bare, ws, cfg, records)

    # C(−1) → C(−2): sequential chain (remove one skip/helix at the hotspot each step).
    prev, prev_dev = base, base_dev
    for step in (1, 2):
        delta = -step
        done = R._done(records, "deviation", delta)
        if done:
            prev = {h: v for h, v in (done.get("skips") or {}).items()}
            prev_dev = R._dev_from_json(done.get("deviation_by_bp"))
            continue
        skips = R.place_deviation_step(bare, prev, -1, prev_dev)
        rec = R.run_point("deviation", delta, skips, bare, ws, cfg, records)
        prev = skips
        prev_dev = R._dev_from_json(rec.get("deviation_by_bp")) if rec.get("status") == "ok" else prev_dev

    print("[priority-C] done — C(+1), C(−1), C(−2) recorded.", flush=True)


if __name__ == "__main__":
    main()
