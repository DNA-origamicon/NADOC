"""Undo recovery bodies are reused only when their content matches exactly."""
from copy import deepcopy

from backend.api.history_response_cache import body_digest, reuse_history_bodies


def test_same_id_changed_or_cleared_body_is_authoritative():
    old = {'id': 'entry', 'post_state_gz_b64': 'newer'}
    for body in ['older', '']:
        payload = {'design': {'feature_log': [{'id': 'entry', 'post_state_gz_b64': body}]}}
        reuse_history_bodies(payload, {'entry': body_digest(old)})
        assert payload['design']['feature_log'][0]['post_state_gz_b64'] == body
        assert payload['feature_log_reused_entry_ids'] == []


def test_matching_bodies_are_omitted_without_mutating_canonical_history():
    entry = {'id': 'entry', 'post_state_gz_b64': 'snapshot',
             'children': [{'id': 'child', 'diff_added_b64': 'bases'}]}
    payload = {'design': {'feature_log': [deepcopy(entry)]}}
    reuse_history_bodies(payload, {'entry': body_digest(entry)})
    wire = payload['design']['feature_log'][0]
    assert wire['post_state_gz_b64'] == ''
    assert wire['children'][0]['diff_added_b64'] == '1'
    assert payload['feature_log_reused_entry_ids'] == ['entry']
    assert entry['post_state_gz_b64'] == 'snapshot'


def test_cold_client_receives_complete_history():
    payload = {'design': {'feature_log': [{'id': 'entry', 'post_state_gz_b64': 'snapshot'}]}}
    expected = deepcopy(payload)
    reuse_history_bodies(payload, {})
    assert payload == expected


def test_child_body_changes_invalidate_reuse():
    entry = {'id': 'entry', 'children': [{'id': 'child', 'diff_modified_b64': 'old'}]}
    payload = {'design': {'feature_log': [deepcopy(entry)]}}
    payload['design']['feature_log'][0]['children'][0]['diff_modified_b64'] = 'new'
    reuse_history_bodies(payload, {'entry': body_digest(entry)})
    assert payload['feature_log_reused_entry_ids'] == []


def test_route_undo_redo_preserve_prior_objects_and_full_restored_bodies():
    import json
    from backend.api import crud, state
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.api.history_response_cache import HistoryCacheRequest
    from tests.conftest import valid_overhang_sites

    token = set_current_doc('__test_history_body_cache')
    try:
        crud.create_bundle(crud.BundleRequest(
            cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42))
        site = valid_overhang_sites(state.get_or_404())[0]
        crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=8))
        target = state.get_or_404().overhangs[0]
        before = state.get_or_404().model_dump()
        crud.patch_overhang(target.id, crud.OverhangPatchRequest(sequence='ACGT'))
        edited_object = state.get_or_404()
        edited = edited_object.model_dump()
        known = {e['id']: body_digest(e) for e in edited['feature_log']}
        wire = json.loads(crud.undo_design(HistoryCacheRequest(history_body_digests=known)).body)
        assert edited_object.model_dump() == edited
        assert state.get_or_404().strands == crud.Design.model_validate(before).strands
        for entry in wire['design']['feature_log']:
            restored = next(e for e in state.get_or_404().model_dump()['feature_log'] if e['id'] == entry['id'])
            if entry['id'] in wire['feature_log_reused_entry_ids']:
                assert body_digest(restored) == known[entry['id']]
            else:
                assert entry == restored
        undone = state.get_or_404()
        undone_dump = undone.model_dump()
        crud.redo_design()
        assert undone.model_dump() == undone_dump
        assert state.get_or_404().strands == edited_object.strands
    finally:
        state.close_session()
        reset_current_doc(token)
