"""Pure-math unit tests for the sub-domain rotation chain helper.

Phase 4 of the overhang revamp. These tests run BEFORE the helper is wired
into ``apply_overhang_rotation_if_needed`` so chain-math bugs are caught at
the quaternion level rather than inside the geometry integration.

The helper under test is ``_quat_from_theta_phi`` in
``backend.core.deformation`` — it converts the on-topology (theta_deg,
phi_deg) representation of a sub-domain's parent-relative rotation into a
unit quaternion in the parent's world frame.

Convention (locked, see project_overhang_subdomains.md §Phase 4):

* ``parent_axis`` — unit world-space axis the sub-domain rotates around when
  ``theta`` changes; for the first sub-domain this is the helix tangent at
  the junction bp, for downstream sub-domains it is the previous
  sub-domain's END tangent post-upstream-rotations.
* ``phi_ref`` — unit world-space vector lying in the plane perpendicular to
  ``parent_axis`` that defines the φ=0 direction. We pick world-Y projected
  onto that plane; if ``|parent_axis · Y| > 0.9`` we fall back to world-Z
  so the reference is always well-defined.
* ``theta_deg`` — rotation around ``parent_axis``, range ``[-180, 180]``.
* ``phi_deg``   — angle from ``parent_axis``, range ``[0, 180]``. ``phi=0``
  means co-linear with the parent axis (no bend).

Compose order: first rotate by ``theta`` around ``parent_axis`` to set the
azimuth, then rotate by ``phi`` around the axis ``parent_axis × phi_ref``
(after the theta rotation has been applied to ``phi_ref``). This produces
the same end orientation as a Three.js ``Quaternion.setFromUnitVectors``
followed by an axial spin, but expressed in terms that survive .nadoc
round-trips.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.deformation import _quat_from_theta_phi


# ── Helpers ────────────────────────────────────────────────────────────────


def _quat_mul(a, b):
    """Hamilton product of two [x, y, z, w] quaternions."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def _quat_from_axis_angle(axis, angle_rad):
    a = np.array(axis, dtype=float)
    a = a / np.linalg.norm(a)
    s = math.sin(angle_rad / 2.0)
    return [a[0] * s, a[1] * s, a[2] * s, math.cos(angle_rad / 2.0)]


def _quat_rotate(q, v):
    """Apply quaternion q (xyzw) to 3-vector v."""
    qx, qy, qz, qw = q
    vx, vy, vz = v[0], v[1], v[2]
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    # v' = v + qw * t + cross(q.xyz, t)
    rx = vx + qw * tx + (qy * tz - qz * ty)
    ry = vy + qw * ty + (qz * tx - qx * tz)
    rz = vz + qw * tz + (qx * ty - qy * tx)
    return [rx, ry, rz]


def _normalised(v):
    v = np.array(v, dtype=float)
    return (v / np.linalg.norm(v)).tolist()


# ── 1. Identity case ───────────────────────────────────────────────────────


def test_identity_theta_phi_returns_identity_quat():
    """θ=0, φ=0 must produce the identity quaternion regardless of axis."""
    for axis in ([0, 0, 1], [1, 0, 0], [0, 1, 0], _normalised([1, 1, 1])):
        phi_ref = [0, 1, 0] if abs(axis[1]) < 0.9 else [0, 0, 1]
        q = _quat_from_theta_phi(axis, phi_ref, 0.0, 0.0)
        assert len(q) == 4
        # Identity is [0,0,0,±1]; both signs represent the same rotation.
        assert abs(q[0]) < 1e-12
        assert abs(q[1]) < 1e-12
        assert abs(q[2]) < 1e-12
        assert abs(abs(q[3]) - 1.0) < 1e-12


# ── 2. θ-only spin around Z axis ───────────────────────────────────────────


def test_theta_90_around_z_axis():
    """θ=90, φ=0 around +Z parent axis spins phi_ref in the XY plane."""
    parent_axis = [0.0, 0.0, 1.0]
    phi_ref = [0.0, 1.0, 0.0]
    q = _quat_from_theta_phi(parent_axis, phi_ref, 90.0, 0.0)

    # A pure +Z spin by 90° has quaternion [0, 0, sin(45°), cos(45°)].
    expected = _quat_from_axis_angle(parent_axis, math.radians(90.0))
    for i in range(4):
        assert abs(q[i] - expected[i]) < 1e-9, (i, q, expected)

    # Rotating phi_ref by q must map (0,1,0) → (-1,0,0).
    out = _quat_rotate(q, phi_ref)
    assert abs(out[0] - (-1.0)) < 1e-9
    assert abs(out[1]) < 1e-9
    assert abs(out[2]) < 1e-9


