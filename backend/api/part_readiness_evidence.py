"""Read-only evidence budget for a single sealed readiness worker request."""
import json
from pathlib import Path

from backend.core.models import Design
from backend.core.oxdna_staleness import design_build_fingerprint
from backend.core.part_document_io import MAX_METADATA_BYTES


class EvidenceLimit(RuntimeError):
    """Must escape ordinary unreadable-record handling: the assessment is incomplete."""


class EvidenceReader:
    def __init__(self):
        self.remaining = MAX_METADATA_BYTES
        self.entries = 30_000  # existing input-graph node allowance

    def visit(self):
        self.entries -= 1
        if self.entries < 0:
            raise EvidenceLimit('Readiness evidence exceeds its input-node allowance')

    def read_file(self, path, *, limit=None, label=None):
        self.visit()
        allowance = min(self.remaining, limit if limit is not None else self.remaining)
        with Path(path).open('rb') as stream:
            value = stream.read(allowance + 1)
        if len(value) > allowance:
            raise EvidenceLimit('Readiness evidence exceeds its cumulative byte allowance')
        self.remaining -= len(value)
        return value

    def read_json(self, path):
        value = json.loads(self.read_file(path))
        if not isinstance(value, dict):
            raise ValueError('Job metadata must be an object')
        return value

    def archive_index(self, root):
        try:
            return self.read_json(root / '.archive_index.json')
        except (OSError, ValueError):
            return {}

    def live_paths(self, root):
        if not root.exists():
            return
        for entry in root.iterdir():
            self.visit()
            path = entry / 'job.json'
            if path.is_file():
                yield path

    def snapshot_identity(self, path):
        design = Design.from_json(self.read_file(path).decode('utf-8'))
        return design.id, design_build_fingerprint(design)

    def revision_identity(self, workspace, project, revision):
        from backend.core.project_revisions import ProjectRevisionStore
        design = ProjectRevisionStore(workspace).load_design(project, revision, reader=self.read_file)
        return design.id, design_build_fingerprint(design)
