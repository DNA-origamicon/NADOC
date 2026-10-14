"""Offline host interaction timing with exact, optional image identity joins.

No runtime calls or image decoding. Host call intervals are neither GPU busy
time nor optical latency; co-occurrence does not establish a causal mechanism.
"""
from collections import Counter
import hashlib
import html
import json
import math
from pathlib import Path

from .gpu_timing import _statistics
from .journal_projection import MAX_BYTES, _constant, _integer, _journal, _mapped_time

LIMITS = [
    "Host call durations include blocking and scheduling; they are not GPU busy time or photon latency.",
    "Menu-open and submitted draw counts do not establish that a menu was visible inside either eye's field of view.",
    "Hover, haptics and long frames can co-occur without either causing the other; controlled comparisons are still required.",
    "Missing legacy hover/haptic telemetry is unavailable, never inferred as zero.",
    "Unknown or nonadjacent final identities break hold/advance comparisons; no nearest-time identity inference is used.",
    "Decoded identities are consumed as pinned evidence, not independently redecoded from image pixels here.",
    "Clock conversion metadata is checked for consistency, not independently calibrated against physical scanout.",
    "Instrumented host spans may overlap; do not add nested menu, sidebar and backdrop spans as independent costs. Clock-query counts are not an overhead calibration.",
    "Haptic dispatched means xrApplyHapticFeedback was invoked, not that physical controller vibration was independently observed.",
]


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError("Invalid boolean " + name)
    return value


def _pair(values, name, convert):
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("Require two " + name)
    return [convert(v, name) for v in values]


def _interval(row, first, last, bounds, *, optional=False):
    a, b = row.get(first), row.get(last)
    if optional and a is None and b is None:
        return None
    a, b = _integer(a, first), _integer(b, last)
    if optional and a == b == 0:
        return None
    if b < a or not bounds[0] <= a <= b <= bounds[1]:
        raise ValueError("Inverted or out-of-frame host interval: " + first)
    return b-a


