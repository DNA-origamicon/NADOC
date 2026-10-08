import pytest
from fastapi import HTTPException
from backend.api import doc_context
from backend.api.generation_progress import tracking, report, snapshot


def test_progress_is_document_scoped_monotone_and_terminal():
    token = doc_context.set_current_doc("test-generator-progress")
    try:
        with tracking("stage-test-success"):
            report("Route crossovers", "Pass 1", 0.4)
            report("Route crossovers", "Pass 2", 0.3)
            assert snapshot("stage-test-success")["fraction"] == 0.4
            assert snapshot("stage-test-success")["detail"] == "Pass 2"
            other = doc_context.set_current_doc("another-generator-doc")
            try:
                with pytest.raises(HTTPException) as error:
                    snapshot("stage-test-success")
                assert error.value.status_code == 404
            finally:
                doc_context.reset_current_doc(other)
            report("Geometry", "Build display", 0.98)
        assert snapshot("stage-test-success")["state"] == "complete"
        assert snapshot("stage-test-success")["fraction"] == 1
        assert snapshot("stage-test-success")["steps"] == [
            "Planning",
            "Route crossovers",
        ]
    finally:
        doc_context.reset_current_doc(token)


def test_failed_progress_does_not_report_completion_and_reporter_resets():
    token = doc_context.set_current_doc("test-generator-progress-failure")
    try:
        with pytest.raises(ValueError), tracking("stage-test-failure"):
            report("Check reach", "", 0.8)
            raise ValueError("Unreachable")
        report("Unrelated later operation", "", 1)
        assert snapshot("stage-test-failure")["state"] == "failed"
        assert snapshot("stage-test-failure")["fraction"] == 0.8
    finally:
        doc_context.reset_current_doc(token)
