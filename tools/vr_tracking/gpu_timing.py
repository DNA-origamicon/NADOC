"""Strict, provenance-preserving summaries of opt-in GPU timestamp pass traces.

These durations measure GPU timeline intervals, including queue idle and CPU
submission gaps. They are not GPU busy time and are not display timestamps.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


_BASE_INTS = {
    "frame", "host_begin_monotonic_ns", "host_collected_monotonic_ns", "valid",
    "view_tools_version", "view_tools_flags", "menu_open", "shadow_calls",
    "motion_detail_reduced", "left_calls", "right_calls", "boundaries",
    "first_eye", "second_eye",
}
_DURATIONS = {"shadow_ns", "left_ns", "right_ns", "total_ns"}
_UNSIGNED = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_SIGNED = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_DROP = re.compile(r"VR_TRACE_DROPPED epoch_ms=([0-9]+(?:\.[0-9]+)?) count=([1-9][0-9]*)\Z")
_STATUS = re.compile(r"VR_GPU_PASS_STATUS phase=(initialized|shutdown) status=(.*)\Z")


def _integer(value, signed=False):
    if not (_SIGNED if signed else _UNSIGNED).fullmatch(value):
        raise ValueError("noncanonical integer")
    result = int(value)
    if result > (1 << 64)-1 or result < -1:
        raise ValueError("integer out of bounds")
    return result


def _parse_sample(line):
    if not line.startswith("VR_GPU_PASS "):
        raise ValueError("interleaved prefix")
    fields = {}
    for token in line[len("VR_GPU_PASS "):].split(" "):
        if token.count("=") != 1:
            raise ValueError("malformed or interleaved field")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise ValueError("empty or duplicate field")
        fields[key] = value
    if not _BASE_INTS | {"reason", "shadow_scope"} <= fields.keys():
        raise ValueError("missing fields")
    for key in _BASE_INTS:
        if key == "shadow_calls" and fields[key] == "unknown" and fields["valid"] in ("0", 0):
            fields[key] = None
            continue
        fields[key] = _integer(fields[key], key in {"first_eye", "second_eye"})
    count = fields["boundaries"]
    if count > 4:
        raise ValueError("too many timestamp boundaries")
    expected = _BASE_INTS | {"reason", "shadow_scope"} | {f"timestamp{i}_ns" for i in range(count)}
    if fields["valid"] == 1:
        expected |= _DURATIONS
    if fields.keys() != expected:
        raise ValueError("unexpected or missing fields; possible interleaved text")
    for key in expected - _BASE_INTS - {"reason", "shadow_scope"}:
        fields[key] = _integer(fields[key])
    if any(fields[k] not in (0, 1) for k in ("valid", "menu_open", "motion_detail_reduced")):
        raise ValueError("invalid boolean")
    if fields["host_collected_monotonic_ns"] < fields["host_begin_monotonic_ns"]:
        raise ValueError("collection precedes submission boundary")
    if fields["shadow_scope"] not in {"unknown", "canonical", "exported_inspection", "skipped"}:
        raise ValueError("unknown shadow scope")
    if fields["valid"]:
        if count != 4 or {fields["first_eye"], fields["second_eye"]} != {0, 1}:
            raise ValueError("invalid eye boundary order")
        if fields["left_calls"] != 1 or fields["right_calls"] != 1 or fields["reason"] != "observed":
            raise ValueError("invalid successful receipt")
        stamps = [fields[f"timestamp{i}_ns"] for i in range(4)]
        if stamps != sorted(stamps):
            raise ValueError("nonmonotonic GPU timestamps")
        expected_durations = {"shadow_ns": stamps[1]-stamps[0], "total_ns": stamps[3]-stamps[0]}
        first = "left_ns" if fields["first_eye"] == 0 else "right_ns"
        second = "right_ns" if first == "left_ns" else "left_ns"
        expected_durations.update({first: stamps[2]-stamps[1], second: stamps[3]-stamps[2]})
        if any(fields[k] != v for k, v in expected_durations.items()):
            raise ValueError("duration/timestamp mismatch")
    return fields


def _statistics(values):
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    offset = (len(ordered)-1)*0.95
    low = math.floor(offset)
    high = math.ceil(offset)
    return {"count": len(values), "median": statistics.median(values),
            "p95": ordered[low] + (ordered[high]-ordered[low])*(offset-low),
            "min": ordered[0], "max": ordered[-1]}


def summarize_gpu_passes(log_path, *, start_ns=None, end_ns=None, boundary_exclusion_ns=0):
    """Read a completed viewer log; optionally select host submission boundaries.

    Every malformed relevant line is reported. Duplicate frame IDs are excluded
    entirely rather than choosing a preferred duplicate. Global trace losses
    cannot be assigned to a host window and therefore invalidate full coverage.
    """
    if (start_ns is None) != (end_ns is None):
        raise ValueError("Both window bounds are required")
    if type(boundary_exclusion_ns) is not int or boundary_exclusion_ns < 0:
        raise ValueError("Boundary exclusion must be a nonnegative integer")
    if start_ns is None:
        if boundary_exclusion_ns:
            raise ValueError("Boundary exclusion requires a window")
        lo = hi = None
    else:
        if any(type(v) is not int or v < 0 for v in (start_ns, end_ns)):
            raise ValueError("Window bounds must be nonnegative integers")
        lo, hi = start_ns+boundary_exclusion_ns, end_ns-boundary_exclusion_ns
        if lo >= hi:
            raise ValueError("Trimmed window is empty")
    path = Path(log_path)
    if path.stat().st_size > 64*1024*1024:
        raise ValueError("GPU trace exceeds bounded 64MiB reader")
    data = path.read_bytes()
    lines = data.decode("utf-8", errors="replace").splitlines()
    parsed, rejected, statuses, drops = [], [], [], []
    candidate_count = 0
    for number, line in enumerate(lines, 1):
        if "VR_GPU_PASS " in line:
            candidate_count += line.count("VR_GPU_PASS ")
            try:
                row = _parse_sample(line)
                row["line"] = number
                parsed.append(row)
            except ValueError as error:
                times = re.findall(r"(?:^| )host_begin_monotonic_ns=([0-9]+)(?: |$)", line)
                rejected.append({"line": number, "kind": "pass_record", "reason": str(error),
                                 "host_begin_monotonic_ns": int(times[0]) if len(times) == 1 else None,
                                 "text_prefix": line[:1024], "text_characters": len(line)})
        elif "VR_GPU_PASS_STATUS " in line:
            match = _STATUS.fullmatch(line)
            try:
                if not match:
                    raise ValueError("interleaved or malformed status")
                status = json.loads(match[2])
                if not isinstance(status, dict):
                    raise ValueError("status is not an object")
                statuses.append({"line": number, "phase": match[1], "status": status})
            except ValueError as error:
                rejected.append({"line": number, "kind": "status_record", "reason": str(error), "text_prefix": line[:1024]})
        elif line.startswith("VR_TRACE_DROPPED ") or "VR_TRACE_DROPPED epoch_ms=" in line:
            match = _DROP.fullmatch(line)
            if match:
                drops.append({"line": number, "epoch_ms": match[1], "count": int(match[2])})
            else:
                rejected.append({"line": number, "kind": "drop_record", "reason": "interleaved or malformed drop record", "text_prefix": line[:1024]})
    frame_counts = Counter(row["frame"] for row in parsed)
    duplicates = {str(frame): count for frame, count in frame_counts.items() if count > 1}
    selected = [row for row in parsed if lo is None or lo <= row["host_begin_monotonic_ns"] < hi]
    eligible = [row for row in selected if row["valid"] and frame_counts[row["frame"]] == 1]
    eligible.sort(key=lambda row: row["host_begin_monotonic_ns"])
    selected_rejected = [row for row in rejected if row["kind"] == "pass_record" and
                         (lo is None or row["host_begin_monotonic_ns"] is not None and lo <= row["host_begin_monotonic_ns"] < hi)]
    unknown_time_rejected = [row for row in rejected if row["kind"] == "pass_record" and row["host_begin_monotonic_ns"] is None]
    shutdown = [row for row in statuses if row["phase"] == "shutdown"]
    counters = shutdown[-1]["status"] if len(shutdown) == 1 else None
    missing = []
    ids = sorted({row["frame"] for row in eligible})
    for a, b in zip(ids, ids[1:]):
        if b > a+1:
            missing.append({"previous_frame": a, "next_frame": b, "missing_pass_frame_ids": b-a-1})
    coverage_reasons = []
    if not counters:
        coverage_reasons.append("missing or ambiguous shutdown counters")
    else:
        if counters.get("completed_frames") != len(parsed):
            coverage_reasons.append("completed native samples do not equal parseable records")
        for key in ("ring_full_frames", "unsupported_frames", "invalid_frames", "sink_failures", "shutdown_unobserved_frames"):
            if type(counters.get(key)) is not int or counters[key] != 0:
                coverage_reasons.append("nonzero or unavailable " + key)
    if rejected:
        coverage_reasons.append("malformed/interleaved relevant records")
    if duplicates:
        coverage_reasons.append("duplicate frame IDs")
    if drops:
        coverage_reasons.append("genuine trace drop records")
    if missing:
        coverage_reasons.append("selected valid samples have frame ID gaps")
    if not eligible:
        coverage_reasons.append("no selected valid samples")
    return {
        "schema": 1, "source": {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "lines": len(lines)},
        "window": {"requested_start_ns": start_ns, "requested_end_ns": end_ns, "boundary_exclusion_ns": boundary_exclusion_ns,
                   "selected_start_ns_inclusive": lo, "selected_end_ns_exclusive": hi,
                   "membership": "host_begin_monotonic_ns at CPU submission boundary, not GPU execution or OpenVR poll receipt"},
        "records": {"candidate_pass_records": candidate_count, "parseable_pass_records": len(parsed),
                    "native_invalid_pass_records": sum(not row["valid"] for row in parsed),
                    "duplicate_frame_ids": duplicates, "rejected": rejected, "genuine_trace_drop_records": drops,
                    "genuine_trace_dropped_total": sum(row["count"] for row in drops), "status_records": statuses},
        "coverage": {"full_log_complete": not coverage_reasons, "limitations": coverage_reasons,
                     "shutdown_counters": counters, "selected_parseable_records": len(selected), "selected_valid_unique_records": len(eligible),
                     "selected_native_invalid_records": sum(not row["valid"] for row in selected), "selected_malformed_pass_records": len(selected_rejected),
                     "malformed_pass_records_without_host_time": len(unknown_time_rejected), "selected_frame_id_gaps": missing,
                     "first_selected_frame": ids[0] if ids else None, "last_selected_frame": ids[-1] if ids else None,
                     "first_selected_host_ns": eligible[0]["host_begin_monotonic_ns"] if eligible else None,
                     "last_selected_host_ns": eligible[-1]["host_begin_monotonic_ns"] if eligible else None},
        "passes_ms": {key[:-3]: _statistics([row[key]/1e6 for row in eligible]) for key in sorted(_DURATIONS)},
        "sample_contexts": dict(Counter(json.dumps({key: row[key] for key in ("view_tools_version", "view_tools_flags", "menu_open", "shadow_scope", "motion_detail_reduced", "first_eye", "second_eye")}, sort_keys=True) for row in eligible)),
        "limits": ["GPU timeline elapsed includes queue idle and CPU submission gaps; it is not pure GPU busy time.",
                   "Scope includes ordinary scene shadow and full renderView in actual eye order, including UI/marker; excludes xrEndFrame.",
                   "Host submission windows differ from OpenVR poll-receipt windows even with identical boundary margins.",
                   "Missing pass records or duplicate frame IDs are evidence gaps, not proof of missing application submissions or physical refreshes.",
                   "The first and last selected frame cannot prove coverage outside their observed span; no optical timing is inferred."],
    }
