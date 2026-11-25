import pytest

from backend.api import doc_context, headless_build as hb, state
from backend.api.corner_preview import evaluate_corner_preview
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import LatticeType
from backend.core.part_history_contract import assess_part_history
from tests.conftest import SIX_HB_CELLS


@pytest.mark.slow
@pytest.mark.parametrize('lattice,cells', [
    (LatticeType.SQUARE, [[0, i] for i in range(8)]),
    (LatticeType.HONEYCOMB, SIX_HB_CELLS),
])
def test_full_preview_is_recorded_replayable_and_never_published(lattice, cells):
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, 168, lattice=lattice, separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        cluster = next(c for c in source.cluster_transforms if c.name == 'Corner source')
        original = source.model_dump()
        entry_stamp = doc_context.current_request_feature_log_entry_id()
        revision_stamp = doc_context.current_request_revision()
        progress = []
        packet, candidate = evaluate_corner_preview(source,
            dict(cluster_id=cluster.id, position_bp=84, angle_deg=90, direction_deg=0),
            on_progress=progress.append)
        assert packet['candidate']['representation'] == 'native-full-v1'
        assert len(packet['candidate']['display_topology']['forced_ligations']) == 2 * len(cells)
        assert len(packet['candidate']['seam_inserts']) == 2 * len(cells)
        assert all(len(row['backbone_positions']) == len(row['sequence'])
                   for row in packet['candidate']['seam_inserts'])
        # Approved atom closure uses actual O5′ landmarks, whose separation
        # is not the ssDNA contour allocation used by the initial length search.
        # Check the delivered points against the shared atom projection below.
        from backend.core.bond_review_insert_positions import insert_positions
        points = insert_positions(candidate, packet['candidate']['nucleotides'])
        for row in packet['candidate']['seam_inserts']:
            # The disposable worker returns JSON arrays; compare exact values
            # after normalizing only the local provider's tuple container.
            assert row['backbone_positions'] == [list(points[('__xb__', row['connection_id'], k)])
                for k in range(len(row['sequence']))]
        from backend.core.design_bond_review import review_design_bonds
        review = review_design_bonds(candidate)
        assert review['geometry']['complete'], review['geometry']
        assert review['geometry']['missing_bonds'] == 0
        assert review['geometry']['long_interhelix'] == 0
        assert review['counts']['matched_forced_interhelix_bonds'] == sum(
            len(row['sequence']) + 1 for row in packet['candidate']['seam_inserts'])
        assert 'FORCED_JUNCTION_FRACTION_GT_20_PERCENT' in review['reason_codes']
        assert packet['feature_id'] == candidate.feature_log[-1].id
        assert progress[0]['percent'] == 0 and progress[-1]['percent'] == 100
        assert [p['percent'] for p in progress] == sorted(p['percent'] for p in progress)
        assert source.model_dump() == original == state.get_or_404().model_dump()
        assert state.copy_for_persist()[1] == revision
        assert doc_context.current_request_feature_log_entry_id() == entry_stamp
        assert doc_context.current_request_revision() == revision_stamp
        proof = assess_part_history(candidate, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        assert progress[-1]['done'] == progress[-1]['total'] == 100
        assert any(p['stage'] == 'Fitting approved scaffold and staple geometry' and 30 < p['percent'] < 100 for p in progress)
        cancelled_progress = []
        def cancel():
            if len(cancelled_progress) > 3:
                raise RuntimeError('cancelled')
        with pytest.raises(RuntimeError, match='cancelled'):
            evaluate_corner_preview(source,
                dict(cluster_id=cluster.id, position_bp=84, angle_deg=90, direction_deg=0),
                on_progress=cancelled_progress.append, check_cancel=cancel)
        assert state.get_or_404().model_dump() == original
        assert state.copy_for_persist()[1] == revision
