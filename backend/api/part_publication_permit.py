"""Private, identity-registered capabilities for exact candidate publication.

These capabilities stay in the trusted host. JSON labels and similarly shaped
Python objects confer no authority. All document comparisons run under state's
lock; the small registry lock never calls back into state. No solver, whole-model
copy or candidate digest runs at the publication boundary.
"""

from dataclasses import dataclass
from re import fullmatch
from threading import Event, Lock
from time import monotonic
from weakref import WeakKeyDictionary, ref

from fastapi import HTTPException

from backend.api import part_publication_policy as policy


MAX_CAPABILITIES = 64
MAX_LIFETIME = 900.0
_lock = Lock()
_admissions = WeakKeyDictionary()
_permits = WeakKeyDictionary()


class EvaluationAdmission:
    """Opaque host handle; its authority lives only in the private registry."""
    __slots__ = ("__weakref__",)


class PublicationPermit:
    __slots__ = ("__weakref__",)


@dataclass(frozen=True)
class AdmissionContext:
    doc_id: str
    session_identity: str
    source: object
    source_revision: int
    policy_generation: int
    operation: str
    request_sha256: str
    scope_tag: str | None


@dataclass(frozen=True)
class _PermitContext:
    admission: AdmissionContext
    candidate: object
    authoring_sha256: str | None
    recipe_sha256: str | None
    evidence_class: str
    expires: float
    cancelled: Event | None


def _refusal(detail, *, code="invalid_publication_permit"):
    raise HTTPException(409, detail={"code": code, "detail": detail})


def _register(registry, handle, context):
    with _lock:
        if len(registry) >= MAX_CAPABILITIES:
            raise HTTPException(429, detail={"code": "publication_admission_limit",
                "detail": "Too many live host publication capabilities"})
        registry[handle] = context
    return handle


def admission_context(admission):
    if type(admission) is not EvaluationAdmission:
        return None
    with _lock:
        return _admissions.get(admission)


def admit_evaluation(doc_id, session, *, operation, request_sha256):
    """Lock-owned admission after capture and exact live-source revalidation."""
    effective = policy.require_evaluation(doc_id, operation)
    if operation == "repair" and getattr(session.design, "group_organization", None) is not None:
        return admit_organized_recipe(doc_id, session, operation=operation, request_sha256=request_sha256)
    if operation not in {"verify", "selection", "append", "edit", "delete", "repair", "batch"}:
        _refusal("Unknown evaluation operation", code="invalid_operation_admission")
    if type(request_sha256) is not str or fullmatch(r"[0-9a-f]{64}", request_sha256) is None:
        raise ValueError("Admission requires the canonical bounded request digest")
    if session.design is None or type(session.revision) is not int or session.revision < 0:
        _refusal("Admission needs a captured live source", code="invalid_evaluation_context")
    context = AdmissionContext(doc_id, session.identity, ref(session.design), session.revision,
        effective.generation, operation, request_sha256, "registered_batch_v1" if operation == "batch" else None)
    return _register(_admissions, EvaluationAdmission(), context)


def context_matches(context, doc_id, session, *, include_source=True):
    return (context is not None and context.doc_id == doc_id and session is not None
        and context.session_identity == session.identity
        and context.policy_generation == policy.resolve(doc_id).generation
        and (not include_source or (context.source() is session.design and context.source_revision == session.revision)))


def _group_operation(operation):
    from backend.core.part_group_organization import KINDS
    return type(operation) is str and (operation in KINDS or operation in {"cluster_op", "visibility-update"})


def _group_source(source, operation):
    from backend.core.models import Design
    from backend.core.part_group_model import GroupOrganization

    if type(source) is not Design:
        return False
    organization = source.group_organization
    if operation == "group-organize":
        return organization is None
    return (type(organization) is GroupOrganization
        and type(organization.version) is int and organization.version == 1)


