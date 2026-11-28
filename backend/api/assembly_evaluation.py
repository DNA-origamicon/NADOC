"""Private verified recipe changes; publication belongs to the job host."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, Field, model_validator
from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.assembly_history_verification import verify
from backend.api.assembly_history_regeneration import regenerate
from backend.api.assembly_history_edit import edited_inputs
from backend.api.assembly_instance_history import InstanceHistoryChange
from backend.core.assembly_history_contract import create_empty_assembly, FIELD_ROLES
from backend.core.part_history_proof import digest


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['suppress', 'reorder', 'edit', 'delete', 'instance-history']
    expected_assembly_id: str = Field(min_length=1, max_length=512)
    expected_revision: StrictInt
    feature_id: str | None = Field(default=None, min_length=1, max_length=512)
    instance_id: str | None = Field(default=None, min_length=1, max_length=512)
    instance_change: InstanceHistoryChange | None = None
    suppressed: StrictBool | None = None
    destination: StrictInt | None = None
    inputs: dict | None = None

    @model_validator(mode='after')
    def operation_fields(self):
        if self.operation == 'instance-history':
            if (self.instance_id is None or self.instance_change is None or self.feature_id is not None
                    or any(value is not None for value in (self.suppressed, self.destination, self.inputs))):
                raise ValueError('Instance history requires its selected instance and native change only')
            return self
        if self.feature_id is None or self.instance_id is not None or self.instance_change is not None:
            raise ValueError('Assembly history requires its selected assembly feature only')
        required = {'suppress': 'suppressed', 'reorder': 'destination', 'edit': 'inputs'}.get(self.operation)
        for name in ('suppressed', 'destination', 'inputs'):
            if (getattr(self, name) is not None) != (name == required):
                raise ValueError('Supply only the fields required by the selected history operation')
        return self


def evaluate(source, operation):
    request = EvaluationRequest.model_validate(operation)
    if source.id != request.expected_assembly_id:
        raise ValueError('Evaluation belongs to another assembly')
    assessment = verify(source, allow_prefix=request.operation == 'suppress')
    if assessment['status'] not in {'verified', 'reproduced_import'}:
        return {**assessment, 'source_assessment': assessment}
    if source.feature_log_cursor != -1:
        # Qualifying a displayed prefix does not certify unseen commands. Replay
        # the unchanged full recipe before proposing a history change; recovery
        # snapshots are neither read nor promoted to proof inputs.
        root = create_empty_assembly(source.recipe_root.initial_name).model_copy(update={'id': source.id})
        try:
            with assembly_state.isolated_evaluation(root):
                restored = regenerate(root, source.feature_log)
        except HTTPException as error:
            return {'status': 'failed', 'native_editable': False, 'issues': [
                {'code': 'source_regeneration_failed', 'detail': error.detail}], 'source_assessment': assessment}
        full_assessment = verify(restored)
        if full_assessment['status'] not in {'verified', 'reproduced_import'}:
            return {**full_assessment, 'source_assessment': assessment}
        assessment = {**full_assessment, 'displayed_prefix_assessment': assessment}
    if request.operation == 'instance-history':
        from backend.api.assembly_instance_history import record_change
        try:
            with assembly_state.isolated_evaluation(source):
                candidate = record_change(request.instance_id, request.instance_change)
        except HTTPException as error:
            return {'status': 'failed', 'native_editable': False, 'issues': [
                {'code': 'instance_history_failed', 'detail': error.detail}], 'source_assessment': assessment}
        return _qualified_candidate(source, candidate, request, assessment)
    log = list(source.feature_log)
    positions = [i for i, row in enumerate(log) if row.id == request.feature_id]
    if len(positions) != 1:
        raise ValueError('Feature identity does not resolve uniquely')
    index = positions[0]
    entry = log[index]
    params = None
    if request.operation == 'suppress':
        if entry.suppressed == request.suppressed:
            raise ValueError('Feature already has that suppression state')
        log[index] = entry.model_copy(update={'suppressed': request.suppressed})
    elif request.operation == 'reorder':
        if not 0 <= request.destination < len(log) or request.destination == index:
            raise ValueError('Invalid or unchanged feature destination')
        log.insert(request.destination, log.pop(index))
    elif request.operation == 'delete':
        log.pop(index)
    else:
        params = edited_inputs(entry, request.inputs)
    root = create_empty_assembly(source.recipe_root.initial_name).model_copy(update={'id': source.id})
    try:
        with assembly_state.isolated_evaluation(root):
            candidate = regenerate(root, log, edited_id=entry.id if request.operation == 'edit' else None,
                                   edited_params=params)
    except HTTPException as error:
        return {'status': 'failed', 'native_editable': False, 'issues': [
            {'code': 'regeneration_failed', 'detail': error.detail}], 'source_assessment': assessment}
    return _qualified_candidate(source, candidate, request, assessment)


def _qualified_candidate(source, candidate, request, assessment):
    proof = verify(candidate)
    if proof['status'] not in {'verified', 'reproduced_import'}:
        return {**proof, 'source_assessment': assessment}
    # Display preferences are not replay inputs, but history edits preserve them.
    candidate = candidate.model_copy(update={name: getattr(source, name) for name, role in FIELD_ROLES.items() if role == 'presentation'})
    before = {i.id: i for i in source.instances}
    candidate.instances = [i.model_copy(update={name: getattr(before[i.id], name) for name in ('visible', 'representation')})
                           if i.id in before else i for i in candidate.instances]
    data = candidate.model_dump(mode='json')
    return {'status': 'ready', 'native_editable': proof['native_editable'], 'issues': [],
            'source_assessment': assessment, 'assessment': proof, 'candidate': data,
            'candidate_sha256': digest(data), 'request_sha256': digest(request.model_dump(mode='json'))}
