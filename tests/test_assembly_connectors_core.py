"""Direct input->output unit tests for backend.core.assembly_connectors.

These pin the connector-frame resolution kernel lifted out of
backend/api/assembly.py (carve-up Refactor #12). The module is pure (api-free):
given a PartInstance + connector label (+ optional Design), it resolves the
connector's local/world SE3 frame or bare world position.

The real cluster-aware "live geometry" path (blunt:/seam0: labels through
deformed_helix_axes) is exercised by the existing assembly route/integration
tests; these unit tests pin the label-parsing guards and the
manual-connector fallback math (T_inst @ ip.position), which is the adapted
surface (the only edit in the lift was _mat4_from_model(x) -> x.to_array(),
provably identical: both compute np.array(values, dtype=float).reshape(4, 4)).
"""

import numpy as np
import pytest

from backend.core.assembly_connectors import (
    _build_connector_frames,
    _build_frame_from_normal,
    _build_world_connector_frames,
    _enforce_connector_coincidence,
    _get_connector_world,
    _get_connector_world_frame,
    _local_frame_for_label,
    _refresh_connector_frames_for_instance,
    _resolve_blunt_label_local,
    _resolve_live_connector_local,
    _resolve_seam_label_local,
)
from backend.core.models import (
    AssemblyJoint,
    ConnectionType,
    Design,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartSourceInline,
    Vec3,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _ip(label, pos, normal=(0.0, 0.0, 1.0)):
    return InterfacePoint(
        label=label,
        position=Vec3(x=pos[0], y=pos[1], z=pos[2]),
        normal=Vec3(x=normal[0], y=normal[1], z=normal[2]),
        connection_type=ConnectionType.BLUNT_END,
    )


def _instance(ips, transform=None):
    src = PartSourceInline(design=Design())
    kw = {"source": src, "interface_points": ips}
    if transform is not None:
        kw["transform"] = transform
    return PartInstance(**kw)


def _translation(dx, dy, dz):
    """Row-major 4x4 pure-translation Mat4x4."""
    m = np.eye(4, dtype=float)
    m[:3, 3] = (dx, dy, dz)
    return Mat4x4.from_array(m)


# ── _build_frame_from_normal ────────────────────────────────────────────────


def test_build_frame_from_normal_is_orthonormal_with_z_along_normal():
    F = _build_frame_from_normal(np.array([1.0, 2.0, 3.0]), np.array([0.0, 0.0, 5.0]))
    assert F is not None
    R = F[:3, :3]
    # columns unit-length + mutually orthogonal
    np.testing.assert_allclose(np.linalg.norm(R, axis=0), [1, 1, 1], atol=1e-9)
    np.testing.assert_allclose(R.T @ R, np.eye(3), atol=1e-9)
    # Z axis == unit normal
    np.testing.assert_allclose(R[:, 2], [0, 0, 1], atol=1e-9)
    # right-handed
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)
    # translation == position
    np.testing.assert_allclose(F[:3, 3], [1, 2, 3], atol=1e-9)


def test_build_frame_from_normal_picks_fallback_ref_when_normal_parallel_to_y():
    # normal nearly +Y triggers the +X reference branch; still orthonormal
    F = _build_frame_from_normal(np.zeros(3), np.array([0.0, 1.0, 0.0]))
    assert F is not None
    R = F[:3, :3]
    np.testing.assert_allclose(R.T @ R, np.eye(3), atol=1e-9)
    np.testing.assert_allclose(R[:, 2], [0, 1, 0], atol=1e-9)


def test_build_frame_from_normal_degenerate_normal_returns_none():
    assert _build_frame_from_normal(np.zeros(3), np.array([0.0, 0.0, 0.0])) is None


# ── label-resolution guards (None paths) ──────────────────────────────────────


def test_resolve_blunt_label_local_rejects_non_blunt_labels():
    d = Design()
    assert _resolve_blunt_label_local(d, "C1") is None
    assert _resolve_blunt_label_local(d, "") is None
    assert _resolve_blunt_label_local(d, "blunt:onlytwo") is None  # missing bp spec


def test_resolve_seam_label_local_rejects_non_seam_and_bad_side():
    d = Design()
    assert _resolve_seam_label_local(d, "C1") is None
    assert _resolve_seam_label_local(d, "seam0:nope") is None  # side not 5p/3p
    assert _resolve_seam_label_local(d, "seam1:5p") is None  # only seam0 synthesized


