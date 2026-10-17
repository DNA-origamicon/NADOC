"""Private extrusion authority in the existing one-shot permit registry."""

from re import fullmatch
from threading import Event
from time import monotonic
from weakref import ref

from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.api.part_immutable_geometry_scope import SCOPE as STORAGE_SCOPE
from backend.api.part_immutable_storage import require_sealed, immutable_pair

ENABLED = False
SCOPE = 'immutable_extrusion_edit_v1'
EVIDENCE = 'independent_geometry_edit'


def require_policy(context=None, *, doc_id=None):
    if context is not None:
        doc_id = context.doc_id
    effective = policy.resolve(doc_id)
    if context is not None and context.policy_generation != effective.generation:
        permits._refusal('Construction policy changed', code='policy_changed')
    if ENABLED is not True or not effective.strict:
        permits._refusal('Immutable geometry editing is not enabled for this host',
                         code='immutable_geometry_unavailable')
    return effective


def source_metadata(source):
    metadata = require_sealed(source)
    if metadata.scope_tag != STORAGE_SCOPE:
        permits._refusal('Immutable extrusion requires its reviewed source scope')
    return metadata


def admit(doc_id, session, *, request_sha256):
    effective = require_policy(doc_id=doc_id)
    source_metadata(session.design)
    if (type(session.revision) is not int or session.revision < 0
            or type(request_sha256) is not str or fullmatch(r'[0-9a-f]{64}', request_sha256) is None):
        permits._refusal('Extrusion admission requires exact revision and request digest')
    context = permits.AdmissionContext(doc_id, session.identity, ref(session.design), session.revision,
        effective.generation, 'extrusion_edit', request_sha256, SCOPE)
    return permits._register(permits._admissions, permits.EvaluationAdmission(), context)


def _candidate(source, candidate, authoring, recipe):
    before, after = source_metadata(source), source_metadata(candidate)
    immutable_pair(source, candidate)
    if (candidate is source or after.authoring_sha256 != authoring or after.recipe_sha256 != recipe
            or before.history_rows != after.history_rows
            or before.preserved_document_sha256 != after.preserved_document_sha256):
        permits._refusal('Extrusion candidate lost its checked transport or preservation binding')


def issue(admission, candidate, *, request_sha256, authoring_sha256, recipe_sha256, expires, cancelled):
    context = permits.admission_context(admission)
    if context is None or context.scope_tag != SCOPE or context.operation != 'extrusion_edit':
        permits._refusal('Extrusion publication requires its original admission')
    require_policy(context)
    if request_sha256 != context.request_sha256:
        permits._refusal('Extrusion request changed after admission')
    now = monotonic()
    if type(expires) not in {int, float} or not now < expires <= now + permits.MAX_LIFETIME:
        permits._refusal('Extrusion publication expired', code='publication_expired')
    if not isinstance(cancelled, Event) or cancelled.is_set():
        permits._refusal('Extrusion publication cancelled', code='cancelled')
    _candidate(context.source(), candidate, authoring_sha256, recipe_sha256)
    return permits._register(permits._permits, permits.PublicationPermit(), permits._PermitContext(
        context, ref(candidate), authoring_sha256, recipe_sha256, EVIDENCE, expires, cancelled))


def check(context, source, candidate):
    require_policy(context.admission)
    if context.evidence_class != EVIDENCE or context.admission.operation != 'extrusion_edit':
        permits._refusal('Unknown immutable geometry evidence')
    _candidate(source, candidate, context.authoring_sha256, context.recipe_sha256)
