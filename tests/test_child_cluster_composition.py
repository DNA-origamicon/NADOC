"""Phase 0 of the overhang-duplex-cluster plan ([[overhang-duplex-cluster]]).

A CHILD ``ClusterRigidTransform`` (``parent_cluster_id`` set) is a domain-level cluster
whose local pose composes INSIDE its parent: its domains end up at
``T_parent(T_child(p_rest))``. This pins the composition math and its three invariants:
  1. child domains = parent∘child (child applied first, in rest coords);
  2. moving the PARENT carries the child rigidly (the child's stored pose is drift-free);
  3. moving the CHILD moves only the child's domains.
Behaviour-neutral: a design with no child clusters is geometry-identical to before.
"""

from __future__ import annotations

import math

import numpy as np

from backend.api.crud import _geometry_for_design
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.deformation import _rot_from_quaternion
from backend.core.models import (
    ClusterRigidTransform,
    Direction,
    Domain,
    DomainRef,
    Helix,
    Strand,
    StrandType,
    Vec3,
)

_IDENTITY = [0.0, 0.0, 0.0, 1.0]


def _quat(axis, deg):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    h = math.radians(deg) / 2.0
    s = math.sin(h)
    return [float(a[0] * s), float(a[1] * s), float(a[2] * s), float(math.cos(h))]


def _xf(quat, pivot, trans):
    """Return f(p) = R(p-pivot)+pivot+trans as a numpy callable."""
    R = _rot_from_quaternion(*quat)
    piv = np.asarray(pivot, float)
    t = np.asarray(trans, float)
    return lambda p: R @ (np.asarray(p, float) - piv) + piv + t


def _seed(*, parent=None, child=None):
    """One 16-bp helix; one staple with a BODY domain (bp 0-7) + a CHILD domain
    (bp 8-15). Optional parent (helix-level) + child (domain-level) clusters."""
    base = _demo_design()
    L = 16
    h = Helix(
        id="cc_h",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=L,
        grid_pos=(0, 0),
    )
    s = Strand(
        id="cc_s",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="cc_h", start_bp=0, end_bp=7, direction=Direction.FORWARD),
            Domain(helix_id="cc_h", start_bp=8, end_bp=15, direction=Direction.FORWARD),
        ],
    )
    clusters = []
    if parent is not None:
        clusters.append(parent)
    if child is not None:
        clusters.append(child)
    return base.model_copy(
        update={
            "helices": [*base.helices, h],
            "strands": [*base.strands, s],
            "cluster_transforms": clusters,
        }
    )


def _bead(nucs, bp):
    n = next(
        x
        for x in nucs
        if x.get("helix_id") == "cc_h"
        and x.get("bp_index") == bp
        and x.get("direction") == "FORWARD"
    )
    return np.asarray(n.get("backbone_position") or n.get("base_position"), float)


# Body domain = bp 0-7 (parent only); child domain = bp 8-15 (parent ∘ child).
_BODY_BP, _CHILD_BP = 3, 11


def test_child_cluster_composes_inside_parent():
    """A child's domains land at T_parent(T_child(rest)); the body domain (parent only)
    lands at T_parent(rest)."""
    rest = _geometry_for_design(_seed())
    rest_body, rest_child = _bead(rest, _BODY_BP), _bead(rest, _CHILD_BP)

    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["cc_h"],
        rotation=_quat([0, 0, 1], 30.0),
        translation=[5.0, 0.0, 0.0],
        pivot=[0.0, 0.0, 0.0],
    )
    child = ClusterRigidTransform(
        id="C",
        name="duplex",
        helix_ids=["cc_h"],
        domain_ids=[DomainRef(strand_id="cc_s", domain_index=1)],
        parent_cluster_id="P",
        rotation=_quat([0, 1, 0], 20.0),
        translation=[0.0, 2.0, 0.0],
        pivot=list(rest_child),
    )  # rest-frame pivot

    nucs = _geometry_for_design(_seed(parent=parent, child=child))
    Tp = _xf(parent.rotation, parent.pivot, parent.translation)
    Tc = _xf(child.rotation, child.pivot, child.translation)

    assert np.allclose(_bead(nucs, _BODY_BP), Tp(rest_body), atol=1e-6)
    assert np.allclose(_bead(nucs, _CHILD_BP), Tp(Tc(rest_child)), atol=1e-6)
    # The child genuinely moved relative to a parent-only pose.
    assert not np.allclose(_bead(nucs, _CHILD_BP), Tp(rest_child), atol=1e-3)


