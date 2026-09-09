"""Direct input→output unit tests for backend/core/cluster_autodetect.py.

These pin the pure cluster-detection functions extracted from crud.py's
"Internal helpers" block (carve-up Refactor #34). No TestClient / HTTP — the
functions take a Design and return a new Design with cluster_transforms set.
"""

from tests.conftest import (
    make_18hb_routed_design,
    make_6hb_design,
    make_mini_hinge_base_design,
)

from backend.core.cluster_autodetect import (
    _autodetect_clusters,
    _cluster_bundle_regions,
    repair_empty_auto_clusters,
)
from backend.core.models import ClusterRigidTransform


def test_bundle_regions_splits_disconnected_blocks():
    """mini_hinge is two lattice-disconnected SQUARE blocks (rows 0–1 / 4–5);
    each becomes its own non-default cluster, covering every gridded helix once."""
    design = make_mini_hinge_base_design().copy_with(cluster_transforms=[])

    out = _cluster_bundle_regions(design)

    assert len(out.cluster_transforms) == 2
    assert all(not ct.is_default for ct in out.cluster_transforms)
    assigned = sorted(h for ct in out.cluster_transforms for h in ct.helix_ids)
    assert assigned == sorted(h.id for h in design.helices)


def test_bundle_regions_single_region_leaves_clusters_empty():
    """A single lattice-connected bundle (6hb) yields NO clusters — the empty
    list signals the downstream _ensure_default_cluster to build the umbrella."""
    design = make_6hb_design().copy_with(cluster_transforms=[])

    out = _cluster_bundle_regions(design)

    assert out.cluster_transforms == []


def test_bundle_regions_noop_when_clusters_exist():
    """If clusters already exist, the function is an identity no-op (early return)."""
    design = make_6hb_design()
    assert design.cluster_transforms  # build left a default cluster

    assert _cluster_bundle_regions(design) is design


def test_autodetect_produces_scaffold_and_geometry_clusters():
    """A routed single-scaffold design (18hb) yields BOTH a scaffold-routing
    cluster and a geometry cluster, combined into cluster_transforms."""
    design = make_18hb_routed_design()

    out = _autodetect_clusters(design)

    names = [ct.name for ct in out.cluster_transforms]
    assert any(n.startswith("Scaffold Cluster") for n in names), names
    assert any(n.startswith("Geometry Cluster") for n in names), names


def test_repair_empty_auto_clusters_restores_membership_without_references():
    """VoltronCoreArm persisted two auto-cluster shells with no members, which
    made cluster coloring fall back to strand colors in every representation."""
    # Reproduce the legacy state explicitly; the user's live Voltron file may
    # already have been repaired or edited by the time this regression runs.
    design = make_18hb_routed_design(length_bp=42)
    reference = make_6hb_design(length_bp=42)
    reference = reference.copy_with(
        helices=[
            h.model_copy(
                update={
                    "id": f"ref::{h.id}",
                    "grid_pos": [h.grid_pos[0] + 100, h.grid_pos[1] + 100],
                }
            )
            for h in reference.helices
        ],
        strands=[
            s.model_copy(
                update={
                    "id": f"ref::{s.id}",
                    "is_reference": True,
                    "domains": [
                        d.model_copy(update={"helix_id": f"ref::{d.helix_id}"})
                        for d in s.domains
                    ],
                }
            )
            for s in reference.strands
        ],
    )
    active_ids = {h.id for h in design.helices}
    design = design.copy_with(
        helices=[*design.helices, *reference.helices],
        strands=[*design.strands, *reference.strands],
        cluster_transforms=[
            ClusterRigidTransform(
                id="scaffold-shell", name="Scaffold Cluster 1", auto_created=True
            ),
            ClusterRigidTransform(
                id="geometry-shell", name="Geometry Cluster 1", auto_created=True
            ),
        ],
    )
    assert all(not c.helix_ids and not c.domain_ids for c in design.cluster_transforms)

    repaired = repair_empty_auto_clusters(design)

    assert [c.name for c in repaired.cluster_transforms] == [
        "Scaffold Cluster 1",
        "Geometry Cluster 1",
    ]
    assert [c.id for c in repaired.cluster_transforms] == [
        "scaffold-shell",
        "geometry-shell",
    ]
    assert all(set(c.helix_ids) == active_ids for c in repaired.cluster_transforms)
    reference_ids = design.reference_helix_ids()
    assert reference_ids
    assert all(
        not (set(c.helix_ids) & reference_ids) for c in repaired.cluster_transforms
    )
