"""Closed organized connection append/edit host; no generic publication authority."""

from copy import deepcopy

from pydantic import ValidationError

from backend.api.part_connection_organization import split
from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import validate_operation_input

CONTEXT = {'version': 1, 'removed_hosts': 'follow_material'}


def normalize(kind, inputs, *, previous=None):
    from backend.api.part_proof_commands import dependencies
    if kind != 'overhang-bulk' or type(inputs) is not dict:
        raise CommandContractError('Select a native connection command', code='invalid_connection_input')
    validate_operation_input(inputs)
    if previous is None:
        values = deepcopy(inputs)
    else:
        split(kind, previous)
        action = previous['action']
        editable = ({'patch'} if action == 'connection-version-patch' else
                    {'name', 'overhang_a_seq', 'overhang_b_seq', 'bridge_length', 'bridge_seq', 'applied'}
                    if action in {'connection-version-create', 'connection-version-connect-direct', 'connection-version-connect-linker'}
                    else set())
        if any(key not in editable and value != previous.get(key) for key, value in inputs.items()):
            raise CommandContractError('Connection identity and reference choices require explicit repair',
                                       code='invalid_connection_input')
        values = {**deepcopy(previous), **deepcopy(inputs)}
    split(kind, values)
    if not dependencies(kind, values).known:
        raise CommandContractError('Connection inputs lack their closed native contract', code='invalid_connection_input')
    return values


def require_context(source, request, header):
    if (type(header.get('connection_recording_version')) is not int
            or header['connection_recording_version'] != 1
            or any(key in header for key in ('pattern_recording_version', 'extrusion_recording_version', 'routing_recording_version'))
            or source.group_organization is None
            or type(header.get('source_revision')) is not int
            or header['source_revision'] != request.expected_revision
            or header.get('source_design_id') != source.id):
        raise CommandContractError('Connection work lacks its owned captured context', code='invalid_capture_context')
    if request.operation == 'append' and request.kind == 'overhang-bulk':
        normalize(request.kind, request.params)
    elif request.operation == 'edit' and request.sub_index is None and request.index < len(source.feature_log):
        entry = source.feature_log[request.index]
        if (entry.feature_type != 'snapshot' or entry.op_kind != 'overhang-bulk'
                or entry.id != header.get('expected_feature_id')):
            raise CommandContractError('Connection edit target changed', code='source_changed')
        normalize(entry.op_kind, request.params, previous=entry.params)
    else:
        raise CommandContractError('Unknown owned connection operation', code='invalid_operation_admission')


def evaluate(source, operation, *, executor=None, dependency_resolver=None):
    from backend.api.part_evaluation import EvaluationRequest, _evaluate
    try:
        request = EvaluationRequest.model_validate(operation['request'])
        require_context(source, request, operation['header'])
        result = _evaluate(source, operation, executor=executor, dependency_resolver=dependency_resolver)
        if result.get('status') == 'ready':
            # Validate in the isolated worker before transferring or publishing
            # an invalid native result. The host still validates its own decode.
            from backend.core.models import Design
            try:
                Design.model_validate(result['candidate'])
            except ValidationError as error:
                raise CommandContractError(str(error)[:2048], code='invalid_connection_output') from error
        return result
    except CommandContractError as error:
        return {'status': error.status, 'issues': [error.as_issue()], 'native_editable': False}
    except (ValueError, KeyError, TypeError) as error:
        return {'status': 'failed', 'issues': [{'code': 'invalid_connection_input', 'detail': str(error)[:2048]}],
                'native_editable': False}


def create(inputs, *, expected_design_id, expected_revision, cancelled=None):
    from backend.api.part_ordinary_recipe_recording import run_connection
    return run_connection(inputs, expected_design_id=expected_design_id,
                          expected_revision=expected_revision, cancelled=cancelled)


def edit(index, params, *, expected_feature_id, expected_design_id, expected_revision, cancelled=None):
    from backend.api.part_ordinary_recipe_recording import run_connection
    return run_connection(params, index=index, expected_feature_id=expected_feature_id,
                          expected_design_id=expected_design_id, expected_revision=expected_revision, cancelled=cancelled)