def _diagnostics(value, bounds):
    if value is None:
        return {"available": False, "reason": "legacy_journal_has_no_interaction_telemetry"}
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Unsupported capture_ui_diagnostics schema")
    if not _bool(value.get("enabled"), "diagnostics enabled"):
        return {"available": False, "reason": "capture_interaction_telemetry_disabled"}
    if (value.get("clock") != "CLOCK_MONOTONIC" or value.get("gpu_timing_available") is not False
            or value.get("onscreen_visibility_available") is not False):
        raise ValueError("Unsupported interaction timing/visibility semantics")
    clock_errors = _integer(value["clock_errors"], "interaction clock errors")
    clock_queries = _integer(value["clock_queries"], "interaction clock queries") if "clock_queries" in value else None
    if clock_errors:
        return {"available": False, "reason": "native_clock_error_invalidates_ui_timing", "clock_errors": clock_errors}
    h = value["haptics"]
    counters = {k: _pair(h[k], k, _integer) for k in
                ("requested", "dispatched", "failed", "host_total_ns", "host_max_ns")}
    for hand in range(2):
        if not counters["failed"][hand] <= counters["dispatched"][hand] <= counters["requested"][hand]:
            raise ValueError("Inconsistent per-frame haptic counters")
        if not counters["host_max_ns"][hand] <= counters["host_total_ns"][hand] <= bounds[1]-bounds[0]:
            raise ValueError("Inconsistent haptic host timing totals")
    events = h["events"]
    overflow = _integer(h["events_overflow"], "haptic event overflow")
    if not isinstance(events, list) or len(events) > 16 or len(events)+overflow != sum(counters["requested"]):
        raise ValueError("Inconsistent bounded haptic event coverage")
    observed = {k: [0, 0] for k in counters}
    previous = bounds[0]
    for event in events:
        hand = _integer(event["hand"], "haptic hand", maximum=1)
        _integer(event["callsite_line"], "haptic callsite", 1)
        amplitude = event["amplitude"]
        if type(amplitude) not in (int, float) or not math.isfinite(amplitude) or not 0 <= amplitude <= 1:
            raise ValueError("Invalid haptic amplitude")
        request = _integer(event["request_ns"], "haptic request")
        if not previous <= request <= bounds[1]:
            raise ValueError("Haptic request outside frame or reordered")
        previous = request
        dispatched = _bool(event["dispatched"], "haptic dispatch")
        if dispatched:
            duration = _interval(event, "dispatch_begin_ns", "dispatch_end_ns", (request, bounds[1]))
            result = _integer(event["xr_result"], "haptic result", -(1 << 31), (1 << 31)-1)
            observed["dispatched"][hand] += 1
            observed["failed"][hand] += int(result < 0)
            observed["host_total_ns"][hand] += duration
            observed["host_max_ns"][hand] = max(observed["host_max_ns"][hand], duration)
        elif event["dispatch_begin_ns"] != 0 or event["dispatch_end_ns"] != 0 or event["xr_result"] is not None:
            raise ValueError("Undispatched haptic has fabricated call timing/result")
        observed["requested"][hand] += 1
    for key in counters:
        if any(a > b or (not overflow and a != b) for a, b in zip(observed[key], counters[key])):
            raise ValueError("Haptic events and counters disagree")
    sidebars, eyes = value["sidebars"], value["eyes"]
    if not isinstance(sidebars, list) or len(sidebars) != 2 or {s.get("hand") for s in sidebars} != {0, 1}:
        raise ValueError("Require unique sidebar hands")
    for item in sidebars:
        _integer(item["hand"], "sidebar hand", maximum=1)
        for k in ("open", "hover_truncated", "hover_previous_known", "hover_change_valid", "hover_changed"):
            _bool(item[k], k)
        if (item["hover_changed"] and not item["hover_change_valid"]) or (item["hover_change_valid"] and (not item["hover_previous_known"] or item["hover_truncated"])):
            raise ValueError("Invalid hover change ownership/coverage")
        if not isinstance(item["hover_id"], str) or len(item["hover_id"].encode()) > 96:
            raise ValueError("Invalid bounded hover identity")
        for k in ("texture_updates", "texture_cache_hits", "texture_update_host_ns", "draw_calls", "draw_host_ns"):
            _integer(item[k], k)
    if not isinstance(eyes, list) or len(eyes) != 2 or {e.get("eye") for e in eyes} != {"left", "right"}:
        raise ValueError("Require unique diagnostic eyes")
    for item in eyes:
        for k in ("menu_draw_calls", "menu_host_ns", "backdrop_copy_calls", "backdrop_host_ns"):
            _integer(item[k], k)
    return {"available": True, "version": 1, "clock_errors": 0, "clock_queries": clock_queries, "haptics": {**counters, "events": events, "events_overflow": overflow},
            "sidebars": sorted(sidebars, key=lambda s: s["hand"]), "eyes": sorted(eyes, key=lambda e: e["eye"])}


