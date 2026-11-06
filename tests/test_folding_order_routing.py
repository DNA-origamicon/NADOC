"""Native folding-order authoring, topology preservation and independent replay."""
import pytest
from fastapi import HTTPException

from backend.api import headless_build as hb, state
from backend.api.routes_clusters import PatchClusterBody, update_cluster
from backend.core.models import Design, LatticeType, StrandType
from backend.core.staple_thermodynamics import estimate_staple_temperatures
from scripts.agent_structure_guard import audit, publish


def _setup():
    design = hb.create_bundle([(0, 0), (0, 3), (0, 6)], 84,
                             lattice=LatticeType.HONEYCOMB, name='Recorded folding order')
    from backend.api.routes_assign_sequences import _ScaffoldSeqBody, assign_scaffold_sequence_endpoint
    for scaffold in design.scaffolds():
        assign_scaffold_sequence_endpoint(_ScaffoldSeqBody(strand_id=scaffold.id))
    # Separate single helices provide independent, fully specified scaffolds.
    for i, helix in enumerate(design.helices):
        grouped = hb.add_cluster(f'Cluster {i+1}', [helix.id])
        if i:
            update_cluster(grouped.cluster_transforms[-1].id, PatchClusterBody(folding_order=i))
    return state.get_or_404()


def _coverage(design):
    return {(d.helix_id, b, d.direction) for s in design.strands if s.strand_type == StrandType.STAPLE
            for d in s.domains for b in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)+1)}


def test_actual_routing_default_isolation_and_saved_replay(tmp_path):
    with hb.scratch_session():
        source = _setup()
        baseline = hb.full_autostaple(experimental={})
        routed = hb.full_autostaple(experimental={'folding_order': True})
        assert _coverage(routed) == _coverage(baseline)
        temperatures = estimate_staple_temperatures(routed)
        from statistics import median
        medians = []
        for c in routed.cluster_transforms:
            if c.folding_order is not None:
                ids = [s.id for s in routed.strands if s.strand_type == StrandType.STAPLE
                       and all(d.helix_id in c.helix_ids for d in s.domains)]
                medians.append((c.folding_order, median(temperatures[sid] for sid in ids)))
        medians.sort()
        assert medians[0][1] >= medians[1][1]+2
        undefined_helix = source.helices[0].id
        def signature(design):
            return sorted((tuple((d.helix_id, d.start_bp, d.end_bp) for d in s.domains), s.sequence)
                          for s in design.strands if s.strand_type == StrandType.STAPLE
                          and all(d.helix_id == undefined_helix for d in s.domains))
        assert signature(routed) == signature(baseline)
        assert routed.feature_log[-1].params['experimental']['folding_order'] is True
        destination = tmp_path/'folding-order.nadoc'
        try:
            publish(routed, destination)
            assert audit(Design.model_validate_json(destination.read_text()))['status'] == 'verified'
        finally:
            destination.unlink(missing_ok=True)


def test_infeasible_gap_is_atomic():
    with hb.scratch_session():
        _setup()
        before = state.get_or_404().model_dump_json()
        with pytest.raises(HTTPException, match='Cannot achieve'):
            hb.full_autostaple(experimental={'folding_order': True, 'temperature_gap_c': 20})
        assert state.get_or_404().model_dump_json() == before


def test_requires_whole_part_and_distinct_stages():
    with hb.scratch_session():
        hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB)
        with pytest.raises(HTTPException, match='two distinct'):
            hb.full_autostaple(experimental={'folding_order': True})


def test_connected_bundle_with_unsupported_scaffold_coverage_fails_atomically():
    with hb.scratch_session():
        design = hb.create_bundle([(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)], 168,
                                 lattice=LatticeType.HONEYCOMB)
        hb.auto_scaffold()
        for stage, helices in enumerate((design.helices[4:5], design.helices[2:4]), 1):
            grouped = hb.add_cluster(f'Stage {stage}', [h.id for h in helices])
            update_cluster(grouped.cluster_transforms[-1].id, PatchClusterBody(folding_order=stage))
        before = state.get_or_404().model_dump_json()
        # One resulting staple crosses discontinuous scaffold coverage within
        # a duplex domain. The temperature view cannot estimate it either.
        with pytest.raises(HTTPException, match='without a supported Tfold'):
            hb.full_autostaple(experimental={'folding_order': True, 'temperature_gap_c': 0.1})
        assert state.get_or_404().model_dump_json() == before


def test_overlapping_undefined_cluster_is_not_silently_rerouted():
    with hb.scratch_session():
        source = _setup()
        hb.add_cluster('Undefined overlap', [source.helices[2].id])
        with pytest.raises(HTTPException, match='overlap'):
            hb.full_autostaple(experimental={'folding_order': True})


def test_regional_ordering_is_rejected():
    with hb.scratch_session():
        source = _setup()
        with pytest.raises(HTTPException, match='entire part'):
            hb.full_autostaple(experimental={'folding_order': True},
                              region=[{'helix_id': source.helices[1].id, 'lo_bp': 0, 'hi_bp': 83}])


def test_unknown_scaffold_sequence_does_not_get_dropped_from_median():
    with hb.scratch_session():
        design = hb.create_bundle([(0, 0), (0, 3)], 84, lattice=LatticeType.HONEYCOMB)
        for i, helix in enumerate(design.helices, 1):
            grouped = hb.add_cluster(f'Cluster {i}', [helix.id])
            update_cluster(grouped.cluster_transforms[-1].id, PatchClusterBody(folding_order=i))
        # Full autostaple assigns the primary scaffold; the secondary is unknown.
        before = state.get_or_404().model_dump_json()
        with pytest.raises(HTTPException, match='without a supported Tfold'):
            hb.full_autostaple(experimental={'folding_order': True})
        assert state.get_or_404().model_dump_json() == before


def test_tied_clusters_are_each_scored_against_the_next_stage():
    with hb.scratch_session():
        source = _setup()
        undefined = next(c for c in source.cluster_transforms if c.name == 'Cluster 1' and c.helix_ids)
        update_cluster(undefined.id, PatchClusterBody(folding_order=1))
        routed = hb.full_autostaple(experimental={'folding_order': True}, max_staple_length=60)
        assert audit(routed)['status'] == 'verified'
        assert len([c for c in routed.cluster_transforms if c.folding_order == 1]) == 2


def test_crossover_thinning_is_local_to_the_early_cluster():
    from backend.core.experimental_autostaple import ExperimentalAutostaple, retain_boundary
    from backend.core.folding_order_routing import ClusterCrossoverPolicy
    with hb.scratch_session():
        source = _setup()
        undefined, early, late = [h.id for h in source.helices]
        # Start from standard 21-bp repeat: only the early cluster is thinned.
        policy = ClusterCrossoverPolicy(source, ExperimentalAutostaple(crossover_repeat_bp=21, folding_order=True))
        assert not retain_boundary(41, policy, helix_ids=(early,))
        assert retain_boundary(20, policy, helix_ids=(early,))
        assert retain_boundary(41, policy, helix_ids=(late,))
        assert retain_boundary(41, policy, helix_ids=(undefined,))
        assert retain_boundary(41, policy, helix_ids=(early, late))
