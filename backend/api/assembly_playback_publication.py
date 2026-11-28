"""Reject delayed display/animation poses after an authoritative assembly edit."""

from fastapi import HTTPException

from backend.api import assembly_state


def apply_playback_update(expected_revision, evaluate, *, expected_assembly_id=None):
    source, revision = assembly_state.copy_for_persist()
    if source is None:
        assembly_state.get_or_404()
    if revision != expected_revision or (expected_assembly_id is not None and source.id != expected_assembly_id):
        return assembly_state.get_or_404(), True
    with assembly_state.isolated_evaluation(source):
        evaluate()
        candidate = assembly_state.get_or_404()
    try:
        result = assembly_state.publish_candidate(
            candidate, source=source, expected_revision=revision, record_undo=False,
        )
        return result, False
    except HTTPException as error:
        if error.status_code != 409:
            raise
        return assembly_state.get_or_404(), True
