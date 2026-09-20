"""Create a detached, instrumented pre-refactor viewer worktree without modifying source.

Usage: python3 scripts/prepare_viewer_baseline.py /absolute/path/to/new/baseline
No servers, installs, commits, downloads, or workspace migrations are performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BASELINE = "cce80858ff528a2648cba3f18351685f75dc673c"
ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTATION = [
    "frontend/build_info.js",
    "frontend/viewer_test_server.js",
    "frontend/src/perf/viewer_test_bridge.js",
    "frontend/src/perf/viewer_test_transport.js",
    "frontend/src/perf/viewer_test_transport.test.js",
    "frontend/src/perf/viewer_snapshot.js",
    "frontend/src/perf/viewer_file_open.js",
    "frontend/src/perf/viewer_file_open.test.js",
    "frontend/src/perf/viewer_test_bridge.test.js",
    "frontend/src/perf/viewer_test_server.test.js",
    "frontend/src/perf/viewer_snapshot.test.js",
    "frontend/src/ui/file_io.js",
    "frontend/src/perf/viewer_capture.js",
    "frontend/src/perf/viewer_metrics.js",
    "frontend/src/perf/viewer_performance.js",
    "frontend/src/perf/viewer_metrics.test.js",
    "frontend/src/perf/viewer_performance.test.js",
    "frontend/src/ui/viewer_performance_panel.js",
    "frontend/src/ui/viewer_performance_panel.test.js",
    "frontend/src/ui/process_log.js",
    "frontend/src/ui/process_log.css",
    "frontend/e2e/viewer_performance.spec.js",
    "frontend/e2e/viewer_performance_benchmark.spec.js",
    "frontend/e2e/global-teardown.js",
    "scripts/viewer_test.mjs",
    "scripts/nadoc_load.py",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    target = args.output.expanduser().resolve()
    if target.exists() or target.is_relative_to(ROOT):
        parser.error("Use a new directory outside the source checkout")
    subprocess.run(["git", "status", "--short"], cwd=ROOT, check=True)
    subprocess.run(["git", "log", "-1", "--oneline"], cwd=ROOT, check=True)
    payload = {name: (ROOT / name).read_bytes() for name in INSTRUMENTATION}
    source_hash = hashlib.sha256()
    for name, content in sorted(payload.items()):
        source_hash.update(name.encode() + b"\0" + content + b"\0")
    subprocess.run(["git", "worktree", "add", "--detach", str(target), BASELINE], cwd=ROOT, check=True)
    for name, content in payload.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    # Wire only diagnostics into the frozen renderer; do not copy candidate main.js.
    main_file = target / "frontend/src/main.js"
    source = main_file.read_text()
    anchor = "  const designRenderer = initDesignRenderer(scene, store)"
    if source.count(anchor) != 1:
        raise RuntimeError("Baseline renderer initialization no longer matches")
    source = "import { initViewerPerformance } from './perf/viewer_performance.js'\n" + source
    source = source.replace(anchor, anchor + "\n  initViewerPerformance({ renderer, camera, controls, store, addFrameCallback, removeFrameCallback, captureCurrentCamera, getDetailLevel: () => designRenderer.getDetailLevel(), getFileOpen: () => _fileOpen })")
    main_file.write_text(source)
    config_file = target / "frontend/vite.config.js"
    config = config_file.read_text()
    config = "import { frontendBuildInfo } from './build_info.js'\nimport { viewerTestPlugin } from './viewer_test_server.js'\n" + config
    config = config.replace("export default {", "export default {\n  plugins: [viewerTestPlugin()],\n  define: { __NADOC_BUILD_INFO__: JSON.stringify(frontendBuildInfo(__dirname)) },", 1)
    config_file.write_text(config)
    # Existing dependencies can be shared read-only for local testing. Each worktree
    # retains its own build directory, workspace, cache, and server processes.
    for name in ["frontend/node_modules", ".venv"]:
        original = ROOT / name
        dest = target / name
        if original.is_dir() and not dest.exists():
            dest.symlink_to(original, target_is_directory=True)
    docs = target / "docs/viewer_performance_manual.md"
    if (ROOT / "docs/viewer_performance_manual.md").exists():
        shutil.copyfile(ROOT / "docs/viewer_performance_manual.md", docs)
    (target / "viewer-baseline-provenance.json").write_text(json.dumps({
        "baseline_commit": BASELINE,
        "instrumentation_sha256": source_hash.hexdigest(),
        "instrumentation_files": INSTRUMENTATION,
        "note": "Detached original renderer plus diagnostics only. No measured performance claim.",
    }, indent=2) + "\n")
    print(f"Baseline prepared at {target}. See docs/viewer_performance_manual.md for isolated launch commands.")


if __name__ == "__main__":
    main()
