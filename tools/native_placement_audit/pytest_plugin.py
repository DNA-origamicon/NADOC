"""Persistent reports for every marked positioning failure, including xdist."""

import json
from pathlib import Path
import re
import shlex

import pytest

from .store import _jsonable, check_review_gate, record_failure, report_directory

NATIVE_FILES = {"test_measured_positioning.py", "test_measured_atomistic.py", "test_display_placement.py",
                "test_native_full_placement.py", "test_native_slab_placement.py",
                "test_oxdna_extensions.py", "test_oxdna_extra_bases.py", "test_cg_seed_ssdna_collapse.py"}
GATE_SELF_TEST = "test_native_placement_review_gate.py"
_config = None
_selected = False
_report_directory = None


def pytest_configure(config):
    global _config, _selected, _report_directory
    _config, _selected = config, False
    # Runtime-negative tests may temporarily redirect their own incident store.
    # Actual parent test failures must remain in the runner's durable ledger.
    _report_directory = report_directory()
    config.addinivalue_line("markers", "native_placement: native Full positioning; failure requires explicit review")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        path = Path(item.path)
        if path.name != GATE_SELF_TEST and (path.name in NATIVE_FILES or "native_placement" in path.name):
            item.add_marker(pytest.mark.native_placement)


@pytest.fixture
def native_placement_evidence(request):
    """Attach source identities and expected/actual coordinate/delta evidence."""
    request.node.add_marker(pytest.mark.native_placement)

    def attach(**evidence):
        request.node.user_properties.append(("native_placement_evidence", json.dumps(_jsonable(evidence))))
    return attach


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if item.get_closest_marker("native_placement"):
        report.user_properties.append(("native_placement", True))
        report.user_properties.append(("native_placement_source", str(item.path)))
        if call.excinfo is not None and hasattr(call.excinfo.value, "details"):
            report.user_properties.append(("native_placement_evidence",
                                           json.dumps(_jsonable(call.excinfo.value.details))))


def pytest_runtest_logreport(report):
    global _selected
    if _config is None or hasattr(_config, "workerinput"):
        return  # Only the xdist controller writes each received failure.
    props = getattr(report, "user_properties", ())
    marked = any(k == "native_placement" and v for k, v in props)
    if not marked:
        return
    _selected = True
    if report.failed or (report.skipped and getattr(report, "wasxfail", None)):
        details = [json.loads(v) for k, v in props if k == "native_placement_evidence"]
        source = next((v for k, v in props if k == "native_placement_source"), None)
        # Explicit files outside rootdir can have a pathless '::test_name'
        # nodeid. Keep the actual item path so the saved command is reproducible.
        test_id = str(source) + report.nodeid if source and report.nodeid.startswith("::") else report.nodeid
        record_failure({"test_id": test_id, "phase": report.when,
            "exception": report.longreprtext or str(getattr(report, "wasxfail", "Placement regression failed")), "evidence": details,
            "reproduce_command": "uv run pytest " + shlex.quote(test_id) + " -vv",
            "source_files": [source or test_id.split("::", 1)[0]], "runner": "pytest"}, directory=_report_directory)


def pytest_collectreport(report):
    global _selected
    path = Path(report.nodeid.split("::", 1)[0])
    filename = path.name
    # Collection can fail before decorators execute, so individually marked
    # suites need a source check too. Successful unmarked tests in such a file
    # retain their ordinary scope; this check applies only to collection errors.
    source_marked = False
    marked_source = None
    if report.failed and _config is not None:
        source = path if path.is_absolute() else _config.rootpath / path
        candidates = [source]
        # An explicitly selected file outside rootdir (e.g. isolated probes with
        # -c /dev/null) can fail at the session collector, whose nodeid names the
        # root rather than the file. Resolve only selected files identified in
        # this exception, never every marked file in the invocation.
        for argument in _config.args:
            selected = Path(str(argument).split("::", 1)[0])
            if selected.suffix == ".py" and selected.name in report.longreprtext:
                candidates.append(selected if selected.is_absolute() else _config.invocation_params.dir / selected)
        for candidate in candidates:
            if candidate.suffix == ".py" and candidate.is_file() and re.search(
                    r"\bpytest\s*\.\s*mark\s*\.\s*native_placement\b",
                    candidate.read_text(encoding="utf-8", errors="replace")):
                source_marked, marked_source = True, candidate
                break
    if report.failed and (filename in NATIVE_FILES or "native_placement" in filename or source_marked):
        if _config is not None and not hasattr(_config, "workerinput"):
            _selected = True
            test_id = report.nodeid if path.suffix == ".py" else str(marked_source or report.nodeid)
            record_failure({"test_id": test_id, "phase": "collection", "runner": "pytest",
                "exception": report.longreprtext, "reproduce_command": "uv run pytest " + shlex.quote(test_id),
                "source_files": [str(marked_source)] if marked_source else []}, directory=_report_directory)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session):
    if not _selected or hasattr(session.config, "workerinput") or session.config.option.collectonly:
        return
    pending = check_review_gate(_report_directory)
    if pending:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal:
            terminal.write_sep("!", "NATIVE FULL PLACEMENT REVIEW REQUIRED", red=True)
            for incident in pending:
                terminal.write_line(f"{incident['incident_id']}: {incident['test_id']}\n  {incident['html']}")
            terminal.write_line("Passing reruns do not clear this gate. Complete the review in docs/native_placement_review.md.")
