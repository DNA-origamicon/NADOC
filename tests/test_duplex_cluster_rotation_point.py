"""P2 [[overhang-duplex-cluster]] — the rotation-point dropdown backend: candidate points
are each participating overhang's ROOT bead + the duplex CENTROID (user decision 4), and
moving the pivot to any of them REBASES the translation so the geometry is unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.api.crud import _geometry_for_design
from backend.core.models import Design
from backend.core.duplex_cluster import (
    materialize_duplex_cluster,
    duplex_cluster_for,
    duplex_cluster_rotation_points,
    set_duplex_cluster_pivot,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"
# Untracked fixture with no headless builder yet (design-automation AF-FIXTURES) — skip cleanly
# where it's absent (a fresh checkout / the other computer) instead of erroring.
pytestmark = pytest.mark.skipif(
    not _FIXTURE.exists(),
    reason="relax_2x2_binding.nadoc missing (untracked; regen via AF-FIXTURES builder)",
)


def _load_materialized():
    d = Design.model_validate(json.loads(_FIXTURE.read_text()))
    drv = d.overhang_bindings[0].driver_oh_id
    dvn = d.overhang_bindings[0].driven_oh_id
    d, _ = materialize_duplex_cluster(d, drv)
    return d, drv, dvn


def _ovhg_beads(des, ids):
    return {
        (n.get("overhang_id"), n["bp_index"], n["direction"]): np.asarray(
            n.get("backbone_position") or n.get("base_position"), float
        )
        for n in _geometry_for_design(des)
        if n.get("overhang_id") in ids
    }


def test_rotation_points_are_each_root_plus_centroid():
    d, drv, dvn = _load_materialized()
    cl = duplex_cluster_for(d, drv)
    pts = duplex_cluster_rotation_points(d, cl)
    kinds = [p["kind"] for p in pts]
    assert kinds.count("overhang_root") == 2 and kinds.count("centroid") == 1
    roots = {p["overhang_id"] for p in pts if p["kind"] == "overhang_root"}
    assert roots == {drv, dvn}
    for p in pts:
        assert len(p["point"]) == 3 and all(isinstance(x, float) for x in p["point"])


def test_moving_pivot_to_any_rotation_point_is_geometry_neutral():
    d, drv, dvn = _load_materialized()
    cl = duplex_cluster_for(d, drv)
    before = _ovhg_beads(d, {drv, dvn})
    for p in duplex_cluster_rotation_points(d, cl):
        moved = set_duplex_cluster_pivot(d, cl.id, p["point"])
        mcl = duplex_cluster_for(moved, drv)
        assert np.allclose(mcl.pivot, p["point"], atol=1e-6)  # pivot set
        after = _ovhg_beads(moved, {drv, dvn})
        assert set(before) == set(after)
        assert (
            max(float(np.linalg.norm(before[k] - after[k])) for k in before) < 1e-6
        ), p["kind"]


def test_rotate_about_centroid_vs_root_differ():
    """Sanity: after moving the pivot to a root bead, applying the SAME extra rotation
    about it moves the duplex differently than about the centroid — the dropdown is
    meaningful, not cosmetic."""
    import math

    d, drv, _dvn = _load_materialized()
    cl = duplex_cluster_for(d, drv)
    pts = {p["kind"]: p["point"] for p in duplex_cluster_rotation_points(d, cl)}

    # a 40° spin composed onto the cluster rotation, about centroid vs about a root
    def spun(pivot):
        m = set_duplex_cluster_pivot(d, cl.id, pivot)
        c = duplex_cluster_for(m, drv)
        h = math.radians(40) / 2
        qz = [0, 0, math.sin(h), math.cos(h)]
        from backend.core.direct_relax import _quat_mul

        q = _quat_mul(np.asarray(qz, float), np.asarray(c.rotation, float))
        c2 = c.model_copy(update={"rotation": [float(x) for x in q]})
        m2 = m.model_copy(
            update={
                "cluster_transforms": [
                    c2 if x.id == c.id else x for x in m.cluster_transforms
                ]
            }
        )
        return _ovhg_beads(m2, {drv})

    a = spun(pts["centroid"])
    b = spun(
        next(
            p["point"]
            for p in duplex_cluster_rotation_points(d, cl)
            if p["kind"] == "overhang_root"
        )
    )
    assert max(float(np.linalg.norm(a[k] - b[k])) for k in a) > 0.5
