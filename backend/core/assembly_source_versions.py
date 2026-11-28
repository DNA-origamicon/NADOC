"""Portable, integrity-checked file-source revisions owned by an assembly."""

import hashlib
import json


def design_digest(design):
    payload = json.dumps(design.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def pinned_design(source):
    revision = getattr(source, "revision", None)
    if revision is None:
        return None
    if source.revision_sha256 != design_digest(revision):
        raise ValueError("Assembly source revision content does not match its recorded digest.")
    return revision


def pin_source(source, design):
    from backend.core.models import PartSourceInline

    revision = design.model_copy(deep=True)
    if source.type == "inline":
        return PartSourceInline(design=revision)
    return source.model_copy(update={"revision": revision, "revision_sha256": design_digest(revision)})
