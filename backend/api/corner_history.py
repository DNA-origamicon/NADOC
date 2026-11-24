"""Corner parameter edits use the native source proof and full suffix replay."""

from time import monotonic

from fastapi import HTTPException

from backend.api.corner_guide import corner_guide
from backend.api.corner_projection_worker import project_corner_in_worker
from backend.api.part_corner_commands import CornerCommand, CornerRequest, observe_evaluation
from backend.api.part_recipe_edit import prepare_change


def corner_feature_index(source, feature_id):
    for index, entry in enumerate(source.feature_log):
        if entry.id == feature_id:
            if getattr(entry, 'op_kind', None) != 'corner' or entry.params.get('_proof_version') not in (1, 2, 3):
                break
            return index
    raise HTTPException(409, detail='The selected Corner feature changed. Reopen its editor.')


def evaluate_corner_edit(source, inputs, feature_id, *, on_progress=None, on_guide=None, check_cancel=None):
    index = corner_feature_index(source, feature_id)
    entry = source.feature_log[index]
    request = CornerRequest.model_validate(inputs)
    check = check_cancel or (lambda: None)
    started = monotonic()
    deadline = started + 120
    rebuilding = False
    fit_started = None

    def checkpoint():
        check()
        if monotonic() > deadline:
            raise HTTPException(408, detail='Corner history preview exceeded its time allowance.')

    def status(stage, done):
        nonlocal fit_started
        checkpoint()
        elapsed = monotonic() - started
        # Four observed phases: prove source, rebuild selected Corner, replay
        # suffix/validate, and project Full. Seam work refines the second phase;
        # its completion is not completion of the full history preview. The
        # elapsed-time estimate is deliberately approximate, not a countdown.
        total = 4
        percent = 100 * done / total
        remaining = None
        if done == 3:
            fit_started = monotonic()
        elif 3 < done < 4 and fit_started is not None:
            fraction = (done - 3) / .99
            remaining = (monotonic() - fit_started) * (1 - fraction) / fraction
        elif done == 4:
            remaining = 0.
        if on_progress:
            on_progress({'stage': stage, 'percent': percent, 'done': done, 'total': total,
                         'elapsed_seconds': elapsed,
                         'remaining_seconds': remaining})

    def bind(kind, params, prefix):
        nonlocal rebuilding
        if kind != 'corner':
            raise ValueError('Corner history editor received a different feature kind.')
        status('Preparing corner plane from its recorded source', 1)
        guide = corner_guide(prefix, request.cluster_id, request.parameters())
        if on_guide:
            on_guide(guide)
        rebuilding = True
        return params

    def progress(done, total):
        if rebuilding:
            status('Rebuilding corner seams' if done < total else 'Replaying later features and validating',
                   1 + done / total if total else 2)
        else:
            checkpoint()

    status('Verifying recorded source and later features', 0)
    # prepare_change independently proves the old source and rebuilds recovery
    # data from native commands. It never reads captured output as authority.
    operation_id = CornerCommand.model_validate(entry.params).operation_id
    with observe_evaluation(operation_id, progress, checkpoint):
        candidate, _ = prepare_change(source, source, index, checkpoint,
            params=request.model_dump(mode='json'), input_binder=bind)
    status('Projecting Full preview including later features', 3)
    component = project_corner_in_worker(candidate, on_progress=lambda done, total:
        status('Fitting approved scaffold and staple geometry', 3 + .99 * done / total if total else 3))
    status('Full corner preview ready', 4)
    return {'candidate': component, 'feature_id': feature_id,
            'junction_review_required': True}, candidate
