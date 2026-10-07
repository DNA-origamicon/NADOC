"""Isolated negative probes; genuine parent failures retain the durable review gate."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools.native_placement_audit.evidence import coordinate_deltas
from tools.native_placement_audit.store import (
    acknowledge, check_review_gate, record_failure,
)

pytestmark = pytest.mark.native_placement


def review():
    return {"root_cause": "Deliberate isolated mismatch in gate self-test",
            "affected_paths": ["temporary synthetic regression"],
            "validation": "The corrected fixture passed; the gate stayed closed until explicit review",
            "regression_tests": ["test_failure_report_survives_a_green_rerun"],
            "evidence": ["Expected/actual coordinates are in the immutable report"]}


def test_report_keeps_every_site_and_explicit_acknowledgement(tmp_path):
    evidence = coordinate_deltas([[0, 0, 0], [1, 0, 0]], [[0, 0, 0], [1.2, 0, 0]], identities=["f", "r"])
    result = record_failure({"test_id": "fixture::native", "exception": "radius mismatch <unsafe>",
                             "evidence": evidence}, tmp_path)
    report_path = Path(result["report"])
    before = report_path.read_bytes()
    report = json.loads(before)
    assert report["evidence"]["sites"][1]["distance_nm"] == pytest.approx(0.2)
    assert report["source_ids"]
    assert "&lt;unsafe&gt;" in Path(result["html"]).read_text()
    assert len(check_review_gate(tmp_path)) == 1
    assert len(check_review_gate(tmp_path)) == 1  # A check cannot clear a failure.
    with pytest.raises(ValueError, match="Review needs"):
        acknowledge(result["incident_id"], reviewer="reviewer", review={}, directory=tmp_path)
    acknowledge(result["incident_id"], reviewer="self-test", review=review(), directory=tmp_path)
    assert check_review_gate(tmp_path) == []
    assert report_path.read_bytes() == before
    assert json.loads((tmp_path / "REVIEW_REQUIRED.json").read_text())["status"] == "reviewed"


def test_missing_evidence_and_new_incidents_keep_gate_closed(tmp_path):
    first = record_failure({"test_id": "first", "exception": "failure"}, tmp_path)
    second = record_failure({"test_id": "second", "exception": "failure"}, tmp_path)
    acknowledge(first["incident_id"], reviewer="self-test", review=review(), directory=tmp_path)
    assert [p["incident_id"] for p in check_review_gate(tmp_path)] == [second["incident_id"]]
    Path(second["report"]).unlink()  # Test-owned tmpdir; simulate evidence loss.
    assert check_review_gate(tmp_path)[0]["missing_evidence"]


def test_failure_report_survives_a_green_rerun(tmp_path):
    target = tmp_path / "test_fixture.py"
    target.write_text("import pytest\n@pytest.mark.native_placement\ndef test_site(native_placement_evidence):\n"
                      "    native_placement_evidence(identity='h:1:FORWARD', expected=[0,0,0], actual=[1,0,0])\n"
                      "    assert False, 'deliberate radius mismatch'\n")
    repo = Path(__file__).resolve().parents[1]
    reports = tmp_path / "reports"
    env = {**os.environ, "NADOC_PLACEMENT_REPORT_DIR": str(reports), "PYTHONPATH": str(repo),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-m", "pytest", "-p", "tools.native_placement_audit.pytest_plugin",
               "-c", "/dev/null", str(target), "-q"]
    failed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    pending = check_review_gate(reports)
    assert len(pending) == 1
    assert json.loads(Path(pending[0]["report"]).read_text())["evidence"][0]["identity"] == "h:1:FORWARD"
    target.write_text("import pytest\n@pytest.mark.native_placement\ndef test_site():\n    assert True\n")
    green = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert green.returncode == 1, green.stdout + green.stderr
    assert "1 passed" in green.stdout
    assert "REVIEW REQUIRED" in green.stdout
    assert len(check_review_gate(reports)) == 1
    acknowledge(pending[0]["incident_id"], reviewer="self-test", review=review(), directory=reports)
    reviewed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr


def test_nonfinite_coordinate_failure_is_reportable(tmp_path):
    import numpy as np
    result = record_failure({"test_id": "nan", "exception": "Non-finite geometry",
                             "evidence": {"actual": np.array([float("nan"), float("inf"), 0])}}, tmp_path)
    assert json.loads(Path(result["report"]).read_text())["evidence"]["actual"] == ["nan", "inf", 0]


@pytest.mark.parametrize("failure", ["syntax", "import", "unmarked_import", "gate_import"])
def test_collection_error_reports_source_markers_without_broadening_execution_scope(tmp_path, failure):
    # The ordinary fixture deliberately has no native filename/suffix; the gate
    # case proves this infrastructure's own import errors are guarded too.
    # Import fails before the marker executes; the syntax case cannot be parsed.
    target = tmp_path / ("test_native_placement_review_gate.py" if failure == "gate_import" else "test_coordinate_frame.py")
    marked = failure != "unmarked_import"
    prefix = "import pytest\n" + ("raise ImportError('fixture import failed')\n" if "import" in failure else "")
    marker = "@pytest.mark.native_placement\n" if marked else ""
    body = "def test_site(:\n    pass\n" if failure == "syntax" else "def test_site():\n    pass\n"
    target.write_text(prefix + marker + body)
    repo = Path(__file__).resolve().parents[1]
    reports = tmp_path / "reports"
    env = {**os.environ, "NADOC_PLACEMENT_REPORT_DIR": str(reports), "PYTHONPATH": str(repo),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-m", "pytest", "-p", "tools.native_placement_audit.pytest_plugin",
               "-c", "/dev/null", str(target), "-q"]
    failed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert failed.returncode != 0, failed.stdout + failed.stderr
    pending = check_review_gate(reports)
    if not marked:
        assert pending == []
        return
    assert len(pending) == 1, failed.stdout + failed.stderr
    report = json.loads(Path(pending[0]["report"]).read_text())
    assert report["phase"] == "collection"
    assert target.name in report["test_id"]
    assert ("SyntaxError" if failure == "syntax" else "ImportError") in report["exception"]
    assert Path(pending[0]["html"]).exists()


def test_parent_assertion_keeps_runner_ledger_when_runtime_probe_changes_environment(tmp_path):
    target = tmp_path / "test_native_placement_review_gate.py"
    unusable = tmp_path / "runtime-report-file"
    unusable.write_text("Deliberately unusable runtime journal")
    target.write_text("import pytest\npytestmark = pytest.mark.native_placement\n"
                      "def test_parent_assertion(monkeypatch):\n"
                      f"    monkeypatch.setenv('NADOC_PLACEMENT_REPORT_DIR', {str(unusable)!r})\n"
                      "    assert False, 'A real parent regression must remain durable'\n")
    repo = Path(__file__).resolve().parents[1]
    reports = tmp_path / "runner-reports"
    env = {**os.environ, "NADOC_PLACEMENT_REPORT_DIR": str(reports), "PYTHONPATH": str(repo),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    command = [sys.executable, "-m", "pytest", "-p", "tools.native_placement_audit.pytest_plugin",
               "-c", "/dev/null", str(target), "-q"]
    failed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "INTERNALERROR" not in failed.stdout + failed.stderr
    pending = check_review_gate(reports)
    assert len(pending) == 1
    report = json.loads(Path(pending[0]["report"]).read_text())
    assert report["test_id"].endswith("test_native_placement_review_gate.py::test_parent_assertion")
    assert "A real parent regression must remain durable" in report["exception"]
    assert unusable.read_text() == "Deliberately unusable runtime journal"


def test_runtime_native_error_returns_500_and_retains_review_latch(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_placement_integrity import native_placement_exception_handler
    from backend.core.native_full_placement import NativePlacementError

    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    app.add_exception_handler(NativePlacementError, native_placement_exception_handler)

    @app.get("/geometry-probe")
    def fail():
        raise NativePlacementError("Native O5 position missing", details={"identity": "h:4:FORWARD", "actual": [float("nan"), float("inf"), 0]})

    response = TestClient(app).get("/geometry-probe", headers={"X-NADOC-Doc": "preserved-copy"})
    assert response.status_code == 500
    assert response.json()["detail"]["review_required"] is True
    assert response.json()["detail"]["details"]["actual"] == ["nan", "inf", 0]
    incident = check_review_gate(tmp_path)[0]
    report = json.loads(Path(incident["report"]).read_text())
    assert report["evidence"]["document_id"] == "preserved-copy"
    assert report["evidence"]["details"]["identity"] == "h:4:FORWARD"
    assert Path(incident["html"]).exists()


def test_frontend_runtime_post_records_exact_diagnostic(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_placement_integrity import router

    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/design/placement-integrity-status").json()["review_required"] is False
    response = client.post("/api/design/placement-integrity-report", json={
        "message": "Missing canonical native slab frame", "identity": "h:3:REVERSE",
        "field": "native_slab_center", "expected": "3D position", "actual": None,
    })
    assert response.status_code == 200
    assert response.json()["review_required"] is True
    report = json.loads(Path(check_review_gate(tmp_path)[0]["report"]).read_text())
    assert report["evidence"]["identity"] == "h:3:REVERSE"
    assert report["evidence"]["field"] == "native_slab_center"
    status = client.get("/api/design/placement-integrity-status").json()
    assert status["review_required"] is True
    assert status["incidents"][0]["incident_id"] == response.json()["incident_id"]
    assert status["incidents"][0]["details"]["evidence"]["identity"] == "h:3:REVERSE"
    acknowledge(response.json()["incident_id"], reviewer="self-test", review=review(), directory=tmp_path)
    assert client.get("/api/design/placement-integrity-status").json()["review_required"] is False


def test_expected_native_rejection_does_not_open_incident(tmp_path, monkeypatch):
    from backend.core.native_full_placement import NativePlacementError

    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path))
    with pytest.raises(NativePlacementError, match="invalid native site"):
        raise NativePlacementError("invalid native site")
    assert check_review_gate(tmp_path) == []
    assert not (tmp_path / "REVIEW_REQUIRED.json").exists()


def test_runtime_status_cannot_report_clear_when_journal_is_corrupt(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_placement_integrity import router

    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path))
    (tmp_path / "REVIEW_REQUIRED.json").write_text("{broken json")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    response = TestClient(app).get("/api/design/placement-integrity-status")
    assert response.status_code == 503
    assert response.json()["review_required"] is True
    assert response.json()["report_delivery_error"]


def test_never_created_journal_is_clear_without_creating_it(tmp_path):
    reports = tmp_path / "never-created"
    assert check_review_gate(reports) == []
    assert not reports.exists()


def test_interrupted_incident_without_report_or_marker_is_not_clear(tmp_path, monkeypatch):
    from backend.api import routes_placement_integrity as integrity

    # A failed first write (for example disk full) leaves no marker to recover.
    (tmp_path / "incidents" / "20260101T000000-000000000000").mkdir(parents=True)
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="no report or review marker"):
        check_review_gate()
    response = integrity.placement_integrity_status()
    assert response.status_code == 503
    assert json.loads(response.body)["review_required"] is True


@pytest.mark.parametrize("location", ["root", "incidents", "incident"])
@pytest.mark.parametrize("fault", ["file", "unreadable"])
def test_unverifiable_journal_cannot_report_clear_or_publish(tmp_path, monkeypatch, location, fault):
    from fastapi import HTTPException
    from backend.api import routes_placement_integrity as integrity

    reports = tmp_path / "reports"
    target = reports
    if location != "root":
        target /= "incidents"
    if location == "incident":
        target /= "20260101T000000-000000000000"
    target.parent.mkdir(parents=True, exist_ok=True)
    if fault == "file":
        target.write_text("A journal directory must not silently become a file")
        expected_error = NotADirectoryError
    else:
        target.mkdir()
        real_scandir = os.scandir
        def denied_scandir(path):
            if Path(path) == target:
                raise PermissionError("Cannot enumerate the placement journal")
            return real_scandir(path)
        monkeypatch.setattr(os, "scandir", denied_scandir)
        expected_error = PermissionError
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(reports))

    with pytest.raises(expected_error):
        check_review_gate()
    response = integrity.placement_integrity_status()
    assert response.status_code == 503
    assert json.loads(response.body)["review_required"] is True
    event = tmp_path / "viewer-event"
    with pytest.raises(HTTPException) as rejected:
        integrity.require_native_placement_review_clear(event_path=event)
    assert rejected.value.status_code == 503
    assert rejected.value.detail["report_delivery_error"]
    assert Path(str(event) + ".placement-error").exists()


def test_vitest_failure_and_green_rerun_share_the_durable_gate(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    vitest = repo / "frontend/node_modules/vitest/vitest.mjs"
    if not shutil.which("node") or not vitest.exists():
        pytest.skip("Vitest/Node unavailable; frontend CI exercises the configured reporter")
    target = tmp_path / "probe.native_placement.test.js"
    config = tmp_path / "vitest.config.mjs"
    config.write_text("export default " + json.dumps({"root": str(tmp_path), "test": {
        "environment": "node", "globals": True, "maxWorkers": 1,
        "include": ["probe.native_placement.test.js"],
        "reporters": ["default", str(repo / "frontend/native_placement_reporter.js")],
    }}) + ";\n")
    target.write_text("test('preserves native placement', () => expect({radius:1}).toEqual({radius:.8491}));\n")
    reports = tmp_path / "review-ledger"
    env = {**os.environ, "NADOC_PLACEMENT_REPORT_DIR": str(reports)}
    command = ["node", str(vitest), "run", "--config", str(config)]
    failed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert failed.returncode != 0, failed.stdout + failed.stderr
    pending = check_review_gate(reports)
    assert len(pending) == 1, failed.stdout + failed.stderr
    report = json.loads(Path(pending[0]["report"]).read_text())
    assert report["runner"] == "vitest"
    assert report["evidence"][0]["actual"]
    target.write_text("test('preserves native placement', () => expect(.8491).toBe(.8491));\n")
    green = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert green.returncode != 0, green.stdout + green.stderr
    assert "1 passed" in green.stdout
    assert len(check_review_gate(reports)) == 1
    acknowledge(pending[0]["incident_id"], reviewer="self-test", review=review(), directory=reports)
    reviewed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr


def test_ci_review_manifest_must_match_exact_report(tmp_path):
    from tools.native_placement_audit.__main__ import main

    original = tmp_path / "downloaded"
    restored = tmp_path / "ci-restored"
    manifests = tmp_path / "review-manifests"
    created = record_failure({"test_id": "ci-native", "exception": "Mismatch"}, original)
    shutil.copytree(original, restored)
    review_file = tmp_path / "completed-review.json"
    review_file.write_text(json.dumps(review()))
    manifest = manifests / (created["incident_id"] + ".json")
    assert main(["--directory", str(original), "acknowledge", created["incident_id"],
                 "--reviewer", "self-test", "--review", str(review_file), "--export-review", str(manifest)]) == 0
    valid = manifest.read_text()
    wrong = json.loads(valid)
    wrong["report_sha256"] = "0" * 64
    manifest.write_text(json.dumps(wrong))
    arguments = ["--directory", str(restored), "apply-reviews", "--from-directory", str(manifests)]
    assert main(arguments) == 2
    assert len(check_review_gate(restored)) == 1
    manifest.write_text(valid)
    assert main(arguments) == 0
    assert check_review_gate(restored) == []
