"""Parametric instance-layout helpers — pure geometry (AF-10).

Where :mod:`backend.core.circle_primitive` turns a *radius* into a disc footprint
of DNA helices, this module turns a layout *spec* (a grid of rows×cols, or a ring
of ``n`` evenly-spaced slots) into a list of world *translations* at which to
place part instances in an assembly. It is the analytic heart of the headless
assembly layout helpers (``headless_assembly_build.place_grid`` / ``place_ring``):
those wrappers call one of these to compute where each copy goes, then drive
``add_instance`` per slot.

It is pure — no IO, no Assembly, no instance mutation. Orientation is **identity**
(parts are translated only, never rotated): which way a part should *face* on a
ring (outward / tangent / fixed) is an orientation convention this module
deliberately does not pick — that is a three-layer directionality question to
resolve with the user before adding (see ``CLAUDE.md``). A slot is a position; the
caller decides the pose.

Plane convention mirrors ``circle_primitive``: a 2-D ``(u, v)`` layout is embedded
in the ``XY`` (default), ``XZ`` or ``YZ`` world plane.

Layering: core (L1). No frontend mirror today (headless layout has no canvas
preview); if one is added, pin it to the same oracle the way ``circle_primitive``
is pinned to ``circle_primitive_logic.js``.
"""

from __future__ import annotations

import math

Vec3 = tuple[float, float, float]


def _embed(u: float, v: float, plane: str) -> Vec3:
    """Embed a 2-D layout point ``(u, v)`` into a world plane.

    ``XY`` → ``(u, v, 0)``; ``XZ`` → ``(u, 0, v)``; ``YZ`` → ``(0, u, v)``.
    """
    p = plane.upper()
    if p == "XY":
        return (u, v, 0.0)
    if p == "XZ":
        return (u, 0.0, v)
    if p == "YZ":
        return (0.0, u, v)
    raise ValueError(f"plane must be one of XY/XZ/YZ, got {plane!r}")


def grid_translations(
    rows: int,
    cols: int,
    *,
    pitch: float,
    row_pitch: float | None = None,
    plane: str = "XY",
    center: bool = False,
) -> list[Vec3]:
    """World translations for a ``rows × cols`` regular grid of part slots.

    Slot ``(i, j)`` (row ``i``, column ``j``) sits at in-plane coordinates
    ``(j · pitch, i · row_pitch)`` — column index drives the ``u`` axis, row index
    the ``v`` axis. ``row_pitch`` defaults to ``pitch`` (square grid). The list is
    row-major: ``[(0,0), (0,1), …, (0,cols-1), (1,0), …]``, so ``len`` is exactly
    ``rows · cols``.

    With ``center=True`` the grid is centred on the origin (the mean of the slots
    is the origin); otherwise slot ``(0, 0)`` is at the origin. Raises
    ``ValueError`` on a non-positive dimension or pitch.
    """
    if rows <= 0 or cols <= 0:
        raise ValueError(f"rows and cols must be positive, got {rows}×{cols}")
    if pitch <= 0:
        raise ValueError(f"pitch must be positive, got {pitch}")
    rp = pitch if row_pitch is None else row_pitch
    if rp <= 0:
        raise ValueError(f"row_pitch must be positive, got {rp}")

    u0 = (cols - 1) / 2.0 * pitch if center else 0.0
    v0 = (rows - 1) / 2.0 * rp if center else 0.0
    out: list[Vec3] = []
    for i in range(rows):
        for j in range(cols):
            out.append(_embed(j * pitch - u0, i * rp - v0, plane))
    return out


def ring_translations(
    n: int,
    *,
    radius: float,
    plane: str = "XY",
    start_angle_deg: float = 0.0,
    center: Vec3 = (0.0, 0.0, 0.0),
) -> list[Vec3]:
    """World translations for ``n`` slots evenly spaced on a ring.

    Slot ``k`` sits at in-plane angle ``start_angle_deg + k · 360°/n`` on a circle
    of ``radius`` about ``center``: ``(radius·cos θ, radius·sin θ)`` embedded in the
    plane, then offset by ``center``. The list is in increasing-``k`` order, so the
    angular step between consecutive slots is exactly ``360°/n`` and ``len`` is
    ``n``. Raises ``ValueError`` on a non-positive ``n`` or radius.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if radius <= 0:
        raise ValueError(f"radius must be positive, got {radius}")

    cx, cy, cz = center
    start = math.radians(start_angle_deg)
    out: list[Vec3] = []
    for k in range(n):
        theta = start + 2.0 * math.pi * k / n
        u = radius * math.cos(theta)
        v = radius * math.sin(theta)
        x, y, z = _embed(u, v, plane)
        out.append((x + cx, y + cy, z + cz))
    return out
