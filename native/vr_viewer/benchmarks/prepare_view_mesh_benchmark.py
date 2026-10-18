"""Prepare bounded offline benchmark input from an existing same-frame capture."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    evidence_bytes = args.evidence.read_bytes()
    evidence = json.loads(evidence_bytes)
    state = evidence["state"]
    presentation = state["presentation"]
    eyes = evidence["eyes"]
    if [eye["eye"] for eye in eyes] != ["left", "right"]:
        raise ValueError("exactly two ordered application eyes are required")
    if any((eye["width"], eye["height"]) != (eyes[0]["width"], eyes[0]["height"]) for eye in eyes):
        raise ValueError("benchmark requires equal eye sizes")
    if evidence["source"] != "application_swapchain" or not evidence["xr_end_frame_succeeded"]:
        raise ValueError("successful application projection capture required")
    rows = [
        [eyes[0]["width"], eyes[0]["height"]],
        presentation["source_center_nm"] + [presentation["normalization_model_per_nm"]]
        + presentation["normalized_offset_model"]
        + [evidence["depth_near_m"], evidence["depth_far_m"]],
        *presentation["model_to_tracking_rows"],
        *[eye["position"] + eye["orientation_xyzw"] + eye["fov_left_right_up_down"] for eye in eyes],
    ]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for row in rows for value in row):
        raise ValueError("finite numeric state required")
    text = "NADOC_VIEW_MESH_BENCH_1\n" + "\n".join(" ".join(format(value, ".17g") for value in row) for row in rows) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(text)
    metadata = {
        "evidence": str(args.evidence.resolve()),
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source": evidence["source"], "session": state["session"], "frame": state["frame"],
        "same_capture_presentation": True,
        "pose_precision_limit": "uses the precision retained in the original capture JSON",
    }
    with args.output.with_suffix(args.output.suffix + ".json").open("x") as stream:
        json.dump(metadata, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
