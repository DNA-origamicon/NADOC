"""Private sealed-source geometry transaction; no HTTP or mutable conversion."""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException

from backend.api import doc_context, state, part_publication_permit as permits
from backend.api import part_immutable_geometry_publication as publication
from backend.api import part_immutable_geometry_worker as worker
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_evaluation_candidate import decode_candidate, CandidateDecodeError
from backend.api.part_evaluation_jobs import EvaluationJob
from backend.api.part_geometry_inputs import KINDS
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_preservation import preservation_digest
from backend.api.part_immutable_revision import prepare_geometry_revision
from backend.api.part_replacement_transaction import publish_replacement
from backend.api.part_source_bound_route import require_current as require_http_source
from backend.api.part_verification_jobs import supervise
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest, ProofBudgetExceeded
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_verification_capture import CaptureLimit

TIME_BUDGET = 5.0


def _refuse(message, code='source_changed', status=409):
    raise HTTPException(status, detail={'code': code, 'detail': message})


def _source(design_id, revision, *, expected_source=None, expected_session_identity=None):
    require_http_source()
    doc = doc_context.get_current_doc()
    publication.require_policy(doc_id=doc)
    session = state._sessions.get(doc)
    if (type(design_id) is not str or not design_id or type(revision) is not int or revision < 0
            or session is None or session.design is None or session.revision != revision):
        _refuse('The captured document revision changed')
    metadata = publication.source_metadata(session.design)
    if metadata.design_id != design_id:
        _refuse('The captured document identity changed')
    if ((expected_source is not None and session.design is not expected_source)
            or (expected_session_identity is not None and session.identity != expected_session_identity)):
        _refuse('The request belongs to an earlier document incarnation')
    return doc, session, metadata


def _current(context, session, deadline, cancelled):
    require_http_source()
    publication.require_policy(context)
    if cancelled.is_set():
        _refuse('Geometry operation cancelled', 'cancelled')
    if monotonic() >= deadline:
        _refuse('Geometry operation deadline exceeded', 'time_limit', 408)
    if (session is None or doc_context.get_current_doc() != context.doc_id
            or state._sessions.get(context.doc_id) is not session
            or not permits.context_matches(context, context.doc_id, session)):
        _refuse('The source, session or revision changed during extrusion editing')


def edit(index, params, *, expected_kind, expected_feature_id, expected_design_id,
         expected_revision, cancelled=None, expected_source=None, expected_session_identity=None):
    return _change('edit', index, params, expected_kind=expected_kind, expected_feature_id=expected_feature_id,
        expected_design_id=expected_design_id, expected_revision=expected_revision, cancelled=cancelled,
        expected_source=expected_source, expected_session_identity=expected_session_identity)


def append(kind, params, *, expected_design_id, expected_revision, cancelled=None,
           expected_source=None, expected_session_identity=None):
    return _change('append', None, params, expected_kind=kind, expected_feature_id=str(uuid4()),
        expected_design_id=expected_design_id, expected_revision=expected_revision, cancelled=cancelled,
        expected_source=expected_source, expected_session_identity=expected_session_identity)


@dataclass(frozen=True, slots=True)
class _StagedGeometry:
    """Private in-process evidence, never a serialized publication capability.

    Only the sealed candidate is retained strongly. Session/source bindings are
    weak; cancellation and the original deadline remain effective after staging.
    No permit is issued until the existing immediate publication path consumes it.
    """
    prepared: object
    admission: object
    context: object
    session: object
    request_hash: str
    authoring_hash: str
    recipe_hash: str
    deadline: float
    cancelled: Event
    design_id: str
    feature_id: str


def _change(action, index, params, **kwargs):
    staged = _stage(action, index, params, **kwargs)
    try:
        with state._lock:
            session = staged.session()
            permit = _issue_staged(staged, session)
            revision = publish_replacement(session, staged.prepared, publication_permit=permit)
        return {'design_id': staged.design_id, 'revision': revision, 'feature_id': staged.feature_id}
    except (CaptureLimit, ProofBudgetExceeded) as error:
        _refuse(str(error), 'geometry_capture_limit', 413)
    except CommandContractError as error:
        raise HTTPException(422, detail=error.as_issue()) from error
    except (ValueError, KeyError, TypeError) as error:
        _refuse(str(error)[:2048], 'invalid_geometry_input', 422)


