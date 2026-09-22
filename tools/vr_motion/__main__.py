"""Run from the repository root: python -m tools.vr_motion --help."""
import argparse
import json
from pathlib import Path

from .behavior import catalog, import_behavior, register
from .model import Profile, reach, summary
from .playback import play_live, witness
from .presets import PRESETS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("reach", help="generate an explicitly uncalibrated synthetic reach")
    gen.add_argument("output", type=Path)
    gen.add_argument("--start", type=float, nargs=3, required=True)
    gen.add_argument("--target", type=float, nargs=3, required=True)
    gen.add_argument("--start-q", type=float, nargs=4, default=[0, 0, 0, 1])
    gen.add_argument("--target-q", type=float, nargs=4, default=[0, 0, 0, 1])
    gen.add_argument("--duration", type=float, help="seconds; default 1.0 or preset duration")
    gen.add_argument("--rate", type=int, default=90)
    gen.add_argument("--hand", choices=["left", "right"], default="right")
    gen.add_argument("--seed", type=int, default=0)
    profiles = gen.add_mutually_exclusive_group()
    profiles.add_argument("--profile", type=Path, help="JSON fields from model.Profile")
    profiles.add_argument("--preset", choices=sorted(PRESETS), help="illustrative, not fitted to people")
    imp = commands.add_parser("import-behavior", help="requires h5py; preserves source coordinates")
    imp.add_argument("input", type=Path)
    imp.add_argument("output", type=Path)
    imp.add_argument("--start-frame", type=int, default=0)
    imp.add_argument("--count", type=int, default=300)
    cat = commands.add_parser("catalog", help="index a raw HDF5 directory; requires h5py")
    cat.add_argument("input", type=Path)
    cat.add_argument("output", type=Path)
    cat.add_argument("--measure", action="store_true", help="scan timing/tracking arrays; potentially slow on HDD")
    reg = commands.add_parser("register", help="apply an explicit source-to-OpenXR calibration")
    reg.add_argument("input", type=Path)
    reg.add_argument("output", type=Path)
    reg.add_argument("--rotation", type=float, nargs=4, required=True, help="XYZW")
    reg.add_argument("--translation", type=float, nargs=3, required=True)
    reg.add_argument("--controller-rotation", type=float, nargs=4, default=[0, 0, 0, 1])
    stats = commands.add_parser("summary")
    stats.add_argument("input", type=Path)
    export = commands.add_parser("witness")
    export.add_argument("input", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--rate", type=int, default=90)
    live = commands.add_parser("live", help="actively play controller inputs into an opted-in viewer")
    live.add_argument("input", type=Path)
    live.add_argument("--socket", type=Path)
    live.add_argument("--state", type=Path)
    live.add_argument("--trace", type=Path, required=True, help="retain bridge command/observation JSONL")
    live.add_argument("--allow-transactions", action="store_true")
    live.add_argument("--max-lag", type=float, default=.15)
    args = parser.parse_args()
    if args.command == "reach":
        profile = Profile(**json.loads(args.profile.read_text())) if args.profile else Profile()
        duration = 1.0
        if args.preset:
            duration, profile = PRESETS[args.preset]
        result = reach(args.start, args.target, start_q=args.start_q, target_q=args.target_q,
            duration_s=args.duration if args.duration is not None else duration, rate_hz=args.rate, hand=args.hand, seed=args.seed, profile=profile)
        if args.preset:
            result["provenance"]["preset"] = args.preset
            result["provenance"]["calibration"] = "illustrative stress test, not a dataset fit or human category"
    elif args.command == "import-behavior":
        result = import_behavior(args.input, args.start_frame, args.count)
    elif args.command == "catalog":
        result = catalog(args.input, args.measure)
    else:
        trace = json.loads(args.input.read_text())
        if args.command == "summary":
            print(json.dumps(summary(trace), indent=2))
            return
        if args.command == "register":
            result = register(trace, args.rotation, args.translation, args.controller_rotation)
        elif args.command == "witness":
            args.output.write_text(witness(trace, args.rate))
            return
        else:
            from frontend.scrywrite.mcp_bridge import Bridge
            result = play_live(trace, Bridge(args.socket, args.trace, args.state),
                allow_transactions=args.allow_transactions, max_lag_s=args.max_lag)
            print(json.dumps(result, indent=2))
            return
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
