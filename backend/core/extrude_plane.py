"""Canonical source-plane defaults, independent of viewing/physical transforms."""

import math
import re

PLANES = {"XY", "XZ", "YZ"}


def resolve_extrude_plane(design, fallback="XY"):
    """Prefer a unanimous source plane; otherwise infer unambiguous rest axes.

    Mixed/unknown geometry is explicitly a fallback, never a majority vote or
    nearest-axis snap. Cluster/physical transforms do not change source planes.
    """
    fallback = fallback if fallback in PLANES else "XY"
    planes = set()
    unknown = False
    for helix in getattr(design, "helices", []):
        match = re.match(r"^h_(XY|XZ|YZ)_-?\d+_-?\d+(?:_|$)", helix.id)
        plane = match[1] if match else None
        if plane is None:
            delta = [
                getattr(helix.axis_end, a) - getattr(helix.axis_start, a)
                for a in ("x", "y", "z")
            ]
            length = math.hypot(*delta)
            if math.isfinite(length) and length > 1e-12:
                aligned = [
                    i
                    for i in range(3)
                    if all(abs(delta[j]) <= length * 1e-6 for j in range(3) if j != i)
                ]
                if len(aligned) == 1:
                    plane = ("YZ", "XZ", "XY")[aligned[0]]
        if plane:
            planes.add(plane)
        else:
            unknown = True
    if len(planes) == 1 and not unknown:
        return next(iter(planes)), "geometry"
    return fallback, "mixed" if len(planes) > 1 else "unknown" if unknown else "empty"


def extrude_plane_record(design):
    plane, reason = resolve_extrude_plane(design)
    lattice = getattr(design, "lattice_type", "HONEYCOMB")
    lattice = getattr(lattice, "value", lattice)
    return f"F {plane} {lattice} {reason}"
