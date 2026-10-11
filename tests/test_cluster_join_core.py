"""Independent molecular and placement invariants for native cluster joins."""

from collections import Counter
import numpy as np
import pytest

from tests.test_cluster_join_api import make_join_design
from backend.core.cluster_join import (
    cluster_join_candidates,
    propose_cluster_join,
    _geometry,
)
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from backend.physics.oxdna_interface import (
    _walk_strand_nucleotides,
    topology_rows,
    resolved_nuc_map,
)


def request(design, kinds=("side", "end"), roll=0, tilt=0, gap=0.8):
    sites = cluster_join_candidates(design)["sites"]
    picks = [
        next(
            p
            for p in sites
            if p["cluster_id"] == f"join_cluster_{i}" and p["kind"] == kind
        )
        for i, kind in enumerate(kinds)
    ]
    return dict(
        first={"cluster_id": picks[0]["cluster_id"], "port_id": picks[0]["id"]},
        second={"cluster_id": picks[1]["cluster_id"], "port_id": picks[1]["id"]},
        expected_design_id=design.id,
        expected_revision=1,
        roll_deg=roll,
        tilt_deg=tilt,
        gap_nm=gap,
    )


def paths(design):
    result = {}
    for step in _walk_strand_nucleotides(design):
        result.setdefault(step.strand.id, []).append(step.key)
    return result


def edges(design):
    return {edge for path in paths(design).values() for edge in zip(path, path[1:])}


def key(site):
    return (site["helix_id"], site["bp_index"], site["direction"])


@pytest.mark.parametrize(
    "kinds", [("side", "end"), ("end", "side"), ("end", "end"), ("side", "side")]
)
def test_native_splice_preserves_every_original_particle_and_unselected_backbone_edge(
    kinds,
):
    original = make_join_design(2)
    before = original.model_dump_json()
    after, report = propose_cluster_join(original, request(original, kinds))
    assert original.model_dump_json() == before
    original_sites = Counter(k for path in paths(original).values() for k in path)
    new_sites = Counter(k for path in paths(after).values() for k in path)
    assert all(new_sites[k] == n for k, n in original_sites.items())
    assert sum((new_sites - original_sites).values()) == report["added_connector_nt"]
    removed = {(key(e["from"]), key(e["to"])) for e in report["removed_edges"]}
    assert removed <= edges(original)
    assert edges(original) - removed <= edges(after)
    assert removed.isdisjoint(edges(after))
    assert (
        key(report["closed_donor_nick"]["from"]),
        key(report["closed_donor_nick"]["to"]),
    ) in edges(after)
    assert len(after.scaffolds()) == 1
    assert [s for s in original.strands if not s.is_scaffold] == [
        s for s in after.strands if not s.is_scaffold
    ]
    assert after.scaffolds()[0].sequence is None
    assert after.scaffolds()[0].custom_scaffold_length is None


def test_preview_transform_exactly_matches_native_authored_donor_pose_and_preserves_host():
    original = make_join_design(2)
    after, report = propose_cluster_join(
        original, request(original, roll=35, tilt=12, gap=3)
    )
    a, b = _geometry(original), _geometry(after)
    matrix = np.array(report["donor_world_delta"]).reshape((4, 4), order="F")
    for key, geometry in a.items():
        expected = geometry[0]
        if key[0] in report["donor_helix_ids"]:
            expected = (matrix @ np.r_[expected, 1])[:3]
        np.testing.assert_allclose(b[key][0], expected, atol=1e-8)


def test_native_export_materializes_connector_particles_and_two_connected_flexible_runs():
    original = make_join_design(2)
    after, report = propose_cluster_join(original, request(original))
    rows, nstrands = topology_rows(after)
    assert len(rows) == len(topology_rows(original)[0]) + report["added_connector_nt"]
    assert nstrands == len(original.strands) - 1
    resolved = resolved_nuc_map(after, _geometry_for_design(after))
    assert len(resolved) == len(rows)
    assert len(after.flexible_connections) == 2
    connector_ids = {b["helix_id"] for b in report["bridges"]}
    assert (
        sum(c.n_ss_bases for c in after.flexible_connections)
        == report["added_connector_nt"]
    )
    for path in paths(after).values():
        for a, b in zip(path, path[1:]):
            if a[0] in connector_ids or b[0] in connector_ids:
                distance = np.linalg.norm(
                    np.array(resolved[a]["backbone_position"])
                    - resolved[b]["backbone_position"]
                )
                assert 0.15 < distance < 0.75
    for i, (_, _, n3, n5) in enumerate(rows):
        if n3 != -1:
            assert rows[n3][3] == i
        if n5 != -1:
            assert rows[n5][2] == i


