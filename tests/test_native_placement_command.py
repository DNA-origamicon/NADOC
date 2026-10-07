"""Native CTest failures use the same durable review protocol as pytest."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.native_placement_audit import check_review_gate

pytestmark = pytest.mark.native_placement


def command(directory, source):
    return subprocess.run([sys.executable, "-m", "tools.native_placement_audit.command", "--test-id", "isolated-native-check",
        "--directory", str(directory), "--", sys.executable, "-c", source],
        capture_output=True, text=True, timeout=10)


def test_failed_native_command_persists_stdout_stderr_and_green_rerun_cannot_clear(tmp_path):
    failed = command(tmp_path, "import sys; print('O5 evidence'); print('invalid slab',file=sys.stderr); sys.exit(3)")
    assert failed.returncode == 2
    incidents = check_review_gate(tmp_path)
    assert len(incidents) == 1
    report = json.loads(Path(incidents[0]["report"]).read_text())
    assert report["evidence"]["stdout"] == "O5 evidence\n"
    assert report["evidence"]["stderr"] == "invalid slab\n"
    assert report["evidence"]["returncode"] == 3
    assert report["source_ids"]
    assert command(tmp_path, "pass").returncode == 2
    assert len(check_review_gate(tmp_path)) == 1


@pytest.mark.parametrize("status", [0, 77])
def test_native_command_preserves_success_and_explicit_skip_without_incident(tmp_path, status):
    assert command(tmp_path, f"raise SystemExit({status})").returncode == status
    assert check_review_gate(tmp_path) == []