def test_moving_the_parent_carries_the_child_rigidly():
    """Changing only the parent's translation shifts BOTH body and child domains by the
    same delta — the child's stored local pose never changes (drift-free)."""
    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["cc_h"],
        rotation=_quat([0, 0, 1], 25.0),
        translation=[1.0, 0.0, 0.0],
        pivot=[0.0, 0.0, 0.0],
    )
    rest_child = _bead(_geometry_for_design(_seed()), _CHILD_BP)
    child = ClusterRigidTransform(
        id="C",
        name="duplex",
        helix_ids=["cc_h"],
        domain_ids=[DomainRef(strand_id="cc_s", domain_index=1)],
        parent_cluster_id="P",
        rotation=_quat([1, 0, 0], 15.0),
        translation=[0.0, 0.0, 1.0],
        pivot=list(rest_child),
    )

    before = _geometry_for_design(_seed(parent=parent, child=child))
    moved_parent = parent.model_copy(update={"translation": [1.0, 3.0, -2.0]})
    after = _geometry_for_design(_seed(parent=moved_parent, child=child))

    delta = np.array([0.0, 3.0, -2.0])
    assert np.allclose(
        _bead(after, _BODY_BP) - _bead(before, _BODY_BP), delta, atol=1e-6
    )
    assert np.allclose(
        _bead(after, _CHILD_BP) - _bead(before, _CHILD_BP), delta, atol=1e-6
    )


def test_moving_the_child_moves_only_its_domains():
    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["cc_h"],
        rotation=_quat([0, 1, 0], 40.0),
        translation=[2.0, 1.0, 0.0],
        pivot=[0.0, 0.0, 0.0],
    )
    rest_child = _bead(_geometry_for_design(_seed()), _CHILD_BP)
    child0 = ClusterRigidTransform(
        id="C",
        name="duplex",
        helix_ids=["cc_h"],
        domain_ids=[DomainRef(strand_id="cc_s", domain_index=1)],
        parent_cluster_id="P",
        rotation=_IDENTITY,
        translation=[0.0, 0.0, 0.0],
        pivot=list(rest_child),
    )
    child1 = child0.model_copy(
        update={"rotation": _quat([0, 0, 1], 35.0), "translation": [0.0, 4.0, 0.0]}
    )

    a = _geometry_for_design(_seed(parent=parent, child=child0))
    b = _geometry_for_design(_seed(parent=parent, child=child1))
    assert np.allclose(
        _bead(a, _BODY_BP), _bead(b, _BODY_BP), atol=1e-6
    )  # body unchanged
    assert not np.allclose(
        _bead(a, _CHILD_BP), _bead(b, _CHILD_BP), atol=1e-3
    )  # child moved


def test_no_child_clusters_is_behaviour_neutral():
    """A domain-level cluster with NO parent behaves exactly as before (parent-then-child
    overwrite) — the child path is inert unless parent_cluster_id is set."""
    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["cc_h"],
        rotation=_quat([0, 0, 1], 20.0),
        translation=[3.0, 0.0, 0.0],
        pivot=[0.0, 0.0, 0.0],
    )
    rest_child = _bead(_geometry_for_design(_seed()), _CHILD_BP)
    # Same numbers, but parent_cluster_id=None → legacy domain-level overwrite = T_child(T_parent).
    legacy = ClusterRigidTransform(
        id="C",
        name="dom",
        helix_ids=["cc_h"],
        domain_ids=[DomainRef(strand_id="cc_s", domain_index=1)],
        rotation=_quat([0, 1, 0], 20.0),
        translation=[0.0, 2.0, 0.0],
        pivot=list(rest_child),
    )
    rest_child_rest = _bead(_geometry_for_design(_seed()), _CHILD_BP)

    nucs = _geometry_for_design(_seed(parent=parent, child=legacy))
    Tp = _xf(parent.rotation, parent.pivot, parent.translation)
    Tc = _xf(legacy.rotation, legacy.pivot, legacy.translation)
    # Legacy overwrite order is child-OUTER: T_child(T_parent(rest)).
    assert np.allclose(_bead(nucs, _CHILD_BP), Tc(Tp(rest_child_rest)), atol=1e-6)
