"""Small host adapters for repair metadata during legacy geometry recovery."""

from fastapi import HTTPException

from backend.core.part_command_errors import CommandContractError
from backend.core.part_repair_document import restore_recovery_draft


def restore_recovery_metadata(source, candidate):
    """Prepare before publishing or changing undo stacks; refusal is atomic."""
    try:
        return restore_recovery_draft(source, candidate)
    except CommandContractError as error:
        raise HTTPException(409, detail=error.as_issue()) from error


def preserve_feature_recovery_metadata(source, candidate):
    """Feature recovery stays in the current branch despite stripped snapshots."""
    return restore_recovery_metadata(source, candidate).copy_with(
        loadouts=source.loadouts, active_loadout_id=source.active_loadout_id,
        last_editable_loadout_id=source.last_editable_loadout_id)
