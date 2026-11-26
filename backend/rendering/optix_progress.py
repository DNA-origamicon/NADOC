"""Interpret Cycles' measured sample counts; never extrapolate from time."""
import json
import math
import re


def render_progress(line):
    if line.startswith("NADOC_PROGRESS "):
        try:
            info = json.loads(line.removeprefix("NADOC_PROGRESS "))
            if info["stage"] not in {"decode", "geometry", "acceleration", "readback"}:
                return None
            fraction = info.get("fraction")
            if fraction is not None and (not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0 <= fraction <= 1):
                return None
            return {"stage": info["stage"], "label": str(info["label"]), "fraction": fraction}
        except (ValueError, KeyError, TypeError):
            return None
    if line.startswith("NADOC_STAGE "):
        return {"stage": "prepare", "label": line.removeprefix("NADOC_STAGE "), "fraction": None}
    # Blender 3.x and 4.x respectively use these two status forms.
    match = re.search(r"(?:Rendering\s+|Sample\s+)(\d+)\s*/\s*(\d+)", line, re.IGNORECASE)
    if match:
        done, total = map(int, match.groups())
        if total > 0 and 0 <= done <= total:
            return {"stage": "tracing", "samples": done, "target": total,
                    "fraction": done / total, "label": f"OptiX · {done}/{total} samples"}
    return None
