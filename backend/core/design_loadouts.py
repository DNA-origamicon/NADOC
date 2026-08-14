"""Pure snapshot and naming operations for design loadouts.

Loadouts are whole-design branch snapshots.  This module deliberately owns no
HTTP or process-global state so the design and assembly APIs can share the
same serialization rules without importing one another.
"""

from __future__ import annotations

import base64
import gzip
import uuid

from backend.core.models import Design, DesignLoadout


def encode_snapshot(design: Design) -> tuple[str, int]:
    """Encode a branch snapshot while avoiding recursive loadout nesting."""
    stripped = design.model_copy(update={"loadouts": [], "active_loadout_id": None})
    raw = stripped.model_dump_json().encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=6)
    return base64.b64encode(compressed).decode("ascii"), len(raw)


def decode_snapshot(payload_b64: str) -> Design:
    """Decode a loadout snapshot into a validated design."""
    if not payload_b64:
        raise ValueError("empty loadout snapshot payload")
    raw = gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))
    return Design.model_validate_json(raw)


def ensure_loadouts(design: Design) -> tuple[list[DesignLoadout], str]:
    """Return materialized loadouts and a valid active loadout id."""
    loadouts = list(design.loadouts or [])
    active_id = design.active_loadout_id
    if loadouts and any(loadout.id == active_id for loadout in loadouts):
        return loadouts, active_id
    if loadouts:
        return loadouts, loadouts[0].id
    payload, size = encode_snapshot(design)
    first = DesignLoadout(
        id=str(uuid.uuid4()),
        name="Loadout 1",
        design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size,
    )
    return [first], first.id


def next_default_name(loadouts: list[DesignLoadout]) -> str:
    """Return the lowest unused ``Loadout N`` name."""
    existing = {loadout.name for loadout in loadouts}
    number = 1
    while f"Loadout {number}" in existing:
        number += 1
    return f"Loadout {number}"


def save_active_snapshot(
    design: Design, loadouts: list[DesignLoadout], active_id: str
) -> list[DesignLoadout]:
    """Update the active editable loadout with the current design state."""
    active = next((loadout for loadout in loadouts if loadout.id == active_id), None)
    if active is not None and active.protected:
        return loadouts
    payload, size = encode_snapshot(design)
    return [
        loadout.model_copy(
            update={
                "design_snapshot_gz_b64": payload,
                "snapshot_size_bytes": size,
            }
        )
        if loadout.id == active_id
        else loadout
        for loadout in loadouts
    ]
