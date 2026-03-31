"""
bp_indexing — helix base-pair coordinate conversion utilities.

Centralises the ``stored ↔ global`` bp conversion so that all modules that
need to reason about helix bp coordinates share one source of truth.

Three helix bp conventions exist in NADOC:

- **native**   : ``bp_start=0``,              ``length_bp=active_count``
- **caDNAno**  : ``bp_start=first_active``,   ``length_bp=full_array_length``
- **hybrid**   : ``bp_start=first_active``,   ``length_bp=active_count``

``stored`` bp index
    The value stored in ``Domain.start_bp`` / ``Domain.end_bp`` and in
    ``Helix.loop_skips[*].bp_index``.

``global`` bp index
    The physical axial position (0 = the logical origin of the design
    coordinate system).  Independent of which helix or convention is used.

Relationship::

    global = stored − helix.bp_start + geo_start
    stored = global − geo_start       + helix.bp_start

where ``geo_start = get_helix_geo_bp_start(helix)``.

For **native** and **caDNAno** helices ``geo_start == helix.bp_start``,
so ``stored == global``.  For **hybrid** helices (``bp_start > 0`` AND
``axis_start.z > 0``), the two diverge and the conversion is non-trivial.

This divergence was the root cause of the auto-crossover bug for hybrid
helices reported in 2026-03.
"""

from __future__ import annotations

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Helix


def get_helix_bp_count(helix: Helix) -> int:
    """Active bp count derived from axis geometry.

    Works correctly for all three helix conventions:

    - native  (``bp_start=0``,  ``length_bp=active_count``)
    - caDNAno (``bp_start=first_active``, ``length_bp=full_array_length``)
    - hybrid  (``bp_start=first_active``, ``length_bp=active_count``)

    The formula ``length_bp - bp_start`` gives the wrong count for hybrid
    helices.  The axis vector always spans exactly the active bp range, so
    rounding its length gives the correct count regardless of storage
    convention.
    """
    ax = np.array([
        helix.axis_end.x - helix.axis_start.x,
        helix.axis_end.y - helix.axis_start.y,
        helix.axis_end.z - helix.axis_start.z,
    ], dtype=float)
    return round(float(np.linalg.norm(ax)) / BDNA_RISE_PER_BP)


def get_helix_geo_bp_start(helix: Helix) -> int:
    """Return the global bp index at which this helix's ``axis_start`` resides.

    For **caDNAno-imported** helices ``axis_start.z == bp_start * RISE``, so
    this returns ``helix.bp_start`` (consistent with the stored field).

    For **native continuation** helices ``bp_start`` is always 0 but
    ``axis_start.z`` may be non-zero (e.g. 14.028 nm for a helix beginning at
    bp 42).  This function derives the correct geometric offset from the axis
    direction vector, so two helices with different physical starting positions
    get different effective bp starts even when both store ``bp_start=0``.
    """
    ax = np.array([
        helix.axis_end.x - helix.axis_start.x,
        helix.axis_end.y - helix.axis_start.y,
        helix.axis_end.z - helix.axis_start.z,
    ], dtype=float)
    length = float(np.linalg.norm(ax))
    if length < 1e-12:
        return helix.bp_start
    hat = ax / length
    start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z], dtype=float)
    return round(float(np.dot(start, hat)) / BDNA_RISE_PER_BP)


def global_to_stored_bp(helix: Helix, global_bp: int, geo_start: int | None = None) -> int:
    """Convert a physical global bp index to the helix's stored bp index.

    ``stored = global − geo_start + helix.bp_start``

    Pass a pre-computed ``geo_start`` (from :func:`get_helix_geo_bp_start`) to
    avoid recomputing it on every call inside a tight loop.
    """
    if geo_start is None:
        geo_start = get_helix_geo_bp_start(helix)
    return global_bp - geo_start + helix.bp_start


def stored_to_global_bp(helix: Helix, stored_bp: int, geo_start: int | None = None) -> int:
    """Convert a helix's stored bp index to a physical global bp index.

    ``global = stored − helix.bp_start + geo_start``

    Pass a pre-computed ``geo_start`` (from :func:`get_helix_geo_bp_start`) to
    avoid recomputing it on every call inside a tight loop.
    """
    if geo_start is None:
        geo_start = get_helix_geo_bp_start(helix)
    return stored_bp - helix.bp_start + geo_start
