"""Wiring tests: progress callback threaded through solvation + the watched runner.

These don't require GROMACS — `_gmx_solvate` is stubbed — so they verify that the
preparation pipeline reports the expected phases and that the hard-timeout safety
net actually kills a hung subprocess.
"""

from __future__ import annotations

import sys
import time
import zipfile
from io import BytesIO

import pytest

import backend.core.namd_solvate as ns
from backend.core.namd_solvate import _Water, _run_watched
from tests.conftest import make_6hb_design, make_minimal_design


def _fake_solvate(_pdb_text, _padding_nm, _tmpdir, progress=None, *, water_shell_nm=None):
    """Stand-in for gmx solvation: emit the solvate phase, return dummy waters."""
    ns._emit(progress, "solvate", None, "fake solvate")
    waters = [_Water(i * 0.31, 0, 0, i * 0.31, 0.1, 0, i * 0.31, -0.1, 0) for i in range(8000)]
    return waters, (12.0, 12.0, 12.0), _pdb_text


def test_progress_threads_through_solvation(monkeypatch):
    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)
    design = make_6hb_design(42)

    seen: list[str] = []
    ns.build_namd_solvated_package(
        design, progress=lambda k, f, m="": seen.append(k),
        ion_conc_mM=0.0, mg_conc_mM=0.0,
    )

    # Every solvation phase the package builder owns must report at least once,
    # in the canonical order (topology before solvate before assemble).
    assert "topology" in seen
    assert "solvate" in seen
    assert "assemble" in seen
    assert seen.index("topology") < seen.index("solvate") < seen.index("assemble")


def test_solvated_package_exports_fast_relaxation_assets(monkeypatch):
    """Downloadable NAMD packages carry the same HMR/GPUresident fast path."""
    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)
    design = make_minimal_design(helix_length_bp=8)

    blob = ns.build_namd_solvated_package(
        design,
        ion_conc_mM=0.0,
        mg_conc_mM=0.0,
    )
    name = (design.metadata.name or "design").replace(" ", "_")
    prefix = f"{name}_namd_solvated/"

    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = set(zf.namelist())
        fast_conf = zf.read(prefix + "namd_fast.conf").decode()
        launch = zf.read(prefix + "launch.sh").decode()
        readme = zf.read(prefix + "README.txt").decode()

    assert prefix + f"{name}_hmr.psf" in names
    assert prefix + "namd_fast.conf" in names
    assert f"structure          {name}_hmr.psf" in fast_conf
    assert "GPUresident        on" in fast_conf
    assert "timestep           4.0" in fast_conf
    assert "PMEGridSpacing     1.5" in fast_conf
    assert 'N_THREADS="${NAMD_THREADS:-' in launch
    assert 'DEVICES="${NAMD_DEVICES:-0}"' in launch
    assert '"+setcpuaffinity"' in launch
    assert "namd_fast.conf" in readme


def test_progress_feeds_tracker_monotonic(monkeypatch):
    """Reports from the real pipeline must drive a monotonically rising bar."""
    from backend.core.md_prep_progress import PrepTracker, build_prep_phases

    monkeypatch.setattr(ns, "_gmx_solvate", _fake_solvate)
    design = make_6hb_design(42)

    clock = [0.0]
    tracker = PrepTracker(build_prep_phases(seeded=False), clock=lambda: clock[0])
    fractions: list[float] = []

    def report(key, frac, msg=""):
        clock[0] += 0.01
        tracker.report(key, frac, msg)
        fractions.append(tracker.snapshot()["fraction"])

    ns.build_namd_solvated_package(design, progress=report, ion_conc_mM=0.0, mg_conc_mM=0.0)

    assert fractions, "expected at least one progress report"
    assert all(b >= a - 1e-9 for a, b in zip(fractions, fractions[1:])), "fraction regressed"
    assert fractions[-1] <= 1.0


def test_run_watched_kills_hung_process():
    """A subprocess that overruns the hard timeout is killed and raises."""
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="exceeded"):
        _run_watched(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            hard_timeout_s=2.0,
        )
    assert time.monotonic() - t0 < 15.0, "watchdog did not kill promptly"


def test_run_watched_returns_on_success():
    res = _run_watched([sys.executable, "-c", "print('ok')"], hard_timeout_s=30.0)
    assert res.returncode == 0
    assert "ok" in res.stdout


def test_run_watched_raises_on_failure():
    with pytest.raises(RuntimeError, match="Command failed"):
        _run_watched([sys.executable, "-c", "import sys; sys.exit(3)"], hard_timeout_s=30.0)
