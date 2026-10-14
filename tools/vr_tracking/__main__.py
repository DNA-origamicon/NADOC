"""Run `python -m tools.vr_tracking --help` for the reusable tracking workflow."""
import argparse
import json
from pathlib import Path

from .workflow import export_final, run_tracking


def main():
    parser = argparse.ArgumentParser(description="Measure actual origami landmarks in original VR pixels. See docs/vr_origami_tracking.md.")
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export", help="Export exact final frames and an editable tracking manifest")
    export.add_argument("--directory", type=Path, required=True)
    export.add_argument("--request", type=int, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--eyes", type=json.loads, required=True, help='Explicit full-source rectangles, e.g. {"left":[0,0,1080,1200],"right":[1080,0,2160,1200]}')
    export.add_argument("--indices", help="Comma-separated frame indices; omitted exports all")
    track = actions.add_parser("track", help="Track pinned reference patches; write JSON and an original-frame review")
    track.add_argument("manifest", type=Path)
    track.add_argument("--output", type=Path, required=True)
    project = actions.add_parser("project-journal", help="Project source anchors through recorded application poses; no final-pixel association")
    project.add_argument("--journal", type=Path, required=True)
    project.add_argument("--anchors", type=Path, required=True, help="Application tracking results.json containing depth anchors")
    project.add_argument("--eye", choices=("left", "right"), required=True)
    project.add_argument("--output", type=Path, required=True)
    identify = actions.add_parser("identify-frames", help="Decode submitted image IDs and join exact journal rows; no timestamp guessing")
    identify.add_argument("manifest", type=Path, help="Final export manifest with explicit marker_search_rectangles")
    identify.add_argument("--journal", type=Path, required=True)
    identify.add_argument("--request", type=int, required=True)
    identify.add_argument("--output", type=Path, required=True)
    temporal = actions.add_parser("compare-temporal", help="Measure molecular image steps separately for reused and new submitted images")
    temporal.add_argument("--tracking", type=Path, required=True)
    temporal.add_argument("--identities", type=Path, required=True)
    temporal.add_argument("--output", type=Path, required=True)
    gpu = actions.add_parser("summarize-gpu-passes", help="Summarize opt-in shadow/eye GPU timeline intervals with trace coverage")
    gpu.add_argument("log", type=Path)
    gpu.add_argument("--start-ns", type=int)
    gpu.add_argument("--end-ns", type=int)
    gpu.add_argument("--boundary-exclusion-ns", type=int, default=0)
    gpu.add_argument("--output", type=Path, required=True)
    interactions = actions.add_parser("summarize-interactions", help="Offline host/menu/haptic timing and optional exact frame-ID joins; no causality or optical claims")
    interactions.add_argument("--journal", type=Path, required=True)
    interactions.add_argument("--identities", type=Path, help="Pinned identify-frames JSON for this exact journal/session/request")
    interactions.add_argument("--output", type=Path, required=True, help="New directory for summary.json and self-contained index.html")
    args = parser.parse_args()
    if args.action == "export":
        result = export_final(args.directory, args.request, args.output, args.eyes,
                              None if args.indices is None else [int(i) for i in args.indices.split(",")])
        print(json.dumps({"output": str(args.output), "frames": len(result["frames"]), "next": "Choose reference landmarks and search rectangles in manifest.json"}))
    elif args.action == "track":
        result = run_tracking(args.manifest, args.output)
        print(json.dumps({"output": str(args.output), "frames": len(result["frames"]), "review": str(args.output / "index.html")}))
    elif args.action == "identify-frames":
        from .frame_identity import join_frame_identities
        result = join_frame_identities(args.manifest, args.journal, args.request)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"output": str(args.output), "association": "encoded_session_eye_frame_crc"}))
    elif args.action == "compare-temporal":
        from .temporal import compare_temporal_motion
        result = compare_temporal_motion(args.tracking, args.identities)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"output": str(args.output), "transitions": len(result["transitions"])}))
    elif args.action == "summarize-gpu-passes":
        from .gpu_timing import summarize_gpu_passes
        result = summarize_gpu_passes(args.log, start_ns=args.start_ns, end_ns=args.end_ns,
                                      boundary_exclusion_ns=args.boundary_exclusion_ns)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"output": str(args.output), "coverage": result["coverage"],
                          "passes_ms": result["passes_ms"]}))
    elif args.action == "summarize-interactions":
        from .interaction_timing import summarize_interactions, write_interaction_report
        result = summarize_interactions(args.journal, args.identities)
        write_interaction_report(result, args.output)
        print(json.dumps({"output": str(args.output), "journal_frames": result["journal_frames"],
                          "review": str(args.output / "index.html"), "causality_verified": False}))
    else:
        from .journal_projection import project_journal
        result = project_journal(args.journal, args.anchors, args.eye)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"output": str(args.output), "coordinate_space": "application_eye_undistorted"}))


if __name__ == "__main__":
    main()