def _group_candidate(source, candidate):
    from backend.core.models import Design
    from backend.core.part_group_model import GroupOrganization

    if type(source) is not Design or type(candidate) is not Design or candidate is source:
        return False
    organization = candidate.group_organization
    return (candidate.id == source.id and type(organization) is GroupOrganization
        and type(organization.version) is int and organization.version == 1)


def _require_group_policy(context):
    from backend.api.part_group_organization_gate import require_group_edit_enabled

    if context.policy_generation != policy.resolve(context.doc_id).generation:
        _refusal("Construction policy changed before the group edit", code="policy_changed")
    policy.require_compatibility(context.doc_id, "owned_group_edit")
    require_group_edit_enabled()


def admit_group_edit(doc_id, session, *, operation, request_sha256):
    """Lock-owned admission for an owned ordinary group or placement edit.

    The group host owns command validation, source capture/CAS and the native
    builder. This records their origin, not independent historical proof.
    """
    from backend.api.part_group_organization_gate import require_group_edit_enabled

    effective = policy.require_compatibility(doc_id, "owned_group_edit")
    require_group_edit_enabled()
    if not _group_operation(operation):
        _refusal("Unknown owned group operation", code="invalid_operation_admission")
    if type(request_sha256) is not str or fullmatch(r"[0-9a-f]{64}", request_sha256) is None:
        raise ValueError("Admission requires the canonical bounded request digest")
    if (not _group_source(session.design, operation)
            or type(session.revision) is not int or session.revision < 0):
        _refusal("Group admission needs its current mutable source", code="invalid_evaluation_context")
    context = AdmissionContext(doc_id, session.identity, ref(session.design), session.revision,
        effective.generation, operation, request_sha256, "group_organization_v1")
    return _register(_admissions, EvaluationAdmission(), context)


def issue_group_edit_permit(admission, candidate, *, request_sha256, expires):
    """Bind the exact candidate after the owned group host validates its result.

    There is no client candidate, generic callback, native-proof claim or new
    registry. The same permit transaction consumes this only after publication.
    """
    context = admission_context(admission)
    if (context is None or context.scope_tag != "group_organization_v1"
            or not _group_operation(context.operation)):
        _refusal("A group publication requires its original host admission")
    _require_group_policy(context)
    if type(request_sha256) is not str or request_sha256 != context.request_sha256:
        _refusal("The group command does not match its host admission")
    now = monotonic()
    if type(expires) not in {int, float} or not now < expires <= now + MAX_LIFETIME:
        _refusal("The group candidate has expired", code="publication_expired")
    source = context.source()
    if not _group_source(source, context.operation) or not _group_candidate(source, candidate):
        _refusal("Group publication needs its distinct owned candidate for the captured part")
    return _register(_permits, PublicationPermit(), _PermitContext(context, ref(candidate),
        None, None, "owned_group_edit", expires, None))


def _require_organized_recipe_policy(context):
    from backend.api.part_group_organization_gate import require_group_edit_enabled

    if context.policy_generation != policy.resolve(context.doc_id).generation:
        _refusal("Construction policy changed before recipe publication", code="policy_changed")
    policy.require_compatibility(context.doc_id, "owned_recipe_rebuild")
    require_group_edit_enabled()


def admit_organized_recipe(doc_id, session, *, operation, request_sha256):
    """Admit named owned recipe hosts; never grant generic edit authority."""
    from backend.api.part_group_organization_gate import require_group_edit_enabled

    effective = policy.require_compatibility(doc_id, "owned_recipe_rebuild")
    require_group_edit_enabled()
    if type(operation) is not str or operation not in {"repair", "deformation_preview", "sweep_preview", "pattern", "extrusion_edit"}:
        _refusal("Unknown owned recipe operation", code="invalid_operation_admission")
    if type(request_sha256) is not str or fullmatch(r"[0-9a-f]{64}", request_sha256) is None:
        raise ValueError("Admission requires the canonical bounded request digest")
    if (not _group_source(session.design, operation)
            or type(session.revision) is not int or session.revision < 0):
        _refusal("Recipe admission needs its organized source", code="invalid_evaluation_context")
    context = AdmissionContext(doc_id, session.identity, ref(session.design), session.revision,
        effective.generation, operation, request_sha256, "organized_recipe_v1")
    return _register(_admissions, EvaluationAdmission(), context)


