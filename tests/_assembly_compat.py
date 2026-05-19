"""Backward-compat helpers for tests written before the Phase 5 contract step.

Phase 5 contract dropped the legacy ``assembly.instances`` field from the
``/api/assembly`` response shape — it's now ``instances_v2`` + ``sources``
(see ``project_path_to_thousands.md``). Frontend readers were migrated at
commit ce34c8b. Many tests still expect the v1 shape; rather than rewrite
every assertion at once, this helper expands the v2 fields back into a
v1-shape list of dicts on demand.

Migrate tests away from this shim as opportunity arises — long-term the
right move is to assert against v2 directly.
"""
from __future__ import annotations

from backend.core.models import PartInstance


def v1_instances(body_or_response):
    """Return the v1-shape ``instances`` list from an assembly response.

    Accepts either a parsed JSON dict (``r.json()``) or a TestClient
    response object (calls ``.json()``). When the response already
    carries a legacy ``instances`` field (older `.nass` files or tests
    that stub a v1 payload directly), return it unchanged. Otherwise
    expand ``instances_v2`` + ``sources`` via ``PartInstance.from_compact_dict``
    and dump back to dict form.
    """
    body = body_or_response.json() if hasattr(body_or_response, "json") else body_or_response
    asm = body["assembly"] if "assembly" in body else body
    if "instances" in asm and asm["instances"]:
        return asm["instances"]
    sources = asm.get("sources", {})
    out = []
    for entry in asm.get("instances_v2", []):
        try:
            # `sources` is keyword-only on PartInstance.from_compact_dict.
            inst = PartInstance.from_compact_dict(entry, sources=sources)
        except Exception:
            # Best-effort: include the raw entry so tests reading id-only
            # patterns still work.
            out.append(entry)
            continue
        out.append(inst.model_dump(mode="json"))
    return out
