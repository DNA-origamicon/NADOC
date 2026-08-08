"""Offline pins for the Tier-A node WC health step (remote_health_eval.py).

Tier A needs numpy/scipy/MDAnalysis on the node.  MDAnalysis IS installed in the dev
env, and there are real relaxation packages under workspace/md_jobs, so we can run the
ACTUAL node path here (minus the cluster) end-to-end: produce output/<seg>.wc.json from
a real chunk DCD, confirm it matches md_health.run_health_check, and feed it to the
stdlib cutoff evaluator's --wc gate.  Skips cleanly if MDAnalysis or a package is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core import remote_cutoff_eval, remote_health_eval

_REPO = Path(__file__).resolve().parents[1]

pytest.importorskip("MDAnalysis")


def _find_nondeclash_chunk():
    """(package_dir, stem, seg) for the smallest non-declash relaxation chunk with a
    DCD + log, or None.  Non-declash = no ``{stem}_build.pdb`` declash marker."""
    ws = _REPO / "workspace" / "md_jobs"
    if not ws.is_dir():
        return None
    best = None
    for dcd in ws.glob("*/package/*/output/*_p*.dcd"):
        name = dcd.stem  # <seg>
        if any(k in name.lower() for k in ("production", "cont", "qualification")):
            continue
        pkg = dcd.parent.parent
        if not (pkg / f"{name}.log").exists():  # seg log lives at package root
            continue
        # infer stem from a non-hmr psf present in the package
        psfs = [p for p in pkg.glob("*.psf") if "hmr" not in p.name]
        if not psfs:
            continue
        stem = psfs[0].stem
        if (pkg / f"{stem}_build.pdb").exists():  # declash design — skip
            continue
        if not (pkg / f"{stem}.pdb").exists():
            continue
        size = dcd.stat().st_size
        if best is None or size < best[0]:
            best = (size, pkg, stem, name)
    return None if best is None else (best[1], best[2], best[3])


def test_health_eval_writes_wc_json_matching_run_health_check(tmp_path):
    found = _find_nondeclash_chunk()
    if not found:
        pytest.skip("no real non-declash relaxation chunk in workspace/md_jobs")
    pkg, stem, seg = found
    from backend.core import md_health

    out = tmp_path / "wc.json"
    rc = remote_health_eval.main(
        ["--package-dir", str(pkg), "--seg", seg, "--stem", stem, "--out", str(out)]
    )
    assert rc == 0, "health step should succeed on a real chunk DCD"
    wc = json.loads(out.read_text())
    assert isinstance(wc, list) and wc and all(isinstance(x, float) for x in wc)

    # faithful pass-through of run_health_check's wc_per_frame (rounded floats)
    ref = md_health.run_health_check(pkg, seg, stem)
    assert wc == [float(x) for x in (ref.wc_per_frame or [])]

    # the stdlib cutoff evaluator must accept the produced wc.json (Tier A gate)
    log = (pkg / f"{seg}.log").read_text(errors="replace")
    code, diag = remote_cutoff_eval.decide(log, wc)
    assert code in (0, 1, 2)
    assert diag.get("tier") in ("A", None)  # A when enough frames


def test_health_eval_missing_dcd_fails_safe(tmp_path):
    # no output/<seg>.dcd -> run_health_check errors -> exit 3, no file written
    (tmp_path / "output").mkdir()
    (tmp_path / "nostem.psf").write_text("")
    (tmp_path / "nostem.pdb").write_text("")
    out = tmp_path / "wc.json"
    rc = remote_health_eval.main(
        [
            "--package-dir",
            str(tmp_path),
            "--seg",
            "nostem_01_p10",
            "--stem",
            "nostem",
            "--out",
            str(out),
        ]
    )
    assert rc == 3
    assert not out.exists()


def test_health_eval_imports_backend_fallback_when_no_sibling():
    # In-repo (no staged sibling), _load_md_health falls back to backend.core.md_health.
    mod = remote_health_eval._load_md_health()
    assert hasattr(mod, "run_health_check")
