"""Sequence scoping through real recorded commands, with saved replay."""
import pytest
from fastapi import HTTPException
from backend.api import headless_build as hb, state
from backend.api.routes_assign_sequences import _ScaffoldSeqBody, assign_scaffold_sequence_endpoint
from backend.core.models import Design, LatticeType
from scripts.agent_structure_guard import audit, publish


def setup_scope():
    design = hb.create_bundle([(0, 0), (0, 3), (0, 6)], 42, lattice=LatticeType.HONEYCOMB)
    design = hb.add_cluster('Target', [h.id for h in design.helices[:2]])
    return design, design.cluster_transforms[-1].id


def assign(**params):
    return assign_scaffold_sequence_endpoint(_ScaffoldSeqBody(**params))


def test_cluster_assigns_each_whole_scaffold_and_replays(tmp_path):
    with hb.scratch_session():
        source, cluster = setup_scope()
        response = assign(cluster_id=cluster, custom_sequence='ACGT')
        result = state.get_or_404()
        assert [s.sequence for s in result.scaffolds()] == ['ACGT'+'N'*38, 'ACGT'+'N'*38, None]
        assert response['padded_nt'] == 76
        assert len(response['assigned_strands']) == 2
        assert result.feature_log[-1].params['cluster_id'] == cluster
        assert [s.model_dump() for s in result.staples()] == [s.model_dump() for s in source.staples()]
        destination = tmp_path/'scoped-sequence.nadoc'
        try:
            publish(result, destination)
            assert audit(Design.model_validate_json(destination.read_text()))['status'] == 'verified'
        finally:
            destination.unlink(missing_ok=True)


def test_selected_strand_and_default_are_distinct():
    with hb.scratch_session():
        source, _ = setup_scope()
        assign(strand_id=source.scaffolds()[2].id, custom_sequence='G'*42)
        assign(custom_sequence='A'*42)
        assert [s.sequence for s in state.get_or_404().scaffolds()] == ['A'*42, None, 'G'*42]
        assert audit(state.get_or_404())['status'] == 'verified'


@pytest.mark.parametrize('scope', ['missing', 'both', 'partial'])
def test_invalid_scope_is_atomic(scope):
    with hb.scratch_session():
        source, cluster = setup_scope()
        if scope == 'partial':
            # A routed bundle's scaffold spans the helix-scoped cluster.
            source = hb.create_bundle([(0,1),(1,1),(1,2),(1,3),(0,3),(0,2)],84,lattice=LatticeType.HONEYCOMB)
            hb.auto_scaffold()
            cluster = hb.add_cluster('Partial', [source.helices[0].id]).cluster_transforms[-1].id
        params = {'cluster_id': 'missing' if scope == 'missing' else cluster}
        if scope == 'both':
            params['strand_id'] = source.scaffolds()[0].id
        before = state.get_or_404().model_dump_json()
        with pytest.raises(HTTPException):
            assign(**params)
        assert state.get_or_404().model_dump_json() == before
