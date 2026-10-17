"""Isolated immutable extrusion edits preserve native replay and input ownership."""

from copy import deepcopy
import json

import pytest

from backend.api import part_immutable_geometry_worker as worker
from backend.api import part_immutable_worker as batch
from backend.api import part_immutable_revision as revisions
from backend.core.models import Design
from tests.test_part_extrusion_edit_routes import KINDS, recipe
from tests.test_group_organization_history import _verified


def prepared(kind='bundle-create'):
    source, index = recipe(kind, False)
    source = Design.model_validate_json(source.model_dump_json())
    source.feature_log[0].post_state_gz_b64 = 'poisoned saved recovery'
    handle = revisions.prepare_geometry_revision(source)
    operation = {'request': {'operation': 'edit', 'index': index, 'expected_revision': 7,
        'params': {'cell_lengths': [14]} if kind == 'circle-segment' else {'length_bp': 14}},
        'header': {'identity': 'host-edit', 'timestamp': '2026-10-17T00:00:00Z',
            'source_revision': 7, 'source_design_id': source.id,
            'expected_kind': kind, 'expected_feature_id': source.feature_log[index].id,
            'extrusion_recording_version': 1}}
    return source, handle, operation


@pytest.mark.parametrize('kind', KINDS)
def test_real_worker_edits_each_native_family_and_regenerates_suffix(kind):
    source, handle, operation = prepared(kind)
    before = handle.payload
    child = worker.GeometryEvaluationWorker(worker.reserve_input(handle), operation)
    try:
        child.start()
        assert child.wait(5)
        result = child.result()
    finally:
        child.close()
    assert result['status'] == 'ready', result
    candidate = Design.model_validate(result['candidate'])
    _verified(candidate)
    index = operation['request']['index']
    for key, value in operation['request']['params'].items():
        assert candidate.feature_log[index].params[key] == value
    assert [e.id for e in candidate.feature_log] == [e.id for e in source.feature_log]
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    assert handle.payload is before
    revisions.prepare_geometry_revision(candidate)


def test_reservation_and_encoding_retain_bytes_without_parent_materialization(monkeypatch):
    source, handle, operation = prepared()
    def forbidden(*_a, **_kw):
        pytest.fail('Parent decoded or projected a source')
    monkeypatch.setattr(worker, '_decoded_exact', forbidden)
    monkeypatch.setattr(worker, 'visit_inputs', forbidden)
    ticket = worker.reserve_input(handle)
    parts, binding = worker.encode_input(ticket, operation)
    assert ticket.source is handle and parts[1] is handle.payload
    operation['request']['params']['length_bp'] = 99
    assert json.loads(parts[2])['request']['params']['length_bp'] == 14
    assert binding['source_sha256']


@pytest.mark.parametrize('fault', ['design', 'revision', 'feature', 'kind', 'extra_header',
    'operation', 'child', 'missing_revision', 'identity_patch', 'invalid_length'])
def test_unadmitted_request_refuses_before_native_evaluation(monkeypatch, fault):
    _, handle, operation = prepared()
    header, request = operation['header'], operation['request']
    if fault == 'design': header['source_design_id'] = 'another'
    elif fault == 'revision': header['source_revision'] = 8
    elif fault == 'feature': header['expected_feature_id'] = 'another'
    elif fault == 'kind': header['expected_kind'] = 'sweep'
    elif fault == 'extra_header': header['verified'] = True
    elif fault == 'operation': request['operation'] = 'delete'; request.pop('params')
    elif fault == 'child': request['sub_index'] = 0
    elif fault == 'missing_revision': request.pop('expected_revision')
    elif fault == 'identity_patch': request['params']['history_seed'] = 'changed'
    else: request['params']['length_bp'] = True
    monkeypatch.setattr(worker, 'evaluate_native', lambda *_: pytest.fail('Invalid input executed'))
    parts, _ = worker.encode_input(worker.reserve_input(handle), operation)
    result = worker.evaluate_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and 'candidate' not in result


def test_batch_and_geometry_frames_and_reservations_are_not_interchangeable():
    source, handle, operation = prepared()
    ticket = worker.reserve_input(handle)
    parts, _ = worker.encode_input(ticket, operation)
    assert batch.evaluate_payload(b''.join(parts))['result']['status'] == 'unverified'
    with pytest.raises(ValueError):
        batch.encode_input(ticket, operation)
    from tests.test_part_immutable_worker import packed
    _, old_handle, old_parts, _ = packed()
    with pytest.raises(ValueError):
        worker.reserve_input(old_handle)
    assert worker.evaluate_payload(b''.join(old_parts))['result']['status'] == 'unverified'


def test_corrupted_materialized_source_cannot_be_fixed_by_an_edit():
    source, _, operation = prepared()
    source.helices[0].length_bp += 1
    handle = revisions.prepare_geometry_revision(source)
    parts, _ = worker.encode_input(worker.reserve_input(handle), operation)
    result = worker.evaluate_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and 'candidate' not in result


def test_capture_deadline_is_still_enforced_in_child(monkeypatch):
    from itertools import count
    from backend.core import part_capture_inputs
    _, handle, operation = prepared()
    ticks = count()
    monkeypatch.setattr(part_capture_inputs, 'monotonic', lambda: next(ticks))
    parts, _ = worker.encode_input(worker.reserve_input(handle), operation)
    result = worker.evaluate_payload(b''.join(parts))['result']
    assert result['status'] == 'unverified' and 'candidate' not in result
    assert result['issues'][0]['code'] == 'geometry_worker_capture_limit'


def test_result_from_another_operation_is_refused(monkeypatch):
    _, handle, operation = prepared()
    child = worker.GeometryEvaluationWorker(worker.reserve_input(handle), operation)
    try:
        report = {'binding': {**child.binding, 'operation_sha256': '0' * 64},
            'result': {'status': 'ready', 'issues': [], 'candidate': {}}}
        monkeypatch.setattr(child, '_read_result', lambda: deepcopy(report))
        with pytest.raises(ValueError, match='binding'):
            child.result()
    finally:
        child.close()


def test_process_runner_does_not_retain_full_input_during_evaluation(monkeypatch):
    from weakref import ref

    class Payload:
        pass

    class Output:
        buf = bytearray(4096)
        closed = False

        def close(self):
            self.closed = True

    output = Output()
    observed = []
    monkeypatch.setattr(batch, 'SharedMemory', lambda **_: output)
    monkeypatch.setattr(batch, '_owned_input', lambda *_: Payload())

    def evaluate(payload):
        lifetime = ref(payload)
        del payload
        observed.append(lifetime() is None)
        return {'issues': [], 'binding': None, 'result': {'status': 'unverified', 'issues': []}}

    batch._run_framed('input', 1, 'output', evaluate)
    assert observed == [True] and output.closed