def _frame(row, previous, header):
    start = _integer(row["host_frame_start_ns"], "host frame start")
    end = _integer(row["host_frame_end_ns"], "host frame end")
    if end < start or (previous and start < previous["host_frame_end_ns"]):
        raise ValueError("Inverted or overlapping application host frames")
    predicted = _integer(row["predicted_display_time_ns"], "predicted display time", -(1 << 63))
    period = row.get("predicted_display_period_ns")
    if period is not None:
        period = _integer(period, "predicted period", 1)
    mapped = _mapped_time(row)
    step = predicted-previous["predicted_display_time_ns"] if previous else None
    if step is not None and step <= 0:
        raise ValueError("Predicted display times must increase")
    mapped_step = mapped-previous["predicted_display_monotonic_ns"] if previous and mapped is not None and previous["predicted_display_monotonic_ns"] is not None else None
    if mapped_step is not None and mapped_step <= 0:
        raise ValueError("Mapped display times must increase")
    lo, hi = header["capture_start_monotonic_ns"], header["capture_end_monotonic_ns"]
    def relation(t):
        return None if t is None else "preroll" if t < lo else "capture" if t < hi else "tail"
    for field, actual in (("host_window_relation", relation(end)), ("predicted_window_relation", relation(mapped))):
        if field in row and row[field] != actual:
            raise ValueError("Journal window relation contradicts timestamps")
    result = {"frame": row["frame"], "host_frame_start_ns": start, "host_frame_end_ns": end,
              "offset_ms": (start-lo)/1e6, "host_window_relation": relation(end), "host_start_window_relation": relation(start),
              "predicted_window_relation": relation(mapped), "predicted_display_time_ns": predicted,
              "predicted_display_monotonic_ns": mapped, "predicted_display_period_ns": period,
              "predicted_step_ns": step, "mapped_predicted_step_ns": mapped_step,
              "host_start_step_ns": start-previous["host_frame_start_ns"] if previous else None,
              "frame_ms": (end-start)/1e6, "actions_ms": None, "locate_views_ms": None, "xr_end_frame_ms": None,
              "menu_open": _pair(row["menu_open"], "menu open", _bool) if "menu_open" in row else None,
              "submitted": _bool(row["submitted"], "submitted"),
              "xr_end_frame_succeeded": _bool(row["xr_end_frame_succeeded"], "xrEndFrame success"),
              "tracking": {}, "interaction": _diagnostics(row.get("capture_ui_diagnostics"), (start, end))}
    # Legacy menu_open is sampled only on the rendered branch. New sidebar
    # diagnostics sample immediately after input, including non-rendered rows.
    rendered_state_observed = any(e.get("rendered") is True for e in row.get("eyes", []))
    if result["interaction"]["available"]:
        result["menu_open"] = [s["open"] for s in result["interaction"]["sidebars"]]
        result["menu_state_source"] = "post_input_sidebar_diagnostics"
    elif rendered_state_observed:
        result["menu_state_source"] = "legacy_rendered_branch"
    else:
        result["menu_open"] = None
        result["menu_state_source"] = "unavailable_on_legacy_nonrendered_row"
    for name, prefix in (("actions", "host_actions"), ("locate_views", "host_locate_views"), ("xr_end_frame", "host_end_frame")):
        interval = _interval(row, prefix+"_start_ns", prefix+"_end_ns", (start, end), optional=True)
        result[name+"_ms"] = None if interval is None else interval/1e6
    flags = row.get("view_state_flags")
    if flags is not None:
        flags = _integer(flags, "view flags", maximum=(1 << 64)-1)
    view_observed = result["locate_views_ms"] is not None or rendered_state_observed
    result["tracking"]["view"] = {"flags": flags, "observed": view_observed,
                                    "valid": None if flags is None or not view_observed else flags & 3 == 3,
                                    "tracked": None if flags is None or not view_observed else flags & 12 == 12}
    hands = row.get("hands")
    result["tracking"]["hands"] = None
    if hands is not None:
        if not isinstance(hands, list) or len(hands) != 2:
            raise ValueError("Require two hand records")
        result["tracking"]["hands"] = []
        for hand in hands:
            flags = _integer(hand["runtime_location_flags"], "runtime hand flags", maximum=(1 << 64)-1)
            valid = _bool(hand["valid"], "applied hand validity")
            locate = _interval(hand, "host_locate_start_ns", "host_locate_end_ns", (start, end), optional=True)
            result["tracking"]["hands"].append({"applied_state_observed": rendered_state_observed,
                "applied_valid": valid if rendered_state_observed else None, "input_source": hand["input_source"] if rendered_state_observed else None,
                "runtime_flags": flags, "runtime_valid": flags & 3 == 3, "runtime_tracked": flags & 12 == 12,
                "runtime_pose_queried": _bool(hand["runtime_pose_queried"], "runtime queried") if "runtime_pose_queried" in hand else None,
                "runtime_pose_action_active": _bool(hand["runtime_pose_action_active"], "runtime active") if "runtime_pose_action_active" in hand else None,
                "locate_ms": None if locate is None else locate/1e6,
                "grip": _bool(hand["grip"], "grip") if rendered_state_observed else None})
    return result


