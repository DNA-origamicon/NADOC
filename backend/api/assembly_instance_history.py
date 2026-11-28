"""Selected-instance history host for the ordinary native part evaluator."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.api import assembly_state, state
from backend.api.assembly_command_replay import command_params
from backend.api.assembly_recorded_mutation import apply_recorded_change
from backend.api.part_evaluation import EvaluationRequest as PartRequest, evaluate as evaluate_part
from backend.core.models import Design


class InstanceHistoryChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['edit', 'delete', 'suppress', 'reorder']
    design_id: str = Field(min_length=1, max_length=512)
    feature_id: str = Field(min_length=1, max_length=512)
    child_id: str | None = Field(default=None, min_length=1, max_length=512)
    params: dict | None = None
    suppressed: StrictBool | None = None
    destination: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def operation_fields(self):
        required = {'edit': 'params', 'suppress': 'suppressed', 'reorder': 'destination'}.get(self.operation)
        for key in ('params', 'suppressed', 'destination'):
            if (getattr(self, key) is not None) != (key == required):
                raise ValueError('Supply only the fields required by the selected part history operation')
        if self.child_id is not None and self.operation not in {'edit', 'delete'}:
            raise ValueError('Suppression and reorder operate on whole history rows')
        from backend.core.part_operation_input import validate_operation_input
        validate_operation_input(self.params)
        return self


def record_change(instance_id, body: InstanceHistoryChange):
    """Authoring command invoked by the public evaluation-job host and replay.

    Source change and constraint propagation finish privately before the ordinary
    assembly recorder publishes a complete command. No part session is installed.
    """
    from backend.api.assembly import (_find_instance, _load_design_from_source,
        _assembly_source_path, _patch_instance_design, PatchInstanceDesignRequest)
    from backend.api import part_proof_commands
    from backend.core.part_history_contract import assess_part_history
    from backend.api.part_group_organization_gate import require_live_design

    def change():
        assembly = assembly_state.get_or_404()
        if assembly.feature_log_cursor != -1:
            raise HTTPException(409, detail='Return to current assembly history before editing an instance.')
        instance = _find_instance(assembly, instance_id)
        source = _load_design_from_source(instance.source, _assembly_source_path(assembly))
        require_live_design(source)
        state._assert_active_loadout_editable(source)
        if source.id != body.design_id:
            raise HTTPException(409, detail='Selected instance source design changed.')
        matches = [index for index, row in enumerate(source.feature_log) if row.id == body.feature_id]
        if len(matches) != 1:
            raise HTTPException(409, detail='Selected part feature identity is missing or ambiguous.')
        index, child = matches[0], None
        if body.child_id is not None:
            row = source.feature_log[index]
            children = [i for i, entry in enumerate(getattr(row, 'children', [])) if entry.id == body.child_id]
            if len(children) != 1:
                raise HTTPException(409, detail='Selected part child identity is missing or ambiguous.')
            child = children[0]
        revision = assembly_state.revision()
        request = PartRequest(operation=body.operation, index=index, sub_index=child,
            params=body.params, suppressed=body.suppressed, destination=body.destination,
            expected_revision=revision)
        result = evaluate_part(source, {'request': request.model_dump(mode='json'),
            'header': {'source_revision': revision, 'source_design_id': source.id}})
        if result.get('status') != 'ready':
            raise HTTPException(409, detail={'message': 'Selected part history cannot regenerate.',
                                            'assessment': result, 'issues': result.get('issues', [])})
        candidate = Design.model_validate(result['candidate'])
        proof = assess_part_history(candidate, execute=part_proof_commands.execute_long,
                                    dependencies=part_proof_commands.dependencies)
        if proof['status'] not in {'verified', 'reproduced_import'}:
            raise HTTPException(409, detail={'message': 'Selected part candidate did not verify.', 'assessment': proof})
        _patch_instance_design(instance_id, PatchInstanceDesignRequest(content=candidate.to_json()))

    return apply_recorded_change(change, op_kind='assembly-instance-history-change',
        label=f'{body.operation.capitalize()} part feature', params=command_params(body, instance_id=instance_id))
