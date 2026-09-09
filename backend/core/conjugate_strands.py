"""Shared naming, grouping, and color policy for conjugated ssDNA handles."""

from __future__ import annotations

import re
import uuid

from backend.core.models import Design, StapleGroup, Strand


CONJUGATE_SSDNA_COLOR = "#c050d0"


def _prefix(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "", (value or "").strip())
    return cleaned or fallback


def next_group_name(design: Design, prefix: str, *, fallback: str) -> str:
    stem = _prefix(prefix, fallback)
    pattern = re.compile(rf"^{re.escape(stem)}-(\d+)$", re.IGNORECASE)
    used = {
        int(match.group(1))
        for group in design.staple_groups
        if (match := pattern.match(group.name or ""))
    }
    number = 1
    while number in used:
        number += 1
    return f"{stem}-{number}"


def assign_conjugate_group(
    design: Design,
    strands: list[Strand],
    *,
    prefix: str,
    fallback: str,
) -> tuple[list[Strand], StapleGroup]:
    """Return consistently colored/named strands and their persisted group."""
    group_name = next_group_name(design, prefix, fallback=fallback)
    assigned = [
        strand.model_copy(update={
            "color": CONJUGATE_SSDNA_COLOR,
            "name": f"{group_name}:S{index}",
        })
        for index, strand in enumerate(strands, start=1)
    ]
    group = StapleGroup(
        id=f"conjugate-{uuid.uuid4()}",
        name=group_name,
        color=CONJUGATE_SSDNA_COLOR,
        strand_ids=[strand.id for strand in assigned],
    )
    return assigned, group


def groups_without_strands(design: Design, strand_ids: set[str]) -> list[StapleGroup]:
    """Remove deleted handles from groups and discard groups left empty."""
    groups = []
    for group in design.staple_groups:
        remaining = [strand_id for strand_id in group.strand_ids if strand_id not in strand_ids]
        if remaining:
            groups.append(group.model_copy(update={"strand_ids": remaining}))
    return groups
