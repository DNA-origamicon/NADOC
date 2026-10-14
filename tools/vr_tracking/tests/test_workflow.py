"""Independent image/pose fixtures: observe a planted stale-render fault."""
import hashlib
import json
import math

import numpy as np
from PIL import Image
import pytest

from tools.vr_tracking.workflow import run_tracking


def scene(tmp_path):
    width, height = 128, 96
    rng = np.random.default_rng(832)
    patches = [rng.integers(20, 255, (13, 13, 3), dtype=np.uint8) for _ in range(2)]
    anchors = [[32, 40], [70, 55]]
    entries = []
    # A 0.25 m translation at z=-2 moves 8 px for width128,90deg FOV.
    # Frame3 intentionally renders old positions despite model pose +0.50 m.
    for index, shift in enumerate((0, 8, 0)):
        directory = tmp_path / f"capture-{index}"
        directory.mkdir()
        rgb = np.zeros((height, width, 3), np.uint8)
        classes = np.zeros((height, width), np.uint8)
        depth = np.ones((height, width), np.float32)
        for (x, y), patch in zip(anchors, patches):
            region = np.s_[y-6:y+7, x+shift-6:x+shift+7]
            rgb[region], classes[region] = patch, 1
            # OpenGL window-depth mapping, supplied independently of module.
            depth[region] = (100 - .02*100/2)/(100-.02)
        image = directory / "left.png"
        Image.fromarray(rgb).save(image)
        (directory / "left.classes.u8").write_bytes(classes[::-1].tobytes())
        (directory / "left.depth.f32").write_bytes(depth[::-1].tobytes())
        model = np.eye(4)
        model[0, 3] = index*.25
        evidence = {"source": "application_swapchain", "xr_end_frame_succeeded": True,
                    "depth_format": "float32-native-endian-window-depth-bottom-up", "class_format": "uint8-bottom-up",
                    "depth_near_m": .02, "depth_far_m": 100,
                    "state": {"session": "1-2", "frame": index+100, "predicted_display_time": index*11111111,
                              "scene_revision": 0, "visualization_sequence": 0, "coordinate_sequence": 0,
                              "representation": "stick", "motion_detail_reduced": False,
                              "view_tools": {"version": 1, "flags": 2304, "sequence": 0},
                              "presentation": {"model_to_tracking_rows": model.tolist(), "source_center_nm": [0,0,0],
                                               "normalization_model_per_nm": 1, "normalized_offset_model": [0,0,0]}},
                    "eyes": [{"eye": "left", "width": width, "height": height, "position": [0,0,0],
                              "orientation_xyzw": [0,0,0,1], "fov_left_right_up_down": [-math.pi/4,math.pi/4,math.pi/4,-math.pi/4]}]}
        metadata = directory / "evidence.json"
        metadata.write_text(json.dumps(evidence))
        entries.append({"id": index, "file": str(image), "png_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                        "evidence_file": str(metadata), "evidence_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest()})
    landmarks = [{"id": str(i), "eye": "left", "template_rect": [x-6,y-6,x+7,y+7],
                  "anchor_xy": [x,y], "anchor_from_depth": True} for i,(x,y) in enumerate(anchors)]
    manifest = {"schema": 1, "coordinate_space": "application_eye_undistorted", "eye_rectangles": {"left": [0,0,width,height]},
                "reference": entries[0], "frames": entries, "landmarks": landmarks,
                "search_rectangles": {str(i): [x-14,y-14,x+30,y+15] for i,(x,y) in enumerate(anchors)}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_pixel_tracking_detects_stale_render_against_independent_pose(tmp_path):
    path, _ = scene(tmp_path)
    result = run_tracking(path, tmp_path / "review")
    rows = result["frames"]
    assert [r["groups"]["left"]["translation_xy"] for r in rows] == [[0,0],[8,0],[0,0]]
    for row, dx in zip(rows, (0,0,-16)):
        for value in row["expected"].values():
            assert value["status"] == "projected"
            np.testing.assert_allclose(value["residual_xy"], [dx,0], atol=.001)
    assert (tmp_path / "review/index.html").is_file()
    # Evidence images are byte-identical, not synthetic overlays used as data.
    assert (tmp_path / "capture-2/left.png").read_bytes() == (tmp_path / "review/originals/00002.png").read_bytes()


def test_changed_original_fails_closed(tmp_path):
    path, manifest = scene(tmp_path)
    image = __import__('pathlib').Path(manifest["frames"][1]["file"])
    image.write_bytes(image.read_bytes()+b"modified")
    with pytest.raises(ValueError, match="hash"):
        run_tracking(path, tmp_path / "review")


def test_background_anchor_is_rejected(tmp_path):
    path, manifest = scene(tmp_path)
    manifest["landmarks"][0].update(template_rect=[0,0,80,70], anchor_xy=[2,2])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="design-class"):
        run_tracking(path, tmp_path / "review")


def test_final_distorted_images_cannot_use_application_depth(tmp_path):
    path, manifest = scene(tmp_path)
    manifest["coordinate_space"] = "final_swapchain_distorted"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="final distorted"):
        run_tracking(path, tmp_path / "review")


def test_pose_from_another_capture_cannot_silently_replace_image_pose(tmp_path):
    path, manifest = scene(tmp_path)
    manifest["frames"][1].update(evidence_file=manifest["frames"][0]["evidence_file"],
                                evidence_sha256=manifest["frames"][0]["evidence_sha256"])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="matching eye"):
        run_tracking(path, tmp_path / "review")


def test_changed_flex_geometry_withholds_rigid_pose_residual(tmp_path):
    path, manifest = scene(tmp_path)
    metadata = __import__('pathlib').Path(manifest['frames'][1]['evidence_file'])
    evidence = json.loads(metadata.read_text())
    evidence['state']['coordinate_sequence'] = 2
    metadata.write_text(json.dumps(evidence))
    manifest['frames'][1]['evidence_sha256'] = hashlib.sha256(metadata.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    result = run_tracking(path, tmp_path / 'review')
    assert all(v['residual_xy'] is None and 'reanchor' in v['reason'] for v in result['frames'][1]['expected'].values())
