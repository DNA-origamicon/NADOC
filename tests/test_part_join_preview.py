"""Preview-selected reference inputs remain isolated and revision/document bound."""
from collections import OrderedDict

import pytest
from fastapi import HTTPException

from backend.api import part_join_preview as previews
from backend.api.doc_context import reset_current_doc, set_current_doc


@pytest.fixture(autouse=True)
def preview_store(monkeypatch):
    token = set_current_doc("join-preview-inputs-test")
    monkeypatch.setattr(previews, "_pending", OrderedDict())
    try:
        yield
    finally:
        reset_current_doc(token)


def test_preview_choices_are_independent_inputs_and_reusable_on_failed_commit():
    choices = [{"anchor_a": {"helix_id": "h"}}]
    previews.remember("token", "design", 3, choices)
    choices[0]["anchor_a"]["helix_id"] = "mutated"
    result = previews.resolve("token", "design", 3)
    assert result[0]["anchor_a"]["helix_id"] == "h"
    result.clear()
    assert previews.resolve("token", "design", 3)


@pytest.mark.parametrize("design,revision", [("other", 3), ("design", 4)])
def test_source_change_cannot_reuse_preview_choices(design, revision):
    previews.remember("token", "design", 3, [])
    with pytest.raises(HTTPException) as exc:
        previews.resolve("token", design, revision)
    assert exc.value.status_code == 409


def test_preview_choices_are_document_scoped():
    previews.remember("token", "design", 3, [])
    token = set_current_doc("different-document")
    try:
        with pytest.raises(HTTPException):
            previews.resolve("token", "design", 3)
    finally:
        reset_current_doc(token)


def test_same_preview_token_cannot_silently_replace_its_choices():
    previews.remember("token", "design", 3, [{"anchor_a": "original"}])
    previews.remember("token", "design", 3, [{"anchor_a": "original"}])
    with pytest.raises(ValueError, match="choices changed"):
        previews.remember("token", "design", 3, [{"anchor_a": "different"}])
    assert previews.resolve("token", "design", 3) == [{"anchor_a": "original"}]


def test_preview_retention_has_age_count_and_input_limits(monkeypatch):
    monkeypatch.setattr(previews, "MAX_PREVIEWS", 2)
    monkeypatch.setattr(previews, "monotonic", lambda: 0)
    for i in range(3):
        previews.remember(str(i), "design", 3, [])
    with pytest.raises(HTTPException):
        previews.resolve("0", "design", 3)
    monkeypatch.setattr(previews, "monotonic", lambda: previews.TTL_SECONDS + 1)
    with pytest.raises(HTTPException):
        previews.resolve("2", "design", 3)
    previews.remember("new", "design", 3, [])
    assert len(previews._pending) == 1
    with pytest.raises(ValueError, match="input limit"):
        previews.remember("huge", "design", 3, ["x" * previews.MAX_CHOICES_BYTES])
    assert len(previews._pending) == 1
