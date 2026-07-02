"""Connection tethers for a regular cluster's move (direct duplex + ss/ds linker) —
`backend.core.connection_tethers`. Verifies moving/fixed assignment + contour per type on
the reference fixtures used elsewhere for the overhang-duplex / linker work."""
from __future__ import annotations

import json
import os

import pytest

from backend.core.connection_tethers import (
    cluster_connection_tethers,
    cluster_movable_links,
    clusters_with_connection_tethers,
)
from backend.core.models import Design

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_DUPLEX_FIXTURE = os.path.join(_ROOT, "workspace", "2x2_OH_test.nadoc")
_LINKER_FIXTURE = os.path.join(_ROOT, "workspace", "3x6_hinge_interior_linker.nadoc")


def _load(path) -> Design:
    if not os.path.exists(path):
        pytest.skip(f"fixture missing: {path}")
    return Design.from_dict(json.load(open(path)))


def _by_name(design):
    return {c.name: c for c in design.cluster_transforms}


def test_direct_duplex_static_tether_only_for_the_parent_part():
    """A directly-connected duplex is a CHILD of one part. Dragging that PARENT part → the duplex
    rides it → a static ~0.67 nm tether to the OTHER part. Dragging the NON-parent part → the
    duplex is a MOVABLE LINK instead (no static connection tether). The duplex child cluster itself
    yields no regular-connection tether."""
    d = _load(_DUPLEX_FIXTURE)
    by_id = {c.id: c for c in d.cluster_transforms}
    dup = next(c for c in d.cluster_transforms if c.overhang_duplex_driver_id)
    parent = by_id[dup.parent_cluster_id]
    other = next(c for c in d.cluster_transforms
                 if not c.overhang_duplex_driver_id and c.id != parent.id)

    tp = cluster_connection_tethers(d, parent)
    assert len(tp) == 1, "the duplex's parent gets a static tether to the other part"
    assert tp[0]["contour_nm"] == pytest.approx(0.67, abs=1e-6)
    assert tp[0]["rigid"] is False

    assert cluster_connection_tethers(d, other) == [], \
        "the non-parent part uses a MOVABLE LINK, not a static duplex tether"
    assert cluster_connection_tethers(d, dup) == []


def test_direct_duplex_movable_link_for_non_parent_part():
    """Dragging the NON-parent part → the duplex is a movable link with a bond to EACH part
    (the dragged part's bond is `part_dragged`, the parent's bond is fixed)."""
    d = _load(_DUPLEX_FIXTURE)
    by_id = {c.id: c for c in d.cluster_transforms}
    dup = next(c for c in d.cluster_transforms if c.overhang_duplex_driver_id)
    parent = by_id[dup.parent_cluster_id]
    other = next(c for c in d.cluster_transforms
                 if not c.overhang_duplex_driver_id and c.id != parent.id)

    links = cluster_movable_links(d, other)
    assert len(links) == 1
    lk = links[0]
    assert lk["kind"] == "duplex" and lk["link_cluster_id"] == dup.id
    assert len(lk["tethers"]) == 2, "duplex bonds to BOTH parts"
    dragged = [t for t in lk["tethers"] if t["part_dragged"]]
    fixed = [t for t in lk["tethers"] if not t["part_dragged"]]
    assert len(dragged) == 1 and len(fixed) == 1
    for t in lk["tethers"]:
        assert t["contour_nm"] == pytest.approx(0.67, abs=1e-6)

    # The PARENT part sees the duplex as a rigid ride-along (static tether), not a movable link.
    assert cluster_movable_links(d, parent) == []


def test_ds_linker_tether_contour_is_duplex_length():
    """A ds linker bridge → each connected cluster gets a free-until-taut tether whose
    contour is the duplex length (n_bp−1)·0.34 nm."""
    from backend.core.constants import BDNA_RISE_PER_BP

    d = _load(_LINKER_FIXTURE)
    conn = (d.overhang_connections or [None])[0]
    if conn is None:
        pytest.skip("linker fixture has no overhang_connections")
    expected = max(1, round(conn.length_value) - 1) * BDNA_RISE_PER_BP
    clusters = _by_name(d)
    for name in ("Cluster 1", "Cluster 2"):
        t = cluster_connection_tethers(d, clusters[name])
        assert len(t) == 1
        assert t[0]["contour_nm"] == pytest.approx(expected, abs=1e-3)
        assert t[0]["rigid"] is True, "a ds linker is a rigid strut (bilateral)"


def test_clusters_with_connection_tethers_lists_connected_parts():
    d = _load(_DUPLEX_FIXTURE)
    names = {c.id: c.name for c in d.cluster_transforms}
    got = {names[i] for i in clusters_with_connection_tethers(d)}
    assert got == {"Cluster 1", "Cluster 2"}
    # A duplex child cluster is excluded (it uses its own duplex-tethers path).
    dup = next(c for c in d.cluster_transforms if c.overhang_duplex_driver_id)
    assert dup.id not in clusters_with_connection_tethers(d)
