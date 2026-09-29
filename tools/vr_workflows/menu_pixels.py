"""Independent stereo menu pixel checks; blank/occluded controls must fail."""

import numpy as np
from PIL import Image
from tools.vr_motion.metrics import rotate, sub


def check(directory, evidence):
    rows = []
    for eye in evidence["eyes"]:
        rgb = np.asarray(Image.open(directory / (eye["eye"] + ".png")).convert("RGB"))
        for control in evidence["state"]["controls"]:
            if not control.get("sidebar"):
                continue
            center = control["position"]
            right = control["hit_half_right"]
            up = control["hit_half_up"]
            # Sample the interior, excluding outlines and the small section heading.
            vertical = control["id"].startswith("tab:")
            scrollbar = control["id"] == "scrollbar" or control["id"].startswith("sim:scroll:")
            footer = control["id"] == "scrollbar" or control["id"] in (
                "close",
                "dock",
            )
            # Batch the same independent OpenXR projection for every sample.
            q = eye["orientation_xyzw"]
            inverse = [-q[0], -q[1], -q[2], q[3]]
            origin = np.asarray(rotate(inverse, sub(center, eye["position"])))
            r = np.asarray(rotate(inverse, right))
            u = np.asarray(rotate(inverse, up))
            xs, ys = np.meshgrid(
                np.linspace(-0.5 if scrollbar else -0.98, 0.5 if scrollbar else 0.9, 180),
                np.linspace(-0.98 if scrollbar else -0.80, 0.98 if scrollbar else 0.80 if vertical or footer else 0.15, 36),
            )
            positions = origin + xs.ravel()[:, None] * r + ys.ravel()[:, None] * u
            left, right_fov, up_fov, down = np.tan(eye["fov_left_right_up_down"])
            with np.errstate(divide="ignore", invalid="ignore"):
                x = (
                    (positions[:, 0] / -positions[:, 2] - left)
                    / (right_fov - left)
                    * eye["width"]
                )
                y = (
                    (up_fov - positions[:, 1] / -positions[:, 2])
                    / (up_fov - down)
                    * eye["height"]
                )
            valid = bool(
                np.all(
                    (positions[:, 2] < -0.001)
                    & (x >= 0)
                    & (x < eye["width"])
                    & (y >= 0)
                    & (y < eye["height"])
                )
            )
            pixels = (
                rgb[y.astype(int), x.astype(int)]
                if valid
                else np.zeros((1, 3), dtype=np.uint8)
            )
            # A scrollbar has a thumb rather than a text label. Disabled thumbs
            # use the desktop muted border color; demand visible neutral pixels.
            # Light foreground on nearly transparent glass; blank dark/white
            # panels are separately rejected by the room-tour negative checks.
            neutral = (pixels.min(axis=1)>100) & (np.ptp(pixels.astype(int),axis=1)<40)
            if scrollbar:
                neutral = (pixels.min(axis=1)>(100 if control["enabled"] else 50)) & (np.ptp(pixels.astype(int),axis=1)<40)
            text = int(neutral.sum())
            gray = True
            if not control["enabled"]:
                gray = bool(text and np.quantile(pixels[neutral].max(axis=1),.98)<230)
            active = True
            if control["active"]:
                active = bool(
                    (
                        (pixels[:, 2] > pixels[:, 0].astype(int)+18) & (pixels[:, 2] > pixels[:, 1].astype(int)+8)
                    ).sum()
                    > 20
                )
            rows.append(
                dict(
                    eye=eye["eye"],
                    side=control["sidebar"],
                    id=control["id"],
                    text_samples=text,
                    in_frame=valid,
                    disabled_gray=gray,
                    active_blue=active,
                    passed=valid and text >= 8 and gray and active,
                )
            )
    return {"passed": bool(rows) and all(r["passed"] for r in rows), "controls": rows}
