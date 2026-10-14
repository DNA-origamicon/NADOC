"""Decode opt-in rendered application frame IDs from original RGB pixels.

The four corner fiducials locate a small projective sampling grid. This is not
lens calibration or image dewarping. No temporal guesses, bit correction,
nearest-timestamp joins, interpolation of frame IDs, or silent fallbacks occur.
A CRC-valid marker establishes which submitted application image contributed
that marker's pixels; it does not prove physical scanout or that every other
pixel used the same source image after compositor processing.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import itertools
import math
from pathlib import Path
import re
import struct
import zlib

import numpy as np
from scipy.ndimage import find_objects, label, map_coordinates

from .journal_projection import _journal
from .template_tracking import SourceFrame, _rect, _contains
from .workflow import digest, load_source, read_json

PROTOCOL = "nadoc-frame-v2"
LEGACY_PROTOCOL = "nadoc-frame-v1"
LAYOUTS = {LEGACY_PROTOCOL: (1, 22, 3, 19), PROTOCOL: (2, 24, 4, 21)}
MAGIC = b"NF"
PAD = bytes.fromhex("a55ac33c")
GRID_CELLS = 24
PAYLOAD_RECT_CELLS = (4, 4, 20, 20)
FIDUCIAL_CENTERS = np.array([[1.5, 1.5], [22.5, 1.5], [1.5, 22.5], [22.5, 22.5]])
FIDUCIAL_COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))


@dataclass(frozen=True)
class DecodeConfig:
    max_search_pixels: int = 1024 * 1024
    max_color_components: int = 64
    max_candidates_per_corner: int = 4
    minimum_fiducial_area: int = 4
    minimum_fiducial_edge_px: float = 38.0
    maximum_fiducial_edge_px: float = 640.0
    minimum_contrast: float = 80.0
    uncertain_bit_margin: float = 0.25

    def __post_init__(self):
        for key, upper in (("max_search_pixels", 4*1024*1024), ("max_color_components", 128),
                           ("max_candidates_per_corner", 4), ("minimum_fiducial_area", 10000)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("Invalid bounded decoder configuration: " + key)
        for key in ("minimum_fiducial_edge_px", "maximum_fiducial_edge_px", "minimum_contrast", "uncertain_bit_margin"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Invalid decoder configuration: " + key)
        if (not 20 <= self.minimum_fiducial_edge_px < self.maximum_fiducial_edge_px <= 1024
                or not 40 <= self.minimum_contrast <= 255
                or not .1 <= self.uncertain_bit_margin <= .4):
            raise ValueError("Decoder acceptance bounds are invalid")


def session_components(session: str) -> tuple[int, int]:
    if not isinstance(session, str) or not re.fullmatch(r"[1-9][0-9]{0,9}-[1-9][0-9]{0,19}", session):
        raise ValueError("Marker requires canonical full PID-start_monotonic_ns session")
    pid, start = map(int, session.split("-"))
    if pid >= 1 << 32 or start >= 1 << 64:
        raise ValueError("Marker session fields exceed wire bounds")
    return pid, start


def marker_packet(session: str, eye: str, frame: int, protocol=PROTOCOL) -> bytes:
    """Canonical wire encoder for fixtures and cross-language protocol checks."""
    pid, start = session_components(session)
    if protocol not in LAYOUTS:
        raise ValueError("Unsupported explicit frame marker protocol")
    if eye not in ("left", "right") or type(frame) is not int or not 0 <= frame < 1 << 64:
        raise ValueError("Invalid marker eye or full uint64 application frame")
    data = struct.pack(">2sBBIQQ", MAGIC, LAYOUTS[protocol][0], int(eye == "right"), pid, start, frame)
    return data + struct.pack(">I", zlib.crc32(data)) + PAD


def marker_cells(session: str, eye: str, frame: int, protocol=PROTOCOL) -> np.ndarray:
    """Exact native-layout RGB cells; fixture only, never a captured original."""
    packet = marker_packet(session, eye, frame, protocol)
    version, side, payload, corner = LAYOUTS[protocol]
    cells = np.zeros((side, side, 3), dtype=np.uint8)
    bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8)).reshape(16, 16)
    cells[payload:payload+16, payload:payload+16] = bits[:, :, None] * 255
    colors = FIDUCIAL_COLORS if version == 1 else ((255, 255, 255),)*4
    for (x, y), color in zip(((0, 0), (corner, 0), (0, corner), (corner, corner)), colors):
        cells[y:y+3, x:x+3] = color
    return cells


def _parse_packet(raw, session, eye, protocol):
    if raw[:2] != MAGIC or raw[2] != LAYOUTS[protocol][0] or raw[28:] != PAD:
        return None, "magic_version_or_padding_mismatch"
    crc = int.from_bytes(raw[24:28], "big")
    if zlib.crc32(raw[:24]) != crc:
        return None, "crc_mismatch"
    _, _, eye_id, pid, start, frame = struct.unpack(">2sBBIQQ", raw[:24])
    if eye_id not in (0, 1) or not pid or not start:
        return None, "invalid_identity_fields"
    identity = {"session": f"{pid}-{start}", "eye": "right" if eye_id else "left",
                "frame": frame, "packet_crc32": crc, "packet_hex": raw.hex()}
    if identity["session"] != session:
        return None, "session_mismatch"
    if identity["eye"] != eye:
        return None, "eye_mismatch"
    return identity, None


def _color_fiducials(rgb, origin, config):
    r, g, b = (rgb[:, :, i].astype(np.int16) for i in range(3))
    masks = [(r > 130) & (r > g+60) & (r > b+60),
             (g > 130) & (g > r+60) & (g > b+60),
             (b > 130) & (b > r+60) & (b > g+35),
             (r > 130) & (g > 130) & (np.minimum(r, g) > b+60)]
    groups = []
    for mask in masks:
        components, count = label(mask)
        if count > config.max_color_components:
            return None, "too_many_color_components"
        candidates = []
        for number, bounds in enumerate(find_objects(components), 1):
            if bounds is None:
                continue
            region = components[bounds] == number
            ys, xs = np.nonzero(region)
            height, width = region.shape
            if (len(xs) < config.minimum_fiducial_area or len(xs) > 30000
                    or len(xs) / (height*width) < .45
                    or max(height, width) > 4*min(height, width)):
                continue
            candidates.append((origin[0] + bounds[1].start + float(xs.mean()),
                               origin[1] + bounds[0].start + float(ys.mean())))
        if not candidates:
            return None, "missing_fiducial"
        if len(candidates) > config.max_candidates_per_corner:
            return None, "too_many_fiducial_candidates"
        groups.append(candidates)
    return groups, None


def _white_fiducials(rgb, origin, config):
    """V2 uses only the green plane, including achromatic corner geometry.

    An explicit ROI must isolate the marker. Foreground bounds provide only a
    coarse size/ordering check; payload values or expected frame IDs never fit
    the grid. Competing geometries remain candidates until strict packet checks.
    """
    mask = rgb[:, :, 1] > 130
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None, "missing_fiducial"
    xmin, xmax, ymin, ymax = xs.min(), xs.max(), ys.min(), ys.max()
    midpoint = ((xmin+xmax)/2, (ymin+ymax)/2)
    coarse_area = (xmax-xmin+1)*(ymax-ymin+1)*9/(24*24)
    components, count = label(mask)
    # Tiny scene fragments cannot become fiducials under the existing area
    # test. Bound eligible components rather than rejecting an intact marker
    # merely because those fragments surround it in the search rectangle.
    # bincount and this lookup are bounded by max_search_pixels. Densely
    # remapping before find_objects also bounds its Python object allocation.
    areas = np.bincount(components.ravel(), minlength=count+1)
    eligible = np.flatnonzero(areas >= config.minimum_fiducial_area)
    eligible = eligible[eligible != 0]
    if len(eligible) > config.max_color_components:
        return None, "too_many_green_components"
    dense = np.zeros(count+1, dtype=components.dtype)
    dense[eligible] = np.arange(1, len(eligible)+1)
    components = dense[components]
    groups = [[], [], [], []]
    for number, bounds in enumerate(find_objects(components), 1):
        if bounds is None:
            continue
        region = components[bounds] == number
        cy, cx = np.nonzero(region)
        height, width = region.shape
        area = len(cx)
        if (area < max(config.minimum_fiducial_area, .5*coarse_area)
                or area > 2*coarse_area or area/(height*width) < .70
                or max(height, width) > 3*min(height, width)):
            continue
        x, y = bounds[1].start+float(cx.mean()), bounds[0].start+float(cy.mean())
        group = int(x > midpoint[0]) + 2*int(y > midpoint[1])
        groups[group].append((origin[0]+x, origin[1]+y, area))
    if any(not group for group in groups):
        return None, "missing_fiducial"
    if any(len(group) > config.max_candidates_per_corner for group in groups):
        return None, "too_many_fiducial_candidates"
    return groups, None


def _corner_areas_match(candidate, matrix):
    for (x, y), point in zip(((1.5, 1.5), (22.5, 1.5), (1.5, 22.5), (22.5, 22.5)), candidate):
        square = np.array([[x-1.5,y-1.5,1], [x+1.5,y-1.5,1], [x+1.5,y+1.5,1], [x-1.5,y+1.5,1]]) @ matrix.T
        square = square[:,:2]/square[:,2:3]
        area = abs(np.dot(square[:,0],np.roll(square[:,1],-1))-np.dot(square[:,1],np.roll(square[:,0],-1)))/2
        if not .65*area <= point[2] <= 1.35*area:
            return False
    return True


def _homography(corners, config, protocol):
    perimeter = corners[[0, 1, 3, 2]]
    edges = np.roll(perimeter, -1, axis=0) - perimeter
    lengths = np.linalg.norm(edges, axis=1)
    cross = edges[:, 0]*np.roll(edges[:, 1], -1)-edges[:, 1]*np.roll(edges[:, 0], -1)
    if (np.any(cross <= 0) or lengths.min() < config.minimum_fiducial_edge_px
            or lengths.max() > config.maximum_fiducial_edge_px or lengths.max() > 4*lengths.min()):
        return None
    a, b = [], []
    far = LAYOUTS[protocol][3] + 1.5
    centers = ((1.5, 1.5), (far, 1.5), (1.5, far), (far, far))
    for (x, y), (u, v) in zip(centers, corners):
        a.extend(([x, y, 1, 0, 0, 0, -u*x, -u*y], [0, 0, 0, x, y, 1, -v*x, -v*y]))
        b.extend((u, v))
    try:
        return np.append(np.linalg.solve(np.array(a), np.array(b)), 1).reshape(3, 3)
    except np.linalg.LinAlgError:
        return None


def _sample(gray, origin, matrix, session, eye, config, protocol):
    offset = LAYOUTS[protocol][2]
    yy, xx = np.mgrid[offset:offset+16, offset:offset+16].astype(float)
    centers = np.stack((xx.ravel()+.5, yy.ravel()+.5), axis=1)
    sample_points = centers[:, None, :] + np.array([[0, 0], [.17, 0], [-.17, 0], [0, .17], [0, -.17]])
    points = np.column_stack((sample_points.reshape(-1, 2), np.ones(256*5))) @ matrix.T
    if np.any(np.abs(points[:, 2]) < 1e-8):
        return None, "invalid_projective_grid"
    points = points[:, :2]/points[:, 2:3] - np.array(origin)
    if (np.any(points < 0) or np.any(points[:, 0] > gray.shape[1]-1)
            or np.any(points[:, 1] > gray.shape[0]-1)):
        return None, "sampling_grid_outside_search_rectangle"
    values = np.median(map_coordinates(gray, [points[:, 1], points[:, 0]], order=1, mode="nearest").reshape(256, 5), axis=1)
    known_bytes = MAGIC + bytes([LAYOUTS[protocol][0]]) + bytes(25) + PAD
    known_bits = np.unpackbits(np.frombuffer(known_bytes, dtype=np.uint8))
    known_mask = np.zeros(256, dtype=bool); known_mask[:24] = True; known_mask[224:] = True
    black = float(np.median(values[known_mask & (known_bits == 0)]))
    white = float(np.median(values[known_mask & (known_bits == 1)]))
    contrast = white-black
    if contrast < config.minimum_contrast:
        return None, "insufficient_marker_contrast"
    normalized = (values-black)/contrast
    margin = np.abs(normalized-.5)
    if np.any(margin < config.uncertain_bit_margin):
        return None, "uncertain_payload_bits"
    raw = np.packbits(normalized > .5).tobytes()
    identity, reason = _parse_packet(raw, session, eye, protocol)
    if reason:
        return None, reason
    return {**identity, "contrast_gray_levels": contrast, "minimum_bit_margin": float(margin.min()),
            "bit_error_correction": False}, None


def decode_frame_identity(source: SourceFrame, eye: str, expected_session: str,
                          search_rect, config: DecodeConfig | None = None, protocol=PROTOCOL) -> dict:
    """Return decoded or explicit unknown; never infer an ID from nearby frames."""
    session_components(expected_session)
    if protocol not in LAYOUTS:
        raise ValueError("Unsupported explicit frame marker protocol")
    config = config or DecodeConfig()
    if not isinstance(source, SourceFrame) or eye not in source.eyes:
        raise ValueError("Marker decoding requires original pixels and explicit eye ownership")
    rect = _rect(search_rect, "marker search rectangle")
    if not _contains(source.eyes[eye], rect):
        raise ValueError("Marker search must lie wholly within its explicit eye rectangle")
    x0, y0, x1, y1 = rect
    if (x1-x0)*(y1-y0) > config.max_search_pixels:
        raise ValueError("Marker search exceeds bounded pixel budget")
    result = {"status": "unknown", "reason": None, "identity": None, "protocol": protocol,
              "coordinate_space": source.coordinate_space, "eye": eye, "search_rect": list(rect),
              "source_rgb_sha256": source.rgb_sha256, "expected_session": expected_session,
              "lens_calibration": False, "optical_output_verified": False}
    rgb = source.rgb[y0:y1, x0:x1]
    groups, reason = (_color_fiducials if protocol == LEGACY_PROTOCOL else _white_fiducials)(rgb, (x0, y0), config)
    if reason:
        result["reason"] = reason
        return result
    gray = np.mean(rgb, axis=2, dtype=np.float64) if protocol == LEGACY_PROTOCOL else rgb[:, :, 1].astype(np.float64)
    result["sampling_channel"] = "RGB_mean" if protocol == LEGACY_PROTOCOL else "green"
    accepted, rejected = [], Counter()
    for candidate in itertools.product(*groups):
        corners = np.asarray([point[:2] for point in candidate])
        matrix = _homography(corners, config, protocol)
        if matrix is None:
            rejected["invalid_fiducial_geometry"] += 1
            continue
        if protocol == PROTOCOL and not _corner_areas_match(candidate, matrix):
            rejected["fiducial_area_inconsistent_with_grid"] += 1
            continue
        identity, reason = _sample(gray, (x0, y0), matrix, expected_session, eye, config, protocol)
        if reason:
            rejected[reason] += 1
        else:
            accepted.append({**identity, "fiducial_centers_xy": corners.tolist(),
                             "cell_to_source_projective_rows": matrix.tolist()})
    result["candidate_rejections"] = dict(rejected)
    result["valid_candidate_count"] = len(accepted)
    if len(accepted) == 1:
        result.update(status="decoded", reason="magic_crc_full_session_and_eye_match", identity=accepted[0])
    else:
        result["reason"] = "ambiguous_multiple_valid_markers" if accepted else "no_valid_marker"
    return result


def _journal_eye(row, eye):
    if row.get("submitted") is not True or row.get("xr_end_frame_succeeded") is not True:
        return None, "journal_frame_not_successfully_submitted"
    eyes = [v for v in row.get("eyes", []) if v.get("eye") == eye]
    if len(eyes) != 1 or eyes[0].get("rendered") is not True:
        return None, "journal_eye_not_rendered"
    marker = eyes[0].get("frame_identity", {})
    if (marker.get("rendered") is not True or type(marker.get("frame")) is not int
            or marker["frame"] != row["frame"] or type(marker.get("packet_crc32")) is not int
            or not 0 <= marker["packet_crc32"] < 1 << 32):
        return None, "journal_marker_not_rendered_for_frame"
    return eyes[0], None


def _reuse_table(frames, eye):
    runs, transitions, current = [], [], None
    previous = None
    for frame in frames:
        joined = frame["eyes"][eye]
        identity = joined.get("identity") if joined["status"] == "joined" else None
        contiguous = (previous is not None and frame["capture_index"] == previous["capture_index"]+1
                      and previous["eyes"][eye]["status"] == "joined")
        if identity is None:
            current = None
        else:
            app = identity["frame"]
            if contiguous:
                old = previous["eyes"][eye]["identity"]["frame"]
                if app != old:
                    transitions.append({"previous_capture_index": previous["capture_index"], "capture_index": frame["capture_index"],
                                        "previous_app_frame": old, "app_frame": app,
                                        "kind": "forward" if app > old else "regression",
                                        "not_observed_app_ids_between": max(0, app-old-1),
                                        "interpretation": "marker IDs absent between adjacent captured presents; not proof of dropped application rendering"})
            if current is not None and contiguous and current["app_frame"] == app:
                current["last_capture_index"] = frame["capture_index"]
                current["captured_present_count"] += 1
                current["last_host_present_enter_ns"] = frame["host_present_enter_ns"]
            else:
                current = {"app_frame": app, "first_capture_index": frame["capture_index"],
                           "last_capture_index": frame["capture_index"], "captured_present_count": 1,
                           "first_host_present_enter_ns": frame["host_present_enter_ns"],
                           "last_host_present_enter_ns": frame["host_present_enter_ns"]}
                runs.append(current)
        previous = frame
    return {"runs": runs, "transitions": transitions,
            "reused_present_count": sum(r["captured_present_count"]-1 for r in runs),
            "run_length_counts": dict(Counter(r["captured_present_count"] for r in runs)),
            "unknown_or_unjoined_breaks_runs": True, "physical_hold_duration_measured": False}


def _marker_follow_config(manifest, search):
    value = manifest.get("marker_roi_follow")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"margin_px", "max_search_rectangles"}:
        raise ValueError("Marker ROI following needs an explicit margin and maximum search rectangles")
    margin, bounds = value["margin_px"], value["max_search_rectangles"]
    if type(margin) is not int or not 0 <= margin <= 64 or not isinstance(bounds, dict) or set(bounds) != set(search):
        raise ValueError("Invalid bounded marker ROI following configuration")
    maximum = {}
    for eye, rectangle in bounds.items():
        rectangle = _rect(rectangle, "maximum marker search rectangle")
        if not _contains(manifest["eye_rectangles"][eye], rectangle) or not _contains(rectangle, search[eye]):
            raise ValueError("Maximum marker search must contain initial ROI within its explicit eye")
        if (rectangle[2]-rectangle[0])*(rectangle[3]-rectangle[1]) > DecodeConfig().max_search_pixels:
            raise ValueError("Maximum marker search exceeds bounded pixel budget")
        maximum[eye] = list(rectangle)
    return {"margin_px": margin, "max_search_rectangles": maximum}


def _following_rectangle(identity, protocol, maximum, margin):
    """Predict only a search location from a previously verified grid."""
    side = LAYOUTS[protocol][1]
    matrix = np.asarray(identity["cell_to_source_projective_rows"], dtype=float)
    corners = np.array([[0,0,1], [side,0,1], [0,side,1], [side,side,1]]) @ matrix.T
    if not np.isfinite(corners).all() or np.any(np.abs(corners[:, 2]) < 1e-8):
        return None
    points = corners[:, :2]/corners[:, 2:3]
    low, high = np.floor(points.min(axis=0))-margin, np.ceil(points.max(axis=0))+margin
    rectangle = [max(maximum[0], int(low[0])), max(maximum[1], int(low[1])),
                 min(maximum[2], int(high[0])), min(maximum[3], int(high[1]))]
    return rectangle if rectangle[0] < rectangle[2] and rectangle[1] < rectangle[3] else None


def _join_frame_identities(manifest_path, journal_path, request: int) -> dict:
    """Decode hashed originals, then join only exact session+eye+uint64 frame IDs.

    Manifest uses workflow.export_final's originals/provenance plus explicit
    marker_search_rectangles. Every frame needs exact request, capture index and
    host_present_enter_ns provenance. Missing retained journal rows stay
    decoded_unjoined; malformed provenance/header is a whole-input error.
    """
    if type(request) is not int or not 0 < request < 1 << 63:
        raise ValueError("Invalid exact capture request")
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = read_json(manifest_path)
    if manifest.get("schema") != 1 or not 1 <= len(manifest.get("frames", [])) <= 2000:
        raise ValueError("Require schema1 manifest with1..2000 original frames")
    header, rows, trailer, journal_hash = _journal(journal_path)
    session_pid, session_start = session_components(header["session"])
    if type(header.get("pid")) is not int or header["pid"] != session_pid:
        raise ValueError("Journal PID differs from its full session identity")
    if header["request"] != request:
        raise ValueError("Capture request differs from pose journal")
    marker_header = header.get("frame_identity", {})
    protocol = marker_header.get("protocol")
    if (marker_header.get("enabled") is not True or protocol not in LAYOUTS
            or type(marker_header.get("version")) is not int or marker_header["version"] != LAYOUTS[protocol][0]
            or type(marker_header.get("session_pid")) is not int or marker_header["session_pid"] != session_pid
            or type(marker_header.get("session_start_ns")) is not int or marker_header["session_start_ns"] != session_start):
        raise ValueError("Journal does not declare this exact opt-in frame identity protocol/session")
    by_id = {row["frame"]: row for row in rows}
    eyes = tuple(manifest["eye_rectangles"])
    search = manifest.get("marker_search_rectangles", {})
    if set(search) != set(eyes):
        raise ValueError("Provide explicit marker search rectangles for every named eye")
    search = {eye: list(_rect(rectangle, "marker search rectangle")) for eye, rectangle in search.items()}
    follow = _marker_follow_config(manifest, search)
    following = {}
    report = {"schema": 1, "protocol": protocol, "session": header["session"], "request": request,
              "manifest_sha256": digest(manifest_path), "journal_sha256": journal_hash,
              "coordinate_space": manifest["coordinate_space"], "frames": [], "reuse": {},
              "association": "exact decoded full session, eye and application frame; no nearest-time association",
              "optical_output_verified": False, "lens_calibration": False,
              "limits": ["Decoded marker identity binds its pixels to a rendered application eye. It does not establish source ownership of all compositor pixels or physical scanout.",
                         "Projective fiducial sampling is a bounded local decoding approximation, not calibrated headset distortion.",
                         "Unknown and decoded-but-unjoined frames remain explicit and break reuse runs.",
                         "Forward ID gaps report application IDs not observed between adjacent captured presents, not automatically dropped rendering."]}
    if follow:
        report["marker_roi_follow"] = {**follow, "initial_search_rectangles": search,
            "policy": "Only exact journal joins update localization; unknown freezes it; capture-index gaps reset initial ROI. No IDs are predicted."}
    previous_index = -1
    previous_host = -1
    for item in manifest["frames"]:
        provenance = item.get("provenance", {})
        index, host = provenance.get("index"), provenance.get("host_present_enter_ns")
        if (type(provenance.get("request")) is not int or provenance["request"] != request
                or type(index) is not int or index <= previous_index
                or type(host) is not int or host <= previous_host):
            raise ValueError("Each source needs exact request and strictly ordered capture index/host-present provenance")
        if manifest["coordinate_space"] == "final_swapchain_distorted":
            saved, present = provenance.get("source_event", {}), provenance.get("present_event", {})
            if (saved.get("event") != "frame_saved" or present.get("event") != "present"
                    or not (present.get("armed") is True or (type(present.get("armed")) is int and present["armed"] == 1))
                    or saved.get("request") != request or present.get("request") != request
                    or type(provenance.get("present")) is not int
                    or saved.get("present") != provenance["present"] or present.get("present") != provenance["present"]
                    or present.get("enter_ns") != host
                    or saved.get("swapchain") != present.get("swapchain")
                    or saved.get("events_file") != present.get("events_file")):
                raise ValueError("Final source/present events disagree with exact capture provenance")
        source = load_source(manifest_path.parent, item, manifest)
        output = {"id": item["id"], "capture_index": index, "host_present_enter_ns": host,
                  "present": provenance.get("present"), "source": source.metadata(), "eyes": {}}
        if follow and index != previous_index+1:
            following.clear()
        for eye in eyes:
            rectangle, followed_index = following.get(eye, (search[eye], None))
            decoded = decode_frame_identity(source, eye, header["session"], rectangle, protocol=protocol)
            if decoded["status"] == "decoded":
                identity = decoded["identity"]
                row = by_id.get(identity["frame"])
                rendered, reason = (None, "decoded_frame_outside_retained_journal") if row is None else _journal_eye(row, eye)
                if rendered is not None and rendered["frame_identity"].get("packet_crc32") != identity["packet_crc32"]:
                    reason = "journal_marker_crc_mismatch"
                if reason:
                    decoded.update(status="decoded_unjoined", reason=reason)
                else:
                    decoded.update(status="joined", reason="exact_session_eye_frame_and_rendered_packet_match",
                                   journal={"frame": row["frame"], "eye": eye,
                                            "predicted_display_time_ns": row.get("predicted_display_time_ns"),
                                            "predicted_display_monotonic_ns": row.get("predicted_display_monotonic_ns"),
                                            "host_frame_start_ns": row.get("host_frame_start_ns"),
                                            "host_frame_end_ns": row.get("host_frame_end_ns"),
                                            "clock_mapping": row.get("clock_mapping")})
            if follow:
                maximum = follow["max_search_rectangles"][eye]
                if not _contains(source.eyes[eye], maximum):
                    raise ValueError("Maximum marker search escaped actual source eye")
                updated = None
                if decoded["status"] == "joined":
                    updated = _following_rectangle(decoded["identity"], protocol, maximum, follow["margin_px"])
                    if updated is not None:
                        following[eye] = (updated, index)
                decoded["roi_follow"] = {"source_capture_index": followed_index,
                    "maximum_search_rect": maximum, "next_search_rect": updated or rectangle,
                    "geometry_updated": updated is not None, "identity_inferred": False}
            output["eyes"][eye] = decoded
        report["frames"].append(output)
        previous_index, previous_host = index, host
    for eye in eyes:
        report["reuse"][eye] = _reuse_table(report["frames"], eye)
    report["status_counts"] = {eye: dict(Counter(f["eyes"][eye]["status"] for f in report["frames"])) for eye in eyes}
    return report


def join_frame_identities(manifest_path, journal_path, request: int) -> dict:
    """Strict bounded original-image/pose-journal join; see internal workflow."""
    try:
        return _join_frame_identities(manifest_path, journal_path, request)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed marker association evidence: " + str(error)) from error