def _issue_staged(staged, session, *, expires=None):
    """State-lock owned; issue only the original sealed candidate's authority."""
    if type(staged) is not _StagedGeometry or staged.session() is not session:
        _refuse('Staging belongs to another session')
    _current(staged.context, session, staged.deadline, staged.cancelled)
    return publication.issue(staged.admission, staged.prepared, request_sha256=staged.request_hash,
        authoring_sha256=staged.authoring_hash, recipe_sha256=staged.recipe_hash,
        expires=staged.deadline if expires is None else min(staged.deadline, expires), cancelled=staged.cancelled)


def _stage(action, index, params, *, expected_kind, expected_feature_id, expected_design_id,
           expected_revision, cancelled=None, expected_source=None, expected_session_identity=None,
           preview_patch=False, foreground_check=None, expires=None):
    """Evaluate and seal privately, with no publication or canonical mutation.

    Private preview seam; no public staged-commit endpoint. A bound preview may
    reserve one turn behind background reads; its checks run before any capture.
    The returned evidence expires on the original operation/lease deadline.
    """
    if (type(expected_kind) is not str or expected_kind not in KINDS
            or type(expected_feature_id) is not str or not 1 <= len(expected_feature_id) <= 512
            or (cancelled is not None and not isinstance(cancelled, Event))):
        _refuse('An exact geometry target and private cancellation event are required', 'invalid_geometry_input', 422)
    deadline = monotonic() + TIME_BUDGET
    cancelled = cancelled if cancelled is not None else Event()
    if foreground_check is not None:
        if preview_patch is not True or not callable(foreground_check) or expires is None:
            _refuse('Foreground admission requires a bound preview lease', 'invalid_geometry_input', 422)
        deadline = min(deadline, expires)
    def check_admission():
        _preparation_checkpoint(deadline, cancelled)
        if foreground_check is not None:
            foreground_check()
    admitted = (_slot.acquire(blocking=False) if foreground_check is None else
                _slot.acquire_foreground(deadline=deadline, check=check_admission))
    if not admitted:
        if foreground_check is not None:
            check_admission()
        _refuse('A part history operation is already running', 'geometry_busy', 429)
    slot_owned = True
    try:
        check_admission()
        request = EvaluationRequest(operation=action, index=index, params=params,
                                    kind=expected_kind if action == 'append' else None,
                                    expected_revision=expected_revision)
        # Own JSON-valued input before admission. No caller alias survives.
        request = EvaluationRequest.model_validate_json(request.model_dump_json())
        operation = {'request': request.model_dump(mode='json'), 'header': {
            'identity': expected_feature_id if action == 'append' else str(uuid4()), 'timestamp': datetime.now(timezone.utc).isoformat(),
            'source_revision': expected_revision, 'source_design_id': expected_design_id,
            'expected_feature_id': expected_feature_id, 'expected_kind': expected_kind,
            'extrusion_recording_version': 1}}
        if preview_patch:
            if preview_patch is not True or action != 'edit' or expected_kind != 'deformation':
                _refuse('Preview validation requires a deformation edit', 'invalid_geometry_input', 422)
            operation['header']['preview_patch'] = True
        validate_operation_input(operation)
        request_hash = digest(operation)
        with state._lock:
            doc, session, source_metadata = _source(expected_design_id, expected_revision,
                expected_source=expected_source, expected_session_identity=expected_session_identity)
            source = session.design
            admission = publication.admit(doc, session, request_sha256=request_hash,
                operation="extrusion_append" if action == "append" else "extrusion_edit")
            context = permits.admission_context(admission)
            ticket = worker.reserve_input(source)
            _current(context, session, deadline, cancelled)
            job = EvaluationJob(doc, ref(source), expected_revision, cancelled=cancelled,
                admitted_operation=context.operation, session_identity=session.identity,
                admission=admission, request_sha256=request_hash)
        slot_owned = False
        result = supervise(job, ticket, lambda captured: worker.GeometryEvaluationWorker(captured, operation),
                           max(0, deadline - monotonic()))
        if result.get('status') != 'ready':
            issues = result.get('issues', [])
            code = issues[0].get('code', 'geometry_evaluation_refused') if issues else 'geometry_evaluation_refused'
            status = 408 if code == 'time_limit' else 413 if code in {
                'geometry_worker_capture_limit', 'worker_input_limit', 'result_limit'} else 409
            raise HTTPException(status, detail={'code': code, 'assessment': result})
        candidate, authoring_hash, recipe_hash = decode_candidate(result['candidate'])
        candidate = candidate.model_copy(update={'annotations_enabled': source_metadata.annotations_enabled})
        if preservation_digest(candidate, allow_view_volumes=True) != source_metadata.preserved_document_sha256:
            _refuse('Geometry candidate changed preserved document state', 'revision_preservation_changed')
        prepared = prepare_geometry_revision(candidate,
            checkpoint=lambda: _preparation_checkpoint(deadline, cancelled))
        with state._lock:
            _current(context, session, deadline, cancelled)
        return _StagedGeometry(prepared, admission, context, ref(session), request_hash,
            authoring_hash, recipe_hash, deadline, cancelled, source_metadata.design_id, expected_feature_id)
    except CandidateDecodeError as error:
        _refuse(str(error), error.code)
    except (CaptureLimit, ProofBudgetExceeded) as error:
        _refuse(str(error), 'geometry_capture_limit', 413)
    except CommandContractError as error:
        raise HTTPException(422, detail=error.as_issue()) from error
    except (ValueError, KeyError, TypeError) as error:
        _refuse(str(error)[:2048], 'invalid_geometry_input', 422)
    finally:
        if slot_owned:
            _slot.release()