def test_resolve_live_connector_local_none_for_manual_label():
    # neither blunt: nor seam0: -> caller falls back to stored ip.position
    assert _resolve_live_connector_local(Design(), "C1") is None


# ── _get_connector_world (design=None -> T @ ip.position fallback) ─────────────


def test_get_connector_world_applies_instance_translation():
    inst = _instance(
        [_ip("C1", (1.0, 0.0, 0.0))], transform=_translation(10.0, 20.0, 30.0)
    )
    world = _get_connector_world(inst, "C1", design=None)
    np.testing.assert_allclose(world, [11.0, 20.0, 30.0], atol=1e-9)


def test_get_connector_world_unknown_label_returns_none():
    inst = _instance([_ip("C1", (1.0, 0.0, 0.0))])
    assert _get_connector_world(inst, "DOES_NOT_EXIST", design=None) is None


# ── _get_connector_world_frame (design=None fallback) ──────────────────────────


def test_get_connector_world_frame_translation_matches_world_position():
    inst = _instance(
        [_ip("C1", (1.0, 2.0, 3.0))], transform=_translation(5.0, 0.0, 0.0)
    )
    F = _get_connector_world_frame(inst, "C1", design=None)
    assert F is not None and F.shape == (4, 4)
    pos = _get_connector_world(inst, "C1", design=None)
    np.testing.assert_allclose(F[:3, 3], pos, atol=1e-9)
    # rotation block orthonormal (frame built from the connector normal)
    np.testing.assert_allclose(F[:3, :3].T @ F[:3, :3], np.eye(3), atol=1e-9)


def test_get_connector_world_frame_unknown_label_returns_none():
    inst = _instance([_ip("C1", (0.0, 0.0, 0.0))])
    assert _get_connector_world_frame(inst, "nope", design=None) is None


# ── _local_frame_for_label (design=None) ───────────────────────────────────────


def test_local_frame_for_label_is_instance_local():
    inst = _instance(
        [_ip("C1", (1.0, 2.0, 3.0))], transform=_translation(99.0, 99.0, 99.0)
    )
    F = _local_frame_for_label(inst, "C1", None)
    assert F is not None
    # local frame ignores the instance world transform: translation == local pos
    np.testing.assert_allclose(F[:3, 3], [1.0, 2.0, 3.0], atol=1e-9)


def test_local_frame_for_label_unknown_returns_none():
    inst = _instance([_ip("C1", (0.0, 0.0, 0.0))])
    assert _local_frame_for_label(inst, "missing", None) is None


# ── _build_world_connector_frames + caching ────────────────────────────────────


def test_build_world_connector_frames_keys_and_positions():
    inst = _instance(
        [_ip("C1", (1.0, 0.0, 0.0))], transform=_translation(0.0, 7.0, 0.0)
    )
    inst_by_id = {inst.id: inst}
    labels_by_inst = {inst.id: {"C1"}}
    frames, local_cache = _build_world_connector_frames(
        inst_by_id, labels_by_inst, lambda i: None
    )
    assert (inst.id, "C1") in frames
    np.testing.assert_allclose(
        frames[(inst.id, "C1")][:3, 3], [1.0, 7.0, 0.0], atol=1e-9
    )
    # local frames cached by (design_key, label); design_for returned None -> key 0
    assert (0, "C1") in local_cache


def test_build_world_connector_frames_skips_missing_instance():
    frames, _ = _build_world_connector_frames({}, {"ghost": {"C1"}}, lambda i: None)
    assert frames == {}


# ── _build_connector_frames (collects labels from joints) ──────────────────────


def test_build_connector_frames_collects_both_joint_sides():
    a = _instance([_ip("CA", (1.0, 0.0, 0.0))])
    b = _instance([_ip("CB", (0.0, 1.0, 0.0))])
    joint = AssemblyJoint(
        instance_a_id=a.id,
        connector_a_label="CA",
        instance_b_id=b.id,
        connector_b_label="CB",
    )

    class _Asm:
        joints = [joint]

    inst_by_id = {a.id: a, b.id: b}
    frames, labels_by_inst, _cache = _build_connector_frames(
        _Asm(), inst_by_id, lambda i: None
    )
    assert labels_by_inst[a.id] == {"CA"}
    assert labels_by_inst[b.id] == {"CB"}
    assert (a.id, "CA") in frames
    assert (b.id, "CB") in frames


