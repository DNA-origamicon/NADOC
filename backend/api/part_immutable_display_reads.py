"""Bounded sealed-source display reads through the existing immutable worker owner."""
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Event
from time import monotonic
from weakref import ref

from fastapi import HTTPException, Request
from fastapi.responses import ORJSONResponse

from backend.api import state, part_strict_geometry_http as geometry
from backend.api import part_immutable_geometry_worker as worker
from backend.api import part_immutable_worker as transport
from backend.api.part_async_work import thread_call
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_revision import _decoded_exact
from backend.api.part_verification_jobs import Job, supervise
from backend.api.part_verification_worker import failure
from backend.core.part_command_errors import CommandContractError

READ_KINDS = frozenset({'design', 'design-display', 'geometry', 'readiness', 'view-volumes', 'dimensions'})
PATHS = frozenset('/api/design' + ('' if kind == 'design' else '/' + kind) for kind in READ_KINDS if kind != 'design-display')
# Readiness is an observational report even during a navigation handoff.
# Passive reads must never reserve the foreground turn or block history admission.
PASSIVE_READ_KINDS = frozenset({'view-volumes', 'dimensions', 'readiness'})
TIME_BUDGET = 5.0


def _geometry_packet(private, revision):
    from backend.core.design_geometry import _geometry_for_helices, _positions_for_design
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    axes = deformed_helix_axes(private)
    nucleotides = _geometry_for_helices(private, None, measured_positioning=True,
        junction_balance=True, helix_axes=axes)
    _apply_ovhg_rotations_to_axes(private, axes, nucleotides)
    packet = {'nucleotides': nucleotides, 'helix_axes': axes}
    if private.deformations or private.cluster_transforms:
        straight = private.model_copy(update={'deformations': [], 'cluster_transforms': []})
        positions, straight_axes = _positions_for_design(straight,
            measured_positioning=True, junction_balance=True)
        packet.update(straight_positions_by_helix=positions, straight_helix_axes=straight_axes)
    packet.update(design_id=private.id, revision=revision)
    return packet


def project_payload(payload):
    binding = None
    try:
        source, raw, binding = transport._frame(payload, expected_magic=worker.MAGIC)
        operation = json.loads(raw)
        fields = {'read', 'design_id', 'revision'}
        if type(operation) is dict and operation.get('read') == 'readiness':
            fields.add('workspace')
        if (type(operation) is not dict or set(operation) != fields
                or operation['read'] not in READ_KINDS
                or type(operation['design_id']) is not str or not 0 < len(operation['design_id']) <= 512
                or type(operation['revision']) is not int or not 0 <= operation['revision'] < 2**64):
            raise ValueError('Invalid sealed display read')
        if operation['read'] == 'readiness' and (type(operation['workspace']) is not str
                or not 0 < len(operation['workspace']) <= 4096 or not Path(operation['workspace']).is_absolute()):
            raise ValueError('Readiness requires its host-selected workspace')
        private = _decoded_exact(source, lambda: None)
        del payload, source
        if private.id != operation['design_id']:
            raise ValueError('Display source identity changed')
        from backend.api import part_deformation_preview_dto as display
        worker.admit_source(private)
        display._admit(private)
        if operation['read'] == 'view-volumes':
            packet = {'view_volumes': [v.model_dump(mode='json') for v in private.view_volumes],
                      'revision': operation['revision']}
        elif operation['read'] == 'dimensions':
            packet = {'document_id': private.id,
                      'dimensions': [d.model_dump(mode='json') for d in private.dimensions],
                      'revision': operation['revision']}
        elif operation['read'] == 'readiness':
            from backend.core.design_readiness import standard_readiness, finish_readiness
            from backend.core.readiness_jobs import completed_simulation
            from backend.api.part_readiness_evidence import EvidenceReader, EvidenceLimit
            packet = standard_readiness(private)
            if packet['available']:
                try:
                    evidence = completed_simulation(private, Path(operation['workspace']), reader=EvidenceReader())
                except EvidenceLimit as error:
                    raise CommandContractError(str(error), code='readiness_evidence_limit') from error
                packet = finish_readiness(packet, evidence)
            packet.update(context='part', document_id=private.id)
        elif operation['read'] in {'design', 'design-display'}:
            from backend.api.crud import _design_response
            from backend.core.validator import validate_design
            # Full recovery bodies prevent stale browser-cache suffix restoration.
            packet = _design_response(private, validate_design(private), full_feature_log=True,
                normalize_legacy=False, revision=operation['revision'])
            if operation['read'] == 'design-display':
                packet.update(_geometry_packet(private, operation['revision']))
        else:
            packet = _geometry_packet(private, operation['revision'])
        result = {'status': 'ready', 'issues': [], 'candidate': display._bounded(packet)}
    except CommandContractError as error:
        result = {'status': error.status, 'issues': [error.as_issue()]}
    except Exception as error:
        result = failure('display_read_input', error)
    return {'issues': [], 'binding': binding, 'result': result}


