"""Preserve document/display state when publishing regenerated authoring state."""

from backend.core.part_history_contract import FIELD_ROLES


def preserve_document_state(source, candidate):
    """Carry non-proof data forward, dropping presentation links just removed.

    This runs only on explicit recipe publication. Missing links that predate the
    operation remain available for diagnosis; it is not a general load migration.
    """
    preserved = {
        name: getattr(source, name)
        for name, role in FIELD_ROLES.items()
        if role in {"presentation", "physical", "document_identity"}
    }
    removed = {item.id for item in source.protein_attachments} - {
        item.id for item in candidate.protein_attachments
    }
    if removed:
        overrides = []
        for override in source.representation_overrides:
            kept = [identity for identity in override.protein_attachment_ids if identity not in removed]
            if kept == override.protein_attachment_ids:
                overrides.append(override)
            elif kept or override.segments:
                overrides.append(override.model_copy(update={"protein_attachment_ids": kept}))
        preserved["representation_overrides"] = overrides
    return candidate.copy_with(**preserved)
