"""Private mutable-part leases shared by three closed native editor families.

One prepared prefix per document, two globally; one nonqueued computation at a
time. Native work and proof run without state/catalog locks. Apply reserves the
commit under the state lock, then releases the catalog lock before the existing
undo/publication transaction. Its full-source snapshot cost is not qualified by
the input capture budget. Ordinary deadlines remain cooperative; fixed numerical
transform histories use the existing isolated worker and separate bounded phases.
"""

from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock, Timer
from time import monotonic
from typing import Literal
import sys
from uuid import UUID, uuid4
from weakref import ref

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from backend.api import doc_context, state
from backend.api import part_group_organization_gate as group_gate
from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as construction_policy
from backend.api import part_preview_family_work as family_work
from backend.api.part_deformation_preview import (
    PreparedCreation, prepare_creation_append,
)
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_recipe_publication import preserve_document_state
from backend.core.part_verification_capture import CaptureLimit, capture


MAX_SESSIONS = 2
MAX_TOMBSTONES = 16
TTL_SECONDS = 60.0
APPLY_SECONDS = 5.0
_lock = Lock()
_work_slot = BoundedSemaphore(1)
_entries = {}
_tombstones = OrderedDict()


class Origin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    expected_design_id: str = Field(min_length=1, max_length=256)
    expected_revision: StrictInt = Field(ge=0)
    feature_id: str = Field(min_length=1, max_length=256)

    @field_validator("preview_id")
    @classmethod
    def nonce(cls, value):
        return str(UUID(value))


class Creation(Origin):
    mode: Literal["create"]
    type: Literal["bend", "twist"]
    targets: list[dict] | None  # Required null is explicit legacy whole/placement scope.
    cluster_ids: list[str]

    @field_validator("feature_id")
    @classmethod
    def future_feature(cls, value):
        return str(UUID(value))


class Change(Origin):
    lease_id: str
    request_sequence: StrictInt = Field(ge=1, le=2**31 - 1)
    params: dict = Field(default_factory=dict)

    @field_validator("lease_id")
    @classmethod
    def lease(cls, value):
        return str(UUID(value))


class Cancel(Origin):
    lease_id: str | None = None

    @field_validator("lease_id")
    @classmethod
    def lease(cls, value):
        return None if value is None else str(UUID(value))


class Evaluation(Change):
    include_geometry: StrictBool = True


class Status(Cancel):
    lease_id: str


@dataclass
class _Entry:
    doc: str
    request: Origin
    lease_id: str
    source: object  # weakref only; never a retained live Design/session
    session_identity: str
    policy_generation: int
    expires: float
    prepared: object = None
    timer: object = None
    sequence: int = 0
    phase: str = "preparing"
    expired_during_commit: bool = False
    identity: dict | None = None  # closed scalar family identity, retained with receipts
    publication: dict | None = None  # bounded scalar receipt; never a model/report
    applying_sequence: int | None = None
    family: str = "deformation"
    numerical: bool = False
    computation: object = None
    payload: dict | None = None
    failure: dict | None = None


def _conflict(detail, code="preview_conflict"):
    raise HTTPException(409, detail={"code": code, "detail": detail})


def _family(value):
    if type(value) is not str or value not in family_work.FAMILIES:
        raise HTTPException(422, detail={"code": "invalid_preview_family", "detail": "Unknown preview family"})
    return value


