"""Rollback evidence must survive drift and must never overwrite current config."""
import hashlib
import json
import os
import stat

import pytest

from tools.vr_capture.baseline import inspect_baseline, main


def fixture(tmp_path, *, symlink=False, kind="configuration"):
    source = tmp_path / "steamvr.vrsettings"
    source.write_text('{"steamvr":{"showMirrorView":false}}\n')
    if symlink:
        link = tmp_path / "active-settings"
        link.symlink_to(source.name)
        source = link
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    backup = snapshot / "saved-settings"
    backup.write_bytes(source.read_bytes())
    meta = source.stat()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    entry = dict(source=str(source), resolved_source=str(source.resolve()), backup=backup.name,
                 kind=kind, mode=oct(stat.S_IMODE(meta.st_mode)), uid=meta.st_uid, gid=meta.st_gid,
                 symlink=os.readlink(source) if source.is_symlink() else None,
                 sha256_backup=digest, sha256_source_before=digest, sha256_source_after=digest,
                 stable_during_copy=True)
    (snapshot / "file-manifest.json").write_text(json.dumps([entry]))
    return source, snapshot, entry


def test_default_cli_verifies_without_writing_source(tmp_path, capsys):
    source, snapshot, _ = fixture(tmp_path)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    assert main([str(snapshot)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["read_only"] and report["operation"] == "verify"
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_preserves_later_user_changes_and_records_conflict(tmp_path):
    source, snapshot, _ = fixture(tmp_path)
    source.write_text("new user settings")
    report = inspect_baseline(snapshot, restore_plan=True)
    assert report["backup_integrity_ok"]
    assert report["configuration_conflicts"] == 1
    assert report["files"][0]["state"] == "changed_review_required"
    assert report["files"][0]["planned_action"].startswith("review_conflict")
    assert source.read_text() == "new user settings"


def test_corrupt_backup_blocks_restore(tmp_path):
    _, snapshot, entry = fixture(tmp_path)
    (snapshot / entry["backup"]).write_text("corrupted")
    report = inspect_baseline(snapshot, restore_plan=True)
    assert not report["backup_integrity_ok"]
    assert report["files"][0]["planned_action"] == "blocked_invalid_backup"


@pytest.mark.parametrize("escape", ["../outside", "/absolute/outside", "symlink"])
def test_rejects_backup_paths_outside_snapshot(tmp_path, escape):
    source, snapshot, entry = fixture(tmp_path)
    if escape == "symlink":
        (snapshot / "symlink").symlink_to(source)
    entry["backup"] = escape
    (snapshot / "file-manifest.json").write_text(json.dumps([entry]))
    with pytest.raises(ValueError, match="snapshot"):
        inspect_baseline(snapshot)


def test_retargeted_config_symlink_is_conflict_even_with_identical_content(tmp_path):
    source, snapshot, _ = fixture(tmp_path, symlink=True)
    replacement = tmp_path / "other-settings"
    replacement.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(replacement.name)
    report = inspect_baseline(snapshot, restore_plan=True)
    assert report["files"][0]["state"] == "path_identity_conflict"
    assert source.is_symlink() and source.resolve() == replacement


def test_observation_paths_are_never_live_restore_candidates(tmp_path):
    _, snapshot, entry = fixture(tmp_path)
    entry["source"] = "/proc/this-must-never-be-read"
    entry["resolved_source"] = entry["source"]
    (snapshot / "file-manifest.json").write_text(json.dumps([entry]))
    report = inspect_baseline(snapshot, restore_plan=True)
    assert report["files"][0]["state"] == "saved_evidence_only"
    assert report["files"][0]["planned_action"] == "retain_evidence_do_not_restore"


def test_missing_original_requires_review_not_automatic_recreation(tmp_path):
    source, snapshot, _ = fixture(tmp_path)
    source.unlink()
    report = inspect_baseline(snapshot, restore_plan=True)
    assert report["files"][0]["state"] == "missing_review_required"
    assert not source.exists()


def test_permission_drift_is_reported(tmp_path):
    source, snapshot, _ = fixture(tmp_path)
    source.chmod(0o600 if stat.S_IMODE(source.stat().st_mode) != 0o600 else 0o640)
    report = inspect_baseline(snapshot)
    assert report["files"][0]["state"] == "changed_review_required"


def test_output_refuses_to_overwrite_current_file(tmp_path):
    source, snapshot, _ = fixture(tmp_path)
    before = source.read_bytes()
    with pytest.raises(FileExistsError):
        main([str(snapshot), "--output", str(source)])
    assert source.read_bytes() == before


def test_empty_manifest_cannot_claim_successful_verification(tmp_path):
    _, snapshot, _ = fixture(tmp_path)
    (snapshot / "file-manifest.json").write_text("[]")
    with pytest.raises(ValueError, match="nonempty"):
        inspect_baseline(snapshot)