def _identities(path, header, journal_hash, native_rows, frames):
    from .frame_identity import LEGACY_PROTOCOL, PROTOCOL, _journal_eye, marker_packet
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Identity evidence exceeds bounded input size")
    data = json.loads(raw, parse_constant=_constant)
    if (type(data.get("schema")) is not int or data["schema"] != 1 or data.get("coordinate_space") != "final_swapchain_distorted"
            or data.get("journal_sha256") != journal_hash or data.get("session") != header["session"]
            or type(data.get("request")) is not int or data["request"] != header["request"]):
        raise ValueError("Identity report journal hash/session/request/coordinates mismatch")
    if (data.get("protocol") not in (PROTOCOL, LEGACY_PROTOCOL)
            or header.get("frame_identity", {}).get("enabled") is not True
            or data["protocol"] != header.get("frame_identity", {}).get("protocol")):
        raise ValueError("Identity and journal marker protocols differ")
    inputs = data["frames"]
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 2000:
        raise ValueError("Require 1..2000 final identity frames")
    by_id = {r["frame"]: r for r in native_rows}
    timing = {r["frame"]: r for r in frames}
    result, previous, eye_names = [], None, None
    for item in inputs:
        index = _integer(item["capture_index"], "capture index")
        present = _integer(item["present"], "present")
        host = _integer(item["host_present_enter_ns"], "host present time")
        if previous and (index <= previous["capture_index"] or present <= previous["present"] or host <= previous["host_present_enter_ns"]):
            raise ValueError("Final identities are reordered or duplicated")
        source = item["source"]; provenance = source["provenance"]
        for key in ("request", "index", "present", "host_present_enter_ns"):
            _integer(provenance.get(key), "source " + key)
        if (source.get("coordinate_space") != data["coordinate_space"] or provenance.get("request") != header["request"]
                or provenance.get("index") != index or provenance.get("present") != present
                or provenance.get("host_present_enter_ns") != host):
            raise ValueError("Final source provenance contradicts identity row")
        names = set(item["eyes"])
        if not names or names-{"left", "right"} or (eye_names is not None and names != eye_names):
            raise ValueError("Inconsistent final eye ownership")
        eye_names = names
        current = {"capture_index": index, "present": present, "host_present_enter_ns": host,
                   "offset_ms": (host-header["capture_start_monotonic_ns"])/1e6, "eyes": {}}
        contiguous = previous is not None and index == previous["capture_index"]+1 and present == previous["present"]+1
        for eye in sorted(names):
            decoded = item["eyes"][eye]
            state = {"status": decoded["status"], "reason": decoded.get("reason"), "app_frame": None,
                     "image_transition": "unavailable", "contiguous_captured_presents": contiguous}
            if decoded["status"] == "joined":
                identity = decoded["identity"]
                frame = _integer(identity["frame"], "decoded application frame", maximum=(1 << 64)-1)
                if identity.get("session") != header["session"] or identity.get("eye") != eye or frame not in by_id:
                    raise ValueError("Joined identity has wrong session/eye or absent journal frame")
                rendered, reason = _journal_eye(by_id[frame], eye)
                packet = marker_packet(header["session"], eye, frame, data["protocol"])
                crc = _integer(identity.get("packet_crc32"), "decoded CRC", maximum=(1 << 32)-1)
                if reason or identity.get("packet_hex") != packet.hex() or crc != int.from_bytes(packet[24:28], "big") or crc != rendered["frame_identity"]["packet_crc32"]:
                    raise ValueError("Joined identity packet/CRC contradicts rendered journal receipt")
                claimed = decoded.get("journal", {})
                if _integer(claimed.get("frame"), "claimed application frame", maximum=(1 << 64)-1) != frame or claimed.get("eye") != eye:
                    raise ValueError("Joined journal ownership mismatch")
                for field in ("predicted_display_time_ns", "predicted_display_monotonic_ns", "host_frame_start_ns", "host_frame_end_ns", "clock_mapping"):
                    if type(claimed.get(field)) is not type(by_id[frame].get(field)) or claimed.get(field) != by_id[frame].get(field):
                        raise ValueError("Joined journal time mismatch: " + field)
                state.update(app_frame=frame, menu_open=timing[frame]["menu_open"], interaction_available=timing[frame]["interaction"]["available"])
                old = previous["eyes"][eye] if previous else None
                if contiguous and old["app_frame"] is not None:
                    state["image_transition"] = "held" if frame == old["app_frame"] else "advanced" if frame > old["app_frame"] else "regressed"
            elif decoded["status"] not in ("unknown", "decoded_unjoined", "decoded"):
                raise ValueError("Unknown decoder status")
            current["eyes"][eye] = state
        current["stereo_app_ids_match"] = (current["eyes"]["left"]["app_frame"] == current["eyes"]["right"]["app_frame"]) if names == {"left", "right"} and all(e["app_frame"] is not None for e in current["eyes"].values()) else None
        result.append(current); previous = current
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "frames": result,
            "status_counts": {eye: dict(Counter(r["eyes"][eye]["status"] for r in result)) for eye in sorted(eye_names)},
            "transition_counts": {eye: dict(Counter(r["eyes"][eye]["image_transition"] for r in result)) for eye in sorted(eye_names)},
            "association": "Exact pinned journal/session/request/eye/frame/CRC; unknowns not inferred"}


