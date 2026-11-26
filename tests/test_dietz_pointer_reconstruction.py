"""Exact reference routing and complete saved/reopened Pointer process."""

import pytest

from backend.core.models import Design
from scripts.agent_structure_guard import audit, publish
from scripts.reconstruct_dietz_pointer import compare_reference, reconstruct


def test_pointer_reference_reopens_and_replays_with_every_source_pointer(tmp_path):
    design, raw, comparison = reconstruct()
    assert comparison['helices'] == 82
    assert comparison['routed_sites'] == 15240
    assert comparison['strand_counts'] == {'scaf': 1, 'stap': 161}
    assert len(design.feature_log) == 1
    assert design.feature_log[0].op_kind == 'cadnano-import'
    assert design.feature_log[0].params['importer_version'] == 3
    target = tmp_path / '__e2e__pointer.nadoc'
    result = publish(design, target)
    assert result['status'] == 'verified'
    assert result['recovery_snapshots_used'] is False
    report = result['bond_review']['report']
    assert report['counts']['nucleotides'] == 15238
    assert report['counts']['interhelix_bonds'] == 901
    assert report['counts']['matched_forced_interhelix_bonds'] == 38
    assert report['geometry']['complete']
    assert report['geometry']['long_interhelix'] == 23
    reopened = Design.model_validate_json(target.read_text())
    assert compare_reference(reopened, raw) == comparison
    assert audit(reopened)['status'] == 'verified'
    # An actual route change must fail the independent reference comparison.
    reopened.strands[0].domains[0].start_bp += 1
    with pytest.raises(AssertionError, match='routing differs'):
        compare_reference(reopened, raw)


def test_published_pointer_scaffold_assignment_is_recorded_and_matches_all_staples(tmp_path):
    from scripts.assign_dietz_pointer_sequence import assign_recorded, compare_published_sequences
    design, raw, _ = reconstruct()
    updated, comparison = assign_recorded(design)
    assert comparison['matched_staple_cores'] == 161
    assert comparison['paired_staple_bases'] == 7249
    assert comparison['published_thymidine_passivation_bases'] == 740
    assert comparison['offset'] == 0
    assert len(updated.feature_log) == 2
    assert updated.feature_log[-1].op_kind == 'assign-scaffold-sequence'
    assert all(s.sequence is None for s in updated.strands if not s.is_scaffold)
    target = tmp_path / '__e2e__sequenced-pointer.nadoc'
    assert publish(updated, target)['status'] == 'verified'
    reopened = Design.model_validate_json(target.read_bytes())
    assert audit(reopened)['status'] == 'verified'
    assert compare_published_sequences(reopened) == comparison
    assert compare_reference(reopened, raw)['all_source_pointers_match']
    scaffold = next(s for s in reopened.strands if s.is_scaffold)
    scaffold.sequence = scaffold.sequence[1:] + scaffold.sequence[:1]
    with pytest.raises(AssertionError):
        compare_published_sequences(reopened)
