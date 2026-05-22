"""
gen_hinge_fixture.py — generate a clean N-hinge .nass progression for the
LOD/scale benchmark ("path to thousands").

Why this exists
---------------
The hand-saved hinge fixtures in workspace/ are inconsistent ("50 hinge
test.nass" actually holds 11 instances; there is no 500-hinge file). For
benchmarking we want a reproducible progression of N = 1, 20, 50, 200, 500
identical-part chains, all grown the SAME way so FPS/LOD numbers are
comparable across scales.

How it works
------------
Drives the FastAPI backend in-process (TestClient, same pattern as
bench_assembly.py). Takes a real saved chain (default: "200 hinge test.nass"),
reduces it to a 2-instance seed (instances 0+1 + the joint that connects them —
that joint carries mate_relative_transform, so resolve is correct), then for
each target N:
    import seed  →  polymerize(count=N, forward)  →  export  →  save
N=1 skips polymerize (just imports a 1-instance assembly).

Output goes to workspace/bench_fixtures/bench_hinge_{N:03d}.nass — a NEW dir,
so existing user .nass files are never overwritten.

Run
---
    export PATH="$HOME/.local/bin:$PATH"
    export NADOC_WORKSPACE=/home/joshua/NADOC/workspace
    python scripts/gen_hinge_fixture.py
    python scripts/gen_hinge_fixture.py --counts 1,20,50,200,500 \
        --seed "workspace/200 hinge test.nass"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DEFAULT_SEED = "workspace/200 hinge test.nass"
_OUT_DIR = _PROJECT_ROOT / "workspace" / "bench_fixtures"


def _instances(data: dict) -> list:
    return data.get("instances_v2") or data.get("instances") or []


def _set_instances(data: dict, insts: list) -> None:
    if "instances_v2" in data:
        data["instances_v2"] = insts
    else:
        data["instances"] = insts


def _build_seed(full: dict, keep: int) -> dict:
    """Reduce a full chain .nass dict to its first ``keep`` instances + the
    joints whose endpoints both survive. Clears the feature log and any
    instance-referencing collections so the imported seed starts clean."""
    data = json.loads(json.dumps(full))  # deep copy
    insts = _instances(data)[:keep]
    _set_instances(data, insts)
    kept_ids = {i["id"] for i in insts}

    def _refs_ok(jt: dict) -> bool:
        a, b = jt.get("instance_a_id"), jt.get("instance_b_id")
        return (a is None or a in kept_ids) and (b is None or b in kept_ids)

    data["joints"] = [j for j in (data.get("joints") or []) if _refs_ok(j)]

    # Start the seed with an empty history + no instance-referencing extras.
    data["feature_log"] = []
    data["feature_log_cursor"] = -1
    for k in ("overhang_bindings", "overhang_connections", "configurations",
              "camera_poses", "animations"):
        if k in data:
            data[k] = []
    return data


def _pick_joint(assembly: dict) -> str | None:
    for j in assembly.get("joints", []):
        if j.get("instance_a_id") and j.get("instance_b_id"):
            return j["id"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate N-hinge bench fixtures.")
    ap.add_argument("--seed", default=_DEFAULT_SEED,
                    help=f"Source .nass chain to seed from (default: {_DEFAULT_SEED})")
    ap.add_argument("--counts", default="1,20,50,200,500",
                    help="Comma-separated target instance counts.")
    ap.add_argument("--out-dir", default=str(_OUT_DIR),
                    help=f"Output directory (default: {_OUT_DIR})")
    args = ap.parse_args()

    seed_path = Path(args.seed)
    if not seed_path.is_absolute():
        seed_path = (_PROJECT_ROOT / seed_path).resolve()
    if not seed_path.is_file():
        print(f"ERROR: seed not found: {seed_path}", file=sys.stderr)
        return 2

    counts = [int(c) for c in args.counts.split(",") if c.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve the part files the .nass references (its source.path entries are
    # relative to the workspace). Default to the main checkout's workspace.
    os.environ.setdefault("NADOC_WORKSPACE", str(_PROJECT_ROOT / "workspace"))

    full = json.loads(seed_path.read_text(encoding="utf-8"))
    if len(_instances(full)) < 2:
        print("ERROR: seed file needs >=2 instances to derive a mate.",
              file=sys.stderr)
        return 2

    from fastapi.testclient import TestClient

    from backend.api import assembly_state
    from backend.api.main import app

    print(f"seed: {seed_path}  (NADOC_WORKSPACE={os.environ['NADOC_WORKSPACE']})",
          file=sys.stderr)

    results = []
    for n in counts:
        assembly_state.close_session()
        client = TestClient(app)

        seed_keep = 1 if n == 1 else 2
        seed = _build_seed(full, seed_keep)

        r = client.post("/api/assembly/import",
                        json={"content": json.dumps(seed)})
        assert r.status_code == 200, f"import failed N={n}: {r.status_code} {r.text[:300]}"

        if n >= 2:
            jid = _pick_joint(r.json()["assembly"])
            assert jid, f"no polymerizable joint in seed for N={n}"
            r = client.post("/api/assembly/polymerize",
                            json={"joint_id": jid, "count": n, "direction": "forward"})
            assert r.status_code == 200, \
                f"polymerize failed N={n}: {r.status_code} {r.text[:300]}"

        # Sanity: geometry must resolve with no per-source errors (the
        # workspace-missing-source trap from bench_assembly.py).
        g = client.get("/api/assembly/geometry")
        assert g.status_code == 200, f"geometry failed N={n}: {g.status_code}"
        errs = g.json().get("errors") or {}
        if errs:
            print(f"  WARN N={n}: /assembly/geometry returned errors: {errs}",
                  file=sys.stderr)

        exp = client.get("/api/assembly/export")
        assert exp.status_code == 200, f"export failed N={n}: {exp.status_code}"
        out_text = exp.text
        out_data = json.loads(out_text)
        got = len(_instances(out_data))

        out_file = out_dir / f"bench_hinge_{n:03d}.nass"
        out_file.write_text(out_text, encoding="utf-8")
        ok = "OK" if got == n else f"!! got {got}"
        results.append((n, got, out_file, ok))
        print(f"  N={n:<4} -> {out_file.name:24s} instances={got:<4} {ok}",
              file=sys.stderr)

    assembly_state.close_session()

    print(json.dumps({
        "out_dir": str(out_dir),
        "fixtures": [{"n": n, "got": got, "file": str(f), "status": ok}
                     for (n, got, f, ok) in results],
    }))
    bad = [r for r in results if r[1] != r[0]]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
