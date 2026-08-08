"""Offline pins for the node-side early-stop evaluator (backend/core/remote_cutoff_eval.py).

The evaluator is a copy of md_cutoff's pure decision + namd_metrics' frame parser,
vendored so it runs stdlib-only on a bare Alpine node.  These tests prove the
vendored copies stay in LOCKSTEP with the originals (same thresholds, same decisions
on the same data, same parse on the same log text) and pin the CLI exit-code contract
the sbatch depends on.  They also replay it against real relaxation logs (mirroring
experiments/exp36_relax_cutoff_bank/) to confirm the remote skip decision matches the
local gate on identical data.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from backend.core import md_cutoff
from backend.core import namd_metrics
from backend.core import remote_cutoff_eval as ev

_REPO = Path(__file__).resolve().parents[1]


# ── 1. stdlib-only invariant (must run on a bare node) ─────────────────────────


def test_evaluator_imports_nothing_from_backend():
    import re

    src = Path(ev.__file__).read_text()
    # No ACTUAL import of backend (docstring/comment provenance references are fine).
    for ln in src.splitlines():
        assert not re.match(r"\s*(from|import)\s+backend", ln), ln


# ── node scripts must parse+run on an OLD python3 (Alpine bare node < 3.7) ──────


def _evaluated_new_syntax_annotations(path):
    """AST-scan for annotations that are EVALUATED at import/def time and use
    Python 3.9+ generic subscription (``list[str]``) or 3.10+ unions (``X | Y``) —
    these crash on the < 3.7 node python.  Function-LOCAL annotations are excluded
    (Python never evaluates them).  Returns a list of offending (lineno, snippet)."""
    import ast

    tree = ast.parse(Path(path).read_text())
    bad = []

    def is_new(node):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            return node.value.id in {
                "list",
                "dict",
                "tuple",
                "set",
                "frozenset",
                "type",
            }
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return True
        return False

    def check(ann):
        if ann is None:
            return
        for n in ast.walk(ann):
            if is_new(n):
                bad.append((getattr(ann, "lineno", -1), ast.dump(ann)[:60]))

    # Evaluated contexts: function signatures + module/class-level AnnAssign.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for a in [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]:
                check(a.annotation)
            check(node.returns)

    # module- and class-level AnnAssign (NOT the ones inside function bodies)
    def scan_annassign(body):
        for stmt in body:
            if isinstance(stmt, ast.AnnAssign):
                check(stmt.annotation)
            if isinstance(stmt, ast.ClassDef):
                scan_annassign(stmt.body)

    scan_annassign(tree.body)
    return bad


@pytest.mark.parametrize(
    "mod", [ev, __import__("backend.core.remote_health_eval", fromlist=["x"])]
)
def test_node_scripts_are_old_python_safe(mod):
    import ast
    import py_compile

    tree = ast.parse(Path(mod.__file__).read_text())
    future = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "__future__"
    ]
    assert not future, (
        "no __future__ import — SyntaxErrors on Alpine's <3.7 node python3"
    )
    # No 3.7+ stdlib at MODULE scope (would ModuleNotFoundError on the 3.6 node python;
    # `dataclasses` was the live-caught one). Runtime imports inside functions (e.g. the
    # health wrapper's MDAnalysis via _load_md_health) are exempt — those are the Tier-A
    # modern-python path, not the bare-node path.
    PY37_PLUS = {
        "dataclasses",
        "contextvars",
        "importlib.metadata",
        "graphlib",
        "zoneinfo",
        "tomllib",
    }
    top_imports = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            top_imports |= {a.name.split(".")[0] for a in stmt.names}
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            top_imports.add(stmt.module.split(".")[0])
    assert not (top_imports & PY37_PLUS), (
        f"3.7+ stdlib imported at module scope (breaks 3.6 node python): {top_imports & PY37_PLUS}"
    )
    bad = _evaluated_new_syntax_annotations(mod.__file__)
    assert not bad, (
        f"evaluated 3.9+/3.10+ annotations would crash the old node python: {bad}"
    )
    py_compile.compile(mod.__file__, doraise=True)  # parses clean


# ── 2. thresholds vendored verbatim ────────────────────────────────────────────


def test_cutoff_params_match_source():
    a = md_cutoff.CutoffParams()
    b = ev.CutoffParams()
    for field in a.__dataclass_fields__:
        assert getattr(a, field) == getattr(b, field), field


# ── 3. decision parity on synthesized series ───────────────────────────────────


def _frames(pots, vols=None):
    out = []
    for i, p in enumerate(pots):
        row = {"TS": float(i), "POTENTIAL": p}
        if vols is not None:
            row["VOLUME"] = vols[i]
        out.append(row)
    return out


def test_energy_plateaued_parity_flat_and_drifting():
    flat = _frames(
        [-1_000_000.0 + (i % 2) * 5.0 for i in range(30)]
    )  # tiny noise, no drift
    drift = _frames([-1_000_000.0 + i * 400.0 for i in range(30)])  # steady climb
    for frames in (flat, drift):
        assert ev.energy_plateaued(frames) == md_cutoff.energy_plateaued(frames)
    assert ev.energy_plateaued(flat) is True
    assert ev.energy_plateaued(drift) is False


def test_should_early_stop_parity_with_wc():
    flat = _frames([-1_000_000.0 + (i % 2) * 5.0 for i in range(30)])
    wc_flat = [0.90 + (i % 2) * 0.005 for i in range(30)]
    wc_drift = [0.90 - i * 0.01 for i in range(30)]
    for wc in (wc_flat, wc_drift):
        a, _ = md_cutoff.should_early_stop_stage(flat, wc)
        b, _ = ev.should_early_stop_stage(flat, wc)
        assert a == b
    assert ev.should_early_stop_stage(flat, wc_flat)[0] is True
    assert ev.should_early_stop_stage(flat, wc_drift)[0] is False


# ── 4. frame-parser parity on real log text ────────────────────────────────────


def _find_relax_logs(limit=6):
    ws = _REPO / "workspace" / "md_jobs"
    if not ws.is_dir():
        return []
    logs = [
        p
        for p in ws.glob("*/package/*/*_p*.log")
        if "production" not in p.name.lower() and "qualification" not in p.name.lower()
    ]
    return sorted(logs)[:limit]


def test_frame_parser_matches_namd_metrics_on_real_logs():
    logs = _find_relax_logs()
    if not logs:
        pytest.skip("no real relaxation logs in workspace/md_jobs")
    for log in logs:
        text = log.read_text(errors="replace")
        assert ev.parse_namd_log_frames(text) == namd_metrics.parse_namd_log_frames(log)


def test_replay_decision_matches_local_gate_on_real_logs():
    logs = _find_relax_logs()
    if not logs:
        pytest.skip("no real relaxation logs in workspace/md_jobs")
    for log in logs:
        text = log.read_text(errors="replace")
        frames = ev.parse_namd_log_frames(text)
        code, _ = ev.decide(text)  # Tier B (energy only)
        if len(frames) < md_cutoff.CutoffParams().min_frames:
            assert code == 2  # insufficient -> fail safe
        else:
            want = 0 if md_cutoff.energy_plateaued(frames) else 1
            assert code == want, log.name


# ── 5. exp36 bank replay (parsed frames -> identical decisions) ─────────────────


def test_bank_frames_decisions_match_source():
    banks = sorted(
        (_REPO / "experiments" / "exp36_relax_cutoff_bank").glob("bank*/frames.tsv")
    )
    if not banks:
        pytest.skip("exp36 bank not present")
    checked = 0
    for tsv in banks:
        by_seg: dict[str, list[dict]] = {}
        with tsv.open() as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                f = {
                    "POTENTIAL": _f(row.get("POTENTIAL")),
                    "VOLUME": _f(row.get("VOLUME")),
                }
                by_seg.setdefault(row["segment"], []).append(f)
        for frames in by_seg.values():
            assert ev.energy_plateaued(frames) == md_cutoff.energy_plateaued(frames)
            checked += 1
    assert checked > 0


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── 6. CLI exit-code contract ──────────────────────────────────────────────────


def _write_log(tmp_path, pots):
    lines = ["ETITLE:      TS   POTENTIAL      VOLUME"]
    for i, p in enumerate(pots):
        lines.append(f"ENERGY:  {i}   {p}   3000000.0")
    log = tmp_path / "chunk.log"
    log.write_text("\n".join(lines) + "\n")
    return log


def test_cli_exit_skip_on_plateau(tmp_path):
    log = _write_log(tmp_path, [-1_000_000.0 + (i % 2) * 5.0 for i in range(30)])
    assert ev.main(["--log", str(log)]) == 0


def test_cli_exit_hold_when_drifting(tmp_path):
    log = _write_log(tmp_path, [-1_000_000.0 + i * 400.0 for i in range(30)])
    assert ev.main(["--log", str(log)]) == 1


def test_cli_exit_err_on_insufficient_frames(tmp_path):
    log = _write_log(tmp_path, [-1_000_000.0] * 5)  # < min_frames
    assert ev.main(["--log", str(log)]) == 2


def test_cli_exit_err_on_missing_log(tmp_path):
    assert ev.main(["--log", str(tmp_path / "nope.log")]) == 2


def test_cli_tier_a_holds_when_wc_drifts(tmp_path):
    import json

    log = _write_log(tmp_path, [-1_000_000.0 + (i % 2) * 5.0 for i in range(30)])
    wc = tmp_path / "wc.json"
    wc.write_text(json.dumps([0.90 - i * 0.01 for i in range(30)]))  # WC degrading
    # energy flat but WC drifting -> Tier A must HOLD (the unsafe case Tier B can't see)
    assert ev.main(["--log", str(log), "--wc", str(wc)]) == 1


def test_cli_tier_a_skips_when_both_flat(tmp_path):
    import json

    log = _write_log(tmp_path, [-1_000_000.0 + (i % 2) * 5.0 for i in range(30)])
    wc = tmp_path / "wc.json"
    wc.write_text(json.dumps([0.90 + (i % 2) * 0.005 for i in range(30)]))
    assert ev.main(["--log", str(log), "--wc", str(wc)]) == 0


# ── 7. runs standalone (no backend on sys.path) ────────────────────────────────


def test_runs_as_standalone_script(tmp_path):
    """Copy the evaluator elsewhere and run it with a bare python3 — proves the
    staged node copy executes without the NADOC package importable."""
    import shutil

    dst = tmp_path / "nadoc_cutoff_eval.py"
    shutil.copy2(ev.__file__, dst)
    log = _write_log(tmp_path, [-1_000_000.0 + (i % 2) * 5.0 for i in range(30)])
    proc = subprocess.run(
        [sys.executable, str(dst), "--log", str(log)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},  # no PYTHONPATH -> no backend
    )
    assert proc.returncode == 0, proc.stderr