def _project(input_name, input_size, output_name):
    transport._run_framed(input_name, input_size, output_name, project_payload)


class DisplayReadWorker(transport.ImmutableEvaluationWorker):
    def __init__(self, ticket, operation):
        parts, self.binding = worker.encode_input(ticket, operation)
        self._initialize_input(parts, _target=_project, _result_limit=worker.MAX_CANDIDATE_BYTES,
                               _name='nadoc-immutable-display-read')


@dataclass
class ReadJob(Job):
    session_identity: str | None = None
    policy_generation: int | None = None


def read(context, kind, cancelled):
    if kind not in READ_KINDS:
        raise HTTPException(422, detail={'code': 'display_read_input'})
    deadline = monotonic() + TIME_BUDGET
    def check():
        geometry._check(context)
        if cancelled.is_set() or monotonic() >= deadline:
            raise HTTPException(409 if cancelled.is_set() else 408,
                detail={'code': 'cancelled' if cancelled.is_set() else 'time_limit'})
    def waiting_check():
        with state._lock:
            check()
    admitted = (_slot.acquire(blocking=False, background=True)
        if kind in PASSIVE_READ_KINDS else
        _slot.acquire_foreground(deadline=deadline, check=waiting_check))
    if not admitted:
        waiting_check()
        raise HTTPException(429, detail={'code': 'geometry_busy'})
    owned = True
    try:
        with state._lock:
            check()
            metadata = geometry.publication.source_metadata(context.source)
            ticket = worker.reserve_input(context.source)
            job = ReadJob(context.doc, ref(context.source), context.revision, cancelled=cancelled,
                session_identity=context.session_identity, policy_generation=context.generation)
        operation = {'read': kind, 'design_id': metadata.design_id, 'revision': context.revision}
        if kind == 'readiness':
            from backend.api.assembly import _WORKSPACE_DIR
            operation['workspace'] = str(_WORKSPACE_DIR.absolute())
        owned = False
        result = supervise(job, ticket, lambda captured: DisplayReadWorker(captured, operation),
                           max(0, deadline - monotonic()))
        if result.get('status') != 'ready':
            issues = result.get('issues', [])
            code = issues[0].get('code', 'display_read_refused') if issues else 'display_read_refused'
            status = 408 if code == 'time_limit' else 413 if code in {
                'preview_limit', 'worker_input_limit', 'result_limit', 'readiness_evidence_limit'} else 409
            raise HTTPException(status, detail={'code': code, 'assessment': result})
        # Bounded JSON encoding also occurs outside the event loop/state lock.
        response = ORJSONResponse(result['candidate'])
        with state._lock:
            check()
        return response
    finally:
        if owned:
            _slot.release()


async def _read(request, kind):
    annotation = kind in {'view-volumes', 'dimensions'}
    allowed = {'doc', 'document_id'} if annotation else {'doc'}
    if kind == 'design':
        allowed = allowed | {'include_geometry'}
    if set(request.query_params) - allowed or any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise HTTPException(422, detail={'code': 'unsupported_display_query'})
    if 'include_geometry' in request.query_params:
        if request.query_params['include_geometry'] != 'true':
            raise HTTPException(422, detail={'code': 'unsupported_display_query'})
        kind = 'design-display'
    context = geometry._context(request)
    if annotation:
        identity = request.query_params.get('document_id')
        if identity is None and kind == 'dimensions':
            raise HTTPException(422, detail={'code': 'document_id_required'})
        if identity is not None:
            with state._lock:
                geometry._check(context)
                if identity != geometry.publication.source_metadata(context.source).design_id:
                    raise HTTPException(409, detail={'code': 'document_identity_mismatch'})
    cancelled, stopped = Event(), Event()
    from backend.api.part_recipe_file_transport import _watch_disconnect
    watcher = asyncio.create_task(_watch_disconnect(request, cancelled, stopped))
    try:
        return await thread_call(read, context, kind, cancelled, cancelled=cancelled)
    finally:
        stopped.set()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


async def design(request: Request):
    return await _read(request, 'design')


async def display_geometry(request: Request):
    return await _read(request, 'geometry')


async def readiness(request: Request):
    return await _read(request, 'readiness')


async def view_volumes(request: Request):
    return await _read(request, 'view-volumes')


async def dimensions(request: Request):
    return await _read(request, 'dimensions')


def definitions():
    return (('/api/design', 'GET', design, 200, 0),
            ('/api/design/geometry', 'GET', display_geometry, 200, 0),
            ('/api/design/readiness', 'GET', readiness, 200, 0),
            ('/api/design/view-volumes', 'GET', view_volumes, 200, 0),
            ('/api/design/dimensions', 'GET', dimensions, 200, 0))
