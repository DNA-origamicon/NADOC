"""Pixel-oracle negatives: state alone, white disabled text and clipped UI fail."""

from PIL import Image, ImageDraw
from tools.vr_workflows.menu_pixels import check


def fixture(tmp_path, *, gray=True, active=False):
    evidence = {
        "eyes": [
            {
                "eye": "left",
                "position": [0, 0, 0],
                "orientation_xyzw": [0, 0, 0, 1],
                "fov_left_right_up_down": [-0.785398, 0.785398, 0.785398, -0.785398],
                "width": 200,
                "height": 200,
            }
        ],
        "state": {
            "controls": [
                {
                    "id": "row",
                    "sidebar": "left",
                    "enabled": False,
                    "active": active,
                    "position": [0, 0, -1],
                    "hit_half_right": [0.5, 0, 0],
                    "hit_half_up": [0, 0.2, 0],
                }
            ]
        },
    }
    image = Image.new("RGB", (200, 200), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 80, 150, 120), fill=(31, 111, 235) if active else (22, 27, 34))
    draw.rectangle(
        (58, 102, 130, 107), fill=(182, 194, 207) if gray else (255, 255, 255)
    )
    image.save(tmp_path / "left.png")
    return evidence


def test_visible_disabled_control_needs_gray_text(tmp_path):
    evidence = fixture(tmp_path)
    assert check(tmp_path, evidence)["passed"]
    fixture(tmp_path, gray=False)
    assert not check(tmp_path, evidence)["passed"]


def test_blank_or_clipped_controls_fail_even_when_state_says_present(tmp_path):
    evidence = fixture(tmp_path)
    Image.new("RGB", (200, 200)).save(tmp_path / "left.png")
    assert not check(tmp_path, evidence)["passed"]
    evidence = fixture(tmp_path)
    evidence["state"]["controls"][0]["position"] = [5, 0, -1]
    assert not check(tmp_path, evidence)["passed"]


def test_active_tab_needs_blue_fill_and_visible_label(tmp_path):
    evidence = fixture(tmp_path, gray=False, active=True)
    evidence["state"]["controls"][0]["enabled"] = True
    assert check(tmp_path, evidence)["passed"]
    fixture(tmp_path, gray=False, active=False)
    assert not check(tmp_path, evidence)["passed"]


def test_scrollbar_requires_visible_thumb(tmp_path):
    evidence = fixture(tmp_path)
    control = evidence["state"]["controls"][0]
    control.update(id="scrollbar", enabled=True)
    image = Image.new("RGB", (200, 200), (22, 27, 34))
    image.save(tmp_path / "left.png")
    assert not check(tmp_path, evidence)["passed"]
    ImageDraw.Draw(image).rectangle((80, 82, 120, 89), fill=(182, 194, 207))
    image.save(tmp_path / "left.png")
    assert check(tmp_path, evidence)["passed"]
    control["enabled"] = False
    ImageDraw.Draw(image).rectangle((80, 82, 120, 118), fill=(63, 70, 79))
    image.save(tmp_path / "left.png")
    assert check(tmp_path, evidence)["passed"]