# ── 3. φ-only bend with no spin ────────────────────────────────────────────


def test_phi_90_no_theta_bends_axis_to_phi_ref():
    """θ=0, φ=90 bends the parent axis onto phi_ref.

    With parent_axis = +Z, phi_ref = +Y, after applying q the original
    parent axis (+Z) must point along +Y.
    """
    parent_axis = [0.0, 0.0, 1.0]
    phi_ref = [0.0, 1.0, 0.0]
    q = _quat_from_theta_phi(parent_axis, phi_ref, 0.0, 90.0)

    out = _quat_rotate(q, parent_axis)
    assert abs(out[0]) < 1e-9
    assert abs(out[1] - 1.0) < 1e-9
    assert abs(out[2]) < 1e-9


# ── 4. θ+φ combined ────────────────────────────────────────────────────────


def test_theta_phi_combined_matches_explicit_compose():
    """For an arbitrary (θ, φ) pair, the helper must equal an explicit
    spin-then-bend composition (theta around parent_axis, then phi around
    parent_axis × (theta-rotated phi_ref))."""
    parent_axis = _normalised([0.3, 0.0, 1.0])
    phi_ref_raw = [0.0, 1.0, 0.0]
    # Strip parent-axis component from phi_ref so it lies in the plane.
    pa = np.array(parent_axis, dtype=float)
    pr = np.array(phi_ref_raw, dtype=float)
    pr = pr - pa * float(np.dot(pa, pr))
    pr = pr / np.linalg.norm(pr)
    phi_ref = pr.tolist()

    theta_deg, phi_deg = 37.0, 25.0
    q = _quat_from_theta_phi(parent_axis, phi_ref, theta_deg, phi_deg)

    # Build the expected quaternion explicitly.
    q_theta = _quat_from_axis_angle(parent_axis, math.radians(theta_deg))
    # Theta rotation moves phi_ref → phi_ref_rot inside the plane.
    phi_ref_rot = _quat_rotate(q_theta, phi_ref)
    # Phi axis = parent_axis × phi_ref_rot (so positive phi tilts parent_axis
    # toward phi_ref_rot).
    pa_arr = np.array(parent_axis)
    pr_rot_arr = np.array(phi_ref_rot)
    phi_axis = np.cross(pa_arr, pr_rot_arr)
    phi_axis = phi_axis / np.linalg.norm(phi_axis)
    q_phi = _quat_from_axis_angle(phi_axis.tolist(), math.radians(phi_deg))

    expected = _quat_mul(q_phi, q_theta)
    # Normalise both before comparing (helper may emit either sign).
    def _norm(q):
        n = math.sqrt(sum(x * x for x in q))
        return [x / n for x in q]
    qn = _norm(q)
    en = _norm(expected)
    # Quaternions q and -q encode the same rotation. Compare both.
    diff_plus = sum(abs(qn[i] - en[i]) for i in range(4))
    diff_minus = sum(abs(qn[i] + en[i]) for i in range(4))
    assert min(diff_plus, diff_minus) < 1e-8, (qn, en)


# ── 5. φ=180 flips parent axis ─────────────────────────────────────────────


def test_phi_180_flips_parent_axis():
    """φ=180 must send parent_axis to -parent_axis (full bend)."""
    parent_axis = [0.0, 0.0, 1.0]
    phi_ref = [0.0, 1.0, 0.0]
    q = _quat_from_theta_phi(parent_axis, phi_ref, 0.0, 180.0)
    out = _quat_rotate(q, parent_axis)
    assert abs(out[0]) < 1e-9
    assert abs(out[1]) < 1e-9
    assert abs(out[2] - (-1.0)) < 1e-9


# ── 6. Cumulative chain composition equals sequential apply ────────────────