def _summary(rows):
    result = {"frames": len(rows), "submitted_frames": sum(r["submitted"] and r["xr_end_frame_succeeded"] for r in rows),
              "timing_ms": {k: _statistics([r[k] for r in rows if r[k] is not None]) for k in ("frame_ms", "actions_ms", "locate_views_ms", "xr_end_frame_ms")},
              "predicted_step_ms": _statistics([r["predicted_step_ns"]/1e6 for r in rows if r["predicted_step_ns"] is not None]),
              "menu_state_counts": dict(Counter("unavailable" if r["menu_open"] is None else "both" if all(r["menu_open"]) else "left" if r["menu_open"][0] else "right" if r["menu_open"][1] else "closed" for r in rows)),
              "view_invalid_frames": sum(r["tracking"]["view"]["valid"] is False for r in rows),
              "view_untracked_frames": sum(r["tracking"]["view"]["tracked"] is False for r in rows),
              "view_flags_unavailable_frames": sum(r["tracking"]["view"]["flags"] is None for r in rows),
              "view_unobserved_frames": sum(not r["tracking"]["view"]["observed"] for r in rows),
              "interaction_telemetry_frames": sum(r["interaction"]["available"] for r in rows),
              "interaction_unavailable_reasons": dict(Counter(r["interaction"]["reason"] for r in rows if not r["interaction"]["available"])),
              "hands": [], "haptics": None, "associations": {}}
    for hand in range(2):
        records = [r["tracking"]["hands"][hand] for r in rows if r["tracking"]["hands"] is not None]
        result["hands"].append({"hand": hand, "records": len(records), "applied_invalid_frames": sum(h["applied_valid"] is False for h in records),
            "applied_state_unavailable_frames": sum(not h["applied_state_observed"] for h in records),
            "queried_runtime_invalid_frames": sum(h["runtime_pose_queried"] is True and not h["runtime_valid"] for h in records),
            "queried_runtime_untracked_frames": sum(h["runtime_pose_queried"] is True and not h["runtime_tracked"] for h in records),
            "runtime_query_unavailable_frames": sum(h["runtime_pose_queried"] is None for h in records),
            "input_source_counts": dict(Counter(h["input_source"] or "unavailable" for h in records))})
    interactions = [r["interaction"] for r in rows if r["interaction"]["available"]]
    if interactions:
        result["haptics"] = {k: [sum(r["haptics"][k][h] for r in interactions) for h in range(2)] for k in ("requested", "dispatched", "failed", "host_total_ns")}
        result["haptics"]["events_overflow"] = sum(r["haptics"]["events_overflow"] for r in interactions)
        result["haptics"]["coverage_frames"] = len(interactions)
    result["ui"] = None
    if interactions:
        queries = [r["clock_queries"] for r in interactions if r["clock_queries"] is not None]
        result["ui"] = {"coverage_frames": len(interactions), "clock_queries": sum(queries) if queries else None,
                        "clock_query_coverage_frames": len(queries), "sidebars": [], "eyes": []}
        for hand in range(2):
            sidebars = [r["sidebars"][hand] for r in interactions]
            result["ui"]["sidebars"].append({"hand": hand,
                **{key: sum(s[key] for s in sidebars) for key in ("texture_updates", "texture_cache_hits", "draw_calls")},
                "texture_update_host_ms": _statistics([s["texture_update_host_ns"]/1e6 for s in sidebars]),
                "draw_host_ms": _statistics([s["draw_host_ns"]/1e6 for s in sidebars]),
                "hover_changes": sum(s["hover_changed"] for s in sidebars),
                "hover_change_unavailable_frames": sum(not s["hover_change_valid"] for s in sidebars)})
        for eye in ("left", "right"):
            eyes = [next(e for e in r["eyes"] if e["eye"] == eye) for r in interactions]
            result["ui"]["eyes"].append({"eye": eye,
                **{key: sum(e[key] for e in eyes) for key in ("menu_draw_calls", "backdrop_copy_calls")},
                "menu_host_ms": _statistics([e["menu_host_ns"]/1e6 for e in eyes]),
                "backdrop_host_ms": _statistics([e["backdrop_host_ns"]/1e6 for e in eyes])})
    for name, predicate in {
        "menu_open": lambda r: None if r["menu_open"] is None else any(r["menu_open"]),
        "hover_changed": _hover_changed,
        "haptic_dispatched": lambda r: any(r["interaction"]["haptics"]["dispatched"]) if r["interaction"]["available"] else None,
    }.items():
        result["associations"][name] = {"interpretation": "Descriptive co-occurrence, not causation", "unavailable_frames": sum(predicate(r) is None for r in rows)}
        for flag in (False, True):
            selected = [r for r in rows if predicate(r) is flag]
            result["associations"][name][str(flag).lower()] = {"frames": len(selected), "frame_ms": _statistics([r["frame_ms"] for r in selected]), "actions_ms": _statistics([r["actions_ms"] for r in selected if r["actions_ms"] is not None])}
    return result


