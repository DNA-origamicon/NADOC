"""Bounded, source-owned handoff from native Corner evaluation to publication.

Only server-evaluated candidates enter this store. The token is not a command or
history substitute: candidates already contain the real recording/replay result.
"""

from collections import OrderedDict
from dataclasses import dataclass
import pickle
from threading import RLock
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.part_publication_policy import resolve
from backend.api.part_corner_commands import CornerRequest

_MAX_BYTES = 96 * 1024**2
_MAX_ENTRIES = 4
_TTL = 900
_lock = RLock()
_entries = OrderedDict()


@dataclass(frozen=True)
class Owner:
    doc: str
    session: str
    source: object
    revision: int
    policy: int


def capture(body):
    with state._lock:
        session = state._session()
        current = state._mutable_design(session.design)
        source = state._snapshot_copy(current) if current is not None else None
        revision = session.revision
        if source is None or source.id != body.expected_design_id or revision != body.expected_revision:
            raise HTTPException(409, detail='The Corner source changed. Select the cluster again.')
        state._assert_active_loadout_editable(session.design)
        owner = Owner(doc_context.get_current_doc(), session.identity, session.design, revision,
                      resolve(doc_context.get_current_doc()).generation)
    return source, owner


def _inputs(body):
    return {key: getattr(body, key) for key in CornerRequest.model_fields}


def _prune():
    now = monotonic()
    for token, row in list(_entries.items()):
        if now - row[0] > _TTL:
            del _entries[token]


def retain(owner, body, feature_id, candidate, packet):
    # Serialize once to bound retained memory and isolate mutable objects from
    # the stream consumer and eventual live session. No client pickle is read.
    payload = pickle.dumps((candidate, packet), protocol=pickle.HIGHEST_PROTOCOL)
    if len(payload) > _MAX_BYTES:
        raise ValueError('Corner preview exceeds its prepared-result budget.')
    token = uuid4().hex
    with _lock:
        _prune()
        for key, row in list(_entries.items()):
            if row[1].doc == owner.doc:
                del _entries[key]
        while _entries and (len(_entries) >= _MAX_ENTRIES
                            or sum(len(row[4]) for row in _entries.values()) + len(payload) > _MAX_BYTES):
            _entries.popitem(last=False)
        _entries[token] = (monotonic(), owner, _inputs(body), feature_id, payload)
    return token


def commit(body, feature_id=None):
    from backend.api.crud import _design_response
    from backend.api.part_source_bound_route import require_current

    with _lock:
        _prune()
        row = _entries.get(body.preview_token)
        if row is None:
            raise HTTPException(409, detail='The Corner preview expired. Calculate the preview again.')
        _, owner, inputs, selected, payload = row
        if (owner.doc != doc_context.get_current_doc() or inputs != _inputs(body)
                or selected != feature_id or owner.source.id != body.expected_design_id
                or owner.revision != body.expected_revision):
            raise HTTPException(409, detail='The Corner preview does not match these inputs. Calculate it again.')
        candidate, packet = pickle.loads(payload)
        with state._lock:
            require_current()
        revision = state.set_design(candidate, expected_source=owner.source,
            expected_revision=owner.revision, expected_session_identity=owner.session,
            expected_policy_generation=owner.policy)
        if feature_id is None:
            doc_context.set_request_feature_log_entry_id(packet['feature_id'])
        del _entries[body.preview_token]
    # Return the exact evaluated display data. In particular, do not project
    # native atoms again or refit the separate undeformed-view anchor on Apply.
    response = _design_response(candidate, packet['_validation'], normalize_legacy=False,
        preserve_feature_log_id=packet['feature_id'], full_feature_log=feature_id is not None,
        revision=revision)
    geometry = packet['candidate']
    response.update({key: geometry[key] for key in ('nucleotides', 'helix_axes',
        'straight_positions_by_helix', 'straight_helix_axes')})
    response['corner'] = {'feature_id': packet['feature_id'], 'junction_review_required': True,
                          'reused_preview': True}
    removed = getattr(packet['_validation'], 'auto_removed_features', [])
    if removed:
        response['removed_features'] = removed
        response['placement_warnings'] = [f'Removed {len(removed)} fine-routing feature(s) whose positions are no longer occupied by a strand: '
                                          + ', '.join(r['label'] for r in removed)]
    return response
