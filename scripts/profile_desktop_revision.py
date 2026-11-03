"""Separate revision-store CPU and fsync costs using disposable documents."""
import cProfile
import gzip
import io
import json
import os
from pathlib import Path
import pstats
import statistics
import tempfile
import time
from scripts.benchmark_desktop_documents import measure


def main():
    root = Path(os.environ['TMPDIR']).resolve()
    assert Path('/media/jojo/Archive').is_mount() and root.is_relative_to('/media/jojo/Archive')
    assert os.environ.get('NADOC_VALIDATION_SCOPE') == '1'
    from backend.api import state
    from backend.core.lattice import make_bundle_design
    from backend.core.models import SnapshotLogEntry
    from backend.core.project_revisions import ProjectRevisionStore
    design = make_bundle_design([(i, 0) for i in range(24)], length_bp=84)
    body, size = state.encode_design_snapshot(design)
    design.feature_log = [SnapshotLogEntry(op_kind='nick', label='Synthetic recovery state', params={}, design_snapshot_gz_b64=body, snapshot_size_bytes=size, post_state_gz_b64=body, post_state_size_bytes=size) for _ in range(1000)]
    raw = design.model_dump_json().encode()
    rows = []
    for level in (9, 6, 3):
        timing, compressed = measure(lambda: gzip.compress(raw, compresslevel=level, mtime=0), 11)
        assert gzip.decompress(compressed) == raw
        rows.append(dict(level=level, compressed_bytes=len(compressed), raw_bytes=len(raw), **timing))
    with tempfile.TemporaryDirectory(prefix='revision-profile-', dir=root) as directory:
        store = ProjectRevisionStore(Path(directory))
        profile = cProfile.Profile()
        head = None
        profile.enable()
        for i in range(5):
            design.metadata.name = str(i)
            result = store.commit(design, loadout_id='benchmark', loadout_name='Benchmark', parent_revision_id=head, expected_head=head)
            head = result.revision_id
        profile.disable()
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(30)
    print(json.dumps(dict(scope='CPU profile and compression screening; synthetic 24 helices / 1000 retained history entries. Compression alternatives are not implemented gains.', compression=rows, profile=stream.getvalue()), indent=2))


if __name__ == '__main__':
    main()