def issue_organized_recipe_permit(admission, candidate, *, request_sha256, expires, cancelled=None):
    """Bind the candidate after the owned host completes its full recipe rebuild.

    Preview retains its complete source proof. Repair uses its checked explicit
    proposal and independently rebuilt candidate. Neither accepts client geometry
    or treats an ordinary group edit as proof of an entire recipe.
    """
    context = admission_context(admission)
    if (context is None or context.scope_tag != "organized_recipe_v1"
            or context.operation not in {"repair", "deformation_preview", "sweep_preview", "pattern", "extrusion_edit"}):
        _refusal("Recipe publication requires its original owned host admission")
    _require_organized_recipe_policy(context)
    if type(request_sha256) is not str or request_sha256 != context.request_sha256:
        _refusal("The recipe request does not match its host admission")
    now = monotonic()
    if type(expires) not in {int, float} or not now < expires <= now + MAX_LIFETIME:
        _refusal("The recipe candidate has expired", code="publication_expired")
    if cancelled is not None and (not isinstance(cancelled, Event) or cancelled.is_set()):
        _refusal("The recipe candidate was cancelled", code="cancelled")
    source = context.source()
    if not _group_source(source, context.operation) or not _group_candidate(source, candidate):
        _refusal("Recipe publication needs its distinct owned candidate for the captured part")
    return _register(_permits, PublicationPermit(), _PermitContext(context, ref(candidate),
        None, None, "owned_recipe_rebuild", expires, cancelled))


def issue_batch_permit(admission, candidate, *, request_sha256, authoring_sha256, recipe_sha256, expires,
                       cancelled, source_status):
    """Trusted job host calls after its existing exact transport checks.

    Native composition is deliberately distinct from independent cold replay.
    An evaluated imported basis is not admitted by this first public profile.
    """
    context = admission_context(admission)
    if context is None or context.operation != "batch" or context.scope_tag != "registered_batch_v1":
        _refusal("A batch publication requires its original host admission")
    if context.policy_generation != policy.resolve(context.doc_id).generation:
        _refusal("Construction policy changed; evaluate again", code="policy_changed")
    if request_sha256 != context.request_sha256:
        _refusal("The evaluated request does not match its host admission")
    if source_status != "verified":
        _refusal("The registered batch source was not natively reproduced")
    if any(type(value) is not str or fullmatch(r"[0-9a-f]{64}", value) is None
           for value in (authoring_sha256, recipe_sha256)):
        raise ValueError("Publication needs both checked candidate projection digests")
    now = monotonic()
    if type(expires) not in {int, float} or not now < expires <= now + MAX_LIFETIME:
        _refusal("The evaluated candidate has expired", code="publication_expired")
    if not isinstance(cancelled, Event) or cancelled.is_set():
        _refusal("The evaluated candidate was cancelled", code="cancelled")
    source = context.source()
    if source is None or candidate is source:
        _refusal("Publication needs a privately decoded candidate for the captured part")
    from backend.api.part_immutable_storage import immutable_pair, require_sealed

    if immutable_pair(source, candidate):
        meta = require_sealed(candidate)
        if (meta.authoring_sha256 != authoring_sha256 or meta.recipe_sha256 != recipe_sha256
                or not policy.resolve(context.doc_id).strict):
            _refusal("Immutable candidate does not match its checked transport or strict policy",
                     code="immutable_publication_scope")
    elif candidate.id != source.id:
        _refusal("Publication needs a privately decoded candidate for the captured part")
    return _register(_permits, PublicationPermit(), _PermitContext(context, ref(candidate),
        authoring_sha256, recipe_sha256, "registered_composition", expires, cancelled))


