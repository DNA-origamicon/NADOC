"""Stable, non-secret identity for RunPod resources owned by this NADOC install."""

from __future__ import annotations

import os
import re
import uuid
from functools import lru_cache
from pathlib import Path

_PREFIX = "nadoc-i-"


def _clean(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", value)[:24]


@lru_cache(maxsize=1)
def installation_id() -> str:
    """Return a stable random id which is deliberately local to one computer."""
    override = os.environ.get("NADOC_INSTANCE_ID", "").strip()
    if override:
        return _clean(override) or uuid.uuid4().hex[:12]
    path = Path.home() / ".config" / "nadoc" / "instance_id"
    try:
        value = path.read_text().strip()
        if value:
            return _clean(value) or uuid.uuid4().hex[:12]
    except FileNotFoundError:
        pass
    value = uuid.uuid4().hex[:12]
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(value + "\n")
        path.chmod(0o600)
    except OSError:
        # Read-only homes still get process-level isolation; an env override makes it
        # durable for packaged/container deployments.
        pass
    return value


def pod_name(design_name: str, job_id: str) -> str:
    return f"{_PREFIX}{installation_id()}-{design_name}-{job_id}"[:191]


def pod_owner(name: str) -> str | None:
    """Extract the owner from a signed pod name; legacy ``nadoc-*`` names return None."""
    if not name.startswith(_PREFIX):
        return None
    rest = name[len(_PREFIX):]
    owner, sep, _ = rest.partition("-")
    return owner if sep and owner else None


def is_foreign_pod(name: str) -> bool:
    owner = pod_owner(name)
    return owner is not None and owner != installation_id()
