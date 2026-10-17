"""Portable repair metadata at ordinary document publication boundaries.

These helpers never inspect action contents or establish regeneration readiness.
Call preservation only for edits within a branch, not file/loadout navigation.
"""

from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import MAX_SOURCES


def preserve_repair_draft(source, candidate):
    """Keep the current proposal, including explicit absence after discard."""
    if candidate.repair_draft is source.repair_draft:
        return candidate
    return candidate.copy_with(repair_draft=source.repair_draft)


def restore_recovery_draft(source, candidate):
    """Restore geometry without losing proposed inputs staged after a snapshot.

    Live bytes win over historical bytes for the same digest. No integrity
    assumption is made here: the explicit audit/evaluator checks those bytes.
    Native candidate publication deliberately does not use this recovery rule.
    """
    updated = preserve_repair_draft(source, candidate)
    if source.repair_draft is None:
        return updated
    if len(source.input_sources) > MAX_SOURCES or len(candidate.input_sources) > MAX_SOURCES:
        raise CommandContractError("Repair draft source retention exceeds the source count limit",
                                   code="repair_draft_source_limit")
    if source.input_sources is candidate.input_sources:
        return updated
    sources = {**candidate.input_sources, **source.input_sources}
    if len(sources) > MAX_SOURCES:
        raise CommandContractError("Repair draft source retention exceeds the source count limit",
                                   code="repair_draft_source_limit")
    return updated.copy_with(input_sources=sources)


def draft_summary(draft):
    """Constant-size response metadata; durable-base checking is explicit."""
    if draft is None:
        return None
    return {"version": draft.version, "draft_id": draft.draft_id,
            "generation": draft.generation, "action_count": len(draft.actions),
            "status": "pending", "base_status": "unchecked"}