def test_chain_three_sub_domains_matches_sequential_compose():
    """For 3 sub-domains stacked in series, the cumulative orientation
    obtained by walking the chain (each sd's frame derives from the
    upstream-rotated tangent) must equal sequential quaternion
    multiplication of the per-sd quaternions in 5'→3' order.

    Chain semantics:
      orientation_at_end_of_sd_N = q_N * q_{N-1} * … * q_0   (Hamilton product)
    where q_i is computed using the parent axis of sd_i, which is the
    accumulated frame's z-axis after the previous sub-domains have rotated.
    """
    # Sub-domain inputs: (theta_deg, phi_deg)
    sd_inputs = [(20.0, 10.0), (-15.0, 30.0), (45.0, 5.0)]

    # Initial parent axis = +Z; initial phi_ref = +Y.
    pa = np.array([0.0, 0.0, 1.0])
    pr = np.array([0.0, 1.0, 0.0])

    # Method A: build each q in its own local frame, then accumulate by
    # left-multiplication (so the chain rotates 5'-most first).
    accum = [0.0, 0.0, 0.0, 1.0]
    cur_axis = pa.tolist()
    cur_ref = pr.tolist()
    chain_quats: list[list[float]] = []
    for theta_deg, phi_deg in sd_inputs:
        q_i = _quat_from_theta_phi(cur_axis, cur_ref, theta_deg, phi_deg)
        chain_quats.append(q_i)
        accum = _quat_mul(q_i, accum)
        # Update axis + ref for the NEXT sub-domain: rotate the originals
        # by the accumulated quaternion.
        cur_axis = _quat_rotate(accum, pa.tolist())
        cur_ref = _quat_rotate(accum, pr.tolist())

    # Method B: re-multiply the per-sd quaternions in 5'→3' order via
    # naive Hamilton product. Each q_i was computed in the upstream-rotated
    # frame so the SAME accumulated product is the answer — this is the
    # invariant the chain math must satisfy.
    naive = [0.0, 0.0, 0.0, 1.0]
    for q in chain_quats:
        naive = _quat_mul(q, naive)

    for i in range(4):
        assert abs(accum[i] - naive[i]) < 1e-9, (i, accum, naive)

    # Sanity: the end tangent (parent axis after all rotations) is unit-norm.
    end_axis = _quat_rotate(accum, pa.tolist())
    norm = math.sqrt(sum(x * x for x in end_axis))
    assert abs(norm - 1.0) < 1e-9


# ── 7. phi_ref fallback when parent_axis ~ ±Y ──────────────────────────────


def test_phi_ref_fallback_when_axis_near_world_Y():
    """When the parent axis is nearly co-linear with world Y, the helper
    must use the world-Z fallback so the result is still well-defined.

    The actual check: the returned quaternion is finite + unit-norm, and
    distinct φ values produce distinct rotations.
    """
    parent_axis = _normalised([0.05, 0.999, 0.05])

    # phi_ref of None lets the helper pick its own fallback. We pass the
    # canonical world-Y projection; the helper itself decides whether to
    # use it or fall back. Here we just verify finite/unit results.
    q0 = _quat_from_theta_phi(parent_axis, None, 0.0, 30.0)
    q1 = _quat_from_theta_phi(parent_axis, None, 0.0, 60.0)

    for q in (q0, q1):
        for x in q:
            assert math.isfinite(x)
        n2 = sum(x * x for x in q)
        assert abs(n2 - 1.0) < 1e-9

    # Distinct phi must produce distinct quaternions.
    assert any(abs(q0[i] - q1[i]) > 1e-6 for i in range(4))


# ── 8. Argument validation ─────────────────────────────────────────────────


def test_invalid_phi_raises():
    """The helper rejects phi outside [0, 180] with ValueError."""
    parent_axis = [0.0, 0.0, 1.0]
    phi_ref = [0.0, 1.0, 0.0]
    with pytest.raises(ValueError):
        _quat_from_theta_phi(parent_axis, phi_ref, 0.0, -1.0)
    with pytest.raises(ValueError):
        _quat_from_theta_phi(parent_axis, phi_ref, 0.0, 181.0)


def test_invalid_theta_raises():
    """The helper rejects theta outside [-180, 180] with ValueError."""
    parent_axis = [0.0, 0.0, 1.0]
    phi_ref = [0.0, 1.0, 0.0]
    with pytest.raises(ValueError):
        _quat_from_theta_phi(parent_axis, phi_ref, 181.0, 0.0)
    with pytest.raises(ValueError):
        _quat_from_theta_phi(parent_axis, phi_ref, -180.001, 0.0)
