"""Manage the explicitly disposable, user-editable VR testing part folder.

Only .nadoc files beneath the marked folder are removed on reset. No symlinked
subdirectory is traversed. Reports and validation expectations live elsewhere.
"""
from contextlib import contextmanager
import argparse
import fcntl
import json
import hashlib
import os
from pathlib import Path

MARKER = '.nadoc-vr-testing.json'
POLICY = {'schema': 'nadoc-vr-testing-workspace-1',
          'reset_policy': 'delete_all_nadoc_parts_including_user_edits',
          'validation_source': False}
README = '''# VR testing workspace

These parts are persistent between test runs. You may open, inspect, and edit them.
**Retesting deletes all .nadoc parts in this folder and its real subfolders,
even if you edited or renamed them.** Move anything you want to keep outside this
folder before retesting. Other user workspace folders are not reset.

These files are test outputs, never fixtures or expected validation results.
Workflow definitions and independent assertions live in tools/vr_workflows and tests.
Evidence is retained under .development-artifacts/vr-workflows, outside this folder.
Symlinked directories are not traversed. Non-part files are retained.

User authorization: 2026-09-22, persistent VR testing workspace with deletion of
old part files on retest, including user edits. See docs/vr_authoring_workflows.md.
'''


def initialize(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('VR testing folder itself must not be a symlink')
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if marker.exists() or marker.is_symlink():
        verify(root)
    else:
        if any(root.iterdir()):
            raise ValueError('refuse to adopt a nonempty unmarked folder')
        with marker.open('x') as stream:
            json.dump(POLICY, stream, indent=2)
        (root / 'README.md').write_text(README)
    return root.resolve()


def verify(root):
    root = Path(root)
    marker = root / MARKER
    if root.is_symlink() or marker.is_symlink() or not marker.is_file():
        raise ValueError('expected an explicitly initialized VR testing folder')
    if json.loads(marker.read_text()) != POLICY:
        raise ValueError('workspace policy mismatch')


@contextmanager
def campaign_workspace(root):
    """Hold for the whole run, including cleanup and writes, to exclude other runs."""
    root = Path(root)
    verify(root)
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    fd = os.open(root / '.campaign.lock', flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root
    finally:
        os.close(fd)


def reset_parts(root):
    """Caller holds campaign_workspace lock. Edited parts are intentionally deleted."""
    root = Path(root)
    verify(root)
    deleted = []
    for directory, subdirs, files in os.walk(root, followlinks=False):
        subdirs[:] = [name for name in subdirs if not (Path(directory)/name).is_symlink()]
        for name in files:
            path = Path(directory)/name
            if path.suffix.lower() == '.nadoc':
                path.unlink()  # A file symlink is unlinked; its target is never removed.
                deleted.append(str(path.relative_to(root)))
    return sorted(deleted)


def publish_parts(root, sources):
    """Publish verified run outputs, never reading old editable parts as inputs."""
    from backend.core.models import Design
    root = Path(root)
    if not sources or set(sources) - {'desktop-then-vr', 'vr-first'}:
        raise ValueError('expected named workflow outputs')
    prepared = {}
    for name, source in sources.items():
        source = Path(source).resolve(strict=True)
        if source.is_relative_to(root.resolve()):
            raise ValueError('editable review parts cannot be publication inputs')
        content = source.read_bytes()
        design = Design.from_json(content.decode())
        if not design.helices:
            raise ValueError('review output must contain authored geometry')
        prepared[name] = (source, content)
    with campaign_workspace(root):
        deleted = reset_parts(root)
        written = []
        for name, (source, content) in prepared.items():
            destination = root / (name+'.nadoc')
            destination.write_bytes(content)
            written.append({'path':str(destination.resolve()), 'source':str(source),
                            'sha256':hashlib.sha256(content).hexdigest()})
    return {'deleted':deleted, 'written':written}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'reset', 'prepare', 'publish'])
    parser.add_argument('--desktop-then-vr', type=Path)
    parser.add_argument('--vr-first', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2]/'workspace'/'VR Testing')
    args = parser.parse_args()
    if args.action == 'init':
        print(initialize(args.root))
    elif args.action == 'publish':
        print(json.dumps(publish_parts(args.root, {name:value for name,value in
            [('desktop-then-vr',args.desktop_then_vr),('vr-first',args.vr_first)] if value is not None})))
    else:
        with campaign_workspace(args.root):
            deleted = reset_parts(args.root)
            created = []
            if args.action == 'prepare':
                from backend.core.models import Design, LatticeType
                for name in ('desktop-then-vr', 'vr-first'):
                    path = args.root / (name+'.nadoc')
                    design = Design(metadata={'name': 'VR Testing — '+name}, lattice_type=LatticeType.HONEYCOMB)
                    with path.open('x') as stream:
                        stream.write(design.to_json())
                    created.append(str(path))
            print(json.dumps({'deleted': deleted, 'created': created}))


if __name__ == '__main__':
    main()
