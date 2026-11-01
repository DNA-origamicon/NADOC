"""Library bytes survive document boundaries; placement never snapshots atoms."""
from copy import deepcopy
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import routes_design_interchange as interchange, routes_protein as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_protein_library_sources import SOURCE_KEY, original_input
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import import_root
from backend.core.part_input_sources import EmbeddedResolver, InputSource
from backend.core.part_verification_capture import capture
from tests.test_protein import _SYNTH_PDB, _SYNTH_PROT_DNA, _design_with_overhang


@pytest.fixture
def client(monkeypatch):
    identity = 'library-input-' + str(uuid4())
    token = set_current_doc(identity)
    prior = dict(state._protein_library)
    design = _design_with_overhang()
    design.overhangs[0].sequence = 'ACGTACGT'
    design.recipe_root = import_root(design)
    state.load_design(design)
    monkeypatch.setattr(interchange, 'NATIVE_FREE_IMPORT_ENABLED', True)
    app = FastAPI()
    app.include_router(routes.router, prefix='/api')
    app.include_router(interchange.router, prefix='/api')
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.drop_doc(identity)
        state._protein_library.clear()
        state._protein_library.update(prior)
        reset_current_doc(token)


def upload(client, content=_SYNTH_PDB, auto=False, **changes):
    response = client.post('/api/design/import/pdb-auto' if auto else '/api/design/protein/import',
        json={'content': content, 'name': 'original', **({'protein_placement': 'library'} if auto else {}), **changes})
    assert response.status_code == (200 if auto else 201), response.text
    return response.json()['protein']['id'] if auto else response.json()['id']


@pytest.mark.parametrize('auto', [False, True])
def test_library_only_keeps_exact_input_without_canonical_edit(client, auto):
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    raw = 'REMARK original non-atom text\n' + _SYNTH_PDB
    identity = upload(client, raw, auto)
    command, data = original_input(state.get_protein_asset(identity))
    assert data == raw.encode() and command.name == 'original'
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == depth
    # Existing portable asset metadata uses the ordinary descriptor/envelope.
    copy = state.get_protein_asset(identity).model_validate_json(state.get_protein_asset(identity).model_dump_json())
    assert original_input(copy) == (command, data)


def test_equal_atoms_with_different_uploaded_bytes_or_filtering_do_not_deduplicate(client):
    first = upload(client, auto=True)
    assert upload(client, auto=True) == first
    assert upload(client, 'REMARK provenance differs\n' + _SYNTH_PDB, auto=True) != first
    mixed = upload(client, _SYNTH_PROT_DNA, auto=True, remove_dna_from_protein=True)
    assert original_input(state.get_protein_asset(mixed))[1] == _SYNTH_PROT_DNA.encode()
    assert original_input(state.get_protein_asset(mixed))[0].exclude_dna is True


@pytest.mark.parametrize('conjugate', [False, True])
def test_cross_document_placement_pins_input_one_undo_and_cold_replay(client, conjugate):
    identity = upload(client)
    library = state.get_protein_asset(identity)
    before = deepcopy(state.get_or_404())
    revision, depth = state.revision(), state.undo_depth()
    response = client.post('/api/design/protein/conjugate' if conjugate else '/api/design/protein/attachments',
        json={'asset_id': identity, 'overhang_id': 'oh_5p', 'conjugation_atom_serial': 9})
    assert response.status_code == 201, response.text
    design = state.get_or_404()
    assert [row.op_kind for row in design.feature_log] == ['protein-import', 'protein-conjugate' if conjugate else 'protein-attach']
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    assert SOURCE_KEY not in design.protein_assets[0].metadata
    assert state.get_protein_asset(identity) is library
    source = InputSource.model_validate(design.feature_log[0].params['source'])
    assert EmbeddedResolver(design.input_sources)(source) == _SYNTH_PDB.encode()
    if conjugate:
        assert response.json()['element_validation']['valid']
        assert response.json()['binder_strand_id'] == design.protein_attachments[0].binder_strand_id
    state.undo()
    assert state.get_or_404() == before
    state.redo()
    assert state.get_or_404() == design
    saved = Design.model_validate_json(design.model_dump_json())
    state.remove_protein_asset(identity)
    for row in saved.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = 'poisoned recovery'
    worker = VerificationWorker(capture(saved))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result['status'] == 'reproduced_import', result
    finally:
        worker.close()
    edited = prepare_change(saved, capture(saved), 0, lambda: None, params={'name': 'Renamed'})[0]
    assert edited.protein_assets[0].name == 'Renamed'
    assert edited.protein_attachments == saved.protein_attachments
    assert assess_part_history(edited, execute=execute, dependencies=dependencies)['status'] == 'reproduced_import'
    preview = prepare_change(saved, capture(saved), 0, lambda: None)
    assert preview['needs_cascade_decision']


@pytest.mark.parametrize('damage', ['missing', 'bytes', 'identity', 'placement', 'stale'])
def test_bad_library_input_or_placement_is_atomic(client, damage):
    identity = upload(client)
    asset = state.get_protein_asset(identity)
    record = asset.metadata[SOURCE_KEY]
    if damage == 'missing':
        asset.metadata.pop(SOURCE_KEY)
    elif damage == 'bytes':
        record['input']['data_b64'] = 'AAAA'
    elif damage == 'identity':
        record['command']['asset_id'] = 'another'
    before, revision, depth, library = (state.get_or_404().model_dump_json(), state.revision(), state.undo_depth(),
                                      deepcopy(state._protein_library))
    response = client.post('/api/design/protein/conjugate', json={'asset_id': identity,
        'overhang_id': 'absent' if damage == 'placement' else 'oh_5p', 'conjugation_atom_serial': 9,
        'expected_revision': revision - 1 if damage == 'stale' else revision})
    expected = {404} if damage == 'placement' else {409, 422}
    assert response.status_code in expected, response.text
    assert state.get_or_404().model_dump_json() == before and state.revision() == revision
    assert state.undo_depth() == depth and state._protein_library == library


def test_library_placement_after_native_bundle_preserves_replay_sources(client):
    from tests.test_part_pending_np_connections import native_prefix
    source = native_prefix.__wrapped__()
    state.load_design(source)
    identity = upload(client)
    target = next(o.id for o in source.overhangs if not o.auxiliary_endpoint)
    response = client.post('/api/design/protein/attachments', json={
        'asset_id': identity, 'overhang_id': target, 'conjugation_atom_serial': 9})
    assert response.status_code == 201, response.text
    portable = Design.model_validate_json(state.get_or_404().model_dump_json())
    assert len(portable.input_sources) == 1
    state.remove_protein_asset(identity)
    worker = VerificationWorker(capture(portable))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result['status'] == 'reproduced_import', result
    finally:
        worker.close()
