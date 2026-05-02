"""End-to-end tests for the mutate_with_reconcile wrapper.

Exercises the full route → state.mutate_with_reconcile → reconciler path,
verifying that newly-created strands/helices land in the right cluster and
inherit its transform.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    DomainRef,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


# ── Scaffold paint smoke test ─────────────────────────────────────────────────


def _seed_design_with_cluster(domain_level: bool = False) -> Design:
    """Single helix at HC cell (0,0), 100 bp, with one cluster.

    domain_level=True → cluster has a placeholder DomainRef so it's
    domain-level (and must accumulate refs as new domains appear).
    """
    h0 = Helix(
        id="h_XY_0_0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=100 * 0.34),
        length_bp=100,
        grid_pos=(0, 0),
    )
    strands = []
    domain_ids: list[DomainRef] = []
    if domain_level:
        seed = Strand(
            id="s_seed",
            domains=[Domain(helix_id="h_XY_0_0", start_bp=0, end_bp=99,
                             direction=Direction.REVERSE)],
            strand_type=StrandType.STAPLE,
        )
        strands.append(seed)
        domain_ids.append(DomainRef(strand_id="s_seed", domain_index=0))

    cluster = ClusterRigidTransform(
        id="c0",
        name="Test Cluster",
        helix_ids=["h_XY_0_0"],
        domain_ids=domain_ids,
        translation=[5.0, 0.0, 0.0],
    )
    return Design(
        helices=[h0],
        strands=strands,
        lattice_type=LatticeType.HONEYCOMB,
        cluster_transforms=[cluster],
    )


def test_scaffold_domain_paint_helix_level_cluster_unchanged(client):
    """Helix-level cluster: painting a scaffold on the clustered helix should
    leave the cluster helix-level (no DomainRefs added)."""
    design_state.set_design(_seed_design_with_cluster(domain_level=False))

    r = client.post(
        "/api/design/scaffold-domain-paint",
        json={"helix_id": "h_XY_0_0", "lo_bp": 0, "hi_bp": 49},
    )
    assert r.status_code == 201, r.text

    design = r.json()["design"]
    clusters = design["cluster_transforms"]
    assert len(clusters) == 1
    c = clusters[0]
    assert c["helix_ids"] == ["h_XY_0_0"]
    assert c["domain_ids"] == []
    # Transform untouched
    assert c["translation"] == [5.0, 0.0, 0.0]


def test_scaffold_domain_paint_domain_level_cluster_gets_new_ref(client):
    """Domain-level cluster: the new scaffold domain must be added to
    cluster.domain_ids since its bp range falls inside the cluster's claim."""
    design_state.set_design(_seed_design_with_cluster(domain_level=True))

    r = client.post(
        "/api/design/scaffold-domain-paint",
        json={"helix_id": "h_XY_0_0", "lo_bp": 0, "hi_bp": 49},
    )
    assert r.status_code == 201, r.text

    design = r.json()["design"]
    clusters = design["cluster_transforms"]
    assert len(clusters) == 1
    c = clusters[0]

    # Find the painted scaffold strand
    scaffold_strand = next(
        s for s in design["strands"] if s["strand_type"] == "scaffold"
    )
    new_id = scaffold_strand["id"]

    refs = {(r["strand_id"], r["domain_index"]) for r in c["domain_ids"]}
    assert ("s_seed", 0) in refs
    assert (new_id, 0) in refs
    assert c["translation"] == [5.0, 0.0, 0.0]


def test_bundle_segment_new_helix_inherits_neighbor_cluster(client):
    """Slice-plane extrude (fresh segment): new helix at adjacent grid_pos to a
    clustered helix should join that cluster via lattice-neighbor proximity."""
    # Seed: existing helix at (0,0) in cluster c0, no helices elsewhere.
    seed = _seed_design_with_cluster(domain_level=False)
    design_state.set_design(seed)

    # Extrude a fresh cell at (0,1) — adjacent to (0,0).
    r = client.post(
        "/api/design/bundle-segment",
        json={"cells": [[0, 1]], "length_bp": 42, "offset_nm": 100 * 0.34},
    )
    assert r.status_code == 201, r.text

    design = r.json()["design"]
    cluster = design["cluster_transforms"][0]
    helix_ids_in_cluster = set(cluster["helix_ids"])
    new_helix_ids = {h["id"] for h in design["helices"] if h["id"] != "h_XY_0_0"}

    # Reconciler should have added the new helix(es) at (0,1) to c0.
    assert new_helix_ids.issubset(helix_ids_in_cluster), (
        f"new helices {new_helix_ids} not in cluster helix_ids {helix_ids_in_cluster}"
    )
    assert cluster["translation"] == [5.0, 0.0, 0.0]


def test_bundle_continuation_new_helix_inherits_via_grid_pos(client):
    """Slice-plane continuation: a continuation cell at the same grid_pos as
    the existing helix produces a new helix that joins the same cluster."""
    seed = _seed_design_with_cluster(domain_level=False)
    design_state.set_design(seed)

    # Continuation at (0,0) with extend_inplace=False so a new helix is created.
    r = client.post(
        "/api/design/bundle-continuation",
        json={
            "cells": [[0, 0]],
            "length_bp": 42,
            "offset_nm": 100 * 0.34,
            "extend_inplace": False,
        },
    )
    assert r.status_code == 201, r.text

    design = r.json()["design"]
    cluster = design["cluster_transforms"][0]
    new_helix_ids = {h["id"] for h in design["helices"] if h["id"] != "h_XY_0_0"}
    assert new_helix_ids.issubset(set(cluster["helix_ids"]))
    assert cluster["translation"] == [5.0, 0.0, 0.0]


def test_undo_after_painted_domain_restores_cluster(client):
    """Undo must restore cluster_transforms to its pre-mutation state."""
    design_state.set_design(_seed_design_with_cluster(domain_level=True))

    r = client.post(
        "/api/design/scaffold-domain-paint",
        json={"helix_id": "h_XY_0_0", "lo_bp": 0, "hi_bp": 49},
    )
    assert r.status_code == 201, r.text

    r_undo = client.post("/api/design/undo")
    assert r_undo.status_code == 200, r_undo.text

    design = r_undo.json()["design"]
    clusters = design["cluster_transforms"]
    refs = {(r["strand_id"], r["domain_index"]) for r in clusters[0]["domain_ids"]}
    assert refs == {("s_seed", 0)}  # only the original ref
