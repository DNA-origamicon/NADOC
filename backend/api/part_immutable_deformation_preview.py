"""Sealed historical preview adapter; ownership stays in the shared lease host."""
from dataclasses import dataclass
import json
from time import monotonic

from fastapi import HTTPException

from backend.api import state, part_immutable_geometry_publication as authority
from backend.api import part_immutable_geometry_worker as geometry
from backend.api import part_immutable_worker as transport
from backend.api.part_evaluation_jobs import EvaluationJob
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_geometry_host import TIME_BUDGET
from backend.api.part_immutable_revision import StrictPartRevision, _decoded_exact
from backend.api.part_verification_jobs import supervise
from backend.api.part_verification_worker import failure
from backend.core.part_capture_inputs import visit_inputs
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from backend.core.part_verification_capture import CaptureLimit


@dataclass(frozen=True, slots=True)
class Prepared:
    deformation_id: str  # No mutable prefix, source or display retained in the lease.
    feature_index: int


def is_source(source):
    return type(source) is StrictPartRevision


def source_id(source):
    return authority.source_metadata(source).design_id


def evaluate_payload(payload):
    from backend.api import part_deformation_preview as native, part_deformation_preview_dto as display
    from backend.api import part_preview_family_work as family
    binding = None
    try:
        raw, operation, binding = transport._frame(payload, expected_magic=geometry.MAGIC)
        del payload
        operation = json.loads(operation)
        if (type(operation) is not dict or set(operation) != {'action', 'feature_id', 'params', 'include_geometry', 'envelope'}
                or operation['action'] not in {'prepare', 'evaluate'}
                or type(operation['feature_id']) is not str or not 0 < len(operation['feature_id']) <= 256
                or type(operation['params']) is not dict or type(operation['include_geometry']) is not bool
                or (operation['action'] == 'prepare' and operation['params'])):
            raise ValueError('Invalid immutable historical preview operation')
        private = _decoded_exact(raw, lambda: None)
        del raw
        geometry.admit_source(private)
        state._assert_active_loadout_editable(private)
        captured = visit_inputs(private, max_nodes=30_000, max_bytes=2_000_000,
            seconds=.025, preserve_entry_types=True, copy_inputs=False, retain_owned=True)
        prepared = native.prepare_from_capture(captured, operation['feature_id'])
        feature_index = next(i for i, row in enumerate(private.feature_log) if row.id == operation['feature_id'])
        del captured, private
        evaluated = native.evaluate(prepared, operation['params'])
        envelope = display._envelope({**operation['envelope'], 'deformation_id': prepared.deformation_id})
        if operation['action'] == 'prepare':
            packet = family.prepare_display('deformation', prepared, evaluated, envelope=envelope)
        else:
            packet = family.evaluate_display('deformation', prepared, evaluated,
                include_geometry=operation['include_geometry'], envelope=envelope)
        result = {'status': 'ready', 'issues': [], 'candidate': packet, 'feature_index': feature_index}
    except CommandContractError as error:
        result = {'status': error.status, 'issues': [error.as_issue()], 'native_editable': False}
    except CaptureLimit as error:
        result = failure('preview_capture_limit', error)
    except Exception as error:
        result = failure('immutable_preview_input', error)
    return {'issues': [], 'binding': binding, 'result': result}


def _evaluate(input_name, input_size, output_name):
    transport._run_framed(input_name, input_size, output_name, evaluate_payload)


class PreviewWorker(transport.ImmutableEvaluationWorker):
    def __init__(self, ticket, operation):
        parts, self.binding = geometry.encode_input(ticket, operation)
        self._initialize_input(parts, _target=_evaluate, _result_limit=geometry.MAX_CANDIDATE_BYTES,
                               _name='nadoc-immutable-deformation-preview')


def run(host, entry, sequence, *, action, params=None, include_geometry=True):
    deadline = min(monotonic() + TIME_BUDGET, entry.expires)
    def check():
        host._current(entry, sequence)
        if entry.cancelled.is_set() or monotonic() >= deadline:
            raise HTTPException(409 if entry.cancelled.is_set() else 408,
                detail={'code': 'cancelled' if entry.cancelled.is_set() else 'time_limit'})
    if not _slot.acquire_foreground(deadline=deadline, check=check):
        check()
        raise HTTPException(429, detail='A part history operation is already running')
    owned = True
    try:
        check()
        operation = {'action': action, 'feature_id': entry.request.feature_id,
            'params': {} if params is None else params, 'include_geometry': include_geometry,
            'envelope': host._envelope(entry, sequence)}
        request_hash = digest(operation)
        with state._lock:
            session = host._source_current(entry)
            ticket = geometry.reserve_input(session.design)
            admission = authority.admit(entry.doc, session, request_sha256=request_hash)
            job = EvaluationJob(entry.doc, entry.source, entry.request.expected_revision,
                cancelled=entry.cancelled, session_identity=entry.session_identity,
                admission=admission, request_sha256=request_hash)
        owned = False
        result = supervise(job, ticket, lambda captured: PreviewWorker(captured, operation),
                           max(0, deadline - monotonic()))
        if result.get('status') != 'ready':
            issues = result.get('issues', [])
            code = issues[0].get('code', 'immutable_preview_refused') if issues else 'immutable_preview_refused'
            status = 408 if code == 'time_limit' else 413 if code in {
                'preview_limit', 'preview_capture_limit', 'worker_input_limit', 'result_limit'} else 409
            raise HTTPException(status, detail={'code': code, 'assessment': result})
        check()
        packet = result['candidate']
        index = result.get('feature_index')
        if type(index) is not int or index < 0:
            raise HTTPException(409, detail='Missing bound historical feature index')
        return packet, Prepared(packet['deformation_id'], index)
    finally:
        if owned:
            _slot.release()



def apply(host, entry, prepared, request):
    from backend.api import part_immutable_geometry_host as geometry_host

    host._current(entry, request.request_sequence)
    staged = geometry_host._stage('edit', prepared.feature_index, request.params,
        expected_kind='deformation', expected_feature_id=request.feature_id,
        expected_design_id=request.expected_design_id, expected_revision=request.expected_revision,
        expected_source=entry.source(), expected_session_identity=entry.session_identity,
        cancelled=entry.cancelled, preview_patch=True, expires=entry.expires,
        foreground_check=lambda: host._current(entry, request.request_sequence))
    host._current(entry, request.request_sequence)
    return host._publish(entry, request, staged.prepared, min(staged.deadline, entry.expires),
        staged.admission, staged.request_hash, immutable_staged=staged)
