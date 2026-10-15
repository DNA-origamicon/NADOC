"""Explicit deterministic IDs for audited feature builders; no global UUID patch."""
import json
from uuid import UUID, uuid5


def identity_factory(seed):
    namespace = UUID(str(seed))

    def identifier(kind, members):
        key = json.dumps([kind, sorted(members)], separators=(",", ":"))
        return str(uuid5(namespace, key))
    return identifier


def preserve_proof_identity(previous, updated):
    """Parameter edits retain the authored identity namespace and contract."""
    return {**updated, **{key: previous[key] for key in ("history_seed", "_proof_version") if key in previous}}
