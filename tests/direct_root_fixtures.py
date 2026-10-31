"""Feasible Direct inputs derived without calling the production root fitter."""

import numpy as np

from backend.core.binding_relax import apply_bind_topology, compute_bind_topology
from backend.core.models import OverhangBinding
from backend.core.overhang_root_constraints import overhang_root_bond


def reachable_parent_translation(source, driver, driven, parent_id):
    """Seat the driven host beside its future duplex root using its original bond.

    This is fixture authoring, not a geometry oracle: callers record the returned
    parent move as a native input. Both builders must independently preserve the
    resulting roots, and cold replay must reproduce the authored history.
    """
    binding = OverhangBinding(name="fixture probe", sub_domain_a_id="a",
        sub_domain_b_id="b", overhang_a_id=driver, overhang_b_id=driven)
    raw = apply_bind_topology(source, compute_bind_topology(source, binding, driver_side="a"))
    original = overhang_root_bond(source, driven)
    relocated = overhang_root_bond(raw, driven)
    delta = relocated.moving + original.fixed - original.moving - relocated.fixed
    parent = next(c for c in source.cluster_transforms if c.id == parent_id)
    return (np.asarray(parent.translation) + delta).tolist()


def connected_root_pair(*, displacement=(3., 2., 1.)):
    """Feasible separate-arm connection, manually moved after automatic Connect."""
    from backend.api.connection_version_direct import materialize_direct
    from backend.core.duplex_cluster import duplex_cluster_for
    from tests.test_direct_root_constraints import reachable_source

    connected = materialize_direct(reachable_source(), "oh_a", "oh_b", "free_end", "root", "end-to-root")
    child = duplex_cluster_for(connected, "oh_a")
    return connected.copy_with(cluster_transforms=[c.model_copy(update={
        "translation": (np.asarray(c.translation) + displacement).tolist()})
        if c.id == child.id else c for c in connected.cluster_transforms])


def assert_preserved_roots(design):
    import pytest
    from backend.core.direct_root_placement import capture_root_lengths

    targets = design.overhang_bindings[0].prior_driven_topology["root_bond_lengths_nm"]
    actual = capture_root_lengths(design, targets)
    assert len(actual) == 2
    for oid, expected in targets.items():
        assert actual[oid] == pytest.approx(expected, abs=1e-8)
