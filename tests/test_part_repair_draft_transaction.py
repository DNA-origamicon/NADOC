"""Metadata publication invariants without the production Design schema."""

from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict
import pytest

from backend.api.part_repair_draft_transaction import publish_draft
from backend.core.part_repair_proposal import DraftInputError


class Unvisited:
    def __iter__(self):
        pytest.fail("Metadata publication traversed geometry, actions or history")

    def __deepcopy__(self, _memo):
        pytest.fail("Metadata publication deep-copied document content")


class HostDesign(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str = "part"
    repair_draft: object = None
    geometry: object
    feature_log: object


class Context:
    def __init__(self):
        self.doc = "tab"
        self.revision = 123
        self.entry = "earlier-entry"

    def get_current_doc(self):
        return self.doc

    def current_request_revision(self):
        return self.revision

    def current_request_feature_log_entry_id(self):
        return self.entry

    def set_request_revision(self, revision):
        self.revision = revision

    def set_request_feature_log_entry_id(self, entry):
        self.entry = entry


class Cancelled(BaseException):
    pass


def draft(generation=0):
    return SimpleNamespace(draft_id="draft", generation=generation, base_design_id="part",
                           actions=Unvisited())


def setup(previous=None):
    source = HostDesign(repair_draft=previous, geometry=Unvisited(), feature_log=Unvisited())
    session = SimpleNamespace(design=source, revision=7, history=Unvisited(), redo=Unvisited())
    context = Context()

    def bump(current):
        current.revision += 1
        context.set_request_revision(current.revision)

    guards = dict(expected_session=session, expected_source=source, expected_doc_id="tab",
        expected_design_id="part", expected_revision=7,
        expected_draft_id=previous.draft_id if previous else None,
        expected_generation=previous.generation if previous else None, bump_revision=bump, context=context)
    return session, context, guards


@pytest.mark.parametrize("operation", ["create", "update", "rebase", "discard"])
def test_metadata_publication_is_one_shallow_replacement_with_no_history_work(operation):
    previous = None if operation == "create" else draft(4)
    session, context, guards = setup(previous)
    source, history, redo = session.design, session.history, session.redo
    prepared = None if operation == "discard" else draft(0 if previous is None else 5)
    assert publish_draft(session, prepared, **guards) == 8
    assert session.design is not source and session.design.repair_draft is prepared
    assert session.design.id == source.id
    assert session.design.geometry is source.geometry and session.design.feature_log is source.feature_log
    assert source.repair_draft is previous
    assert session.history is history and session.redo is redo
    assert session.revision == context.revision == 8 and context.entry == "earlier-entry"


@pytest.mark.parametrize("change", ["doc", "missing_source", "source_identity", "design_id", "revision",
                                    "draft_id", "generation", "discarded", "created"])
def test_stale_publication_rejects_before_copy_or_revision_hook(change, monkeypatch):
    previous = draft(4)
    session, context, guards = setup(None if change == "created" else previous)
    if change == "doc":
        context.doc = "other-tab"
    elif change == "missing_source":
        session.design = None
    elif change == "source_identity":
        session.design = session.design.model_copy()
    elif change == "design_id":
        session.design.id = "different-part"
    elif change == "revision":
        session.revision += 1
    elif change == "draft_id":
        session.design.repair_draft = SimpleNamespace(draft_id="replacement", generation=4)
    elif change == "generation":
        session.design.repair_draft = draft(5)
    elif change == "discarded":
        session.design.repair_draft = None
    else:
        session.design.repair_draft = draft()
    source, revision = session.design, session.revision
    monkeypatch.setattr(HostDesign, "model_copy", lambda *_a, **_k: pytest.fail("Stale publication copied Design"))
    guards["bump_revision"] = lambda *_: pytest.fail("Stale publication bumped revision")
    with pytest.raises(DraftInputError) as error:
        publish_draft(session, draft(5), **guards)
    assert error.value.code == "draft_conflict"
    assert session.design is source and session.revision == revision
    assert context.revision == 123 and context.entry == "earlier-entry"


@pytest.mark.parametrize("error_type", [RuntimeError, Cancelled])
@pytest.mark.parametrize("phase", ["copy", "bump"])
def test_failure_restores_source_revision_and_request_context(phase, error_type, monkeypatch):
    session, context, guards = setup(draft(4))
    source, history, redo = session.design, session.history, session.redo

    def fail(*_args, **_kwargs):
        session.revision = 99
        context.set_request_revision(99)
        context.set_request_feature_log_entry_id("partial-entry")
        raise error_type("interrupted")

    if phase == "copy":
        monkeypatch.setattr(HostDesign, "model_copy", fail)
    else:
        guards["bump_revision"] = fail
    with pytest.raises(error_type, match="interrupted"):
        publish_draft(session, draft(5), **guards)
    assert session.design is source and source.repair_draft.generation == 4
    assert session.revision == 7 and context.revision == 123 and context.entry == "earlier-entry"
    assert session.history is history and session.redo is redo


@pytest.mark.parametrize("changes", [
    {"expected_revision": True}, {"expected_revision": -1},
    {"expected_generation": None}, {"expected_generation": True}, {"expected_generation": -1},
    {"expected_draft_id": None},
])
def test_incomplete_or_untrusted_host_guards_fail_before_publication(changes):
    session, context, guards = setup(draft(4))
    source = session.design
    with pytest.raises(ValueError):
        publish_draft(session, draft(5), **{**guards, **changes})
    assert session.design is source and session.revision == 7 and context.revision == 123


@pytest.mark.parametrize("previous,prepared", [
    (None, None), (None, draft(1)), (draft(4), draft(4)), (draft(4), draft(6)),
    (draft(4), SimpleNamespace(draft_id="other", generation=5, base_design_id="part")),
    (draft(4), SimpleNamespace(draft_id="draft", generation=5, base_design_id="other-part")),
    (None, SimpleNamespace(draft_id="draft", generation=False, base_design_id="part")),
])
def test_prepared_generation_must_match_the_explicit_transition(previous, prepared):
    session, context, guards = setup(previous)
    source = session.design
    with pytest.raises(ValueError):
        publish_draft(session, prepared, **guards)
    assert session.design is source and session.revision == 7 and context.revision == 123


@pytest.mark.parametrize("bad_bump", ["absent", "double", "unstamped"])
def test_revision_hook_must_publish_exactly_one_matching_request_revision(bad_bump):
    session, context, guards = setup()
    source = session.design

    def bump(current):
        if bad_bump != "absent":
            current.revision += 2 if bad_bump == "double" else 1
        if bad_bump != "unstamped":
            context.set_request_revision(current.revision)

    with pytest.raises(RuntimeError, match="exactly one"):
        publish_draft(session, draft(), **{**guards, "bump_revision": bump})
    assert session.design is source and session.revision == 7 and context.revision == 123


def test_matching_part_and_revision_in_another_tab_cannot_accept_captured_source():
    left, _, left_guards = setup()
    right, right_context, right_guards = setup()
    # Even sharing the exact same Design object cannot bypass document binding.
    right.design = left.design
    right_context.doc = "right-tab"
    with pytest.raises(DraftInputError):
        publish_draft(right, draft(), **{**left_guards, "expected_session": right, "context": right_context,
                                       "bump_revision": right_guards["bump_revision"]})
    assert left.design is right.design and left.design.repair_draft is None
    assert left.revision == right.revision == 7


def test_closed_and_reopened_session_cannot_reuse_capture_even_with_same_source_and_revision():
    closed, _, guards = setup()
    reopened = SimpleNamespace(design=closed.design, revision=closed.revision,
                               history=Unvisited(), redo=Unvisited())
    guards["bump_revision"] = lambda *_: pytest.fail("Closed session capture reached publication")
    with pytest.raises(DraftInputError) as error:
        publish_draft(reopened, draft(), **guards)
    assert error.value.code == "draft_conflict"
    assert reopened.design is closed.design and reopened.design.repair_draft is None
    assert reopened.revision == closed.revision == 7
