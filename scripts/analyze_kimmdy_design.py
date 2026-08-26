#!/usr/bin/env python3
"""Run KIMMDY-style CPD analysis on an arbitrary NADOC NAMD design.

Examples:

  uv run python scripts/analyze_kimmdy_design.py \
      --job workspace/md_jobs/29c5b267380f --mode designed

  uv run python scripts/analyze_kimmdy_design.py \
      --job /media/jojo/Archive/NADOC_archive/a_job --mode all-tt \
      --pair-scope interstrand --stride 50 --screen-cutoff-ang 6

  uv run python scripts/analyze_kimmdy_design.py \
      --design workspace/2hb_1xT.nadoc --topology package/design.psf \
      --dcd package/output/production.dcd --mode explicit \
      --pair 'D000:43~D001:44'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.core.kimmdy_analysis import (  # noqa: E402
    PAIR_MODES,
    PAIR_SCOPES,
    RATE_MODELS,
    analyze_kimmdy_trajectory,
    resolve_analysis_source,
    write_kimmdy_outputs,
)
from backend.core.models import Design  # noqa: E402


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = argument_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--job", type=Path, help="managed/archive NADOC MD job directory")
    source.add_argument("--design", type=Path, help="explicit .nadoc or design.json")
    argument_parser.add_argument("--topology", type=Path, help="PSF/topology override")
    argument_parser.add_argument("--dcd", type=Path, nargs="+", help="trajectory override(s)")
    argument_parser.add_argument("--out", type=Path, help="output directory")
    argument_parser.add_argument("--mode", choices=sorted(PAIR_MODES), default="designed")
    argument_parser.add_argument(
        "--pair", action="append", default=[], metavar="SEG:RES~SEG:RES",
        help="explicit T-T pair; repeat for multiple pairs",
    )
    argument_parser.add_argument(
        "--pair-scope", choices=sorted(PAIR_SCOPES), default="all",
        help="retain all, cross-strand, or same-strand candidate pairs",
    )
    argument_parser.add_argument(
        "--screen-cutoff-ang", type=float, default=6.0,
        help="all-tt midpoint-distance candidate cutoff in Angstrom (default 6)",
    )
    argument_parser.add_argument("--max-candidates", type=int, default=500)
    argument_parser.add_argument("--start", type=int, default=0)
    argument_parser.add_argument("--stop", type=int)
    argument_parser.add_argument("--stride", type=int, default=1)
    argument_parser.add_argument(
        "--max-frames", type=int, default=2000,
        help="widen stride to span the interval in at most this many samples; 0 disables",
    )
    argument_parser.add_argument(
        "--rate-model", choices=sorted(RATE_MODELS), default="upstream",
        help="primary ranking score; both models are always exported",
    )
    return argument_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    source = resolve_analysis_source(
        job_dir=args.job,
        design_path=args.design,
        topology_path=args.topology,
        trajectory_paths=args.dcd or (),
        output_dir=args.out,
    )
    design = Design.model_validate_json(source.design_path.read_text())

    last = {"stage": None, "done": 0}

    def progress(stage: str, done: int, total: int) -> None:
        if stage != last["stage"] or done == 1 or done == total or done - last["done"] >= 100:
            print(f"[{stage}] {done}/{total}", flush=True)
            last.update(stage=stage, done=done)

    report, series = analyze_kimmdy_trajectory(
        source.topology_path,
        source.trajectory_paths,
        design,
        pair_mode=args.mode,
        explicit_pairs=args.pair,
        pair_scope=args.pair_scope,
        screen_cutoff_ang=args.screen_cutoff_ang,
        max_candidates=args.max_candidates,
        start=args.start,
        stop=args.stop,
        stride=args.stride,
        max_frames=None if args.max_frames == 0 else args.max_frames,
        rate_model=args.rate_model,
        progress=progress,
    )
    report["source"] = {
        "design": str(source.design_path),
        "job": str(source.job_dir) if source.job_dir else None,
        "package": str(source.package_dir) if source.package_dir else None,
    }
    outputs = write_kimmdy_outputs(report, series, source.output_dir)

    print(
        f"\n{report['n_topology_thymines']} topology thymines; "
        f"{report['n_candidates']} analysed pairs; "
        f"{report['n_sampled_frames']}/{report['n_total_frames']} frames"
    )
    print(
        f"{'rank':>4}  {'pair':<38} {'<k>':>9} {'max k':>9} "
        f"{'%>=.1':>7} {'min d A':>8} {'intended':>9}"
    )
    for row in report["pairs"][:20]:
        print(
            f"{row['rank']:>4}  {row['label'][:38]:<38} "
            f"{row['primary_propensity_mean']:>9.5f} "
            f"{row['primary_propensity_max']:>9.5f} "
            f"{row['pct_primary_ge_0_1']:>7.2f} "
            f"{10 * row['d_mid_min_nm']:>8.2f} "
            f"{str(row['intended_weld']):>9}"
        )
    print("\n" + json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
