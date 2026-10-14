"""Compare measured molecular motion with exact submitted-image identities."""
from collections import defaultdict
import math
from pathlib import Path

import numpy as np

from .workflow import digest, read_json


def _key(source):
    p = source.get("provenance", {})
    key = tuple(p.get(k) for k in ("request", "index", "present"))
    if any(type(x) is not int or x < 0 for x in key):
        raise ValueError("Every source requires exact request/index/present provenance")
    return key


def _positions(frame, eye):
    positions = {}
    for item in frame.get("groups", {}).get(eye, {}).get("matches", []):
        name = item.get("landmark_id")
        if not isinstance(name, str) or name in positions or item.get("eye") != eye:
            raise ValueError("Invalid or repeated per-eye landmark identity")
        xy = item.get("position_xy") if item.get("status") == "tracked" else None
        if xy is not None and (not isinstance(xy, list) or len(xy) != 2
                               or any(type(v) not in (int, float) or not math.isfinite(v) for v in xy)):
            raise ValueError("Invalid accepted landmark position")
        positions[name] = xy
    return positions


def _validate_joined_eyes(frame, session):
    eyes = frame.get("eyes")
    if not isinstance(eyes, dict) or not eyes or set(eyes) - {"left", "right"}:
        raise ValueError("Require named eye identity records")
    for eye, decoded in eyes.items():
        if not isinstance(decoded, dict):
            raise ValueError("Invalid eye identity record")
        if decoded.get("status") != "joined":
            continue
        identity = decoded.get("identity", {})
        if (not isinstance(identity, dict) or identity.get("session") != session
                or identity.get("eye") != eye
                or type(identity.get("frame")) is not int
                or not 0 <= identity["frame"] < 1 << 64):
            raise ValueError("Joined identity has inconsistent session, eye or frame")


def compare_temporal_motion(tracking_path, identities_path):
    """Join by captured-present provenance and pixel hash, never file name/time.

    Unknown IDs or rejected positions break comparisons. This reports image
    displacement conditioned on image reuse, not optical double-image spacing.
    """
    tracking_path, identities_path = Path(tracking_path), Path(identities_path)
    tracked, identities = read_json(tracking_path), read_json(identities_path)
    if (tracked.get("schema") != 1 or identities.get("schema") != 1
            or tracked.get("coordinate_space") != "final_swapchain_distorted"
            or identities.get("coordinate_space") != tracked["coordinate_space"]):
        raise ValueError("Require matching final-output tracking and frame-identity reports")
    if not 1 <= len(identities.get("frames", [])) <= 2000:
        raise ValueError("Require 1..2000 identity frames")
    if not isinstance(identities.get("session"), str) or not identities["session"]:
        raise ValueError("Require a session identity")
    by_key = {}
    for frame in tracked.get("frames", []):
        key = _key(frame["source"])
        if key in by_key:
            raise ValueError("Duplicate tracked captured-present identity")
        by_key[key] = frame
    report = {"schema": 1, "tracking_sha256": digest(tracking_path),
              "identities_sha256": digest(identities_path), "request": identities["request"],
              "session": identities["session"], "coordinate_space": tracked["coordinate_space"],
              "transitions": [], "summary": {},
              "limits": ["Displacements are measured molecular pixels, not marker movement or optical double-image separation.",
                         "Final-present host intervals are not physical display latency or scanout timestamps.",
                         "Unknown identities, rejected landmarks and missing/nonadjacent captures break comparisons.",
                         "A reused image can still move through compositor reprojection; a new image can legitimately remain stationary.",
                         "Original landmark thresholds and quantization remain unchanged; no expected-position lens calibration is inferred."]}
    previous = None
    accumulated = defaultdict(list)
    for identity in identities["frames"]:
        _validate_joined_eyes(identity, identities["session"])
        key = _key(identity["source"])
        frame = by_key.get(key)
        if key[0] != identities["request"]:
            raise ValueError("Mixed capture requests")
        if frame is not None:
            a, b = frame["source"], identity["source"]
            for field in ("rgb_sha256", "width", "height", "coordinate_space", "eye_rectangles"):
                if not a.get(field) or a[field] != b.get(field):
                    raise ValueError("Tracking and identity source pixels/coordinates differ: " + field)
        if previous is not None:
            old_id, old_frame, old_key = previous
            if key[1] <= old_key[1] or identity["host_present_enter_ns"] <= old_id["host_present_enter_ns"]:
                raise ValueError("Identity frames must be strictly ordered")
            contiguous = key[1] == old_key[1]+1 and key[2] == old_key[2]+1
            for eye, decoded in identity["eyes"].items():
                old_decoded = old_id["eyes"].get(eye, {})
                kind = "unavailable"
                if contiguous and decoded["status"] == old_decoded.get("status") == "joined":
                    old_app, new_app = old_decoded["identity"]["frame"], decoded["identity"]["frame"]
                    kind = "reused" if old_app == new_app else "advanced" if new_app > old_app else "regressed"
                row = {"eye": eye, "previous_capture_index": old_key[1], "capture_index": key[1],
                       "image_transition": kind, "contiguous_captured_presents": contiguous,
                       "host_present_interval_ns": identity["host_present_enter_ns"]-old_id["host_present_enter_ns"],
                       "landmarks": []}
                if frame is not None and old_frame is not None and kind != "unavailable":
                    old_positions, positions = _positions(old_frame, eye), _positions(frame, eye)
                    for name in sorted(set(old_positions) & set(positions)):
                        a, b = old_positions[name], positions[name]
                        if a is None or b is None:
                            continue
                        delta = [b[i]-a[i] for i in (0, 1)]
                        distance = math.hypot(*delta)
                        row["landmarks"].append({"landmark_id": name, "delta_xy_px": delta, "distance_px": distance})
                        accumulated[(eye, name, kind)].append(distance)
                report["transitions"].append(row)
        previous = identity, frame, key
    for (eye, name, kind), values in accumulated.items():
        report["summary"].setdefault(eye, {}).setdefault(name, {})[kind] = {
            "count": len(values), "median_distance_px": float(np.median(values)),
            "p95_distance_px": float(np.percentile(values, 95)), "max_distance_px": max(values)}
    return report