def test_second_cluster_with_external_route_is_rejected_without_mutation():
    original = make_join_design(2)
    joined, _ = propose_cluster_join(original, request(original))
    # Both selections now resolve into the same linear molecule.
    body = request(joined)
    before = joined.model_dump_json()
    with pytest.raises(ValueError, match="already share a scaffold"):
        propose_cluster_join(joined, body)
    assert joined.model_dump_json() == before


def test_nonadjacent_donor_nick_is_rejected_without_mutation():
    original = make_join_design(2)
    body = request(original)
    donor = next(s for s in original.scaffolds() if s.id == "scaffold_join1")
    donor.domains[0].start_bp += (
        1 if donor.domains[0].direction == Direction.FORWARD else -1
    )
    before = original.model_dump_json()
    with pytest.raises(ValueError, match="nick is not adjacent"):
        propose_cluster_join(original, body)
    assert original.model_dump_json() == before


def test_local_ports_on_bent_host_allow_repeated_joins_without_moving_prior_geometry():
    from backend.core.models import DeformationOp, BendParams

    original = make_join_design(3)
    original.deformations = [
        DeformationOp(
            type="bend",
            plane_a_bp=0,
            plane_b_bp=95,
            affected_helix_ids=original.cluster_transforms[0].helix_ids,
            params=BendParams(curvature_deg_per_bp=0.4, direction_deg=15),
        )
    ]
    first, _ = propose_cluster_join(original, request(original))
    sites = cluster_join_candidates(first)["sites"]
    fixed = [
        p for p in sites if p["cluster_id"] == "join_cluster_0" and p["kind"] == "side"
    ]
    donor = next(
        p for p in sites if p["cluster_id"] == "join_cluster_2" and p["kind"] == "end"
    )
    final = None
    for port in fixed:
        body = dict(
            first={"cluster_id": port["cluster_id"], "port_id": port["id"]},
            second={"cluster_id": donor["cluster_id"], "port_id": donor["id"]},
            expected_design_id=first.id,
            expected_revision=2,
        )
        try:
            final, report = propose_cluster_join(first, body)
            break
        except ValueError as exc:
            assert "clashes" in str(exc)
    assert final is not None
    assert len(final.scaffolds()) == 1
    before, after = _geometry(first), _geometry(final)
    for site, geometry in before.items():
        if site[0] not in report["donor_helix_ids"]:
            np.testing.assert_allclose(after[site][0], geometry[0], atol=1e-8)
    assert len(final.flexible_connections) == 4
    assert {p for path in paths(original).values() for p in path} <= {
        p for path in paths(final).values() for p in path
    }


def test_loop_copies_and_skips_away_from_port_are_preserved_in_native_export():
    from backend.core.models import LoopSkip

    original = make_join_design(2)
    for helix in (original.helices[0], original.helices[-1]):
        helix.loop_skips = [
            LoopSkip(bp_index=10, delta=2),
            LoopSkip(bp_index=15, delta=-1),
        ]
    after, report = propose_cluster_join(original, request(original))
    a = Counter(k for path in paths(original).values() for k in path)
    b = Counter(k for path in paths(after).values() for k in path)
    assert all(b[k] == n for k, n in a.items())
    assert (
        len(topology_rows(after)[0]) - len(topology_rows(original)[0])
        == report["added_connector_nt"]
    )


