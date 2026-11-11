"""Preserve document/display state when publishing regenerated authoring state."""

from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_repair_document import preserve_repair_draft
from backend.core.part_history_proof import IDENTITY_METADATA_FIELDS


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
    from backend.core.presentation_checkpoints import restore_history_channels
    preserved.update(restore_history_channels(source, candidate))
    # Semantic document intent survives geometry regeneration and history seeks.
    preserved['document_history'] = source.document_history
    document_keys = {key for event in source.document_history
                     if event.kind == 'document-metadata' for key in event.params['changes']}
    # File location/signoff is excluded from recipe proof. Keep the live
    # document's claim when a regenerated empty root supplies fresh metadata.
    preserved['metadata'] = candidate.metadata.model_copy(update={
        name: getattr(source.metadata, name) for name in IDENTITY_METADATA_FIELDS | document_keys})
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
    return preserve_repair_draft(source, candidate.copy_with(**preserved))
