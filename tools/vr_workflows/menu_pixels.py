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
            left, right_fov, up_fov, down = np.tan(eye["fov_left_right_up_down"])
            def samples(x_values, y_values):
                xs, ys = np.meshgrid(x_values, y_values)
                positions = origin + xs.ravel()[:, None] * r + ys.ravel()[:, None] * u
                with np.errstate(divide="ignore", invalid="ignore"):
                    x = ((positions[:, 0] / -positions[:, 2] - left)
                         / (right_fov - left) * eye["width"])
                    y = ((up_fov - positions[:, 1] / -positions[:, 2])
                         / (up_fov - down) * eye["height"])
                in_frame = bool(np.all(
                    (positions[:, 2] < -0.001) & (x >= 0) & (x < eye["width"])
                    & (y >= 0) & (y < eye["height"])))
                pixels = (rgb[y.astype(int), x.astype(int)] if in_frame
                          else np.zeros((1, 3), dtype=np.uint8))
                return in_frame, pixels

            valid, pixels = samples(
                np.linspace(-0.5 if scrollbar else -0.98, 0.5 if scrollbar else 0.9, 180),
                np.linspace(-0.98 if scrollbar else -0.80, 0.98 if scrollbar else 0.80 if vertical or footer else 0.15, 36),
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
                # Active cards use a blue outline. Check their whole bounds
                # separately from the interior text/disabled-color sample.
                active_visible, active_pixels = samples(
                    np.linspace(-1, 1, 180), np.linspace(-1, 1, 72))
                active = active_visible and bool(
                    (
                        (active_pixels[:, 2] > active_pixels[:, 0].astype(int)+18) & (active_pixels[:, 2] > active_pixels[:, 1].astype(int)+8)
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
