"""File-oriented origami landmark tracking, with reproducible original evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image

from .projection import (APPLICATION_EYE, ApplicationFrame, ImagePoints,
                         project_source_points, unproject_application_depth)
from .template_tracking import SourceFrame, TrackConfig, make_template, track_landmarks


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path, limit=16 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("JSON evidence exceeds bounded input size")
    return json.loads(path.read_text())


def resolve(base, filename):
    return (base / filename).resolve(strict=True)


def shape_identity(evidence):
    state = evidence["state"]
    keys = ("scene_revision", "visualization_sequence", "coordinate_sequence")
    view = state.get("view_tools", {})
    if (any(type(state.get(k)) is not int for k in keys)
            or not isinstance(state.get("representation"), str)
            or type(state.get("motion_detail_reduced")) is not bool
            or any(type(view.get(k)) is not int for k in ("version", "flags", "sequence"))):
        raise ValueError("Capture lacks complete geometry/representation identity")
    return {"session": state["session"], **{key: state[key] for key in keys},
            "representation": state["representation"], "motion_detail_reduced": state["motion_detail_reduced"],
            "view_tools": {key: view[key] for key in ("version", "flags", "sequence")}}


def load_source(base, item, manifest):
    path = resolve(base, item["file"])
    if item.get("png_sha256") != digest(path):
        raise ValueError("Original PNG hash missing or changed: " + str(path))
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.width * image.height * 3 > 128 * 1024 * 1024:
            raise ValueError("Original must be a bounded RGB PNG; no implicit conversions")
        rgb = np.asarray(image)
    return SourceFrame(rgb, manifest["coordinate_space"], manifest["eye_rectangles"],
                       {**item.get("provenance", {}), "file": str(path), "png_sha256": item["png_sha256"]})


def evidence_for(base, item, frame, eye):
    """Only accept a captured eye with its sibling native metadata and pixels.

    Pin the metadata hash too: an arbitrary 'latest state' cannot be substituted
    for a captured pose. This binds local evidence, not compositor presentation.
    """
    if frame.coordinate_space != APPLICATION_EYE:
        raise ValueError("Expected application projection cannot be compared to final distorted pixels")
    path = resolve(base, item["evidence_file"])
    if item.get("evidence_sha256") != digest(path):
        raise ValueError("Capture metadata hash missing or changed")
    original = path.parent / f"{eye}.png"
    if not original.is_file() or digest(original) != item["png_sha256"]:
        raise ValueError("Image is not the matching eye from this native capture")
    evidence = read_json(path)
    context = ApplicationFrame.from_capture_evidence(evidence, eye)
    camera = context.camera
    if frame.eyes.get(eye) != (0, 0, camera.width, camera.height) or frame.rgb.shape[:2] != (camera.height, camera.width):
        raise ValueError("Application projection requires its full original eye image")
    return evidence, context, path.parent


def anchor_from_depth(base, item, frame, landmark):
    eye = landmark["eye"]
    evidence, context, directory = evidence_for(base, item, frame, eye)
    if (evidence.get("depth_format") != "float32-native-endian-window-depth-bottom-up"
            or evidence.get("class_format") != "uint8-bottom-up"):
        raise ValueError("Unsupported native class/depth layout")
    xy = landmark.get("anchor_xy")
    if xy is None or len(xy) != 2 or any(type(v) is not int for v in xy):
        raise ValueError("Depth anchors require explicit integer pixel centers")
    x, y = xy
    height, width = frame.rgb.shape[:2]
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError("Depth anchor outside eye image")
    classes = directory / f"{eye}.classes.u8"
    depth = directory / f"{eye}.depth.f32"
    if classes.stat().st_size != width * height or depth.stat().st_size != width * height * 4:
        raise ValueError("Native class/depth dimensions do not match the capture")
    mask = np.memmap(classes, dtype=np.uint8, mode="r", shape=(height, width))[::-1]
    if mask[y, x] != 1:
        raise ValueError("Anchor is not a visible design-class pixel")
    values = np.memmap(depth, dtype=np.float32, mode="r", shape=(height, width))[::-1]
    pixels = ImagePoints([xy], APPLICATION_EYE, eye, width, height, context.identity)
    result = unproject_application_depth(pixels, [float(values[y, x])], context,
                                         near_m=evidence["depth_near_m"], far_m=evidence["depth_far_m"])
    if not result.valid[0]:
        raise ValueError("Anchor lacks valid foreground depth")
    return {"source_nm": result.source_nm[0].tolist(), "anchor_xy": xy,
            "kind": "rendered_surface_sample_not_strand_identity",
            "reference_frame": context.identity.__dict__,
            "shape_identity": shape_identity(evidence),
            "classes_sha256": digest(classes), "depth_sha256": digest(depth)}


def run_tracking(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(strict=True), Path(output)
    manifest, base = read_json(manifest_path), manifest_path.parent
    if manifest.get("schema") != 1 or not 1 <= len(manifest.get("frames", [])) <= 2000:
        raise ValueError("Tracking requires schema 1 and 1..2000 explicit frames")
    landmarks = manifest.get("landmarks", [])
    if not 1 <= len(landmarks) <= 64 or len({p["id"] for p in landmarks}) != len(landmarks):
        raise ValueError("Provide 1..64 distinctly named landmarks")
    if len(landmarks) * len(manifest["frames"]) > 8192:
        raise ValueError("Report exceeds 8192 landmark/frame measurements; split the clip")
    if len({str(p["id"]) for p in manifest["frames"]}) != len(manifest["frames"]):
        raise ValueError("Frame IDs must be distinct")
    config = TrackConfig(**manifest.get("config", {}))
    reference = load_source(base, manifest["reference"], manifest)
    templates, anchors = {}, {}
    for item in landmarks:
        template = make_template(reference, item["id"], item["eye"], item["template_rect"],
                                 anchor_xy=item.get("anchor_xy"), config=config)
        templates.setdefault(item["eye"], []).append(template)
        if item.get("anchor_from_depth") is True:
            anchors[item["id"]] = anchor_from_depth(base, manifest["reference"], reference, item)
    output.mkdir(parents=True, exist_ok=False)
    (output / "originals").mkdir()
    shutil.copyfile(resolve(base, manifest["reference"]["file"]), output / "reference.png")
    if digest(output / "reference.png") != manifest["reference"]["png_sha256"]:
        raise ValueError("Reference changed during evidence copy")
    report = {"schema": 1, "coordinate_space": manifest["coordinate_space"],
              "manifest_sha256": digest(manifest_path), "reference": reference.metadata(),
              "templates": [t.metadata() for group in templates.values() for t in group],
              "anchors": anchors, "frames": [],
              "limits": ["Positions are measured from real original RGB patches; matching can fail under rotation, deformation, occlusion, or repetitive detail.",
                         "Integer translation sampling has at least ±0.5 pixel quantization; correlation is not a calibrated accuracy or probability.",
                         "Translation consensus is a per-eye image-motion estimate, not a 6DOF pose.",
                         "Final distorted pixels have no expected-pose residual until lens mapping and app-to-present association are calibrated.",
                         "A repeated position across presents is temporal evidence; this tool does not establish physical scanout or perceived doubling.",
                         "Depth anchors refer to the reference rendered surface and require unchanged molecular shape; re-anchor after Flex geometry or representation changes."]}
    shutil.copyfile(manifest_path, output / "manifest.json")
    for number, item in enumerate(manifest["frames"]):
        frame = load_source(base, item, manifest)
        groups = {eye: track_landmarks(frame, group, {t.landmark_id: manifest["search_rectangles"][t.landmark_id] for t in group},
                                      config, consensus_tolerance_px=manifest.get("consensus_tolerance_px", 2.0))
                  for eye, group in templates.items()}
        expected = {}
        for eye, group in groups.items():
            context = None
            frame_shape = None
            if anchors and frame.coordinate_space == APPLICATION_EYE and "evidence_file" in item:
                evidence, context, _ = evidence_for(base, item, frame, eye)
                frame_shape = shape_identity(evidence)
            for match in group["matches"]:
                name = match["landmark_id"]
                value = {"status": "unavailable", "position_xy": None, "residual_xy": None,
                         "reason": "requires_same_frame_application_evidence_and_reference_depth_anchor"}
                if frame.coordinate_space != APPLICATION_EYE:
                    value["reason"] = "final_distortion_and_app_to_present_association_not_calibrated"
                elif context is not None and name in anchors:
                    if frame_shape != anchors[name]["shape_identity"]:
                        value["reason"] = "geometry_representation_or_session_changed_reanchor_required"
                        expected[name] = value
                        continue
                    projection = project_source_points([anchors[name]["source_nm"]], context)
                    if projection.in_front[0]:
                        xy = projection.image.xy[0]
                        value.update(status="projected", position_xy=xy.tolist(), reason="same_frame_applied_render_pose",
                                     inside_image=bool(projection.inside_image[0]), frame=context.identity.__dict__)
                        if match["status"] == "tracked":
                            value["residual_xy"] = (np.array(match["position_xy"])-xy).tolist()
                    else:
                        value.update(status="behind_eye", reason="source_anchor_behind_eye")
                expected[name] = value
        relative = f"originals/{number:05d}.png"
        shutil.copyfile(resolve(base, item["file"]), output / relative)
        if digest(output / relative) != item["png_sha256"]:
            raise ValueError("Original changed during evidence copy")
        report["frames"].append({"id": item["id"], "image_file": relative, "source": frame.metadata(),
                                 "groups": groups, "expected": expected})
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    from .review import write_review
    write_review(output, report)
    return report


def export_final(directory, request, output, eyes, indices=None):
    """Decode selected final originals with exact request/present/file provenance."""
    from tools.vr_capture.pixels import decode_frame
    from tools.vr_capture.review import png_bytes
    directory, output = Path(directory).resolve(strict=True), Path(output)
    rows = []
    for path in sorted(directory.glob("events-*.jsonl")):
        with path.open() as stream:
            for line in stream:
                if len(line) > 65536:
                    raise ValueError("Compositor event exceeds line limit")
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("request") == request:
                    rows.append({**row, "events_file": path.name})
    starts = [r for r in rows if r.get("event") == "capture_start"]
    if len(starts) != 1:
        raise ValueError("Require exactly one capture start for this request")
    presents = sorted((r for r in rows if r.get("event") == "present" and r.get("armed")), key=lambda r: r["enter_ns"])
    saved = [r for r in rows if r.get("event") == "frame_saved"]
    key = lambda row: (row["events_file"], row["swapchain"], row["present"])
    by_key = {key(r): r for r in saved}
    if not presents or len(by_key) != len(saved) or len({key(r) for r in presents}) != len(presents) or set(by_key) != {key(r) for r in presents}:
        raise ValueError("Missing or duplicate present/image accounting; audit capture before tracking")
    selected = set(range(len(presents))) if indices is None else set(indices)
    if not selected or any(type(i) is not int or i < 0 or i >= len(presents) for i in selected):
        raise ValueError("Invalid explicit frame indices")
    output.mkdir(parents=True, exist_ok=False)
    items = []
    for index in sorted(selected):
        present = presents[index]
        row = by_key[key(present)]
        raw = decode_frame(directory, row)
        png = png_bytes(raw, row["width"], row["height"], row["format"])
        name = f"original-{index:04d}-present-{present['present']}.png"
        (output / name).write_bytes(png)
        provenance = {"request": request, "present": present["present"], "present_id": str(present.get("present_id")),
                      "index": index, "host_present_enter_ns": present["enter_ns"],
                      "source_directory": str(directory), "source_event": row,
                      "present_event": present,
                      "raw_sha256": hashlib.sha256(raw).hexdigest(),
                      "pixel_transform": "Lossless BGRA/RGBA to RGB only; no resize, dewarp or blending"}
        items.append({"id": index, "file": name, "png_sha256": hashlib.sha256(png).hexdigest(), "provenance": provenance})
    manifest = {"schema": 1, "coordinate_space": "final_swapchain_distorted", "eye_rectangles": eyes,
                "reference": items[0], "frames": items, "landmarks": [], "search_rectangles": {}}
    # Validate the explicit panel layout before publishing a usable manifest.
    load_source(output, items[0], manifest)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
