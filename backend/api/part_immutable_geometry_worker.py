"""Closed extrusion-edit byte worker; no live document or publication authority."""

import json
from time import monotonic

from backend.api import part_immutable_worker as transport
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES, evaluate_native
from backend.api.part_geometry_inputs import KINDS, normalize, normalize_creation
from backend.api.part_immutable_geometry_scope import SCOPE, admit_source
from backend.api.part_immutable_revision import _decoded_exact
from backend.api.part_verification_worker import failure
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_capture_inputs import visit_inputs
from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_verification_capture import CaptureLimit


MAGIC = b"NADOC-G1"
_HEADER_FIELDS = frozenset({"identity", "timestamp", "source_revision", "source_design_id",
    "expected_feature_id", "expected_kind", "extrusion_recording_version"})


def reserve_input(source):
    return transport._reserve_input(source, scope=SCOPE)


def encode_input(ticket, operation):
    return transport._encode_input(ticket, operation, scope=SCOPE, magic=MAGIC)


def _project(source_bytes, operation_bytes):
    operation = json.loads(operation_bytes)
    validate_operation_input(operation)
    if (type(operation) is not dict or set(operation) != {"request", "header"}
            or type(operation['header']) is not dict or set(operation['header']) != _HEADER_FIELDS):
        raise ValueError('Invalid geometry worker operation envelope')
    header = operation['header']
    request = EvaluationRequest.model_validate(operation['request'])
    if (request.operation not in {'edit', 'append'} or request.sub_index is not None
            or type(request.expected_revision) is not int
            or type(header['source_revision']) is not int
            or request.expected_revision != header['source_revision']
            or type(header['extrusion_recording_version']) is not int
            or header['extrusion_recording_version'] != 1
            or header['expected_kind'] not in KINDS
            or any(type(header[key]) is not str or not header[key] for key in
                   ('identity', 'timestamp', 'source_design_id', 'expected_feature_id'))):
        raise ValueError('Invalid geometry worker captured context')
    private = _decoded_exact(source_bytes, lambda: None)
    if private.id != header['source_design_id']:
        raise CommandContractError('The selected extrusion source changed', code='source_changed')
    if request.operation == 'append':
        if request.kind != header['expected_kind'] or header['expected_feature_id'] != header['identity']:
            raise ValueError('Invalid extrusion append identity')
        # Validate before native evaluation, but keep public inputs: the append
        # evaluator derives receipts from the independently regenerated prefix.
        normalize_creation(request.kind, request.params, identity=header['identity'])
    else:
        if request.index >= len(private.feature_log):
            raise CommandContractError('The selected extrusion source changed', code='source_changed')
        entry = private.feature_log[request.index]
        if (type(entry) is not SnapshotLogEntry or entry.id != header['expected_feature_id']
                or entry.op_kind != header['expected_kind']):
            raise CommandContractError('The selected extrusion feature changed', code='source_changed')
        values = normalize(entry.op_kind, entry.params, request.params)
        operation['request'] = request.model_copy(update={'params': values}).model_dump(mode='json')
    deadline = monotonic() + .025
    admit_source(private)
    captured = visit_inputs(private, max_nodes=30_000, max_bytes=2_000_000,
        seconds=max(0, deadline - monotonic()), preserve_entry_types=True,
        copy_inputs=False, retain_owned=True)
    return captured, operation


def decode_input(payload):
    source, operation, binding = transport._frame(payload, expected_magic=MAGIC)
    captured, operation = _project(source, operation)
    return captured, operation, binding


def evaluate_payload(payload):
    binding = None
    try:
        source, operation, binding = transport._frame(payload, expected_magic=MAGIC)
        del payload
        captured, operation = _project(source, operation)
        del source
        result = evaluate_native(captured, operation)
        if result.get('status') == 'ready':
            # Independent schema/scope validity is required in addition to replay.
            admit_source(Design.model_validate(result['candidate']))
    except CommandContractError as error:
        result = {'status': error.status, 'issues': [error.as_issue()], 'native_editable': False}
    except CaptureLimit as error:
        result = failure('geometry_worker_capture_limit', error)
    except Exception as error:
        result = failure('geometry_worker_input', error)
    return {'issues': [], 'binding': binding, 'result': result}


def _evaluate(input_name, input_size, output_name):
    transport._run_framed(input_name, input_size, output_name, evaluate_payload)


class GeometryEvaluationWorker(transport.ImmutableEvaluationWorker):
    def __init__(self, ticket, operation):
        parts, self.binding = encode_input(ticket, operation)
        self._initialize_input(parts, _target=_evaluate, _result_limit=MAX_CANDIDATE_BYTES,
                               _name='nadoc-immutable-extrusion-evaluation')