# ── _refresh_connector_frames_for_instance ─────────────────────────────────────


def test_refresh_updates_world_frame_after_move():
    inst = _instance(
        [_ip("C1", (1.0, 0.0, 0.0))], transform=_translation(0.0, 0.0, 0.0)
    )
    inst_by_id = {inst.id: inst}
    labels_by_inst = {inst.id: {"C1"}}
    frames, local_cache = _build_world_connector_frames(
        inst_by_id, labels_by_inst, lambda i: None
    )
    np.testing.assert_allclose(
        frames[(inst.id, "C1")][:3, 3], [1.0, 0.0, 0.0], atol=1e-9
    )

    # move the instance, then refresh -> world frame tracks the new transform
    inst.transform = _translation(100.0, 0.0, 0.0)
    _refresh_connector_frames_for_instance(
        frames, labels_by_inst, inst_by_id, inst.id, lambda i: None, local_cache
    )
    np.testing.assert_allclose(
        frames[(inst.id, "C1")][:3, 3], [101.0, 0.0, 0.0], atol=1e-9
    )


def test_refresh_drops_entries_for_vanished_instance():
    inst = _instance([_ip("C1", (1.0, 0.0, 0.0))])
    inst_by_id = {inst.id: inst}
    labels_by_inst = {inst.id: {"C1"}}
    frames, local_cache = _build_world_connector_frames(
        inst_by_id, labels_by_inst, lambda i: None
    )
    assert (inst.id, "C1") in frames
    # instance no longer in the lookup -> its frame entries are popped
    _refresh_connector_frames_for_instance(
        frames, labels_by_inst, {}, inst.id, lambda i: None, local_cache
    )
    assert (inst.id, "C1") not in frames


# ── _enforce_connector_coincidence (graph-mutation write twin) ─────────────────


class _Asm:
    """Minimal stand-in for an Assembly: _enforce_connector_coincidence only
    reads .joints and (via _build_inst_by_id) .instances."""

    def __init__(self, instances, joints):
        self.instances = instances
        self.joints = joints


def _mate(a, ca, b, cb, joint_type="rigid"):
    return AssemblyJoint(
        joint_type=joint_type,
        instance_a_id=a.id,
        connector_a_label=ca,
        instance_b_id=b.id,
        connector_b_label=cb,
    )


def test_enforce_snaps_drifted_child_onto_parent_connector():
    # parent CA at world origin; child CB drifted to world (5,0,0).
    a = _instance([_ip("CA", (0.0, 0.0, 0.0))], transform=_translation(0.0, 0.0, 0.0))
    b = _instance([_ip("CB", (0.0, 0.0, 0.0))], transform=_translation(5.0, 0.0, 0.0))
    joint = _mate(a, "CA", b, "CB")
    asm = _Asm([a, b], [joint])

    _enforce_connector_coincidence(asm, visited={b.id})

    # child snapped so CB now coincides with CA at the origin
    cb = _get_connector_world(b, "CB")
    np.testing.assert_allclose(cb, [0.0, 0.0, 0.0], atol=1e-9)
    np.testing.assert_allclose(
        b.transform.to_array()[:3, 3], [0.0, 0.0, 0.0], atol=1e-9
    )
    # axis_origin synced to the parent connector world position
    np.testing.assert_allclose(joint.axis_origin, [0.0, 0.0, 0.0], atol=1e-9)


def test_enforce_noop_when_already_coincident():
    # both connectors already at world (3,0,0): below the 1e-6 snap threshold.
    a = _instance([_ip("CA", (0.0, 0.0, 0.0))], transform=_translation(3.0, 0.0, 0.0))
    b = _instance([_ip("CB", (0.0, 0.0, 0.0))], transform=_translation(3.0, 0.0, 0.0))
    joint = _mate(a, "CA", b, "CB")
    asm = _Asm([a, b], [joint])

    _enforce_connector_coincidence(asm, visited={b.id})

    # transform untouched; axis_origin NOT reassigned (would be [3,0,0] if it were)
    np.testing.assert_allclose(
        b.transform.to_array()[:3, 3], [3.0, 0.0, 0.0], atol=1e-9
    )
    assert joint.axis_origin == [0.0, 0.0, 0.0]  # model default, never reassigned


