"""Read bounded native pose evidence and project unchanged application geometry.

No runtime calls, pixel writes, final-present matching, or optical claims. Every
native application row is retained as projected or explicitly unavailable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .projection import APPLICATION_EYE, ApplicationFrame, FrameIdentity, project_source_points
from .workflow import shape_identity

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 8192
MAX_LINE_BYTES = 64 * 1024


def _constant(value):
    raise ValueError("Nonfinite JSON number: " + value)


def _integer(value, name, minimum=0, maximum=(1 << 63)-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid " + name)
    return value


def _journal(path):
    records, total, sha = [], 0, hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            line = stream.readline(MAX_LINE_BYTES+1)
            if not line:
                break
            total += len(line)
            if total > MAX_BYTES or len(line) > MAX_LINE_BYTES or len(records) >= MAX_ROWS+2:
                raise ValueError("Pose journal exceeds bounded input size")
            if not line.endswith(b"\n"):
                raise ValueError("Pose journal has an incomplete final line")
            sha.update(line)
            record = json.loads(line, parse_constant=_constant)
            if not isinstance(record, dict):
                raise ValueError("Pose journal records must be objects")
            records.append(record)
    if len(records) < 3:
        raise ValueError("Pose journal lacks header, application rows or completion")
    header, rows, trailer = records[0], records[1:-1], records[-1]
    if (header.get("event") != "pose_journal_start" or type(header.get("schema")) is not int or header.get("schema") != 1
            or header.get("source") != "application_projection"
            or header.get("space") != "OpenXR_LOCAL" or header.get("units") != "meters"
            or header.get("clock") != "CLOCK_MONOTONIC"):
        raise ValueError("Unsupported pose journal header or coordinate units")
    if header.get("clock_mapping") not in ("XR_KHR_convert_timespec_time", "unavailable"):
        raise ValueError("Unknown journal clock mapping capability")
    FrameIdentity(header["session"], 0, 0)
    _integer(header["request"], "journal request", 1)
    start = _integer(header["capture_start_monotonic_ns"], "capture start")
    end = _integer(header["capture_end_monotonic_ns"], "capture end")
    if end <= start:
        raise ValueError("Pose journal capture interval is empty")
    capacity = _integer(header["capacity_frames"], "journal capacity", 1, MAX_ROWS)
    if len(rows) > capacity or any(row.get("event") != "application_frame" for row in rows):
        raise ValueError("Pose journal contains excess or non-application rows")
    if (trailer.get("event") != "pose_journal_complete" or trailer.get("complete") is not True
            or _integer(trailer.get("overflow_frames"), "overflow frames") != 0
            or _integer(trailer.get("frames"), "completion frame count") != len(rows)):
        raise ValueError("Pose journal completion is missing, partial or inconsistent")
    failures = _integer(trailer.get("mapping_failures"), "mapping failures", 0, len(rows))
    unavailable = sum(row.get("clock_mapping") == "unavailable" for row in rows)
    if header["clock_mapping"] == "unavailable":
        if unavailable != len(rows) or failures:
            raise ValueError("Journal clock capability contradicts rows or failure count")
    elif failures != unavailable:
        raise ValueError("Journal clock mapping failure count is inconsistent")
    prior = -1
    for row in rows:
        current = _integer(row.get("frame"), "application frame", maximum=(1 << 64)-1)
        if current <= prior or row.get("source") != "application_projection":
            raise ValueError("Pose journal application frames are duplicated, reordered or wrong-source")
        prior = current
    return header, rows, trailer, sha.hexdigest()


def _anchors(path, eye):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Anchor results exceed bounded input size")
    results = json.loads(raw, parse_constant=_constant)
    if results.get("schema") != 1 or results.get("coordinate_space") != APPLICATION_EYE:
        raise ValueError("Anchors must come from application-eye tracking results")
    anchors = results.get("anchors", {})
    templates = results.get("templates", [])
    if not isinstance(anchors, dict) or not 1 <= len(anchors) <= 64 or not isinstance(templates, list) or len(templates) > 64:
        raise ValueError("Require 1..64 bounded depth anchors and templates")
    owners = {}
    for template in templates:
        name, owner = template.get("landmark_id"), template.get("eye")
        if not isinstance(name, str) or not name or name in owners or owner not in ("left", "right"):
            raise ValueError("Template landmark/eye ownership is invalid or duplicated")
        owners[name] = owner
    if any(name not in owners for name in anchors):
        raise ValueError("Depth anchor lacks template eye ownership")
    selected = {}
    for name, anchor in anchors.items():
        if owners[name] != eye:
            continue
        point = np.asarray(anchor["source_nm"], dtype=float)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError("Anchor source position must be finite source nanometers")
        identity = anchor["shape_identity"]
        if shape_identity({"state": identity}) != identity:
            raise ValueError("Anchor geometry identity is incomplete or noncanonical")
        reference = anchor["reference_frame"]
        FrameIdentity(**reference)
        if reference["session"] != identity["session"]:
            raise ValueError("Anchor reference session and shape session disagree")
        selected[name] = anchor
    if not selected:
        raise ValueError("No depth anchors belong to requested eye")
    return selected, hashlib.sha256(raw).hexdigest()


def _mapped_time(row):
    mapping = row.get("clock_mapping")
    value = row.get("predicted_display_monotonic_ns")
    if mapping == "unavailable":
        if value is not None:
            raise ValueError("Unavailable clock mapping has a fabricated mapped time")
        return None
    if mapping != "XR_KHR_convert_timespec_time":
        raise ValueError("Unknown application clock mapping")
    return _integer(value, "mapped monotonic display time")


def project_journal(journal_path, anchors_result_path, eye):
    """Return expected original-eye pixels for each coherent recorded app frame.

    Unsubmitted, unrendered and changed-geometry rows remain explicit unavailable
    entries. Malformed or partial input evidence raises ValueError. Frame times
    do not imply an application-frame to final-present association.
    """
    try:
        return _project_journal(journal_path, anchors_result_path, eye)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed pose journal or anchor evidence: " + str(error)) from error


def _project_journal(journal_path, anchors_result_path, eye):
    if eye not in ("left", "right"):
        raise ValueError("Choose an explicit left or right eye")
    header, rows, trailer, journal_sha = _journal(journal_path)
    anchors, anchors_sha = _anchors(anchors_result_path, eye)
    output = {"schema": 1, "coordinate_space": APPLICATION_EYE, "eye": eye,
              "session": header["session"], "request": header["request"],
              "journal_file": str(Path(journal_path).resolve()), "journal_sha256": journal_sha,
              "anchors_result_file": str(Path(anchors_result_path).resolve()), "anchors_result_sha256": anchors_sha,
              "journal_complete": True, "journal_frames": len(rows),
              "mapping_failures": trailer["mapping_failures"], "anchors": anchors,
              "final_present_association_verified": False, "optical_output_verified": False,
              "capture_start_monotonic_ns": header["capture_start_monotonic_ns"],
              "capture_end_monotonic_ns": header["capture_end_monotonic_ns"], "frames": []}
    for row in rows:
        identity = FrameIdentity(header["session"], row["frame"], row["predicted_display_time_ns"])
        mapped = _mapped_time(row)
        result = {"frame": identity.frame, "predicted_display_time_ns": identity.predicted_display_time_ns,
                  "predicted_display_monotonic_ns": mapped, "clock_mapping": row["clock_mapping"],
                  "host_frame_start_ns": _integer(row["host_frame_start_ns"], "host frame start"),
                  "host_frame_end_ns": _integer(row["host_frame_end_ns"], "host frame end"),
                  "status": "unavailable", "reason": None, "expected": {}}
        if result["host_frame_end_ns"] < result["host_frame_start_ns"]:
            raise ValueError("Application host interval is inverted")
        if row.get("submitted") is not True or row.get("xr_end_frame_succeeded") is not True:
            result["reason"] = "application_frame_not_successfully_submitted"
        else:
            eyes = [item for item in row.get("eyes", []) if item.get("eye") == eye]
            if len(eyes) != 1:
                raise ValueError("Journal has missing or duplicate eye ownership")
            if eyes[0].get("rendered") is not True:
                result["reason"] = "eye_not_rendered"
            else:
                context = ApplicationFrame.from_journal(header, row, eye)
                shape = shape_identity({"state": {**row, "session": header["session"]}})
                result.update(status="projected", width=context.camera.width, height=context.camera.height)
                for name, anchor in anchors.items():
                    if anchor["shape_identity"] != shape:
                        result["expected"][name] = {"status": "unavailable", "reason": "geometry_representation_or_session_changed_reanchor_required"}
                        continue
                    projected = project_source_points([anchor["source_nm"]], context)
                    front = bool(projected.in_front[0])
                    result["expected"][name] = {"status": "projected" if front else "behind_eye",
                        "position_xy": projected.image.xy[0].tolist() if front else None,
                        "forward_depth_m": float(projected.forward_depth_m[0]),
                        "in_front": front, "inside_image": bool(projected.inside_image[0])}
                if not any(value["status"] == "projected" for value in result["expected"].values()):
                    result.update(status="unavailable", reason="no_front_facing_unchanged_anchor_projection")
        output["frames"].append(result)
    return output
