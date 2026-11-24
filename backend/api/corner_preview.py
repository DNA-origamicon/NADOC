"""Isolated Corner evaluation through the same native recording transaction.

Preview never installs a candidate in the live session. Its candidate retains
the source recipe and a real Corner entry; native Full projection is display
output, not a physical-validity certificate.
"""

from contextvars import copy_context
from time import monotonic
from uuid import uuid4

from backend.api import state
from backend.api.corner_build import build_corner
from backend.api.feature_recording import record_feature
from backend.api.part_corner_commands import CornerCommand
from backend.api.corner_projection_worker import project_corner_in_worker


def evaluate_corner_preview(source, inputs, *, on_progress=None, check_cancel=None):
    """Accept an owned source copy; preserve live state and request context."""
    check = check_cancel or (lambda: None)
    started = monotonic()
    fit_started = None

    def progress(done, total, stage):
        nonlocal fit_started
        check()
        if on_progress:
            elapsed = monotonic() - started
            fraction = done / total if total else 0
            # Routing is much cheaper than the molecular fit. Do not extrapolate
            # its speed into a misleading sub-second estimate for Full geometry.
            remaining = None
            if done == 30:
                fit_started = monotonic()
            elif 30 < done < 100 and fit_started is not None:
                fit_fraction = (done - 30) / 69
                remaining = (monotonic() - fit_started) * (1 - fit_fraction) / fit_fraction
            elif done == 100:
                remaining = 0.
            on_progress({'percent': 100 * fraction, 'done': done, 'total': total, 'stage': stage,
                         'elapsed_seconds': elapsed,
                         'remaining_seconds': remaining})

    def evaluate():
        check()
        command = CornerCommand(**inputs, operation_id=uuid4().hex)
        # Count completed work, not a timer-driven animation: each tested seam
        # length, recording and final projection. The source is already visible
        # in the editor; projecting and sending it again doubles preview data.
        session = state._DesignSession(design=source.model_copy(deep=True))
        progress(0, 0, 'Fitting duplex tips to the corner plane')

        def seam_progress(done, total):
            progress(20 * done / total if total else 20, 100, 'Calculating scaffold and staple seams')

        def build(design):
            return build_corner(design, command, check_cancel=check,
                on_progress=seam_progress)

        candidate, validation, entry = record_feature(session, 'corner',
            f'Corner: {command.angle_deg:g}° at {command.position_bp} bp',
            command.model_dump(mode='json', by_alias=True), build)
        progress(30, 100, 'Fitting approved scaffold and staple geometry')
        after = project_corner_in_worker(candidate, on_progress=lambda done, total:
            progress(30 + 69 * done / total if total else 30, 100,
                     'Fitting approved scaffold and staple geometry'))
        progress(100, 100, 'Full corner preview ready')
        return {'candidate': after, 'feature_id': entry.id,
                'junction_review_required': True, '_validation': validation}, candidate

    # record_feature sets request revision/entry ContextVars. The detached
    # session and copied context prevent those stamps leaking into the host.
    return copy_context().run(evaluate)
