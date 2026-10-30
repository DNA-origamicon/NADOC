"""A comparison-fixture admission failure must not leak document context."""
from contextlib import ExitStack
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from backend.api import doc_context, part_evaluation_jobs as jobs, state
from tests.test_part_evaluation_comparison import ready


def test_capture_setup_failure_restores_document_and_removes_session(monkeypatch):
    previous = doc_context.get_current_doc()
    captured = []

    def fail(_request):
        captured.append(doc_context.get_current_doc())
        assert captured[-1] != previous
        assert state.peek_design(captured[-1]) is not None
        raise HTTPException(413, 'Part verification capture budget exceeded')

    monkeypatch.setattr(jobs, 'start', fail)
    with ExitStack() as cleanup:
        request = SimpleNamespace(addfinalizer=cleanup.callback)
        fixture = ready.__wrapped__(monkeypatch, request)
        with pytest.raises(HTTPException, match='capture budget exceeded'):
            next(fixture)
    assert doc_context.get_current_doc() == previous
    assert captured and state.peek_design(captured[0]) is None
