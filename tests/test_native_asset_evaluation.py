"""Actual disposable workers reconstruct source-pinned asset commands."""
from uuid import uuid4

import pytest

from backend.api import part_evaluation_capture as capturing
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import import_root
from tests.test_nanoparticle_attachment import attachment_source as attachment_source

pytestmark = [pytest.mark.slow, pytest.mark.headless]


def worker(source, request):
    request = {**request, 'expected_revision': 7}
    # Worker correctness uses the existing generous test-only clock. Live
    # capture qualification is separate; retain its failed evidence unchanged.
    from backend.core.part_verification_capture import capture
    coated = any(p.coating is not None for p in source.nanoparticles)
    limits = dict(capturing.COATING_PROFILE) if coated else {}
    isolated = capture(source, **{**limits, 'seconds': 1.0}, preserve_entry_types=True)
    job = EvaluationWorker(isolated, {'request': request, 'header': {'identity': str(uuid4()),
        'timestamp': '2026-11-01T22:00:00+00:00', 'source_revision': 7, 'source_design_id': source.id}})
    try:
        job.start()
        assert job.wait(30), 'Asset worker timed out'
        return job.result()
    finally:
        job.close()


def append(source, kind, params):
    result = worker(source, {'operation': 'append', 'kind': kind, 'params': params})
    assert result['status'] == 'ready', result
    return Design.model_validate(result['candidate'])


def poison(design):
    design = Design.model_validate_json(design.model_dump_json())
    for row in design.feature_log:
        for entry in (row, *getattr(row, 'children', ())):
            for name in ('design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64',
                         'diff_added_b64', 'diff_removed_b64', 'diff_modified_b64'):
                if name in type(entry).model_fields:
                    setattr(entry, name, 'poisoned recovery')
    return design


def test_biotin_create_edit_remove_and_cold_replay_with_real_workers(monkeypatch):
    monkeypatch.setattr(capturing, 'BIOTIN_APPEND_ENABLED', True)
    root = create_empty_part('Biotin worker', 'HONEYCOMB')
    coated = append(root, 'streptavidin-coating', {'action': 'create', 'diameter_nm': 10.,
        'coating': {'count_override': 1}})
    identity = coated.nanoparticles[0].id
    attached = append(coated, 'nanoparticle-biotin-dna', {'action': 'create', 'nanoparticle_id': identity,
        'sequence': 'ACGTACGT', 'linker_nm': 2.})
    assert len(attached.nanoparticles[0].biotin_dna) == 1
    assert worker(poison(attached), {'operation': 'verify'})['status'] == 'reproduced_import'
    edited = worker(poison(attached), {'operation': 'edit', 'index': 2, 'params': {'sequence': 'ACGTACGA'}})
    assert edited['status'] == 'ready', edited
    edited = Design.model_validate(edited['candidate'])
    assert edited.strands[0].sequence == 'ACGTACGA'
    assert edited.strands[0].id == attached.strands[0].id
    removed = append(edited, 'nanoparticle-biotin-dna', {'action': 'remove', 'nanoparticle_id': identity})
    assert not removed.strands and not removed.helices and not removed.extensions
    assert worker(poison(removed), {'operation': 'verify'})['status'] == 'reproduced_import'


def test_fitting_move_relax_and_cold_replay_with_real_workers(attachment_source, monkeypatch):
    monkeypatch.setattr(capturing, 'NP_FITTING_APPEND_ENABLED', True)
    source, identity = attachment_source
    # A declared imported basis; the three numerical suffix commands must
    # reproduce from it, independently of their saved output/recovery.
    source = source.copy_with(feature_log=[])
    source.recipe_root = import_root(source)
    selected = source.nanoparticle_conjugations[0].surface_strands[0].strand_id
    fitted = append(source, 'nanoparticle-attach-overhang', {'nanoparticle_id': identity,
        'overhang_id': 'target_3p', 'strand_id': selected})
    moved = append(fitted, 'nanoparticle-bound-move', {'nanoparticle_id': identity,
        'gizmo_move': {'pivot': [0., 0., 0.], 'translation': [.1, .2, 0.], 'rotation': [0., 0., 0., 1.]}})
    relaxed = append(moved, 'nanoparticle-connection-relax', {'nanoparticle_id': identity})
    result = worker(poison(relaxed), {'operation': 'verify'})
    assert result['status'] == 'reproduced_import', result
    assert result['checked_commands'] == 3
    edited = worker(poison(relaxed), {'operation': 'edit', 'index': 1, 'params': {
        'gizmo_move': {'pivot': [0., 0., 0.], 'translation': [.2, .1, 0.], 'rotation': [0., 0., 0., 1.]}}})
    assert edited['status'] == 'ready', edited
    result = worker(poison(Design.model_validate(edited['candidate'])), {'operation': 'verify'})
    assert result['status'] == 'reproduced_import', result
