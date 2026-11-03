"""Ordinary asset entry points use the existing cancellable recipe job owner."""
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import state, part_evaluation_capture as rollout


def enabled(kind):
    flag = rollout.BIOTIN_APPEND_ENABLED if kind in {'nanoparticle-biotin-dna', 'streptavidin-coating'} else rollout.NP_FITTING_APPEND_ENABLED
    # Documents without a declared recipe retain their existing compatibility
    # route. Never manufacture an import root from the current solved output.
    with state._lock:
        source = state._session().design
        return flag and source is not None and source.recipe_root is not None


def start(kind, params, *, expected_revision=None, expected_design_id=None):
    from backend.api.part_evaluation_jobs import start as start_job
    with state._lock:
        session = state._session()
        source = session.design
        if source is None:
            raise HTTPException(404, 'Open a part before editing an asset.')
        if ((expected_revision is not None and session.revision != expected_revision)
                or (expected_design_id is not None and source.id != expected_design_id)):
            raise HTTPException(409, 'The part changed before asset editing.')
        state._assert_active_loadout_editable(source)
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise HTTPException(409, 'Return to the latest history position before editing assets.')
        revision, identity = session.revision, session.identity
    try:
        return start_job({'operation': 'append', 'kind': kind, 'params': params, 'expected_revision': revision},
            expected_source=source, expected_session_identity=identity)
    except ValidationError as error:
        raise HTTPException(422, detail={'code': 'invalid_asset_inputs', 'detail': str(error)}) from error


def coating_patch(particle_id, body, *, expected_revision=None, expected_design_id=None):
    values = body.model_dump(exclude_unset=True)
    if 'coating' in values:
        action = 'remove' if values['coating'] is None else 'set'
        choices = {k: v for k, v in values.items() if k != 'coating' or v is not None}
    elif body.diameter_nm is not None:
        action, choices = 'repack', values
    else:
        action, choices = 'move', values
    return start('streptavidin-coating', {'action': action, 'nanoparticle_id': particle_id, **choices},
        expected_revision=expected_revision, expected_design_id=expected_design_id)