def _parse(model, value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        validate_operation_input(value)
        return model.model_validate(deepcopy(value))
    except (ValueError, TypeError) as error:
        raise HTTPException(422, detail={"code": "invalid_preview_request", "detail": str(error)}) from error


@contextmanager
def _mapped_errors():
    try:
        yield
    except CaptureLimit as error:
        raise HTTPException(413, detail={"code": "preview_capture_limit", "detail": str(error)}) from error
    except CommandContractError as error:
        status = 413 if error.code == "preview_limit" else 422
        raise HTTPException(status, detail=error.as_issue()) from error


def _remember_cancel(entry):
    key = (entry.doc, entry.family, entry.request.preview_id)
    _tombstones[key] = monotonic() + TTL_SECONDS
    _tombstones.move_to_end(key)
    while len(_tombstones) > MAX_TOMBSTONES:
        _tombstones.popitem(last=False)


def _remove(entry, *, remember=True):
    """Catalog-lock owned; cancel does not wait for timer/native completion."""
    if _entries.get(entry.doc) is entry:
        _entries.pop(entry.doc)
    if remember:
        _remember_cancel(entry)
    entry.prepared = entry.payload = entry.failure = None
    if entry.computation is not None:
        entry.computation.cancelled.set()
    if entry.timer is not None:
        entry.timer.cancel()
        entry.timer = None


def _prune():
    now = monotonic()
    for entry in list(_entries.values()):
        if entry.expires <= now and entry.phase != "committing":
            _remove(entry)
    for key, expiry in list(_tombstones.items()):
        if expiry <= now:
            _tombstones.pop(key)


def _expire(entry, deadline=None):
    with _lock:
        if deadline is not None and (entry.expires != deadline or monotonic() < deadline):
            return
        if _entries.get(entry.doc) is entry:
            if entry.phase == "committing":
                entry.expired_during_commit = True
            else:
                _remove(entry)
        # Commit completion either retains a scalar receipt until the original
        # expiry, or removes an already expired entry; rollback also prunes it.


def _renew(entry, seconds):
    """Catalog-lock owned; old callbacks cannot retire a later phase."""
    if entry.timer is not None:
        entry.timer.cancel()
    entry.expires = monotonic() + seconds
    entry.expired_during_commit = False
    deadline = entry.expires
    entry.timer = Timer(seconds, lambda: _expire(entry, deadline))
    entry.timer.daemon = True
    entry.timer.start()


def _matches_request(entry, request, family):
    return entry.family == family and all(getattr(entry.request, name) == getattr(request, name) for name in (
        "preview_id", "expected_design_id", "expected_revision", "feature_id",
    )) and (getattr(request, "lease_id", None) in {None, entry.lease_id})


def _catalog_current(entry, sequence=None):
    if (_entries.get(entry.doc) is not entry or entry.expires <= monotonic()
            or (sequence is not None and sequence != entry.sequence)):
        _conflict("The preview expired, was cancelled, or was superseded")


def _source_current(entry):
    """State-lock owned; never creates a closed document/session."""
    if doc_context.get_current_doc() != entry.doc:
        _conflict("The request belongs to a different document")
    session = state._sessions.get(entry.doc)
    policy = _source_policy(entry.doc, None if session is None else session.design, entry.family)
    if policy.generation != entry.policy_generation:
        _conflict("Construction policy changed; open a new preview", "policy_changed")
    expected_revision = (entry.publication["revision"] if entry.phase == "applied"
                         else entry.request.expected_revision)
    if (session is None or session.identity != entry.session_identity
            or session.revision != expected_revision
            or session.design is not entry.source() or type(session.design) is not Design
            or session.design.id != entry.request.expected_design_id):
        _conflict("The preview's original part or session changed", "source_changed")
    state._assert_active_loadout_editable(session.design)
    return session


def _source_policy(doc, source, family="deformation"):
    """Only this owned preview host may read staged organization for editing.

    This grants no generic mutation/publication bypass: Apply still needs its
    full recipe rebuild and exact candidate-bound host permit.
    """
    if type(source) is Design and source.group_organization is not None:
        selected = construction_policy.require_compatibility(doc, f"{family}_preview")
        group_gate.require_group_edit_enabled()
        return selected
    return state._require_compatibility_write(f"{family}_preview", doc_id=doc)


def _current(entry, sequence=None):
    # The only nested lock order is state -> catalog. No native work here.
    with state._lock:
        session = _source_current(entry)
        with _lock:
            _catalog_current(entry, sequence)
        return session.revision


def _envelope(entry, sequence, *, prepared=None):
    # Measure before projection; the caller conservatively charges lease time
    # from request start. The final origin check still refuses actual expiry.
    identity = (family_work.identity_fields(entry.family, prepared) if prepared is not None
                else entry.identity or family_work.identity_fields(entry.family))
    return {**entry.request.model_dump(), "lease_id": entry.lease_id,
            "doc_id": entry.doc, **identity,
            "request_sequence": sequence,
            "remaining_seconds": max(0, entry.expires - monotonic())}


def _finish(entry, sequence, payload, *, prepared=None):
    """Accept an owned result against both origins in one short lock window."""
    with state._lock:
        _source_current(entry)
        with _lock:
            _catalog_current(entry, sequence)
            if prepared is not None:
                entry.prepared, entry.phase = prepared, "ready"
                entry.identity = family_work.identity_fields(entry.family, prepared)
            return payload


def _claim(request, *, applying=False, family="deformation"):
    _family(family)
    admitted = False
    with _lock:
        _prune()
        entry = _entries.get(doc_context.get_current_doc())
        if entry is None or not _matches_request(entry, request, family):
            _conflict("The preview lease does not match this document/request")
        if entry.phase != "ready":
            _conflict("The preview is still preparing or committing")
        if request.request_sequence <= entry.sequence:
            _conflict("The preview request was superseded")
        if entry.computation is not None:
            # A completed async result becomes ready just before its supervisor
            # releases work ownership. Do not destroy its retrieval packet when
            # an immediate edit loses that race; no edit has been admitted yet.
            admitted = _work_slot.acquire(blocking=False)
            if not admitted:
                raise HTTPException(429, detail={"code": "preview_busy", "detail": "A preview operation is already running"})
        # A newer request invalidates any older in-flight response even when
        # the work slot is busy. The caller retries with a new sequence number.
        entry.sequence = request.request_sequence
        entry.payload = entry.failure = None
        entry.computation = None
        if applying:
            entry.applying_sequence = request.request_sequence
        prepared = entry.prepared
    if not admitted and not _work_slot.acquire(blocking=False):
        if applying:
            with _lock:
                if entry.applying_sequence == request.request_sequence:
                    entry.applying_sequence = None
        raise HTTPException(429, detail={"code": "preview_busy", "detail": "A preview operation is already running"})
    return entry, prepared


def prepare(value, *, family="deformation"):
    """Reserve a caller-known nonce, capture under lock, then prepare privately."""
    return _prepare(_parse(Origin, value), family=_family(family))


def prepare_create(value):
    """Prepare fixed source controls without creating a temporary operation."""
    return _prepare(_parse(Creation, value))


def _prepare(request, *, family="deformation"):
    if not _work_slot.acquire(blocking=False):
        raise HTTPException(429, detail={"code": "preview_busy", "detail": "A preview operation is already running"})
    entry = None
    transferred = False
    try:
        with _mapped_errors():
            with state._lock:
                doc = doc_context.get_current_doc()
                session = state._sessions.get(doc)
                source = None if session is None else session.design
                policy = _source_policy(doc, source, family)
                if type(source) is not Design:
                    _conflict("Preview requires an existing mutable standard part")
                if source.id != request.expected_design_id or session.revision != request.expected_revision:
                    _conflict("The part changed before preview capture", "source_changed")
                state._assert_active_loadout_editable(source)
                with _lock:
                    _prune()
                    if (doc, family, request.preview_id) in _tombstones:
                        _conflict("This preview opening was cancelled")
                    old = _entries.get(doc)
                    if old is not None:
                        if old.request.preview_id == request.preview_id or old.phase == "committing":
                            _conflict("This preview is already active or committing")
                        _remove(old)
                    elif len(_entries) >= MAX_SESSIONS:
                        raise HTTPException(429, detail={"code": "preview_capacity", "detail": "Close an existing preview first"})
                    origin = Origin.model_validate({name: getattr(request, name) for name in Origin.model_fields})
                    entry = _Entry(doc, origin, str(uuid4()), ref(source), session.identity, policy.generation,
                                   monotonic() + TTL_SECONDS, family=family)
                    _entries[doc] = entry
                captured = capture(source, preserve_entry_types=True)
            # Do not keep the live source/session in this computation frame.
            del source, session
            if family == "transform":
                from backend.api import part_transform_preview_computation as numerical
                if numerical.required(captured):
                    from backend.api.part_transform_preview import select_from_capture
                    from backend.api.part_deformation_preview import _checkpoint
                    kind = select_from_capture(captured, request.feature_id, _checkpoint())[3]
                    result = numerical.begin_prepare(sys.modules[__name__], entry, captured, kind)
                    transferred = True
                    return result
            timer = Timer(max(0, entry.expires - monotonic()), lambda: _expire(entry))
            timer.daemon = True
            with _lock:
                _catalog_current(entry)
                entry.timer = timer
            timer.start()
            creation = ({"deformation_id": str(uuid4()), "kind": request.type,
                         "targets": request.targets, "cluster_ids": request.cluster_ids}
                        if type(request) is Creation else None)
            prepared = family_work.prepare(family, captured, request.feature_id, creation=creation)
            del captured
            evaluated = family_work.evaluate_original(family, prepared)
            payload = family_work.prepare_display(family, prepared, evaluated,
                envelope=_envelope(entry, 0, prepared=prepared))
            return _finish(entry, 0, payload, prepared=prepared)
    except BaseException:
        if entry is not None:
            with _lock:
                if _entries.get(entry.doc) is entry:
                    _remove(entry)
        raise
    finally:
        if not transferred:
            _work_slot.release()


def evaluate(value, *, family="deformation"):
    request = _parse(Evaluation, value)
    entry, prepared = _claim(request, family=family)
    try:
        with _mapped_errors():
            _current(entry, request.request_sequence)
            evaluated = family_work.evaluate(family, prepared, request.params)
            payload = family_work.evaluate_display(family, prepared, evaluated,
                include_geometry=request.include_geometry,
                envelope=_envelope(entry, request.request_sequence))
            return _finish(entry, request.request_sequence, payload)
    finally:
        _work_slot.release()


def cancel(value, *, family="deformation"):
    """Cancel known work, or briefly remember a nonce before Prepare arrives.

    Tombstones are bounded to sixteen entries and sixty seconds, not permanent
    replay protection. Clients create a fresh UUID for every editor opening.
    """
    _family(family)
    request = _parse(Cancel, value)
    with _lock:
        _prune()
        doc = doc_context.get_current_doc()
        entry = _entries.get(doc)
        if entry is not None and entry.request.preview_id == request.preview_id:
            if not _matches_request(entry, request, family):
                _conflict("Cancellation does not match the current preview lease")
            if entry.phase == "committing":
                return {"status": "commit_in_progress", "preview_id": request.preview_id,
                        "lease_id": entry.lease_id}
            if entry.phase == "applied":
                # Cancellation cannot undo publication. This receipt describes
                # the completed action; status separately checks its freshness.
                return dict(entry.publication)
            _remove(entry)
        else:
            _remember_cancel(_Entry(doc, request, "", None, "", -1, 0, family=family))
        return {"status": "cancelled", "preview_id": request.preview_id}


def status(value, *, family="deformation"):
    """Inspect a known lease; success binds the original or published revision."""
    _family(family)
    request = _parse(Status, value)
    with _lock:
        _prune()
        entry = _entries.get(doc_context.get_current_doc())
        if entry is None or not _matches_request(entry, request, family):
            _conflict("The preview lease does not match this document/request")
    with state._lock:
        _source_current(entry)
        with _lock:
            _catalog_current(entry)
            phase = entry.phase
            if phase == "ready" and entry.applying_sequence == entry.sequence:
                phase = "applying"
            result = {**_envelope(entry, entry.sequence), "status": phase}
            if entry.publication is not None:
                result.update(entry.publication)
            if entry.computation is not None:
                from backend.api.part_transform_preview_computation import fields
                result["computation"] = fields(entry.computation)
            if entry.payload is not None:
                result["result"] = {**entry.payload, "remaining_seconds": result["remaining_seconds"]}
            if entry.failure is not None:
                result["failure"] = entry.failure
    # A caller cannot mutate the retained display/error; no large copy or
    # whole-response admission runs while the state or catalog lock is held.
    if not entry.numerical:
        return result
    from backend.api.part_transform_preview_dto import _bounded
    with _mapped_errors():
        result = _bounded(deepcopy(result))
    return _finish(entry, result["request_sequence"], result)


def apply(value, *, family="deformation"):
    """Full existing recipe edit against the bound source; one atomic undo."""
    from backend.api.part_history_verification import _slot as proof_slot

    request = _parse(Change, value)
    from backend.core.part_history_proof import digest
    request_sha256 = digest(request.model_dump(mode="json"))
    entry, prepared = _claim(request, applying=True, family=family)
    proof_admitted = False
    transferred = False
    try:
        if entry.numerical:
            from backend.api import part_transform_preview_computation as numerical
            with _mapped_errors():
                _current(entry, request.request_sequence)
                params = family_work.apply_params(family, prepared, request.params)
                with state._lock:
                    session = _source_current(entry)
                    with _lock:
                        _catalog_current(entry, request.request_sequence)
                    admission = (permits.admit_organized_recipe(entry.doc, session,
                        operation=f"{family}_preview", request_sha256=request_sha256)
                        if session.design.group_organization is not None else None)
                    captured = capture(session.design, preserve_entry_types=True)
                del session
                result = numerical.begin_apply(sys.modules[__name__], entry, captured,
                    request, params, admission, request_sha256)
                transferred = True
                return result
        if not proof_slot.acquire(blocking=False):
            raise HTTPException(429, detail="A part history operation is already running")
        proof_admitted = True
        deadline = monotonic() + APPLY_SECONDS

        def check():
            if monotonic() > deadline:
                raise HTTPException(408, detail="Recipe regeneration time limit")
            _current(entry, request.request_sequence)

        with _mapped_errors():
            check()
            # Reuse the exact local parameter/scope contract; this does not
            # replace the fresh full source proof in prepare_change below.
            params = family_work.apply_params(family, prepared, request.params)
            with state._lock:
                session = _source_current(entry)
                if monotonic() > deadline:
                    raise HTTPException(408, detail="Recipe regeneration time limit")
                with _lock:
                    _catalog_current(entry, request.request_sequence)
                admission = (permits.admit_organized_recipe(entry.doc, session,
                    operation=f"{family}_preview", request_sha256=request_sha256)
                    if session.design.group_organization is not None else None)
                captured = capture(session.design, preserve_entry_types=True)
            del session
            if type(prepared) is PreparedCreation:
                candidate, _report = prepare_creation_append(captured, prepared, request.params, check)
            else:
                indices = [i for i, row in enumerate(captured.feature_log) if row.id == request.feature_id]
                if len(indices) != 1:
                    _conflict("The original native feature identity is no longer unique")
                candidate, _report = prepare_change(captured, captured, indices[0], check, params=params)
            check()
            return _publish(entry, request, candidate, deadline, admission, request_sha256)

    finally:
        with _lock:
            if not transferred and entry.applying_sequence == request.request_sequence:
                entry.applying_sequence = None
        if proof_admitted:
            proof_slot.release()
        if not transferred:
            _work_slot.release()


def _publish(entry, request, candidate, deadline, admission, request_sha256, *, renew_receipt=False):
    """The sole preview publication transaction, shared by both compute lanes."""
    committing = False
    try:
        with state._lock:
            session = _source_current(entry)
            if monotonic() > deadline:
                raise HTTPException(408, detail="Recipe regeneration time limit")
            with _lock:
                _catalog_current(entry, request.request_sequence)
                entry.phase = "committing"
                committing = True
            # Reservation closes cancellation/supersession. No catalog
            # lock spans preservation, native dependency checks or undo.
            candidate = preserve_document_state(session.design, candidate)
            state._assert_active_loadout_editable(session.design, candidate)
            state._assert_photoproduct_dependencies(candidate)
            # Preservation and dependency validation may consume the last
            # allowance even for legacy sources without a publication permit.
            if monotonic() > deadline:
                raise HTTPException(408, detail="Recipe regeneration time limit")
            _source_current(entry)
            with _lock:
                _catalog_current(entry, request.request_sequence)
            permit = (permits.issue_organized_recipe_permit(admission, candidate,
                request_sha256=request_sha256, expires=min(deadline, entry.expires))
                if admission is not None else None)
            revision = (publish_replacement(session, candidate, publication_permit=permit)
                        if permit is not None else publish_replacement(session, candidate))
            receipt = {**entry.request.model_dump(), "status": "applied",
                       "lease_id": entry.lease_id, "design_id": candidate.id,
                       "revision": revision, **entry.identity,
                       "doc_id": entry.doc, "request_sequence": request.request_sequence}
            with _lock:
                entry.source = ref(candidate)
                entry.publication = receipt
                entry.prepared = None
                entry.phase = "applied"
                if renew_receipt:
                    entry.payload = entry.failure = None
                    _renew(entry, TTL_SECONDS)
                elif entry.expires <= monotonic() or entry.expired_during_commit:
                    _remove(entry)
        return dict(receipt)
    except BaseException:
        if committing:
            with state._lock:
                session = state._sessions.get(entry.doc)
                unchanged = (session is not None and session.identity == entry.session_identity
                             and session.design is entry.source()
                             and session.revision == entry.request.expected_revision)
                with _lock:
                    if _entries.get(entry.doc) is entry:
                        if entry.publication is not None:
                            # Canonical publication already succeeded. If a
                            # receipt timer could not start, catalog pruning
                            # still enforces its fixed scalar-retention deadline.
                            return dict(entry.publication)
                        if unchanged and entry.expires > monotonic() and not entry.expired_during_commit:
                            entry.phase = "ready"
                        else:
                            _remove(entry)
        raise


def clear_for_testing():
    """Private lifecycle cleanup for isolated in-memory service tests only."""
    with _lock:
        for entry in list(_entries.values()):
            if entry.phase == "committing":
                raise RuntimeError("Cannot clear a committing preview")
            _remove(entry, remember=False)
        _tombstones.clear()
