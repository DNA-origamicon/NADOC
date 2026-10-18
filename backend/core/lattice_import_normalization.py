"""Unchanged pure normalization shared by lattice import route and replay."""

from backend.core.models import Design, Vec3


def _recenter_design(design: "Design") -> "Design":
    """Translate all helix axes so the XY bounding box center is at the origin.

    Only X and Y are shifted (Z runs along the helix axis and is left alone).
    No-op when the design has no helices or is already centered.
    """
    if not design.helices:
        return design
    xs = [h.axis_start.x for h in design.helices]
    ys = [h.axis_start.y for h in design.helices]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    if abs(cx) < 1e-6 and abs(cy) < 1e-6:
        return design
    new_helices = [
        h.model_copy(
            update={
                "axis_start": Vec3(
                    x=h.axis_start.x - cx, y=h.axis_start.y - cy, z=h.axis_start.z
                ),
                "axis_end": Vec3(
                    x=h.axis_end.x - cx, y=h.axis_end.y - cy, z=h.axis_end.z
                ),
            }
        )
        for h in design.helices
    ]
    new_overhangs = [
        o.model_copy(update={"pivot": [o.pivot[0] - cx, o.pivot[1] - cy, o.pivot[2]]})
        for o in design.overhangs
    ]
    # Shift previously-set cluster pivots so they stay in sync with the recentered
    # helix axes.  Skip pivots that are still [0,0,0] (never activated) — those will
    # be computed fresh from geometry when the move/rotate tool is first used.
    _ZERO = [0.0, 0.0, 0.0]
    new_clusters = [
        ct.model_copy(
            update={"pivot": [ct.pivot[0] - cx, ct.pivot[1] - cy, ct.pivot[2]]}
        )
        if list(ct.pivot) != _ZERO
        else ct
        for ct in design.cluster_transforms
    ]
    return design.model_copy(
        update={
            "helices": new_helices,
            "overhangs": new_overhangs,
            "cluster_transforms": new_clusters,
        }
    )
