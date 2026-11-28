"""Atomic publication boundary for assembly history operations.

This is recovery-history evaluation, not independent process verification.
Legacy snapshot anchors retain their existing qualification status.
"""

from backend.api import assembly_state


def apply_history_change(evaluate):
    """Evaluate in a disposable session, then publish exactly one undo step.

    Only in-memory history commands belong here. Source-file mutations must
    first acquire a separate versioned source publication contract.
    """
    source, revision = assembly_state.copy_for_persist()
    if source is None:
        assembly_state.get_or_404()
    with assembly_state.isolated_evaluation(source):
        evaluate()
        candidate = assembly_state.get_or_404()
    return assembly_state.publish_candidate(
        candidate, source=source, expected_revision=revision
    )
