"""Verify a saved VR configuration baseline or produce a read-only rollback plan.

Default: ``python -m tools.vr_capture.baseline SNAPSHOT``.
Add ``--restore-plan`` for per-file recovery decisions. This tool never restores
files, edits settings, stops processes, or reads complete process environments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


_HASH = re.compile(r"[0-9a-f]{64}")
_OBSERVATION_ROOTS = {"proc", "sys", "dev"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"Not a regular file: {path}")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_path(snapshot: Path, entry: dict) -> Path:
    relative = Path(entry["backup"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Backup path must stay inside the snapshot")
    path = snapshot / relative
    if not path.resolve().is_relative_to(snapshot):
        raise ValueError("Backup symlink escapes the snapshot")
    return path


def inspect_baseline(snapshot: Path, *, restore_plan: bool = False) -> dict:
    """Check copied payloads and original config identities without writing either.

    Non-configuration entries (live sidecars, executable snapshots, sysfs) are
    checked as saved evidence only: their live paths are never read for rollback.
    Every config drift is a conflict requiring attribution, including deletion.
    """
    snapshot = snapshot.resolve(strict=True)
    entries = json.loads((snapshot / "file-manifest.json").read_text())
    if not isinstance(entries, list) or not entries:
        raise ValueError("Expected a nonempty list in file-manifest.json")
    results = []
    for entry in entries:
        source = Path(entry["source"])
        if not source.is_absolute() or len(source.parts) < 2:
            raise ValueError("Original configuration paths must be absolute")
        expected = entry["sha256_backup"]
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            raise ValueError("Invalid backup SHA256")
        backup = _backup_path(snapshot, entry)
        result = {
            "source": str(source), "backup": str(backup),
            "kind": entry.get("kind"), "expected_sha256": expected,
            "expected_mode": entry.get("mode"), "expected_uid": entry.get("uid"),
            "expected_gid": entry.get("gid"), "expected_symlink": entry.get("symlink"),
            "expected_resolved_source": entry.get("resolved_source"),
        }
        try:
            result["backup_sha256"] = _sha256(backup)
            result["backup_valid"] = (
                result["backup_sha256"] == expected
                and entry.get("stable_during_copy") is True
                and entry.get("sha256_source_before") == expected
                and entry.get("sha256_source_after") == expected
            )
        except (OSError, ValueError) as error:
            result.update(backup_valid=False, backup_error=str(error))
        eligible = entry.get("kind") == "configuration" and source.parts[1] not in _OBSERVATION_ROOTS
        result["configuration_restore_eligible"] = eligible
        if not eligible:
            result["state"] = "saved_evidence_only"
        else:
            try:
                source.lstat()
                current_link = os.readlink(source) if source.is_symlink() else None
                current_resolved = str(source.resolve())
                result.update(current_symlink=current_link, current_resolved_source=current_resolved)
                identity_matches = (
                    current_link == entry.get("symlink")
                    and current_resolved == entry.get("resolved_source")
                )
                if not identity_matches:
                    # Do not follow a config link whose target changed after baseline.
                    result["state"] = "path_identity_conflict"
                else:
                    current = source.stat()
                    result.update(current_sha256=_sha256(source), current_mode=oct(stat.S_IMODE(current.st_mode)),
                                  current_uid=current.st_uid, current_gid=current.st_gid)
                    same = all(result[f"current_{key}"] == result[f"expected_{key}"]
                               for key in ("sha256", "mode", "uid", "gid"))
                    result["state"] = "unchanged" if same else "changed_review_required"
            except FileNotFoundError:
                result["state"] = "missing_review_required"
            except (OSError, ValueError) as error:
                result.update(state="unreadable_review_required", current_error=str(error))
        if restore_plan:
            if not result["backup_valid"]:
                action = "blocked_invalid_backup"
            elif not eligible:
                action = "retain_evidence_do_not_restore"
            elif result["state"] == "unchanged":
                action = "none"
            else:
                action = "review_conflict_preserve_current_and_merge_experiment_changes_only"
            result["planned_action"] = action
        results.append(result)
    return {
        "schema": 1, "snapshot": str(snapshot), "read_only": True,
        "operation": "restore_plan" if restore_plan else "verify",
        "backup_integrity_ok": all(r["backup_valid"] for r in results),
        "configuration_matches": all(r["state"] == "unchanged" for r in results if r["configuration_restore_eligible"]),
        "configuration_conflicts": sum(r["configuration_restore_eligible"] and r["state"] != "unchanged" for r in results),
        "files": results,
        "restore_policy": "No automatic restoration. Attribute every difference to the experiment or later user edits; preserve current files before an approved scoped merge. Never restore proc/sys/dev or live sidecars over a running viewer.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--restore-plan", action="store_true", help="Produce review decisions; never modifies source configs")
    parser.add_argument("--output", type=Path, help="Create a new report file; refuses to overwrite an existing path")
    args = parser.parse_args(argv)
    try:
        report = inspect_baseline(args.snapshot, restore_plan=args.restore_plan)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Baseline inspection failed: {error}\n")
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as stream:
            stream.write(payload)
    else:
        print(payload, end="")
    return 0 if report["backup_integrity_ok"] and report["configuration_matches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
