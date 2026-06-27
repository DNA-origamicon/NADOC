"""Pure ssDNA flexible-relax solver — backend/core/flexible_relax.py.

Pins (1) the position-based-dynamics solver's correctness (an overstretched
tether is pulled to its contour) and (2) JS↔Python PARITY: the Python solver
reproduces the golden the vitest ``flexible_relax_solver.test.js`` produces from
the SAME fixture, so a headless relax matches the in-app one. The orchestration
+ headless wrapper + the contour-constraint oracle are exercised in
``test_headless_build.py`` / ``test_automation_harness.py``.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.flexible_relax import relax_cluster_pose

# Shared parity fixtures + goldens — IDENTICAL to flexible_relax_solver.test.js.
_PIVOT = [0.0, 0.0, 0.0]

# Asymmetric two-tether case → engages the rotation pass.
_ARMED_ROT = [
    ([5.0, 3.0, 0.0], [0.0, 3.0, 0.0], 2.0),
    ([5.0, -1.0, 0.0], [0.0, -1.0, 0.0], 2.0),
]
_GOLDEN_ROT_POS = [-3.012416081, -0.03970986, 0.0]
_GOLDEN_ROT_QUAT = [0.0, 0.0, 0.006411506, 0.999979446]

# Single-tether case → translate-only.
_ARMED_TRANS = [([5.0, 0.0, 0.0], [0.0, 0.0, 0.0], 3.0)]


def test_parity_rotation_case_matches_js_golden():
    """The asymmetric two-tether relax reproduces the JS solver's pose to 1e-6
    (the JS↔Python parity pin — headless == in-app)."""
    tr, rot, residual, moved = relax_cluster_pose(
        _PIVOT, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], _ARMED_ROT, translate_only=False
    )
    assert moved
    assert residual < 0.05
    np.testing.assert_allclose(tr, _GOLDEN_ROT_POS, atol=1e-6)
    # Compare rotations (quaternion sign is gauge — compare the rotation itself).
    delta = (Rotation.from_quat(rot) * Rotation.from_quat(_GOLDEN_ROT_QUAT).inv()).magnitude()
    assert delta < 1e-6, f"rotation diverged from JS golden by {delta} rad"
    # The rotation pass actually fired (not a pure translation).
    assert abs(rot[2]) > 1e-3 or Rotation.from_quat(rot).magnitude() > 1e-3


def test_parity_translate_only_matches_js_golden():
    """A single overstretched tether slides to its contour with no rotation —
    same as the JS translate-only golden."""
    tr, rot, residual, moved = relax_cluster_pose(
        _PIVOT, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], _ARMED_TRANS, translate_only=True
    )
    assert moved
    assert abs(tr[0] + 2.0) < 1e-3  # 5 → 3 via a −2 slide along x
    assert Rotation.from_quat(rot).magnitude() < 1e-9  # no rotation
    # Moved anchor lands on the contour sphere.
    chord = float(np.linalg.norm(np.array([5.0, 0, 0]) + np.array(tr) - np.array([0.0, 0, 0])))
    assert abs(chord - 3.0) < 1e-3


def test_solver_is_noop_when_not_overstretched():
    """A tether already within contour → the solver reports no move and returns
    the input transform unchanged (the can't-go-red-vacuously guard for callers)."""
    tr, rot, residual, moved = relax_cluster_pose(
        _PIVOT, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0],
        [([1.0, 0.0, 0.0], [0.0, 0.0, 0.0], 3.0)], translate_only=False,
    )
    assert not moved
    assert tr == [0.0, 0.0, 0.0]
    assert rot == [0.0, 0.0, 0.0, 1.0]
    assert residual < 1e-9  # nothing overstretched


def test_solver_respects_pivot_for_rotation():
    """Rotation is about the supplied pivot, not the origin — a nonzero pivot
    shifts the solved translation (the door-jamb hinge centre)."""
    tr0, _r0, _res0, _m0 = relax_cluster_pose(
        _PIVOT, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], _ARMED_ROT, translate_only=False
    )
    tr1, _r1, _res1, _m1 = relax_cluster_pose(
        [2.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], _ARMED_ROT, translate_only=False
    )
    # Different pivot → different solved pose (rotation centre moved).
    assert not np.allclose(tr0, tr1, atol=1e-3)