def _preparation_checkpoint(deadline, cancelled):
    if cancelled.is_set():
        _refuse('Geometry operation cancelled', 'cancelled')
    if monotonic() >= deadline:
        _refuse('Geometry operation deadline exceeded', 'time_limit', 408)


def history(action, *, expected_design_id, expected_revision, expected_source=None, expected_session_identity=None):
    """Undo/redo only exact retained immutable handles, without reconstruction."""
    if type(action) is not str or action not in {'undo', 'redo'}:
        _refuse('Unknown immutable history action', 'invalid_geometry_input', 422)
    with state._lock:
        _, session, metadata = _source(expected_design_id, expected_revision,
            expected_source=expected_source, expected_session_identity=expected_session_identity)
        origin, destination = (session.history, session.redo) if action == 'undo' else (session.redo, session.history)
        if not origin:
            _refuse(f'Nothing to {action}', 'empty_history', 404)
        target = origin[-1]
        target_metadata = publication.source_metadata(target)
        if target_metadata.design_id != metadata.design_id:
            _refuse('Retained history belongs to another design')
        if len(session.history) + len(session.redo) > state.MAX_UNDO_STEPS:
            _refuse('Retained history exceeds its step allowance', 'geometry_capture_limit', 413)
        before, undo, redo = session.design, list(session.history), list(session.redo)
        marker = doc_context.current_request_revision()
        entry_marker = doc_context.current_request_feature_log_entry_id()
        try:
            destination.append(before)
            origin.pop()
            session.design = target
            state._bump_revision(session)
            if session.revision != expected_revision + 1 or doc_context.current_request_revision() != session.revision:
                raise RuntimeError('Immutable history did not assign exactly one revision')
        except BaseException:
            session.design, session.revision = before, expected_revision
            session.history.clear()
            session.history.extend(undo)
            session.redo.clear()
            session.redo.extend(redo)
            doc_context.set_request_revision(marker)
            doc_context.set_request_feature_log_entry_id(entry_marker)
            raise
        return {'design_id': metadata.design_id, 'revision': session.revision}


def _project_staged(staged):
    """Project privately within staging's original deadline and authority binding."""
    if type(staged) is not _StagedGeometry:
        _refuse('Projection requires private staged evidence', 'invalid_geometry_input', 422)
    if not _slot.acquire(blocking=False):
        _refuse('A part history operation is already running', 'geometry_busy', 429)
    slot_owned = True
    try:
        with state._lock:
            session = staged.session()
            _current(staged.context, session, staged.deadline, staged.cancelled)
            ticket = worker.reserve_input(staged.prepared)
            job = EvaluationJob(staged.context.doc_id, staged.context.source,
                staged.context.source_revision, cancelled=staged.cancelled,
                session_identity=staged.context.session_identity, admission=staged.admission,
                request_sha256=staged.request_hash)
        operation = {'projection': 'staged_deformation_v1', 'feature_id': staged.feature_id,
                     'design_id': staged.design_id}
        slot_owned = False
        result = supervise(job, ticket, lambda captured: worker.GeometryProjectionWorker(captured, operation),
                           max(0, staged.deadline - monotonic()))
        if result.get('status') != 'ready':
            issues = result.get('issues', [])
            code = issues[0].get('code', 'geometry_projection_refused') if issues else 'geometry_projection_refused'
            status = 408 if code == 'time_limit' else 413 if code in {
                'preview_limit', 'geometry_worker_capture_limit', 'worker_input_limit', 'result_limit'} else 409
            raise HTTPException(status, detail={'code': code, 'assessment': result})
        with state._lock:
            _current(staged.context, session, staged.deadline, staged.cancelled)
        return result['candidate']
    finally:
        if slot_owned:
            _slot.release()
