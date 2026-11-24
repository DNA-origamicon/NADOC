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
            simulation = control["id"].startswith("sim:")
            scrubber = control["id"] == "sim:local:t:311"
            range_wheel = control["id"] in ("sim:local:t:300", "sim:local:t:301", "sim:local:t:302")
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

            # Simulation buttons put their label at the top inset, including
            # the tall side Play button. Inspect that interior as well as the
            # lower half; this is not a separate card section heading.
            valid, pixels = samples(
                np.linspace(-1.08 if scrubber else -0.5 if scrollbar else -0.98, 1.08 if scrubber else 0.5 if scrollbar else 0.9, 180),
                np.linspace(-0.98 if scrollbar or scrubber else -0.80, 0.98 if scrollbar or scrubber else 0.80 if vertical or footer or simulation else 0.15, 36),
                )
            # A scrollbar has a thumb rather than a text label. Disabled thumbs
            # use the desktop muted border color; demand visible neutral pixels.
            # Light foreground on nearly transparent glass; blank dark/white
            # panels are separately rejected by the room-tour negative checks.
            neutral = (pixels.min(axis=1)>100) & (np.ptp(pixels.astype(int),axis=1)<40)
            if scrollbar:
                neutral = (pixels.min(axis=1)>(100 if control["enabled"] else 50)) & (np.ptp(pixels.astype(int),axis=1)<40)
            if scrubber:
                # The raised scrubber has a cyan draggable handle, no text inside
                # its hit target. Demand colored foreground across the full track.
                neutral = ((pixels[:, 2].astype(int)-pixels[:, 0]>35) & (pixels[:, 1]>100)) if control["enabled"] else (pixels.min(axis=1)>45)
            if range_wheel:
                # These controls are ribbed cyan cylinders; their numeric labels
                # sit beside, rather than inside, the physical hit surface.
                neutral = ((pixels[:, 2].astype(int)-pixels[:, 0]>25) & (pixels[:, 1]>70)) if control["enabled"] else (pixels.min(axis=1)>30)
            file_table = control.get("tab") == "file-browser"
            if file_table:
                # Option 4 uses solid slate surfaces and blue-grey disabled text,
                # not the generic sidebar's neutral-grey stroke palette.
                target = [89,194,255] if scrollbar else [230,240,255] if control["enabled"] or control["id"] == "routing-help" else [140,168,196]
                neutral = np.all(np.abs(pixels.astype(int)-np.array(target)) <= 20, axis=1)
                if control["id"].startswith("routing:file-entry-"):
                    # The parent row's name is only "..". Its type/date/size
                    # are also visible glyphs, in the gallery's muted palette.
                    neutral |= np.all(np.abs(pixels.astype(int)-np.array([140,168,196])) <= 20, axis=1)
            text = int(neutral.sum())
            gray = True
            if not control["enabled"] and not (file_table and control["id"] == "routing-help"):
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
