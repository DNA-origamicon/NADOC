"""Immutable, bounded presentation artifacts; never authored molecular documents."""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_PRESENTATION_BYTES = 512 * 1024 * 1024
LIBRARY_FOLDER = "compiled_presentations"


class PresentationLibrary:
    def __init__(self, workspace: Path):
        self.root = workspace / LIBRARY_FOLDER

    def _check_root(self):
        if self.root.is_symlink():
            raise ValueError("Presentation library must not be a symbolic link")

    def path(self, presentation_id: str, suffix=".html") -> Path:
        self._check_root()
        if not re.fullmatch(r"[a-f0-9]{64}", presentation_id):
            raise ValueError("Invalid presentation identifier")
        path = self.root / (presentation_id + suffix)
        if path.is_symlink():
            raise ValueError("Presentation files must not be symbolic links")
        return path

    def begin(self):
        self._check_root()
        self.root.mkdir(parents=True, exist_ok=True)
        return tempfile.NamedTemporaryFile(dir=self.root, suffix=".partial", delete=False)

    def commit(self, temporary: Path, name: str, kind: str) -> dict:
        size = temporary.stat().st_size
        if not 0 < size <= MAX_PRESENTATION_BYTES:
            raise ValueError("Invalid presentation size")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            prefix = handle.read(65536)
            if not prefix.lower().startswith(b"<!doctype html>") or b'id="nadoc-presentation-data"' not in prefix:
                raise ValueError("Expected a compiled NADOC presentation")
            digest.update(prefix)
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        key = digest.hexdigest()
        dest, metadata = self.path(key), self.path(key, ".json")
        if metadata.exists() and dest.exists():
            return json.loads(metadata.read_text())
        record = {"id": key, "name": name, "kind": kind, "size": size,
                  "created_at": datetime.now(timezone.utc).isoformat()}
        # The manifest is the visibility marker. Never list partial uploads.
        os.replace(temporary, dest)
        with self.begin() as out:
            meta_temp = Path(out.name)
            try:
                out.write(json.dumps(record).encode())
                out.flush()
                os.fsync(out.fileno())
                os.replace(meta_temp, metadata)
            finally:
                meta_temp.unlink(missing_ok=True)
        return record

    def entries(self) -> list[dict]:
        self._check_root()
        entries = []
        for path in self.root.glob("*.json"):
            try:
                metadata = self.path(path.stem, ".json")
                data = json.loads(metadata.read_text())
                artifact = self.path(path.stem)
                if data["id"] == path.stem and artifact.stat().st_size == data["size"]:
                    entries.append(data)
            except (ValueError, OSError, KeyError, TypeError):
                continue
        return sorted(entries, key=lambda entry: entry["created_at"], reverse=True)
