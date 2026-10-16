"""Semantic assembly readiness identity, independent of live representation.

All other persisted assembly and instance data remain part of the identity.
File-content revisions are supplied separately by the route's source stamps.
"""

from __future__ import annotations

import hashlib

import orjson

from backend.core.models import Assembly, PartSourceInline


def assembly_readiness_fingerprint(assembly: Assembly) -> str:
    """Hash full assessment inputs while excluding only instance representation.

    Shared inline Designs are encoded once within this call. Source object
    identity is only a local dedup optimization, never the semantic cache key.
    Do not use the v2 serializer: its source-ID dedup can hide different content
    in two inline sources that happen to carry the same Design ID.
    """
    def digest(value):
        return hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()

    content = assembly.model_dump(mode="json", exclude={"instances"})
    inline = {}
    instances = []
    for instance in assembly.instances:
        item = instance.model_dump(mode="json", exclude={"representation", "source"})
        source = instance.source
        if isinstance(source, PartSourceInline):
            identity = id(source.design)
            if identity not in inline:
                inline[identity] = digest(source.design.model_dump(mode="json"))
            item["source"] = {**source.model_dump(mode="json", exclude={"design"}),
                              "design": inline[identity]}
        else:
            item["source"] = source.model_dump(mode="json")
        instances.append(item)
    content["instances"] = instances
    return digest(content)
