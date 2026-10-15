"""Thin trusted host operations for construction policy and empty creation.

State owns the lock and the session registry. These functions are embedding
interfaces, not routes, environment flags, saved settings or request authority.
"""

from backend.api import part_publication_policy as policy


# Do not switch public creation until typed persistence/qualified restore and the
# complete immutable capture/publication lifecycle have been measured.
IMMUTABLE_STRICT_STORAGE_ENABLED = False


def configure(configuration):
    from backend.api import state
    from backend.api.part_immutable_storage import is_immutable, _refuse

    with state._lock:
        if type(configuration) is not policy.HostPolicyConfiguration:
            raise TypeError("Construction policy requires a host configuration object")
        for doc, session in state._sessions.items():
            if is_immutable(session.design) and configuration.document_modes.get(doc, configuration.default_mode) != "registered_only":
                _refuse("Convert or close the immutable part before changing its storage policy",
                        code="immutable_policy_transition")
        return policy._install_configuration(configuration)


def current_policy():
    from backend.api import state
    from backend.api.doc_context import get_current_doc

    with state._lock:
        return policy.resolve(get_current_doc())


def require_compatibility(operation, *, doc_id=None):
    """Early guard for adapters before acquiring bytes, callbacks or file I/O."""
    from backend.api import state
    from backend.api.doc_context import get_current_doc

    with state._lock:
        return policy.require_compatibility(doc_id or get_current_doc(), operation)


def _create_empty_part_locked(name, lattice_type):
    """State-lock-owned primitive shared by embedding and scalar HTTP output."""
    from backend.api import state
    from backend.api.doc_context import get_current_doc
    from backend.api.part_publication_permit import prepare_empty_creation
    from backend.api.part_replacement_transaction import publish_replacement

    session = state._session()
    candidate, permit = prepare_empty_creation(get_current_doc(), session,
        name=name, lattice_type=lattice_type)
    publish_replacement(session, candidate, publication_permit=permit)
    return candidate


def create_empty_part(name="Untitled", lattice_type="HONEYCOMB"):
    from backend.api import state
    from backend.api.doc_context import get_current_doc

    if IMMUTABLE_STRICT_STORAGE_ENABLED and policy.resolve(get_current_doc()).strict:
        return create_immutable_empty(name, lattice_type)[0]
    with state._lock:
        return _create_empty_part_locked(name, lattice_type)


def create_immutable_empty(name="Untitled", lattice_type="HONEYCOMB", *, expected_policy_generation=None):
    """Internal staged creation; public switch stays closed pending persistence.

    Explicit creation reserves an actual empty session before preparation. On
    failure that empty reservation remains harmless and reusable; a closed or
    replaced reservation is never recreated at publication.
    """
    from fastapi import HTTPException
    from backend.api import state
    from backend.api.doc_context import get_current_doc
    from backend.api.document_identity import require_document_identity
    from backend.api.part_immutable_storage import require_empty_session
    from backend.api import part_publication_permit as permits
    from backend.api.part_replacement_transaction import publish_replacement

    if type(name) is not str or not name.strip() or len(name) > 1024 or lattice_type not in {"HONEYCOMB", "SQUARE"}:
        raise ValueError("Empty part creation requires a bounded name and supported lattice")
    doc = require_document_identity(get_current_doc())
    with state._lock:
        current = policy.resolve(doc)
        if not current.strict:
            raise HTTPException(409, detail={"code": "immutable_publication_scope", "detail": "Immutable creation requires strict host policy"})
        if expected_policy_generation is not None and (
                type(expected_policy_generation) is not int or current.generation != expected_policy_generation):
            raise HTTPException(409, detail={"code": "policy_changed", "detail": "Host policy changed before empty creation"})
        session = state._session()
        require_empty_session(session)
        admission = permits.admit_empty_creation(doc, session)
    candidate, permit = permits.prepare_admitted_empty(admission, name=name, lattice_type=lattice_type)
    with state._lock:
        if state._sessions.get(doc) is not session:
            raise HTTPException(409, detail={"code": "source_changed", "detail": "The empty session was closed or replaced"})
        require_empty_session(session)
        revision = publish_replacement(session, candidate, publication_permit=permit)
    return candidate, revision
