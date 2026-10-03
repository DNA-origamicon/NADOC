"""Offline pins for the node WC health step (remote_health_eval.py).

Run the actual node path (minus the cluster) with a generated CHARMM topology and
deterministic DCD frames: write WC JSON, compare with md_health.run_health_check,
and feed it to the stdlib cutoff evaluator. No user workspace jobs are required.
"""

from __future__ import annotations

import json

import pytest

from backend.core import remote_cutoff_eval, remote_health_eval

pytest.importorskip("MDAnalysis")


# Generated CHARMM topology and deterministic DCD frames isolate the transport
# contract from incomplete/running trajectories in the user's workspace.
pytest_plugins = ["tests.md_trajectory_fixture"]


def test_health_eval_writes_wc_json_matching_run_health_check(tmp_path, generated_md):
    pkg, stem, seg = generated_md.folder, generated_md.psf.stem, generated_md.dcd.stem
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

    # the stdlib cutoff evaluator must accept the produced wc.json
    log = "ETITLE: TS POTENTIAL VOLUME\n" + "\n".join(
        f"ENERGY: {i} -1000.0 500000.0" for i in range(len(wc))
    )
    code, diag = remote_cutoff_eval.decide(log, wc)
    assert code in (0, 1, 2)
    assert "wc_plateaued" in diag or diag.get("reason") == "insufficient_frames"


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
