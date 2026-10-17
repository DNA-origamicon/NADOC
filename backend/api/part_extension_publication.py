"""Closed extension authority in the existing one-shot publication registry."""

from re import fullmatch
from threading import Event
from time import monotonic
from weakref import ref

from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as policy
from backend.api.part_group_organization_gate import require_group_edit_enabled
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_group_model import GroupOrganization

SCOPE = "extensions_v1"
EVIDENCE = "owned_extension_edit"
KINDS = frozenset({"extension-upsert", "extension-delete"})
MAX_HISTORY_ROWS = 2_000


def require_policy(context=None, *, doc_id=None):
    if context is not None:
        doc_id = context.doc_id
        if context.policy_generation != policy.resolve(doc_id).generation:
            permits._refusal("Construction policy changed during extension preparation", code="policy_changed")
    require_group_edit_enabled()
    return policy.require_compatibility(doc_id, EVIDENCE)


def source_valid(source):
    return (type(source) is Design and type(source.group_organization) is GroupOrganization
            and type(source.group_organization.version) is int and source.group_organization.version == 1)


def candidate_valid(source, candidate, operation):
    if (not source_valid(source) or type(candidate) is not Design or candidate is source
            or operation not in KINDS or type(candidate.feature_log) is not list
            or len(candidate.feature_log) != len(source.feature_log) + 1
            or len(candidate.feature_log) > MAX_HISTORY_ROWS):
        return False
    if any(getattr(candidate, field) is not getattr(source, field)
           for field in Design.model_fields if field not in {"extensions", "feature_log"}):
        return False
    if any(a is not b for a, b in zip(source.feature_log, candidate.feature_log)):
        return False
    entry = candidate.feature_log[-1]
    return (type(candidate.extensions) is list and type(entry) is SnapshotLogEntry
            and entry.op_kind == operation and type(entry.params) is dict
            and type(entry.params.get("_proof_version")) is int
            and entry.params["_proof_version"] == (2 if operation == "extension-upsert" else 1))


def admit(doc_id, session, *, operation, request_sha256):
    effective = require_policy(doc_id=doc_id)
    if type(operation) is not str or operation not in KINDS:
        permits._refusal("Unknown extension publication operation", code="invalid_operation_admission")
    if type(request_sha256) is not str or fullmatch(r"[0-9a-f]{64}", request_sha256) is None:
        raise ValueError("Extension admission requires a bounded request digest")
    if not source_valid(session.design) or type(session.revision) is not int or session.revision < 0:
        permits._refusal("Extension admission requires its current mutable organized source")
    context = permits.AdmissionContext(doc_id, session.identity, ref(session.design), session.revision,
        effective.generation, operation, request_sha256, SCOPE)
    return permits._register(permits._admissions, permits.EvaluationAdmission(), context)


def issue(admission, candidate, *, request_sha256, expires, cancelled=None):
    context = permits.admission_context(admission)
    if context is None or context.scope_tag != SCOPE or context.operation not in KINDS:
        permits._refusal("Extension publication requires its original host admission")
    require_policy(context)
    if request_sha256 != context.request_sha256 or type(request_sha256) is not str:
        permits._refusal("Extension request changed after admission")
    now = monotonic()
    if type(expires) not in {int, float} or not now < expires <= now + permits.MAX_LIFETIME:
        permits._refusal("Extension publication expired", code="publication_expired")
    if cancelled is not None and (not isinstance(cancelled, Event) or cancelled.is_set()):
        permits._refusal("Extension publication cancelled", code="cancelled")
    if not candidate_valid(context.source(), candidate, context.operation):
        permits._refusal("Extension publication exceeded its extensions/history authority")
    return permits._register(permits._permits, permits.PublicationPermit(), permits._PermitContext(
        context, ref(candidate), None, None, EVIDENCE, expires, cancelled))


def check(context, source, candidate):
    if context.evidence_class != EVIDENCE or not candidate_valid(source, candidate, context.admission.operation):
        permits._refusal("Extension publication lost its checked source or owned fields")
