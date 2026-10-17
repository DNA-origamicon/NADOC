"""Durable first creation, followed by one exact empty-session publication.

File ownership and host publication authority remain separate. Complete bytes
written before a failed/closed publication stay pending for explicit recovery.
"""

from fastapi import HTTPException

from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as policy, session_cache, state
from backend.api.doc_context import get_current_doc
from backend.api.document_identity import require_document_identity
from backend.api.part_immutable_persistence import PersistenceCapture, StrictPersistence
from backend.api.part_immutable_storage import require_empty_session
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.part_command_errors import CommandContractError


def _owner():
    owner = session_cache._strict_persistence
    if type(owner) is not StrictPersistence:
        raise HTTPException(503, detail={"code": "strict_cache_unavailable",
            "detail": "Durable strict storage is unavailable on this host"})
    return owner


def _check_reservation(owner, doc, session, revision, generation):
    """Caller owns state._lock; no file work or model traversal here."""
    if session_cache._strict_persistence is not owner:
        raise HTTPException(409, detail={"code": "strict_cache_changed",
            "detail": "Durable storage changed during empty creation"})
    if state._sessions.get(doc) is not session or session.revision != revision:
        raise HTTPException(409, detail={"code": "source_changed",
            "detail": "The empty session was closed or changed during creation"})
    current = policy.resolve(doc)
    if not current.strict or current.generation != generation:
        raise HTTPException(409, detail={"code": "policy_changed",
            "detail": "Host policy changed during empty creation"})
    require_empty_session(session)


def create_durable_empty(name="Untitled", lattice_type="HONEYCOMB", *, expected_policy_generation=None):
    """Host-owned empty root only; accepts neither a Design nor saved bytes.

    Explicit creation reserves an actual empty session before preparation. A
    failed operation may retain that empty reservation; it never recreates one
    that was closed while work ran outside the state lock.
    """
    if type(name) is not str or not name.strip() or len(name) > 1024 or lattice_type not in {"HONEYCOMB", "SQUARE"}:
        raise ValueError("Empty part creation requires a bounded name and supported lattice")
    doc = require_document_identity(get_current_doc())
    owner = _owner()
    with state._lock:
        current = policy.resolve(doc)
        if not current.strict:
            raise HTTPException(409, detail={"code": "immutable_publication_scope",
                "detail": "Durable immutable creation requires strict host policy"})
        if expected_policy_generation is not None and (
                type(expected_policy_generation) is not int or current.generation != expected_policy_generation):
            raise HTTPException(409, detail={"code": "policy_changed",
                "detail": "Host policy changed before empty creation"})
        if session_cache._strict_persistence is not owner:
            raise HTTPException(409, detail={"code": "strict_cache_changed", "detail": "Durable storage changed"})
        session = state._session()
        require_empty_session(session)
        revision, generation = session.revision, current.generation
        admission = permits.admit_empty_creation(doc, session)
    try:
        # Reserve the absent file before building. A pending/corrupt record is
        # preserved, and a legacy writer admitted earlier must finish first.
        absent = owner.reserve_empty(doc)
        candidate, permit = permits.prepare_admitted_empty(admission, name=name, lattice_type=lattice_type)
        with state._lock:
            _check_reservation(owner, doc, session, revision, generation)
        capture = PersistenceCapture(doc, session.identity, revision + 1, candidate)
        lease = owner.write_initial(capture, absent)
        with owner.bind_for_publication(capture, lease):
            with state._lock:
                _check_reservation(owner, doc, session, revision, generation)
                assigned = publish_replacement(session, candidate, publication_permit=permit)
        return candidate, assigned
    except CommandContractError as error:
        raise HTTPException(409, detail=error.as_issue()) from error
