"""HTTP-free normalization and invariant rules for connection versions."""

from __future__ import annotations

from typing import Optional

from backend.core.models import Design


def clean_sequence(value) -> Optional[str]:
    if not value:
        return None
    cleaned = "".join(char for char in str(value).upper() if char in "ACGTN")
    return cleaned or None


def pair_key(overhang_a_id: str, overhang_b_id: str) -> frozenset[str]:
    return frozenset((overhang_a_id, overhang_b_id))


def assign_default_names(design: Design) -> None:
    """Fill empty version names V1, V2, … per unordered overhang pair."""
    by_pair: dict[frozenset[str], list] = {}
    for version in design.connection_versions:
        by_pair.setdefault(
            pair_key(version.overhang_a_id, version.overhang_b_id), []
        ).append(version)
    for versions in by_pair.values():
        versions.sort(key=lambda version: version.created_at)
        used = {version.name for version in versions if version.name}
        number = 1
        for version in versions:
            if version.name:
                continue
            while f"V{number}" in used:
                number += 1
            version.name = f"V{number}"
            used.add(version.name)
            number += 1


def enforce_applied_mutex(design: Design, applied_id: str) -> None:
    """Clear the applied flag on pair-siblings of the applied version."""
    target = next(
        (version for version in design.connection_versions if version.id == applied_id),
        None,
    )
    if target is None or not target.applied:
        return
    target_pair = pair_key(target.overhang_a_id, target.overhang_b_id)
    for version in design.connection_versions:
        if version.id != applied_id and pair_key(
            version.overhang_a_id, version.overhang_b_id
        ) == target_pair:
            version.applied = False
