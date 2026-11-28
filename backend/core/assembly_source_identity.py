"""Content identity for portable assembly sources, including their provenance."""

import hashlib
import json


def source_key(source, payload=None):
    if payload is None:
        payload = source.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    prefix = f"i:{source.design.id}" if source.type == "inline" else f"f:{source.path}"
    return f"{prefix}:{digest}"


def compact_sources(instances):
    """Deduplicate equal source contents; hash each shared object once per call.

    The local cache never outlives the serialization operation, so subsequent
    mutable source edits cannot reuse a stale identity.
    """
    sources, compact, seen = {}, [], {}
    for instance in instances:
        source = instance.source
        identity = id(source)
        if identity not in seen:
            payload = source.model_dump(mode="json")
            key = source_key(source, payload)
            seen[identity] = key
            sources.setdefault(key, payload)
        compact.append(instance.to_compact_dict(src_key=seen[identity]))
    return sources, compact