def _hover_changed(row):
    if not row["interaction"]["available"]:
        return None
    sidebars = row["interaction"]["sidebars"]
    if any(s["hover_changed"] for s in sidebars):
        return True
    return False if all(s["hover_change_valid"] for s in sidebars) else None


def summarize_interactions(journal_path, identities_path=None):
    """Strictly summarize retained host timing, with no runtime or input calls."""
    try:
        header, native, trailer, sha = _journal(journal_path)
        frames = []
        for row in native:
            frames.append(_frame(row, frames[-1] if frames else None, header))
        result = {"schema": 1, "source": "offline_application_interaction_timing", "session": header["session"],
                  "request": header["request"], "journal_path": str(Path(journal_path).resolve()), "journal_sha256": sha,
                  "journal_complete": True, "journal_frames": len(frames), "mapping_failures": trailer["mapping_failures"],
                  "capture_start_monotonic_ns": header["capture_start_monotonic_ns"], "capture_end_monotonic_ns": header["capture_end_monotonic_ns"],
                  "frames": frames, "summary": {"all_retained": _summary(frames),
                      "host_start_in_capture": _summary([r for r in frames if r["host_start_window_relation"] == "capture"]),
                      "predicted_in_capture": _summary([r for r in frames if r["predicted_window_relation"] == "capture"])},
                  "identities": None, "causality_verified": False, "optical_output_verified": False,
                  "physical_refresh_mapping_verified": False, "limits": LIMITS}
        if identities_path is not None:
            result["identities"] = _identities(identities_path, header, sha, native, frames)
        return result
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed interaction timing evidence: " + str(error)) from error


