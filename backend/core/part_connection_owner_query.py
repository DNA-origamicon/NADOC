"""Stable identities of native direct connection creation outputs."""

from backend.core.feature_identity import identity_factory


def owner_ids(seed):
    identifier = identity_factory(seed)
    return identifier('connection-duplex', []), identifier('connection-binding', [])