def test_enforce_skips_when_parent_also_moved():
    # both endpoints in visited -> the FK delta already preserved coincidence.
    a = _instance([_ip("CA", (0.0, 0.0, 0.0))], transform=_translation(0.0, 0.0, 0.0))
    b = _instance([_ip("CB", (0.0, 0.0, 0.0))], transform=_translation(5.0, 0.0, 0.0))
    joint = _mate(a, "CA", b, "CB")
    asm = _Asm([a, b], [joint])

    _enforce_connector_coincidence(asm, visited={a.id, b.id})

    # child NOT snapped: parent moved too
    np.testing.assert_allclose(
        b.transform.to_array()[:3, 3], [5.0, 0.0, 0.0], atol=1e-9
    )


def test_enforce_skips_non_rigid_revolute_joint():
    a = _instance([_ip("CA", (0.0, 0.0, 0.0))], transform=_translation(0.0, 0.0, 0.0))
    b = _instance([_ip("CB", (0.0, 0.0, 0.0))], transform=_translation(5.0, 0.0, 0.0))
    joint = _mate(a, "CA", b, "CB", joint_type="prismatic")
    asm = _Asm([a, b], [joint])

    _enforce_connector_coincidence(asm, visited={b.id})

    np.testing.assert_allclose(
        b.transform.to_array()[:3, 3], [5.0, 0.0, 0.0], atol=1e-9
    )


def test_enforce_skips_world_anchored_joint():
    # instance_a_id is None (world-anchored) -> nothing to align to.
    b = _instance([_ip("CB", (0.0, 0.0, 0.0))], transform=_translation(5.0, 0.0, 0.0))
    joint = AssemblyJoint(
        joint_type="rigid",
        instance_a_id=None,
        connector_a_label="CA",
        instance_b_id=b.id,
        connector_b_label="CB",
    )
    asm = _Asm([b], [joint])

    _enforce_connector_coincidence(asm, visited={b.id})

    np.testing.assert_allclose(
        b.transform.to_array()[:3, 3], [5.0, 0.0, 0.0], atol=1e-9
    )


def test_enforce_also_snaps_base_transform_when_present():
    a = _instance([_ip("CA", (0.0, 0.0, 0.0))], transform=_translation(0.0, 0.0, 0.0))
    b = _instance([_ip("CB", (0.0, 0.0, 0.0))], transform=_translation(5.0, 0.0, 0.0))
    b.base_transform = _translation(5.0, 0.0, 0.0)
    joint = _mate(a, "CA", b, "CB")
    asm = _Asm([a, b], [joint])

    _enforce_connector_coincidence(asm, visited={b.id})

    # the same -5 x snap is applied to base_transform too
    np.testing.assert_allclose(
        b.base_transform.to_array()[:3, 3], [0.0, 0.0, 0.0], atol=1e-9
    )


def test_enforce_propagates_snap_to_rigid_subtree_child():
    # b drifted (+5 x); c is rigidly attached to b and must ride the snap.
    a = _instance([_ip("CA", (0.0, 0.0, 0.0))], transform=_translation(0.0, 0.0, 0.0))
    b = _instance(
        [_ip("CB", (0.0, 0.0, 0.0)), _ip("CB2", (0.0, 0.0, 0.0))],
        transform=_translation(5.0, 0.0, 0.0),
    )
    c = _instance([_ip("CC", (0.0, 0.0, 0.0))], transform=_translation(9.0, 0.0, 0.0))
    parent_joint = _mate(a, "CA", b, "CB")
    rigid_child = _mate(b, "CB2", c, "CC", joint_type="rigid")
    asm = _Asm([a, b, c], [parent_joint, rigid_child])

    _enforce_connector_coincidence(asm, visited={b.id})

    # b snapped -5 -> at origin; c rode the same -5 snap -> 9 - 5 = 4
    np.testing.assert_allclose(
        b.transform.to_array()[:3, 3], [0.0, 0.0, 0.0], atol=1e-9
    )
    np.testing.assert_allclose(
        c.transform.to_array()[:3, 3], [4.0, 0.0, 0.0], atol=1e-9
    )
