"""Regression: a deformed-continuation segment placed at a BENT end must keep its
stored 3D pose — the geometry pipeline must NOT canonicalise it back to a straight
axis-along-+Z lattice helix.

Bug (2026-06-11): placing a primitive (e.g. an 18hb) onto a bent end produced fresh
helices whose ids match ``h_XY_{r}_{c}`` → ``grid_pos`` got back-filled →
``_normalize_helix_for_grid`` rewrote their axis to straight-+Z → the active bend then
re-applied on top, collapsing the whole bundle onto a single 45° sheet. (The
continuation helices, whose ids carry a ``_N`` suffix → ``grid_pos`` stays None, were
correct, which is why only the fresh part collapsed.)
"""

from __future__ import annotations

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.deformation import _normalize_helix_for_grid
from backend.core.models import Helix, LatticeType, Vec3


def _helix(hid, gp, bp_start, length, start, end):
    return Helix(id=hid, grid_pos=gp, bp_start=bp_start, length_bp=length,
                 axis_start=Vec3(x=start[0], y=start[1], z=start[2]),
                 axis_end=Vec3(x=end[0], y=end[1], z=end[2]))


def test_normalize_canonicalises_a_straight_lattice_helix():
    """A normal lattice helix (axis straight along +Z at the bp-derived Z) normalises:
    its Z is rewritten from the bp range, unchanged here because it's already canonical."""
    z_end = 42 * BDNA_RISE_PER_BP
    h = _helix("h_XY_0_2", (0, 2), 0, 42, (3.9, 0.0, 0.0), (3.9, 0.0, z_end))
    n = _normalize_helix_for_grid(h, LatticeType.HONEYCOMB)
    assert abs(n.axis_start.z - 0.0) < 1e-6
    assert abs(n.axis_end.z - z_end) < 1e-6
    # Lattice XY preserved (re-centering safe).
    assert (n.axis_start.x, n.axis_start.y) == (3.9, 0.0)


def test_normalize_preserves_a_freeform_posed_helix():
    """A deformed-continuation segment at a bent end (axis along +X, non-canonical Z,
    grid_pos back-filled from its id) must be returned UNCHANGED — its pose is authoritative."""
    h = _helix("h_XY_2_2", (2, 2), 234, 42, (78.2, 6.8, 86.7), (92.2, 6.8, 86.7))
    assert h.grid_pos == (2, 2)  # back-filled from the id, despite the bent pose
    n = _normalize_helix_for_grid(h, LatticeType.HONEYCOMB)
    assert (n.axis_start.x, n.axis_start.y, n.axis_start.z) == (78.2, 6.8, 86.7)
    assert (n.axis_end.x, n.axis_end.y, n.axis_end.z) == (92.2, 6.8, 86.7)


def test_soup_fixture_bent_primitive_is_not_collapsed():
    """End-to-end on the reported file: the 18 placed helices form a 2D cross-section
    (a honeycomb disc), not a collapsed 1-D 45° sheet."""
    import json
    from pathlib import Path

    import numpy as np

    from backend.core.deformation import deformed_helix_axes
    from backend.core.models import Design

    path = Path("workspace/soup.nadoc")
    if not path.exists():
        import pytest
        pytest.skip("soup.nadoc fixture not present")

    d = Design.model_validate(json.loads(path.read_text()))
    axes = {a["helix_id"]: a for a in deformed_helix_axes(d)}
    fresh_cells = {(2, 2), (2, 1), (3, 1), (3, 2), (3, 3), (2, 3),
                   (2, 4), (2, 5), (2, 6), (1, 6), (1, 5), (1, 4)}
    placed = [h for h in d.helices
              if h.id.endswith("_0") or (h.grid_pos and tuple(h.grid_pos) in fresh_cells)]
    starts = np.array([axes[h.id]["start"] for h in placed])
    # Cross-section spans 2 dimensions (y and z) → a real bundle, not a line.
    assert np.ptp(starts[:, 1]) > 4.0, "cross-section collapsed in y"
    assert np.ptp(starts[:, 2]) > 4.0, "cross-section collapsed in z (the 45° collapse bug)"
    # Every placed helix runs along +X (the bent axis), not along Z.
    for h in placed:
        a = axes[h.id]
        assert abs(a["end"][0] - a["start"][0]) > 5.0, f"{h.id} not along the bent axis"
