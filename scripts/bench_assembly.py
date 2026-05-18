"""
bench_assembly.py — Phase 0 baseline harness for the "path to thousands" refactor.

What this does
--------------
Drives the FastAPI backend in-process (via fastapi.testclient.TestClient — same
pattern the test suite uses) and times an ordered, representative sequence of
assembly operations on a .nass file: load → fetch full geometry → polymerize
64 steps on an existing joint → resolve → export. Wall-clock per op is measured
with time.perf_counter and printed as a single JSON object on stdout. A
human-readable table is printed to stderr alongside.

How to run
----------
    export PATH="$HOME/.local/bin:$PATH"   # if you need uv/just
    python scripts/bench_assembly.py --n 500 workspace/hinge_test.nass
    python scripts/bench_assembly.py --n 50  workspace/hinge_test.nass
    python scripts/bench_assembly.py                 # defaults: --n 500, workspace/hinge_test.nass

--n N truncates the assembly to its first N instances (dropping joints that
reference removed instances) before the test runs, so the same source file can
be benchmarked at multiple scales.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_DEFAULT_NASS = "workspace/hinge_test.nass"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Allow running from any CWD (e.g. `python scripts/bench_assembly.py` vs
# `python /abs/path/scripts/bench_assembly.py`).
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _resolve_workspace_root(nass_path: Path) -> Path:
    """Pick the workspace dir containing the part .nadoc files referenced by
    the .nass. .nass files normally store relative ``source.path`` entries
    (e.g. ``Ultimate Polymer Hinge.nadoc``) that backend resolves against
    ``_WORKSPACE_DIR``. When running this script from a git worktree whose
    own ``workspace/`` is empty (or missing — workspace is gitignored), we
    point at the main checkout's workspace instead so the parts resolve.
    """
    candidates: list[Path] = []
    env_ws = os.environ.get("NADOC_WORKSPACE")
    if env_ws:
        candidates.append(Path(env_ws))
    candidates.append(_PROJECT_ROOT / "workspace")
    # Sibling repo at .../NADOC/workspace if we're in .claude/worktrees/<x>/.
    candidates.append(_PROJECT_ROOT.parent.parent.parent / "workspace")
    # The .nass's own parent dir is often where its parts live.
    candidates.append(nass_path.parent)
    for c in candidates:
        if c.is_dir():
            return c
    # Fall back to project-local workspace even if missing; backend will 4xx
    # with a useful message.
    return _PROJECT_ROOT / "workspace"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_PROJECT_ROOT), text=True,
        ).strip()
    except Exception:
        return "unknown"


def _truncate_assembly_json(text: str, n: int | None) -> tuple[str, int]:
    """Truncate the loaded assembly JSON to the first ``n`` instances.

    Drops joints whose ``instance_a_id`` or ``instance_b_id`` no longer exists,
    and prunes overhang bindings / connections / configurations that reference
    removed instances (so the import endpoint doesn't 4xx on us). Feature log
    is left intact — it's purely descriptive.

    Returns (json_text, final_instance_count).
    """
    data = json.loads(text)
    instances = data.get("instances", []) or []
    if n is not None and n < len(instances):
        instances = instances[:n]
        data["instances"] = instances

        kept_ids: set[str] = {i["id"] for i in instances}

        def _refs_ok(jt: dict) -> bool:
            a = jt.get("instance_a_id")
            b = jt.get("instance_b_id")
            return (a is None or a in kept_ids) and (b is None or b in kept_ids)

        data["joints"] = [j for j in (data.get("joints") or []) if _refs_ok(j)]

        # Conservative scrub of other instance-id-referencing collections —
        # if the .nass has none of these populated (the hinge_test fixture
        # doesn't), these are no-ops.
        def _binding_refs_ok(b: dict) -> bool:
            return (
                b.get("instance_a_id") in kept_ids
                and b.get("instance_b_id") in kept_ids
            )

        if data.get("overhang_bindings"):
            data["overhang_bindings"] = [
                b for b in data["overhang_bindings"] if _binding_refs_ok(b)
            ]
        if data.get("overhang_connections"):
            data["overhang_connections"] = [
                c for c in data["overhang_connections"]
                if c.get("instance_a_id") in kept_ids
                and c.get("instance_b_id") in kept_ids
            ]
    return json.dumps(data), len(instances)


def _pick_polymerize_joint(assembly: dict) -> str | None:
    """Find a joint with both endpoints set, suitable for polymerize.

    Polymerize also requires the two sides share the same source — for the
    hinge_test fixture every joint qualifies (uniform parts), so the first
    fully-connected joint is fine.
    """
    for j in assembly.get("joints", []):
        if j.get("instance_a_id") and j.get("instance_b_id"):
            return j["id"]
    return None


def _time_ms(fn) -> tuple[float, object]:
    t0 = time.perf_counter()
    out = fn()
    dt_ms = (time.perf_counter() - t0) * 1000.0
    return dt_ms, out


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark assembly operations.")
    ap.add_argument("path", nargs="?", default=_DEFAULT_NASS,
                    help="Path to .nass file (default: workspace/hinge_test.nass)")
    ap.add_argument("--n", type=int, default=None,
                    help="Truncate to first N instances before benchmarking")
    ap.add_argument("--polymerize-steps", type=int, default=64,
                    help="Steps for the polymerize op (default: 64)")
    args = ap.parse_args()

    nass_path = Path(args.path)
    if not nass_path.is_absolute():
        nass_path = (_PROJECT_ROOT / nass_path).resolve()
    if not nass_path.is_file():
        print(f"ERROR: file not found: {nass_path}", file=sys.stderr)
        return 2

    raw = nass_path.read_text(encoding="utf-8")
    content, n_instances = _truncate_assembly_json(raw, args.n)

    # Point the backend's _WORKSPACE_DIR at a real dir holding the part files
    # the .nass references (its ``source.path`` entries are typically relative).
    os.environ.setdefault("NADOC_WORKSPACE", str(_resolve_workspace_root(nass_path)))

    # Import the app lazily so any timing covers only the ops, not import cost.
    from fastapi.testclient import TestClient

    from backend.api import assembly_state
    from backend.api.main import app

    assembly_state.close_session()
    client = TestClient(app)

    ops: dict[str, float] = {}

    # 1. Load (via import — raw JSON content, mirrors the browser-upload path).
    def _load():
        r = client.post("/api/assembly/import", json={"content": content})
        assert r.status_code == 200, f"import failed: {r.status_code} {r.text[:300]}"
        return r.json()

    dt, loaded = _time_ms(_load)
    ops["load"] = dt
    assembly = loaded["assembly"]

    # 2. Fetch full assembly geometry.
    def _geom():
        r = client.get("/api/assembly/geometry")
        assert r.status_code == 200, f"geometry failed: {r.status_code} {r.text[:300]}"
        return r.json()

    dt, _ = _time_ms(_geom)
    ops["geometry"] = dt

    # 3. Polymerize 64 steps on an existing joint.
    jid = _pick_polymerize_joint(assembly)
    if jid is None:
        print("ERROR: no joint with both endpoints set; cannot polymerize.",
              file=sys.stderr)
        return 3

    # The seed mate's instance count already contributes 2 to the chain, so
    # `count = current + polymerize_steps` grows the chain by `polymerize_steps`
    # new instances. The route requires count >= 2 and treats count == 2 as a
    # no-op, so we always have count > 2 here.
    target_count = 2 + int(args.polymerize_steps)

    def _polym():
        r = client.post("/api/assembly/polymerize", json={
            "joint_id": jid,
            "count": target_count,
            "direction": "forward",
        })
        assert r.status_code == 200, f"polymerize failed: {r.status_code} {r.text[:300]}"
        return r.json()

    dt, _ = _time_ms(_polym)
    ops[f"polymerize_{args.polymerize_steps}"] = dt

    # 4. Resolve.
    def _resolve():
        r = client.post("/api/assembly/resolve", json={})
        assert r.status_code == 200, f"resolve failed: {r.status_code} {r.text[:300]}"
        return r.json()

    dt, _ = _time_ms(_resolve)
    ops["resolve"] = dt

    # 5. Export.
    def _export():
        r = client.get("/api/assembly/export")
        assert r.status_code == 200, f"export failed: {r.status_code} {r.text[:300]}"
        return r.content

    dt, _ = _time_ms(_export)
    ops["export"] = dt

    result = {
        "N": n_instances,
        "ops": {k: round(v, 3) for k, v in ops.items()},
        "git_sha": _git_sha(),
    }

    # Human-readable table → stderr (kept separate from JSON stdout so the
    # JSON line stays cleanly parseable by downstream tooling).
    print(f"\nbench_assembly  N={n_instances}  sha={result['git_sha'][:10]}",
          file=sys.stderr)
    print(f"  file: {nass_path}", file=sys.stderr)
    print(f"  {'op':<22}{'ms':>14}", file=sys.stderr)
    print(f"  {'-' * 22}{'-' * 14}", file=sys.stderr)
    for name, ms in result["ops"].items():
        print(f"  {name:<22}{ms:>14.3f}", file=sys.stderr)
    print("", file=sys.stderr)

    # Machine-readable JSON on stdout (single line).
    print(json.dumps(result))

    assembly_state.close_session()
    return 0


if __name__ == "__main__":
    sys.exit(main())
