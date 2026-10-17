"""Extrusion storage is exact and isolated, never implicit batch authority."""

import json

from fastapi import HTTPException
import pytest

from backend.api import part_immutable_revision as revisions
from backend.api import part_immutable_worker as worker
from backend.api.part_immutable_evaluation import check_request
from backend.api.part_immutable_storage import immutable_pair
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_publication_policy import SessionPolicy
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_verification_capture import CaptureLimit
from tests.test_part_extrusion_edit_routes import KINDS, recipe
from tests.test_group_organization_history import _verified
from tests.test_part_publication_permit import context as context, issue


@pytest.mark.parametrize('kind', KINDS)
def test_all_native_extrusion_families_survive_exact_sealed_roundtrip_and_cold_replay(kind):
    source, _ = recipe(kind, False)
    # Normalize the same typed JSON boundary used by worker publication.
    source = Design.model_validate_json(source.model_dump_json())
    source.feature_log[0].design_snapshot_gz_b64 = 'not executable recovery'
    handle = revisions.prepare_geometry_revision(source)
    assert revisions.is_prepared_revision(handle)
    assert revisions.revision_metadata(handle).scope_tag == 'native_extrusion_v1'
    assert json.loads(handle.payload) == source.model_dump(mode='json')
    restored = revisions.materialize_revision(handle)
    _verified(restored)
    before = handle.payload
    source.feature_log[0].params['length_bp'] = 99
    restored.feature_log[0].params['length_bp'] = 100
    assert handle.payload is before
    assert revisions.materialize_revision(handle).feature_log[0].params['length_bp'] not in {99, 100}
    with pytest.raises(CommandContractError):
        revisions.prepare_revision(revisions.materialize_revision(handle))


@pytest.mark.parametrize('fault', ['generated', 'version', 'kind', 'organized', 'cursor', 'history_limit'])
def test_unadmitted_recipe_cannot_gain_a_geometry_seal(fault):
    source, _ = recipe('bundle-create', fault == 'organized')
    source = Design.model_validate_json(source.model_dump_json())
    if fault == 'generated':
        source.feature_log[0].params['_generator'] = {'name': 'unreviewed'}
    elif fault == 'version':
        source.feature_log[0].params['_proof_version'] = True
    elif fault == 'kind':
        source.feature_log[0].op_kind = 'sweep'
    elif fault == 'cursor':
        source.feature_log_cursor = 0
    elif fault == 'history_limit':
        source.feature_log *= 33
    with pytest.raises(CaptureLimit if fault == 'history_limit' else CommandContractError):
        revisions.prepare_geometry_revision(source)


def test_storage_scope_is_not_replay_evidence():
    source, _ = recipe('bundle-create', False)
    source = Design.model_validate_json(source.model_dump_json())
    source.feature_log[0].params['length_bp'] += 1
    handle = revisions.prepare_geometry_revision(source)
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history
    report = assess_part_history(revisions.materialize_revision(handle), execute=execute, dependencies=dependencies)
    assert report['status'] != 'verified'


def test_existing_worker_and_evaluation_do_not_accept_geometry_scope(monkeypatch):
    source, _ = recipe('bundle-create', False)
    handle = revisions.prepare_geometry_revision(Design.model_validate_json(source.model_dump_json()))
    monkeypatch.setattr(revisions, '_decoded_exact', lambda *_: pytest.fail('Admission decoded source'))
    with pytest.raises(ValueError, match='admitted storage scope'):
        worker.reserve_input(handle)
    with pytest.raises(HTTPException) as error:
        check_request(handle, EvaluationRequest(operation='verify'), 0,
                      SessionPolicy('registered_only', 'registered-batch-v1', 1))
    assert error.value.detail['code'] == 'immutable_publication_scope'


def test_identical_empty_bytes_do_not_allow_cross_scope_replacement():
    source = create_empty_part('Same bytes', 'HONEYCOMB')
    old = revisions.prepare_revision(source)
    new = revisions.prepare_geometry_revision(source)
    assert old.payload == new.payload
    with pytest.raises(HTTPException) as error:
        immutable_pair(old, new)
    assert error.value.detail['code'] == 'immutable_publication_scope'
    assert immutable_pair(new, revisions.prepare_geometry_revision(source))


def test_batch_permit_cannot_publish_geometry_even_with_matching_digests(context):
    source = create_empty_part('Geometry', 'HONEYCOMB')
    context.design = revisions.prepare_geometry_revision(source)
    candidate = revisions.prepare_geometry_revision(source)
    metadata = revisions.revision_metadata(candidate)
    with pytest.raises(HTTPException) as error:
        issue(context, candidate, authoring_sha256=metadata.authoring_sha256,
              recipe_sha256=metadata.recipe_sha256)
    assert error.value.detail['code'] == 'immutable_publication_scope'


@pytest.mark.parametrize('field,value', [('annotations', [{}]), ('loadouts', [{}]),
    ('protein_assets', [{}]), ('nanoparticles', [{}]), ('input_sources', {'unreviewed': {}})])
def test_geometry_scope_does_not_expand_document_or_asset_preservation(field, value):
    source = create_empty_part('Geometry', 'HONEYCOMB')
    setattr(source, field, value)
    with pytest.raises(CommandContractError):
        revisions.prepare_geometry_revision(source)
