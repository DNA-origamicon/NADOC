"""Selection contracts use file metadata and mocked launchers, never broad suites."""

import json
from pathlib import Path
import subprocess

import pytest

from scripts import test_affected as backend
from scripts import test_frontend as frontend


@pytest.fixture
def repo(tmp_path):
    for name in ("backend/leaf.py", "backend/unknown.py", "tests/test_leaf.py",
                 "tests/test_consumer.py", "frontend/src/leaf.js", "frontend/src/leaf.test.js",
                 "frontend/src/style.css"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return tmp_path


def test_mapping_includes_consumers_and_deduplicates_explicit_tests(repo):
    selected, reasons = backend.select(
        ["backend/leaf.py", "tests/test_leaf.py"], ["tests/test_consumer.py"], "",
        repo, {"backend/leaf.py": ["tests/test_leaf.py", "tests/test_consumer.py"]})
    assert selected == ["tests/test_consumer.py", "tests/test_leaf.py"]
    assert len(reasons) == 2


@pytest.mark.parametrize("tests,reason", [([], ""), (["tests/test_leaf.py"], ""), ([], "reviewed")])
def test_unknown_impact_cannot_silently_pass_or_expand(repo, tests, reason):
    with pytest.raises(ValueError, match="Unmapped"):
        backend.select(["backend/unknown.py"], tests, reason, repo, {})


def test_unknown_impact_requires_tests_and_explicit_rationale(repo):
    selected, reasons = backend.select(["backend/unknown.py"], ["tests/test_consumer.py"],
                                       "covers the API consumer", repo, {})
    assert selected == ["tests/test_consumer.py"]
    assert "covers the API consumer" in reasons[0]


@pytest.mark.parametrize("target", ["tests/", "../outside.py", "backend/leaf.py", "tests/missing.py"])
def test_invalid_test_targets_fail(repo, target):
    with pytest.raises(ValueError):
        backend.test_target(target, repo)


def test_deleted_mapping_target_and_empty_selection_fail(repo):
    with pytest.raises(ValueError):
        backend.select(["backend/leaf.py"], [], "", repo,
                       {"backend/leaf.py": ["tests/deleted.py"]})
    with pytest.raises(ValueError):
        backend.select([], [], "", repo, {})
    with pytest.raises(ValueError):
        backend.select(["backend/leaf.py"], [], "", repo, {"backend/leaf.py": []})


def test_repo_manifest_targets_exist():
    mapping = json.loads(backend.MAP.read_text())
    for source, targets in mapping.items():
        assert backend.relative_file(source) == source
        assert targets
        for target in targets:
            assert backend.test_target(target) == target


def test_backend_command_preserves_resource_and_scope_guards():
    cmd = backend.command(["tests/test_focused_selection.py"])
    assert cmd[1].endswith("validation_guard.sh")
    assert cmd[3].endswith("test_guard.sh")
    assert cmd[4:8] == ["test-affected", "0", "focused", "--"]
    assert "tests/" not in cmd
    assert "not slow" not in cmd


def test_frontend_explicit_and_related_commands(repo):
    explicit = frontend.command(["src/leaf.test.js", "frontend/src/leaf.test.js"], False, repo)
    related = frontend.command(["frontend/src/leaf.js"], True, repo)
    assert explicit[1].endswith("validation_guard.sh")
    assert explicit[-2:] == ["run", "src/leaf.test.js"]
    assert related[-3:] == ["related", "--run", "src/leaf.js"]
    assert "--passWithNoTests" not in related
    assert frontend.command(["src/leaf.test.js"], False, repo, watch=True)[-2:] == ["watch", "src/leaf.test.js"]
    assert frontend.command(["src/leaf.js"], True, repo, watch=True)[-2:] == ["related", "src/leaf.js"]


@pytest.mark.parametrize("paths,related", [([], False), (["src/"], False),
    (["src/leaf.js"], False), (["../backend/leaf.py"], True), (["src/style.css"], True)])
def test_frontend_rejects_implicit_sweeps_and_non_import_inputs(repo, paths, related):
    with pytest.raises(ValueError):
        frontend.command(paths, related, repo)


def test_dry_run_never_launches_and_real_run_propagates_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(backend.subprocess, "call", lambda *a, **k: calls.append((a, k)) or 7)
    target = "tests/test_focused_selection.py"
    assert backend.main([target, "--dry-run"]) == 0
    assert not calls
    assert backend.main([target]) == 7
    assert calls[0][1]["cwd"] == backend.ROOT
    calls.clear()
    target = "src/ui/library_filename.test.js"
    assert frontend.main([target, "--dry-run"]) == 0
    assert not calls
    assert frontend.main([target]) == 7
    assert calls[0][1]["cwd"] == frontend.ROOT / "frontend"


def test_broad_recipes_remain_explicit_and_session_gated():
    recipes = (Path(__file__).resolve().parents[1] / "justfile").read_text()
    for name in ("test-regression", "test-fast", "test-frontend-all"):
        assert f'test_guard.sh "{name}" 0 1 --' in recipes
    assert "scripts/test_affected.py" in recipes
    assert "scripts/test_frontend.py" in recipes


def test_just_preserves_rationale_arguments_without_shell_evaluation():
    reason = "covers endpoint consumers; $(false) and `false` remain literal"
    result = subprocess.run([
        "just", "test-smart", "justfile", "--test", "tests/test_focused_selection.py",
        "--reason", reason, "--dry-run",
    ], cwd=backend.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert reason in result.stdout


@pytest.mark.parametrize("recipe", ["test-smart", "test-affected", "test-frontend", "test-frontend-watch"])
def test_empty_just_selection_cannot_start_a_suite(recipe):
    result = subprocess.run(["just", recipe], cwd=backend.ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "required: paths" in result.stderr
    assert "test session starts" not in result.stdout
