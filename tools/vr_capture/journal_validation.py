"""Bounded validation of saved native pose/marker receipts; no pixel decoding.

The authenticated viewer's saved counters alone do not prove it submitted two
rendered eyes. This checks the retained journal against the requested capture and
the full marker session. It does not associate pixels with final presents, verify
the runtime's clock conversion independently, or establish optical output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import zlib

MAX_FRAMES = 8192  # PoseJournal::maximumFrames
MAX_LINE_BYTES = 16384  # Fixed native schema is under this bound, including header.
MAX_FILE_BYTES = (MAX_FRAMES + 2) * MAX_LINE_BYTES
CLOCK_MAPPING = "XR_KHR_convert_timespec_time"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, minimum=0, maximum=(1 << 63)-1):
    require(type(value) is int and minimum <= value <= maximum, "Invalid " + name)
    return value


def relation(value, start, end):
    return "preroll" if value < start else "tail" if value >= end else "capture"


def marker_crc(pid, session_start, frame, eye):
    return zlib.crc32(struct.pack(">2sBBIQQ", b"NF", 2, eye, pid, session_start, frame))


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field: " + key)
        result[key] = value
    return result


def _parse(line):
    def invalid_constant(value):
        raise ValueError("Nonfinite JSON value: " + value)
    value = json.loads(line, object_pairs_hook=_object, parse_constant=invalid_constant)
    require(isinstance(value, dict), "Journal row must be an object")
    return value


def _marker_config(value, pid, session_start):
    require(isinstance(value, dict), "Missing marker configuration")
    expected = {"enabled": True, "protocol": "nadoc-frame-v2", "version": 2,
                "session_pid": pid, "session_start_ns": session_start,
                "coordinate_space": "application_eye_undistorted", "grid_cells": 24,
                "cell_pixels": 8, "payload_rect_cells": [4, 4, 16, 16], "packet_bytes": 32,
                "byte_order": "big-endian", "bit_order": "row-major MSB-first",
                "magic_hex": "4e46", "pad_hex": "a55ac33c"}
    for key, expected_value in expected.items():
        require(value.get(key) == expected_value and type(value.get(key)) is type(expected_value),
                "Marker configuration mismatch: " + key)


def _stereo_receipts(row, pid, session_start):
    require(row.get("submitted") is True and row.get("should_render") is True,
            "Application frame was not submitted/rendered")
    result = integer(row.get("xr_end_frame_result"), "xrEndFrame result", -(1 << 31), (1 << 31)-1)
    require(result >= 0 and row.get("xr_end_frame_succeeded") is True, "xrEndFrame did not succeed")
    eyes = row.get("eyes")
    require(isinstance(eyes, list) and len(eyes) == 2, "Journal must contain two eyes")
    require({e.get("eye") for e in eyes if isinstance(e, dict)} == {"left", "right"},
            "Journal must contain distinct left/right eyes")
    for eye in eyes:
        require(eye.get("rendered") is True, "Eye was not rendered")
        width = integer(eye.get("width"), "eye width", 192, (1 << 31)-1)
        height = integer(eye.get("height"), "eye height", 240, (1 << 31)-1)
        receipt = eye.get("frame_identity")
        require(isinstance(receipt, dict) and receipt.get("rendered") is True, "Missing rendered frame marker")
        frame = integer(receipt.get("frame"), "marker frame", 0, (1 << 64)-1)
        require(frame == row["frame"], "Marker frame differs from application frame")
        crc = integer(receipt.get("packet_crc32"), "marker CRC", 0, (1 << 32)-1)
        require(crc == marker_crc(pid, session_start, frame, 0 if eye["eye"] == "left" else 1),
                "Marker CRC does not match full session/frame/eye")
        expected_rect = [width//2-96, (height*40+50)//100-96, 192, 192]
        require(receipt.get("rectangle_xywh") == expected_rect, "Marker rectangle differs from native v2 layout")
        begin = integer(receipt.get("host_draw_start_ns"), "marker start", 1)
        end = integer(receipt.get("host_draw_end_ns"), "marker end", begin)
        require(row["host_frame_start_ns"] <= begin <= end <= row["host_frame_end_ns"],
                "Marker receipt falls outside its application frame")


def validate_saved_journal(context, native, *, request, viewer_pid, started, marker):
    """Return a verdict and bounded evidence; invalid proof never erases pixels."""
    result = {"valid": False, "pixel_decoding_verified": False,
              "final_present_association_verified": False, "optical_output_verified": False,
              "clock_conversion_independently_verified": False}
    try:
        require(all(isinstance(value, dict) for value in (context, native, started, marker)),
                "Journal validation requires object metadata")
        _validate(context, native, request, viewer_pid, started, marker, result)
        result["valid"] = True
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        result["error"] = str(error)
    return result


def _validate(context, native, request, viewer_pid, started, marker, result):
    request = integer(request, "request", 1, (1 << 64)-1)
    pid = integer(viewer_pid, "viewer PID", 1, (1 << 32)-1)
    session = context["session"]
    require(isinstance(session, str), "Invalid journal session")
    parts = session.split("-")
    require(len(parts) == 2 and all(p.isascii() and p.isdecimal() and not p.startswith("0") for p in parts),
            "Invalid canonical journal session")
    session_pid, session_start = map(int, parts)
    integer(session_start, "session start", 1, (1 << 64)-1)
    require(session_pid == pid, "Journal session PID mismatch")
    _marker_config(marker, pid, session_start)
    require(started.get("request") == request, "Capture request mismatch")
    start = integer(started.get("start_ns"), "capture start", 1)
    end = integer(started.get("end_ns"), "capture end", start+1)
    require(end-start <= 10_000_000_000, "Capture window exceeds native bound")
    require(native.get("phase") == "saved" and native.get("request") == request,
            "Native saved status/request mismatch")
    require(native.get("window_bound") is True and native.get("clock_mapping_available") is True,
            "Native saved clock/window unavailable")
    require(native.get("capture_start_monotonic_ns") == start and native.get("capture_end_monotonic_ns") == end,
            "Native saved capture window mismatch")
    require(native.get("overflow_frames") == 0 and native.get("mapping_failures") == 0,
            "Native journal overflow or clock mapping failure")
    expected_count = integer(native.get("frame_count"), "native frame count", 1, MAX_FRAMES)
    directory = Path(context["directory"])
    path = Path(native["path"])
    require(directory.is_absolute() and directory.resolve(strict=True) == directory,
            "Journal directory must be absolute without symlinks")
    require(path.is_absolute() and path.parent == directory,
            "Journal file is outside the configured directory")
    require(path.name == f"pose-journal-{pid}-{request}.jsonl", "Journal filename identity mismatch")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(info.st_uid == os.getuid() and not info.st_mode & 0o022, "Journal directory is not owner-controlled")
        fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and not before.st_mode & 0o022,
                "Journal must be an owned regular file")
        require(0 < before.st_size <= MAX_FILE_BYTES, "Journal file exceeds size bound")
        digest = hashlib.sha256()
        count = 0
        header = footer = previous = None
        counts = {"preroll": 0, "capture": 0, "tail": 0}
        valid_counts = dict(counts)
        invalid_outside = []
        offsets = []
        gaps = []
        for line_index in range(MAX_FRAMES+3):
            line = stream.readline(MAX_LINE_BYTES+1)
            if not line:
                break
            require(len(line) <= MAX_LINE_BYTES and line.endswith(b"\n"), "Journal line exceeds bound or is truncated")
            require(footer is None, "Journal contains data after completion")
            digest.update(line)
            row = _parse(line)
            if header is None:
                header = row
                require(row.get("event") == "pose_journal_start" and row.get("schema") == 1
                        and row.get("source") == "application_projection", "Invalid journal header")
                require(row.get("session") == session and row.get("pid") == pid and row.get("request") == request,
                        "Journal header identity mismatch")
                require(row.get("clock") == "CLOCK_MONOTONIC" and row.get("clock_mapping") == CLOCK_MAPPING,
                        "Journal clock mapping unavailable")
                require(row.get("capture_start_monotonic_ns") == start and row.get("capture_end_monotonic_ns") == end,
                        "Journal header capture window mismatch")
                require(row.get("tail_ns") == 100_000_000 and context.get("tail_ns", 100_000_000) == 100_000_000,
                        "Journal tail mismatch")
                capacity = integer(row.get("capacity_frames"), "journal capacity", 1, MAX_FRAMES)
                armed = integer(row.get("armed_monotonic_ns"), "journal arm", 1, start)
                require(end+row["tail_ns"] <= armed+30_000_000_000, "Journal exceeds native armed window")
                _marker_config(row.get("frame_identity"), pid, session_start)
                continue
            if row.get("event") == "pose_journal_complete":
                footer = row
                continue
            require(row.get("event") == "application_frame" and row.get("source") == "application_projection",
                    "Unexpected journal event")
            count += 1
            require(count <= capacity, "Journal exceeds native frame capacity")
            frame = integer(row.get("frame"), "application frame", 0, (1 << 64)-1)
            predicted = integer(row.get("predicted_display_time_ns"), "predicted OpenXR time", -(1 << 63))
            mapped = integer(row.get("predicted_display_monotonic_ns"), "mapped prediction", 1)
            integer(row.get("predicted_display_period_ns"), "predicted period", 1)
            host_start = integer(row.get("host_frame_start_ns"), "host frame start", armed)
            host_end = integer(row.get("host_frame_end_ns"), "host frame end", host_start)
            require(row.get("clock_mapping") == CLOCK_MAPPING, "Frame clock mapping unavailable")
            group = relation(mapped, start, end)
            require(row.get("predicted_window_relation") == group and row.get("host_window_relation") == relation(host_end, start, end),
                    "Journal window relation disagrees with mapped/host time")
            counts[group] += 1
            offsets.append(mapped-predicted)
            if previous is not None:
                require(frame > previous[0] and predicted > previous[1] and mapped > previous[2]
                        and host_start >= previous[3], "Journal frame/time order is not monotonic")
                gaps.append(mapped-previous[2])
            previous = (frame, predicted, mapped, host_end)
            try:
                _stereo_receipts(row, pid, session_start)
            except (ValueError, TypeError, KeyError) as error:
                require(group != "capture" and row["host_window_relation"] != "capture", f"Capture frame {frame}: {error}")
                if len(invalid_outside) < 16:
                    invalid_outside.append({"frame": frame, "relation": group, "error": str(error)})
            else:
                valid_counts[group] += 1
        else:
            raise ValueError("Journal exceeds native row capacity")
        after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "Journal changed during validation")
        require(footer is not None and footer.get("complete") is True, "Journal completion footer is missing or incomplete")
        require(footer.get("frames") == count == expected_count, "Journal frame count differs from saved status/footer")
        require(footer.get("overflow_frames") == 0 and footer.get("mapping_failures") == 0,
                "Journal completion reports overflow or mapping failure")
        require(all(valid_counts.values()), "Valid stereo marker receipts do not bracket the capture window")
        result.update(path=str(path), sha256=digest.hexdigest(), bytes=before.st_size,
                      request=request, session=session, frame_count=count, frame_relations=counts,
                      valid_stereo_marker_relations=valid_counts, invalid_outside_capture=invalid_outside,
                      mapped_offset_spread_ns=max(offsets)-min(offsets), maximum_mapped_step_ns=max(gaps, default=0),
                      receipt_coverage_verified=True, clock_mapping_metadata_consistent=True)
