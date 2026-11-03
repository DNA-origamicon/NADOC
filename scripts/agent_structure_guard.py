"""Mandatory fail-closed publication boundary for agent-authored NADOC parts."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from backend.core.models import Design
from backend.core.part_history_proof import command_rows
from experiments.recorded_review_process import ProcessRequired, verify


def audit(design):
    """Require part authoring operations as well as complete process replay."""
    for feature_id, kind, params in command_rows(design, 2000):
        if kind == 'diagnostic-process' or kind.startswith('assembly-'):
            action = params.get('action', kind)
            raise ProcessRequired(
                f'Feature {feature_id} ({action}) is not a user-facing part operation. '
                'Assembly and internal simulation/diagnostic steps cannot author a .nadoc part.'
            )
    return verify(design)


def publish(design, path, *, expected_existing_sha256=None):
    """Verify the serialized artifact before creating/replacing the named file."""
    path = Path(path)
    raw = design.model_dump_json()
    result = audit(Design.model_validate_json(raw))
    if path.exists():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_existing_sha256 is None or actual != expected_existing_sha256:
            raise ProcessRequired('Existing destination changed or replacement was not explicitly bound')
    elif expected_existing_sha256 is not None:
        raise ProcessRequired('Expected replacement target is missing')
    # Verification completes before any file is created. Exclusive staging and
    # replacement preserve an existing file if writing fails.
    temporary = path.with_name(path.name + '.agent-writing')
    owns_staging = False
    try:
        with temporary.open('x') as stream:
            owns_staging = True
            stream.write(raw)
        if expected_existing_sha256 is None:
            os.link(temporary, path)  # refuse if a destination appeared during staging
        else:
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_existing_sha256:
                raise ProcessRequired('Replacement destination changed during staging')
            temporary.replace(path)
    finally:
        if owns_staging:
            temporary.unlink(missing_ok=True)
    return {**result, 'path':str(path), 'sha256':hashlib.sha256(raw.encode()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(Design.model_validate_json(args.file.read_text())), indent=2))
