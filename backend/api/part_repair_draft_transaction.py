"""Failure-atomic publication of already prepared repair metadata.

State supplies its current session while holding its document lock, plus the
existing revision/context hooks. This helper owns no lock, session registry or
Design schema. Preparation, action copying, hashing and validation happen before
entry. The privately prepared draft transfers to session ownership on success.
"""

from backend.core.part_repair_proposal import DraftInputError


def _conflict(detail):
    raise DraftInputError(detail, code="draft_conflict")


def publish_draft(session, prepared_draft, *, expected_session, expected_source, expected_doc_id,
                  expected_design_id, expected_revision, expected_draft_id,
                  expected_generation, bump_revision, context):
    """Compare-and-swap one proposal; return the assigned session revision.

    ``context`` supplies the existing doc_context accessors and setters.
    ``bump_revision`` may modify only session.revision and request context, as
    state._bump_revision does. Neither callback may release the host's lock.
    ``expected_session`` and ``expected_source`` are private runtime handles
    retained at capture, never values accepted from JSON or persisted drafts.
    No geometry, feature history, undo stack or draft action is visited here.
    The caller must never mutate prepared_draft after successful publication.
    """
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Draft publication requires a trusted nonnegative revision")
    if (expected_draft_id is None) != (expected_generation is None) or (
        expected_generation is not None and (type(expected_generation) is not int or expected_generation < 0)
    ):
        raise ValueError("Draft publication requires a complete identity/generation guard")
    if session is not expected_session or context.get_current_doc() != expected_doc_id:
        _conflict("The document changed while the repair draft was being prepared")
    before = session.design
    if before is None or before is not expected_source or before.id != expected_design_id or session.revision != expected_revision:
        _conflict("The part or revision changed while the repair draft was being prepared")
    current = before.repair_draft
    actual = (None, None) if current is None else (current.draft_id, current.generation)
    if actual != (expected_draft_id, expected_generation):
        _conflict("The repair draft was replaced, changed or discarded")

    # These are trusted preparation-output invariants, not another schema
    # validation pass under the lock. Creation starts at zero; edit/rebase
    # keeps identity and advances exactly once; explicit discard is None.
    if prepared_draft is None:
        if current is None:
            raise ValueError("Draft publication cannot discard an absent proposal")
    elif (prepared_draft.base_design_id != before.id
          or type(prepared_draft.generation) is not int
          or prepared_draft.generation != (0 if current is None else current.generation + 1)
          or (current is not None and prepared_draft.draft_id != current.draft_id)):
        raise ValueError("Prepared repair draft does not match its publication generation")

    revision = session.revision
    request_revision = context.current_request_revision()
    request_entry = context.current_request_feature_log_entry_id()
    try:
        candidate = before.model_copy(update={"repair_draft": prepared_draft})
        session.design = candidate
        bump_revision(session)
        if session.revision != revision + 1 or context.current_request_revision() != session.revision:
            raise RuntimeError("Draft publication did not assign exactly one request revision")
        return session.revision
    except BaseException:
        session.design = before
        session.revision = revision
        context.set_request_revision(request_revision)
        context.set_request_feature_log_entry_id(request_entry)
        raise