def prepare_empty_creation(doc_id, session, *, name, lattice_type):
    """Create the candidate here; this API never accepts an authored Design."""
    if type(name) is not str or not name or len(name) > 1024 or lattice_type not in {"HONEYCOMB", "SQUARE"}:
        raise ValueError("Empty part creation requires a bounded name and supported lattice")
    if session.design is not None:
        _refusal("Close the active part before creating a new empty part", code="part_already_open")
    from backend.core.part_history_contract import create_empty_part

    candidate = create_empty_part(name, lattice_type)
    context = AdmissionContext(doc_id, session.identity, lambda: None, session.revision,
        policy.resolve(doc_id).generation, "create_empty", "", "empty_root_v1")
    permit = _register(_permits, PublicationPermit(), _PermitContext(context, ref(candidate),
        None, None, "explicit_empty_root", monotonic() + MAX_LIFETIME, None))
    return candidate, permit


def admit_empty_creation(doc_id, session):
    """Lock-owned reservation for host-built immutable empty content only."""
    from backend.api.part_immutable_storage import require_empty_session

    require_empty_session(session)
    current = policy.resolve(doc_id)
    if not current.strict:
        _refusal("Immutable empty admission requires strict host policy", code="immutable_publication_scope")
    context = AdmissionContext(doc_id, session.identity, lambda: None, session.revision,
        current.generation, "create_empty", "", "empty_root_v1")
    return _register(_admissions, EvaluationAdmission(), context)


def admit_recovery(doc_id, session, *, request_sha256):
    """Host-only empty-session admission; no public operation selects restore."""
    from backend.api.part_immutable_storage import require_empty_session

    require_empty_session(session)
    current = policy.resolve(doc_id)
    if not current.strict:
        _refusal("Recovery requires strict host policy", code="immutable_publication_scope")
    if type(request_sha256) is not str or fullmatch(r"[0-9a-f]{64}", request_sha256) is None:
        raise ValueError("Recovery admission requires the canonical bounded request digest")
    context = AdmissionContext(doc_id, session.identity, lambda: None, session.revision,
        current.generation, "restore", request_sha256, "strict_recovery_v1")
    return _register(_admissions, EvaluationAdmission(), context)


def issue_recovery_permit(admission, candidate, *, qualification, expires, cancelled):
    from backend.api.part_immutable_recovery import require_qualification
    from backend.api.part_immutable_storage import require_sealed

    context = admission_context(admission)
    if context is None or context.operation != "restore" or context.scope_tag != "strict_recovery_v1":
        _refusal("Recovery needs its original host admission")
    if not policy.resolve(context.doc_id).strict or context.policy_generation != policy.resolve(context.doc_id).generation:
        _refusal("Recovery host policy changed", code="policy_changed")
    require_qualification(qualification, admission, candidate)
    metadata = require_sealed(candidate)
    now = monotonic()
    if type(expires) not in {int, float} or not now < expires <= now + MAX_LIFETIME:
        _refusal("Recovery candidate expired", code="publication_expired")
    if not isinstance(cancelled, Event) or cancelled.is_set():
        _refusal("Recovery was cancelled", code="cancelled")
    return _register(_permits, PublicationPermit(), _PermitContext(context, ref(candidate),
        metadata.authoring_sha256, metadata.recipe_sha256, "independent_cold_replay", expires, cancelled))


def prepare_admitted_empty(admission, *, name, lattice_type):
    """Build/seal outside state lock; this API accepts no authored model/bytes."""
    from backend.api.part_immutable_revision import prepare_revision
    from backend.core.part_history_contract import create_empty_part

    context = admission_context(admission)
    if context is None or context.operation != "create_empty" or context.scope_tag != "empty_root_v1":
        _refusal("Empty preparation needs its original private creation admission")
    if type(name) is not str or not name.strip() or len(name) > 1024 or lattice_type not in {"HONEYCOMB", "SQUARE"}:
        raise ValueError("Empty part creation requires a bounded name and supported lattice")
    candidate = prepare_revision(create_empty_part(name, lattice_type))
    permit = _register(_permits, PublicationPermit(), _PermitContext(context, ref(candidate),
        None, None, "explicit_empty_root", monotonic() + MAX_LIFETIME, None))
    return candidate, permit


