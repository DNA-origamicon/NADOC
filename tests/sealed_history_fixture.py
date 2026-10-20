"""Explicit sealed fixture controls, reachable only in the isolated history app."""
from contextlib import contextmanager
from hashlib import sha256
import json

from backend.api import state, part_publication_policy as policy
from backend.api import part_immutable_geometry_publication as gate
from backend.api.part_immutable_revision import prepare_geometry_revision, materialize_revision
from backend.api.part_strict_http import StrictPartDispatch

DOCUMENTS = frozenset({'__e2e__history-bend', '__e2e__history-twist'})


class FixtureDispatch(StrictPartDispatch):
    async def __call__(self, scope, receive, send):
        # Only test controls bypass dispatch, never design or ordinary app routes.
        if scope.get('path', '').startswith('/api/__e2e__/history/'):
            return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


@contextmanager
def enabled():
    previous, configuration = gate.ENABLED, policy.current_configuration()
    gate.ENABLED = True
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(
        default_mode=configuration.default_mode,
        document_modes={**configuration.document_modes, **{doc: 'registered_only' for doc in DOCUMENTS}}))
    try:
        yield
    finally:
        try:
            for doc in DOCUMENTS:
                state.drop_doc(doc)
            state.configure_part_publication_policy(configuration)
        finally:
            gate.ENABLED = previous


def seed(source):
    prepared = prepare_geometry_revision(source)
    with state._lock:
        session = state._session()
        session.design = prepared
        session.revision += 1
        session.history.clear()
        session.redo.clear()
        session.redo.append(prepared)


def source():
    with state._lock:
        value = state._session().design
    return materialize_revision(value)


def checkpoint():
    with state._lock:
        session = state._session()
        current, revision = session.design, session.revision
        history, redo = tuple(session.history), tuple(session.redo)
    def digest(value):
        return sha256(json.dumps(materialize_revision(value).model_dump(mode='json'), sort_keys=True).encode()).hexdigest()
    return {'design': materialize_revision(current).model_dump(mode='json'), 'revision': revision,
            'history': [digest(value) for value in history], 'redo': [digest(value) for value in redo],
            'sealed': True}