def test_overlapping_default_pose_cannot_invalidate_rigid_preview_contract():
    from backend.core.models import ClusterRigidTransform

    original = make_join_design(2)
    body = request(original)
    original.cluster_transforms.append(
        ClusterRigidTransform(
            id="overlap-default",
            is_default=True,
            helix_ids=list(original.cluster_transforms[1].helix_ids),
            translation=[2, 3, 4],
        )
    )
    before = original.model_dump_json()
    with pytest.raises(ValueError, match="overlapping cluster"):
        propose_cluster_join(original, body)
    assert original.model_dump_json() == before


def test_existing_kinematic_joint_on_donor_is_explicitly_rejected():
    from backend.core.models import ClusterJoint

    original = make_join_design(2)
    body = request(original)
    original.cluster_joints = [ClusterJoint(cluster_id="join_cluster_1")]
    with pytest.raises(ValueError, match="existing joint"):
        propose_cluster_join(original, body)


def test_connector_arc_hard_overlap_is_rejected_without_mutation():
    original = make_join_design(2)
    sites = cluster_join_candidates(original)["sites"]
    fixed = [
        p for p in sites if p["cluster_id"] == "join_cluster_0" and p["kind"] == "side"
    ][9]
    donor = next(
        p for p in sites if p["cluster_id"] == "join_cluster_1" and p["kind"] == "end"
    )
    body = dict(
        first={"cluster_id": fixed["cluster_id"], "port_id": fixed["id"]},
        second={"cluster_id": donor["cluster_id"], "port_id": donor["id"]},
        expected_design_id=original.id,
        expected_revision=1,
        roll_deg=90,
    )
    # This pose has 0.949 nm rigid-DNA clearance, but a newly inserted return
    # arc bead sits only 0.186 nm from host h_XY_2_1 bp24 REVERSE.
    before = original.model_dump_json()
    with pytest.raises(ValueError, match=r"Connector placement clashes.*0.19 nm"):
        propose_cluster_join(original, body)
    assert original.model_dump_json() == before


@pytest.mark.parametrize("roll,tilt,gap", [(0, 0, 0.8), (35, 12, 3)])
def test_valid_native_connector_controls_report_their_nonbonded_clearance(
    roll, tilt, gap
):
    original = make_join_design(2)
    _, report = propose_cluster_join(
        original, request(original, roll=roll, tilt=tilt, gap=gap)
    )
    assert report["minimum_connector_clearance_nm"] >= 0.30
    assert "not all-atom" in report["clearance_scope"]


def test_side_port_cannot_discard_an_existing_extra_base_ligation_annotation():
    from backend.core.models import ForcedLigation

    original = make_join_design(2)
    body = request(original)
    port = next(
        p
        for p in cluster_join_candidates(original)["sites"]
        if p["id"] == body["first"]["port_id"]
    )
    a, b = port["from"], port["to"]
    original.forced_ligations.append(
        ForcedLigation(
            id="annotated-side-edge",
            three_prime_helix_id=a["helix_id"],
            three_prime_bp=a["bp_index"],
            three_prime_direction=a["direction"],
            five_prime_helix_id=b["helix_id"],
            five_prime_bp=b["bp_index"],
            five_prime_direction=b["direction"],
            extra_bases="TT",
        )
    )
    before = original.model_dump_json()
    assert port["id"] not in {
        p["id"] for p in cluster_join_candidates(original)["sites"]
    }
    with pytest.raises(ValueError, match="site is stale or unavailable"):
        propose_cluster_join(original, body)
    assert original.model_dump_json() == before


def test_closing_donor_nick_cannot_consume_an_extra_base_ligation_annotation():
    from backend.core.models import ForcedLigation

    original = make_join_design(2)
    body = request(original)
    donor = next(s for s in original.scaffolds() if s.id == "scaffold_join1")
    first, last = donor.domains[0], donor.domains[-1]
    original.forced_ligations.append(
        ForcedLigation(
            id="annotated-original-nick",
            three_prime_helix_id=last.helix_id,
            three_prime_bp=last.end_bp,
            three_prime_direction=last.direction,
            five_prime_helix_id=first.helix_id,
            five_prime_bp=first.start_bp,
            five_prime_direction=first.direction,
            extra_bases="TT",
        )
    )
    before = original.model_dump_json()
    with pytest.raises(ValueError, match="nick carries extra bases"):
        propose_cluster_join(original, body)
    assert original.model_dump_json() == before