def check_publication(permit, *, doc_id, session, candidate):
    """Lock-owned precondition; nothing is consumed until publication succeeds."""
    if type(permit) is not PublicationPermit:
        _refusal("A registered-only replacement needs a host publication permit")
    with _lock:
        context = _permits.get(permit)
    if context is None:
        _refusal("The publication permit is unknown or already consumed")
    if context.admission.policy_generation != policy.resolve(doc_id).generation:
        _refusal("Construction policy changed; evaluate again", code="policy_changed")
    if not context_matches(context.admission, doc_id, session) or context.candidate() is not candidate:
        _refusal("The publication does not match its source, session or exact candidate")
    check_liveness(context)
    from backend.api.part_immutable_storage import immutable_pair, is_immutable, require_sealed, require_empty_session

    if context.admission.scope_tag == "group_organization_v1":
        if (context.evidence_class != "owned_group_edit"
                or not _group_operation(context.admission.operation)
                or not _group_source(session.design, context.admission.operation)
                or not _group_candidate(session.design, candidate)):
            _refusal("Group publication lost its checked source or candidate binding")
    elif context.admission.scope_tag == "organized_recipe_v1":
        if (context.evidence_class != "owned_recipe_rebuild"
                or context.admission.operation not in {"repair", "deformation_preview", "sweep_preview", "pattern", "extrusion_edit"}
                or not _group_source(session.design, context.admission.operation)
                or not _group_candidate(session.design, candidate)):
            _refusal("Recipe publication lost its checked source or candidate binding")
    elif context.admission.scope_tag == "registered_batch_v1":
        from backend.api.part_batch_publication_scope import admit_batch_source
        from backend.core.part_command_errors import CommandContractError

        # These are fixed typed checks, not caller-supplied callbacks. They also
        # apply to compatibility batch jobs; ordinary legacy edits are separate.
        try:
            if immutable_pair(session.design, candidate):
                meta = require_sealed(candidate)
                if (not policy.resolve(doc_id).strict or meta.authoring_sha256 != context.authoring_sha256
                        or meta.recipe_sha256 != context.recipe_sha256):
                    _refusal("Immutable publication lost its checked transport binding", code="immutable_publication_scope")
            else:
                admit_batch_source(session.design)
                admit_batch_source(candidate)
        except CommandContractError as error:
            raise HTTPException(422, detail=error.as_issue()) from error
    elif context.admission.scope_tag == "strict_recovery_v1":
        metadata = require_sealed(candidate)
        require_empty_session(session)
        if (not policy.resolve(doc_id).strict or context.evidence_class != "independent_cold_replay"
                or metadata.authoring_sha256 != context.authoring_sha256
                or metadata.recipe_sha256 != context.recipe_sha256):
            _refusal("Recovery lost its checked candidate binding", code="immutable_publication_scope")
    elif context.admission.scope_tag == "empty_root_v1":
        if is_immutable(candidate):
            require_sealed(candidate)
            require_empty_session(session)
            if not policy.resolve(doc_id).strict:
                _refusal("Immutable publication requires strict policy", code="immutable_publication_scope")
    else:
        _refusal("This publication scope has no host contract")
    return context


def check_liveness(context):
    """Repeat after undo preparation, immediately before assignment."""
    if context.admission.scope_tag == "group_organization_v1":
        _require_group_policy(context.admission)
    elif context.admission.scope_tag == "organized_recipe_v1":
        _require_organized_recipe_policy(context.admission)
    if monotonic() >= context.expires:
        _refusal("The publication permit expired", code="publication_expired")
    if context.cancelled is not None and context.cancelled.is_set():
        _refusal("The evaluated candidate was cancelled", code="cancelled")


def consume_publication(permit, context):
    """Call inside the replacement rollback bracket, after assigning revision."""
    with _lock:
        if _permits.get(permit) is not context:
            _refusal("The publication permit is unknown or already consumed")
        del _permits[permit]
