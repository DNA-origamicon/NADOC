"""
Direct unit tests for the pure deformation-helper functions extracted from
``backend/api/crud.py`` into ``backend/core/deformation.py`` (carve-router
Refactor #3, the service push that precedes the routes_deformation.py lift).

These cover ``parse_deformation_params`` and ``resolve_cluster_scope`` at the
input→output level — no ``TestClient``, no HTTP — which is the adapted-code pin
the router lift then rides on for B=1.
"""

from __future__ import annotations

import pytest

from backend.core.deformation import parse_deformation_params, resolve_cluster_scope
from backend.core.lattice import make_bundle_design
from backend.core.models import BendParams, ClusterRigidTransform, TwistParams


# ── parse_deformation_params ───────────────────────────────────────────────────


def test_parse_bend_params():
    p = parse_deformation_params("bend", {"angle_deg": 30.0, "direction_deg": 10.0})
    assert isinstance(p, BendParams)


def test_parse_twist_params():
    p = parse_deformation_params("twist", {"angle_deg": 45.0})
    assert isinstance(p, TwistParams)


def test_parse_strips_kind_discriminator():
    # A stray ``kind`` key (the pydantic discriminator) must be dropped, not
    # forwarded into the params constructor.
    p = parse_deformation_params("bend", {"kind": "bend", "angle_deg": 12.0, "direction_deg": 0.0})
    assert isinstance(p, BendParams)


def test_parse_unknown_type_raises_valueerror():
    # Core raises ValueError (HTTP-free); the api layer translates to a 400.
    with pytest.raises(ValueError, match="Unknown deformation type"):
        parse_deformation_params("squish", {"angle_deg": 1.0})


# ── resolve_cluster_scope ──────────────────────────────────────────────────────


@pytest.fixture()
def _two_cluster_design():
    """6-helix HC bundle; first 3 helices → cluster A, last 3 → cluster B."""
    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    design = make_bundle_design(cells, length_bp=420)
    h_ids = [h.id for h in design.helices]
    cluster_a = ClusterRigidTransform(name="ArmA", helix_ids=h_ids[:3])
    cluster_b = ClusterRigidTransform(name="ArmB", helix_ids=h_ids[3:])
    design = design.copy_with(cluster_transforms=[cluster_a, cluster_b])
    return design, h_ids, cluster_a, cluster_b


def test_empty_cluster_ids_returns_helices_unchanged(_two_cluster_design):
    design, h_ids, _a, _b = _two_cluster_design
    out = resolve_cluster_scope(design, [], h_ids)
    assert out == {"cluster_ids": [], "helix_ids": h_ids}


def test_single_cluster_filters_to_its_helices(_two_cluster_design):
    design, h_ids, cluster_a, _b = _two_cluster_design
    out = resolve_cluster_scope(design, [cluster_a.id], h_ids)
    assert out["cluster_ids"] == [cluster_a.id]
    assert out["helix_ids"] == h_ids[:3]


def test_two_clusters_union(_two_cluster_design):
    design, h_ids, cluster_a, cluster_b = _two_cluster_design
    out = resolve_cluster_scope(design, [cluster_a.id, cluster_b.id], h_ids)
    assert set(out["cluster_ids"]) == {cluster_a.id, cluster_b.id}
    assert out["helix_ids"] == h_ids  # union covers all 6


def test_missing_cluster_id_dropped_and_treated_unscoped(_two_cluster_design):
    design, h_ids, _a, _b = _two_cluster_design
    out = resolve_cluster_scope(design, ["does-not-exist"], h_ids)
    # All named clusters missing → resolved empty → unscoped (helix_ids unchanged).
    assert out == {"cluster_ids": [], "helix_ids": h_ids}


def test_partial_helix_list_intersected_with_cluster(_two_cluster_design):
    design, h_ids, cluster_a, _b = _two_cluster_design
    # Pass only helices 2..4; cluster A owns helices 0..2 → intersection = {h_ids[2]}.
    out = resolve_cluster_scope(design, [cluster_a.id], h_ids[2:5])
    assert out["helix_ids"] == [h_ids[2]]
