"""Thin trusted host operations for construction policy and empty creation.

State owns the lock and the session registry. These functions are embedding
interfaces, not routes, environment flags, saved settings or request authority.
"""

from backend.api import part_publication_policy as policy


def configure(configuration):
    from backend.api import state

    with state._lock:
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


def create_empty_part(name="Untitled", lattice_type="HONEYCOMB"):
    from backend.api import state
    from backend.api.doc_context import get_current_doc
    from backend.api.part_publication_permit import prepare_empty_creation
    from backend.api.part_replacement_transaction import publish_replacement

    with state._lock:
        session = state._session()
        candidate, permit = prepare_empty_creation(get_current_doc(), session,
            name=name, lattice_type=lattice_type)
        publish_replacement(session, candidate, publication_permit=permit)
        return candidate
