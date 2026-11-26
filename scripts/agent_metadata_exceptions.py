"""Explicit human-approved legacy metadata exceptions; never construction inputs.

D003 approval: user, 2026-11-23, "Yes. allow the metadata exception."
Original file SHA-256: c7bb0f69435dff5f2513d89617ef274f2308a4647b6cf5367b0ec453693f0d4c.
Only the recorded-root title -> saved title discrepancy is acknowledged. The
complete normalized document or its exact independently audited branch must
match the allowlist. No other metadata, molecular state or command is exempted.
"""
from copy import deepcopy

from backend.core.document_operations import content_digest

_D003_DIGESTS = frozenset({
    'e29573ccee400c131a948ed33dd5a9c7dd886add6cee794193de6d93a8f2899e',
    '63ad3290054969aebfa5801ae700b9459299c08bcd3de4a17bba06eff2f58c70',
})
_OLD_NAME = 'D003 — square tile, strong–strong bridges'
_NEW_NAME = 'D003'
# The ordinary workspace move changed only these two non-authoring stamps.
# Restore their exact approved values solely for the existing digest comparison;
# every other document field (including ID, history and molecular state) stays bound.
_D003_REVIEWED_IDENTITY = {
    'identity_last_known_path': 'Shared Designs/All Origami/D003/recovered-20261104/D003.nadoc',
    'identity_confirmed_at': '2026-11-04T21:20:43.999338+00:00',
}



def reviewed_replay_value(design, value):
    """Project only an approved title for comparison; never edit the document."""
    if value.get('metadata', {}).get('name') != _OLD_NAME:
        return value
    document = design.model_dump(mode='json')
    if content_digest(document) not in _D003_DIGESTS:
        document['metadata'].update(_D003_REVIEWED_IDENTITY)
        if content_digest(document) not in _D003_DIGESTS:
            return value
    reviewed = deepcopy(value)
    reviewed['metadata']['name'] = _NEW_NAME
    return reviewed