def write_interaction_report(result, output):
    """Write a new bounded JSON + self-contained interactive timeline directory."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    def browser_safe(value):
        if isinstance(value, dict):
            return {k: browser_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [browser_safe(v) for v in value]
        return str(value) if type(value) is int and abs(value) > (1 << 53)-1 else value
    data = json.dumps(browser_safe(result), allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    page = '''<!doctype html><meta charset="utf-8"><title>VR interaction timing</title>
<style>body{font:15px system-ui;margin:2rem;max-width:1400px;background:#fafafa;color:#202832}canvas{width:100%;border:1px solid #ccd;background:white}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.35rem;border-bottom:1px solid #ddd}pre{white-space:pre-wrap}label{margin-right:1rem}button{margin:.5rem}small{color:#456}</style>
<h1>VR interaction timing</h1><p>Host intervals and descriptive co-occurrence. No causality, GPU busy-time or optical latency claim.</p>
<p id="provenance"></p><label><input id="capture" type="checkbox" checked>Host frame starts inside capture interval</label><label>Minimum frame ms <input id="minimum" type="number" value="0" min="0" step="1"></label>
<p>Blue: whole frame. Orange: input/actions. Red dots: dispatched haptics. Green dots: hover change. Gray lane: menu open. Bottom lane: exact final IDs (orange held, blue advanced, gray unknown/boundary). Click a frame for its evidence.</p>
<canvas id="plot" width="1400" height="300"></canvas><p id="counts"></p><pre id="details"></pre>
<table><thead><tr><th>Frame</th><th>Offset ms</th><th>Host frame ms</th><th>Actions ms</th><th>xrEndFrame ms</th><th>Menu L/R</th><th>Hover</th><th>Haptic calls</th></tr></thead><tbody id="rows"></tbody></table>
<h2>Limits</h2><ul>LIMITS</ul><script id="evidence" type="application/json">DATA</script>
<script>
const d=JSON.parse(document.getElementById('evidence').textContent),c=document.getElementById('plot'),ctx=c.getContext('2d');let shown=[];
const fmt=x=>x===null?'unavailable':Number(x).toFixed(3),byId=id=>document.getElementById(id);
byId('provenance').textContent='Session '+d.session+'; request '+d.request+'; journal SHA256 '+d.journal_sha256;
function draw(){shown=d.frames.filter(r=>(!byId('capture').checked||r.host_start_window_relation==='capture')&&r.frame_ms>=Number(byId('minimum').value));ctx.clearRect(0,0,c.width,c.height);byId('rows').replaceChildren();byId('details').textContent='';if(!shown.length){byId('counts').textContent='No selected frames';return;}
const lo=shown[0].offset_ms,hi=shown[shown.length-1].offset_ms+shown[shown.length-1].frame_ms,scale=Math.max(1,...shown.map(r=>r.frame_ms));const x=t=>10+(t-lo)/Math.max(1,hi-lo)*1380;
for(const r of shown){const a=x(r.offset_ms),w=Math.max(1,x(r.offset_ms+r.frame_ms)-a);ctx.fillStyle='#387bc1';ctx.fillRect(a,240-r.frame_ms/scale*200,w,r.frame_ms/scale*200);if(r.actions_ms!==null){ctx.fillStyle='#dc8617';ctx.fillRect(a,240-r.actions_ms/scale*200,w,r.actions_ms/scale*200);}if(r.menu_open&&r.menu_open.some(Boolean)){ctx.fillStyle='#aeb8c4';ctx.fillRect(a,247,w,8);}if(r.interaction.available){if(r.interaction.haptics.dispatched.some(v=>v>0)){ctx.fillStyle='#d62828';ctx.fillRect(a,12,4,5);}if(r.interaction.sidebars.some(s=>s.hover_changed)){ctx.fillStyle='#138341';ctx.fillRect(a,23,4,5);}}}
if(d.identities)for(const p of d.identities.frames){if(p.offset_ms<lo||p.offset_ms>hi)continue;let n=0;for(const e of Object.values(p.eyes)){ctx.fillStyle=e.image_transition==='held'?'#dc8617':e.image_transition==='advanced'?'#387bc1':'#bbb';ctx.fillRect(x(p.offset_ms),267+n*10,3,8);n++;}}
byId('counts').textContent=shown.length+' selected application frames; table shows first '+Math.min(300,shown.length)+'. Missing telemetry stays unavailable.';
for(const r of shown.slice(0,300)){const tr=document.createElement('tr'),v=r.interaction;const values=[String(r.frame),fmt(r.offset_ms),fmt(r.frame_ms),fmt(r.actions_ms),fmt(r.xr_end_frame_ms),r.menu_open?JSON.stringify(r.menu_open):'unavailable',v.available?v.sidebars.map(s=>s.hover_id||'none').join(' / '):'unavailable',v.available?v.haptics.dispatched.join(' / '):'unavailable'];for(const t of values){const td=document.createElement('td');td.textContent=t;tr.append(td);}tr.onclick=()=>byId('details').textContent=JSON.stringify(r,null,2);byId('rows').append(tr);}
c.onclick=e=>{const t=lo+((e.clientX-c.getBoundingClientRect().left)/c.getBoundingClientRect().width*c.width-10)/1380*(hi-lo);const r=shown.reduce((a,b)=>Math.abs(b.offset_ms-t)<Math.abs(a.offset_ms-t)?b:a);byId('details').textContent=JSON.stringify(r,null,2);};}
byId('capture').onchange=draw;byId('minimum').oninput=draw;draw();</script>'''
    page = page.replace("LIMITS", "".join("<li>"+html.escape(v)+"</li>" for v in result["limits"])).replace("DATA", data)
    (output/"index.html").write_text(page)
    return output
