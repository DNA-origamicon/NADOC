"""Independent wire-packet and saved-journal negatives without a VR runtime."""
import copy
import json
import os
from pathlib import Path
import struct
import zlib

import pytest

from tools.vr_capture import journal_validation as validation


def write_journal(directory, *, pid=123, request=99, start=1_000_000_000, end=1_050_000_000):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = {"enabled": True, "protocol": "nadoc-frame-v2", "version": 2, "session_pid": pid,
              "session_start_ns": 10, "coordinate_space": "application_eye_undistorted", "grid_cells": 24,
              "cell_pixels": 8, "payload_rect_cells": [4, 4, 16, 16], "packet_bytes": 32,
              "byte_order": "big-endian", "bit_order": "row-major MSB-first", "magic_hex": "4e46", "pad_hex": "a55ac33c"}
    context = {"enabled": True, "directory": str(directory), "session": f"{pid}-10", "tail_ns": 100_000_000}
    header = {"event": "pose_journal_start", "schema": 1, "source": "application_projection",
              "session": context["session"], "pid": pid, "request": request, "clock": "CLOCK_MONOTONIC",
              "clock_mapping": "XR_KHR_convert_timespec_time", "capture_start_monotonic_ns": start,
              "capture_end_monotonic_ns": end, "tail_ns": 100_000_000, "capacity_frames": 8192,
              "armed_monotonic_ns": start-100_000_000, "frame_identity": marker}
    frames = []
    for frame, mapped in enumerate((start-20_000_000, start+(end-start)//3, start+2*(end-start)//3, end+20_000_000)):
        group = "preroll" if mapped < start else "tail" if mapped >= end else "capture"
        host_end = mapped-1_000_000
        row = {"event": "application_frame", "source": "application_projection", "frame": frame,
               "predicted_display_time_ns": mapped-2_000_000_000, "predicted_display_monotonic_ns": mapped,
               "predicted_display_period_ns": 11_111_111, "clock_mapping": "XR_KHR_convert_timespec_time",
               "predicted_window_relation": group, "host_window_relation": group,
               "host_frame_start_ns": mapped-10_000_000, "host_frame_end_ns": host_end,
               "submitted": True, "should_render": True, "xr_end_frame_result": 0, "xr_end_frame_succeeded": True, "eyes": []}
        for eye, name in enumerate(("left", "right")):
            packet = b"NF" + bytes((2, eye)) + struct.pack(">IQQ", pid, 10, frame)
            row["eyes"].append({"eye": name, "width": 512, "height": 512, "rendered": True,
                                "frame_identity": {"rendered": True, "frame": frame, "packet_crc32": zlib.crc32(packet),
                                 "rectangle_xywh": [160, 109, 192, 192], "host_draw_start_ns": mapped-5_000_000,
                                 "host_draw_end_ns": mapped-4_000_000}})
        frames.append(row)
    footer = {"event": "pose_journal_complete", "complete": True, "frames": len(frames), "overflow_frames": 0, "mapping_failures": 0}
    rows = [header, *frames, footer]
    path = directory/f"pose-journal-{pid}-{request}.jsonl"
    path.write_text("".join(json.dumps(row)+"\n" for row in rows))
    path.chmod(0o600)
    native = {"phase": "saved", "request": request, "window_bound": True, "clock_mapping_available": True,
              "capture_start_monotonic_ns": start, "capture_end_monotonic_ns": end,
              "frame_count": len(frames), "overflow_frames": 0, "mapping_failures": 0, "path": str(path)}
    args = {"request": request, "viewer_pid": pid,
            "started": {"request": request, "start_ns": start, "end_ns": end}, "marker": marker}
    return context, native, args, rows


def test_valid_stereo_receipts_cover_both_boundaries_without_pixel_claim(tmp_path):
    context, native, args, _ = write_journal(tmp_path)
    result = validation.validate_saved_journal(context, native, **args)
    assert result["valid"], result
    assert result["valid_stereo_marker_relations"] == {"preroll": 1, "capture": 2, "tail": 1}
    assert result["frame_count"] == 4 and len(result["sha256"]) == 64
    assert not result["pixel_decoding_verified"] and not result["final_present_association_verified"]
    assert not result["clock_conversion_independently_verified"]


def test_crc_matches_independent_native_protocol_golden():
    assert validation.marker_crc(0x12345678, 0x0123456789abcdef, 0xfedcba9876543210, 1) == 0x9fc2de62


@pytest.mark.parametrize("change,error", [
    (lambda r: r[2].update(submitted=False), "not submitted"),
    (lambda r: r[2].update(xr_end_frame_result=-1), "did not succeed"),
    (lambda r: r[2]["eyes"][0].update(rendered=False), "Eye was not rendered"),
    (lambda r: r[2]["eyes"][0].pop("frame_identity"), "Missing rendered"),
    (lambda r: r[2]["eyes"][0]["frame_identity"].update(rendered=False), "Missing rendered"),
    (lambda r: r[2]["eyes"][0]["frame_identity"].update(frame=99), "differs from application"),
    (lambda r: r[2]["eyes"][0]["frame_identity"].update(packet_crc32=0), "CRC"),
    (lambda r: r[2]["eyes"][0]["frame_identity"].update(host_draw_end_ns=r[2]["host_frame_end_ns"]+1), "outside its application"),
    (lambda r: r[2]["eyes"][1].update(eye="left"), "distinct left/right"),
    (lambda r: r[0].update(request=5), "header identity"),
    (lambda r: r[0].update(pid=6), "header identity"),
    (lambda r: r[0].update(session="123-11"), "header identity"),
    (lambda r: r[0].update(capture_end_monotonic_ns=7), "header capture window"),
    (lambda r: r[0]["frame_identity"].update(session_start_ns=11), "Marker configuration"),
    (lambda r: r[2].update(predicted_display_monotonic_ns=None), "mapped prediction"),
    (lambda r: r[2].update(clock_mapping="unavailable"), "clock mapping unavailable"),
    (lambda r: r[2].update(predicted_window_relation="tail"), "relation disagrees"),
    (lambda r: r[2].update(predicted_display_time_ns=r[1]["predicted_display_time_ns"]), "not monotonic"),
    (lambda r: r[-1].update(complete=False), "footer"),
    (lambda r: r[-1].update(frames=3), "frame count"),
    (lambda r: r[-1].update(mapping_failures=1), "mapping failure"),
    (lambda r: r.pop(), "footer"),
    (lambda r: r.append(copy.deepcopy(r[1])), "after completion"),
    (lambda r: r[1]["eyes"][0].update(rendered=False), "bracket"),
    (lambda r: r[-2]["eyes"][0].update(rendered=False), "bracket"),
])
def test_invalid_retained_evidence_never_validates(tmp_path, change, error):
    context, native, args, rows = write_journal(tmp_path)
    change(rows)
    Path(native["path"]).write_text("".join(json.dumps(row)+"\n" for row in rows))
    result = validation.validate_saved_journal(context, native, **args)
    assert not result["valid"]
    assert error in result["error"]


@pytest.mark.parametrize("kind", ["absent", "symlink", "fifo", "outside", "writable", "oversized_line", "truncated", "duplicate_json_key"])
def test_file_boundaries_and_ownership(tmp_path, kind):
    context, native, args, _ = write_journal(tmp_path/"journals")
    path = Path(native["path"])
    if kind in ("absent", "symlink", "fifo"):
        content = path.read_bytes()
        path.unlink()
        if kind == "symlink":
            target = path.with_suffix(".target")
            target.write_bytes(content)
            path.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(path)
    elif kind == "outside":
        native["path"] = str(tmp_path/path.name)
    elif kind == "writable":
        path.chmod(0o666)
    elif kind == "oversized_line":
        path.write_bytes(b" "*(validation.MAX_LINE_BYTES+1)+b"\n")
    elif kind == "truncated":
        path.write_bytes(path.read_bytes()[:-1])
    else:
        path.write_bytes(b'{"event":"pose_journal_start","event":"other"}\n')
    assert not validation.validate_saved_journal(context, native, **args)["valid"]


def test_context_identity_and_saved_counts_are_not_trusted(tmp_path):
    context, native, args, _ = write_journal(tmp_path)
    for changed in ({"request": 98}, {"frame_count": 3}, {"phase": "writing"}, {"mapping_failures": 1}, {"capture_start_monotonic_ns": 0}):
        assert not validation.validate_saved_journal(context, {**native, **changed}, **args)["valid"]
    assert not validation.validate_saved_journal({**context, "session": "0123-10"}, native, **args)["valid"]
