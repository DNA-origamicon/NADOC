"""Instance-owned part commands through native recording and assembly transactions."""
from contextvars import copy_context
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.api import assembly_state, state
from backend.api.assembly_command_replay import command_params, output_id, output_created_at
from backend.api.assembly_recorded_mutation import apply_recorded_change
from backend.api.feature_recording import record_feature


def record_overhang(instance_id, body, *, overhang_id=None):
    from backend.api.assembly import (_find_instance, _load_design_from_source,
        _assembly_source_path, _replace_instance_design, _assembly_response)
    from backend.api.crud import OverhangExtrudeRequest, _build_overhang_extrude
    from backend.api.overhang_patch import OverhangPatchRequest
    from backend.api.part_overhang_patch import patch
    from backend.api.part_group_organization_gate import require_live_design

    extruding = overhang_id is None
    if extruding:
        body = body.model_copy(update={'history_seed': body.history_seed or str(uuid4())})
    part_id, created = output_id('part_feature_id'), output_created_at()
    kind = 'assembly-instance-overhang-extrude' if extruding else 'assembly-instance-overhang-patch'
    params = command_params(body, instance_id=instance_id, part_feature_id=part_id, created_at=created,
                            **({} if extruding else {'overhang_id': overhang_id}))
    result = {}

    def evaluate():
        assembly = assembly_state.get_or_404()
        instance = _find_instance(assembly, instance_id)
        source = _load_design_from_source(instance.source, _assembly_source_path(assembly))
        require_live_design(source)
        state._assert_active_loadout_editable(source)
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise HTTPException(409, detail='Return to current part history before editing an instance.')
        if any(row.id == part_id for row in source.feature_log):
            raise HTTPException(409, detail='Part feature output identity already exists.')
        session = state._DesignSession(design=source.model_copy(deep=True))
        if extruding:
            native = OverhangExtrudeRequest.model_validate(body.model_dump())
            part_kind, label = 'overhang-extrude', f'Overhang extrude: {body.length_bp} bp'
            inputs = native.model_dump(mode='json')
            build = lambda design: _build_overhang_extrude(design, native)
        else:
            native = OverhangPatchRequest.model_validate(body.model_dump(exclude_unset=True))
            part_kind, label = 'overhang-sequence', 'Overhang patch'
            inputs = {**native.model_dump(mode='json', exclude_unset=True), 'overhang_id': overhang_id}
            build = lambda design: patch(design, overhang_id, native)[0]
        try:
            # Shared recorder owns reconciliation, validation and real recovery
            # entries. Detached session/context preserve the open part document.
            with state._lock:
                updated, _, _ = copy_context().run(record_feature, session, part_kind, label, inputs, build,
                    entry_id=part_id, timestamp=datetime.fromtimestamp(created, timezone.utc).isoformat())
        except ValueError as error:
            raise HTTPException(400, detail=str(error)) from error
        _replace_instance_design(assembly, instance, updated)
        result['design'] = updated

    candidate = apply_recorded_change(evaluate, op_kind=kind,
        label='Extrude instance overhang' if extruding else 'Patch instance overhang', params=params)
    return {**_assembly_response(candidate), 'design': result['design'].model_dump(mode='json')}
