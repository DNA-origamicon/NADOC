"""Unit tests for the node-side live-metrics collector.

Runs on Alpine's bare node python3 (3.6), so the module must stay stdlib-only with
no dataclasses and no `from __future__ import annotations` — asserted below,
because a syntax error there kills metrics for every remote run silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.core import remote_live_metrics as rlm

# Real benchmark line from SLURM 30954752 (2hb_1-0xT on an A100 MIG 3g.20gb).
BENCH = "Info: Benchmark time: 8 CPUs 0.0112177 s/step 0.0324585 days/ns 0 MB memory"

# NAMD ENERGY row, built column-by-column so the indices under test are explicit.
_COLS = [
    ("TS", 1000),
    ("BOND", 926.7192),
    ("ANGLE", 2418.8493),
    ("DIHED", 3229.9065),
    ("IMPRP", 46.1629),
    ("ELECT", -267647.4928),
    ("VDW", 23796.9782),
    ("BOUNDARY", 0.0),
    ("MISC", 0.0),
    ("KINETIC", 56166.6602),
    ("TOTAL", -199108.1187),
    ("TEMP", 300.6518),
    ("POTENTIAL", -255274.7789),
    ("TOTAL3", -199085.9257),
    ("TEMPAVG", 299.1),
    ("PRESSURE", -14.0723),
    ("GPRESSURE", -13.5),
    ("VOLUME", 614380.7687),
    ("PRESSAVG", 1.1687),
    ("GPRESSAVG", 1.5),
]
ENERGY = "ENERGY: " + " ".join(str(v) for _, v in _COLS)


def test_energy_column_indices_match_namds_layout():
    """A one-column drift here would report GPRESSURE as VOLUME and nobody would
    notice, so pin the layout itself."""
    names = [n for n, _ in _COLS]
    assert names[rlm._E_TS] == "TS"
    assert names[rlm._E_TEMP] == "TEMP"
    assert names[rlm._E_TOTAL] == "TOTAL"
    assert names[rlm._E_PRESSURE] == "PRESSURE"
    assert names[rlm._E_VOLUME] == "VOLUME"
    assert names[rlm._E_GPRESSAVG] == "GPRESSAVG"


def test_parses_speed_from_the_benchmark_line():
    m = rlm.parse_log_text(BENCH)
    assert m["ns_per_day"] == 1.0 / 0.0324585
    assert m["s_per_step"] == 0.0112177


def test_parses_scalars_from_the_energy_line():
    m = rlm.parse_log_text(ENERGY)
    assert m["temperature_k"] == 300.6518
    assert m["total_energy_kcal"] == -199108.1187
    assert m["pressure_bar"] == -14.0723
    assert m["volume_ang3"] == 614380.7687


def test_uses_the_LAST_energy_line_not_the_first():
    later = ENERGY.replace("ENERGY: 1000 ", "ENERGY: 500000 ", 1)
    m = rlm.parse_log_text(BENCH + "\n" + ENERGY + "\n" + later)
    assert m["step"] == 500000


def test_missing_values_are_absent_not_zero():
    """A production stage with outputEnergies=125000 prints no ENERGY line for many
    minutes. Reporting 0 K / 0 bar would be a confident lie."""
    m = rlm.parse_log_text("Info: startup chatter\nLDB: TIME 818.189 LOAD: AVG 0.14")
    assert "temperature_k" not in m
    assert "ns_per_day" not in m


def test_timing_lines_advance_the_step_counter():
    """TIMING appears far more often than ENERGY on a production stage."""
    m = rlm.parse_log_text(ENERGY + "\nTIMING: 120000  CPU: 1350.2\n")
    assert m["step"] == 120000


def test_step_from_restart_xsc(tmp_path):
    """restartfreq ticks even when the log is silent — the honest progress source."""
    x = tmp_path / "s.restart.xsc"
    x.write_text("# NAMD extended system\n#$LABELS step a_x\n200000 59.16 0 0\n")
    assert rlm.step_from_xsc(x) == 200000
    assert rlm.step_from_xsc(tmp_path / "nope.xsc") is None


def test_collect_picks_the_newest_log_and_writes_atomically(tmp_path):
    import os, time

    (tmp_path / "output").mkdir()
    old = tmp_path / "00_reseed.log"
    old.write_text(ENERGY)
    new = tmp_path / "01_production.log"
    new.write_text(BENCH + "\n" + ENERGY)
    os.utime(old, (time.time() - 500, time.time() - 500))
    data = rlm.collect(str(tmp_path))
    assert data["segment"] == "01_production"
    assert "ns_per_day" in data

    rlm.main(["prog", str(tmp_path)])  # interval 0 -> one pass
    out = json.loads((tmp_path / "output" / "live_metrics.json").read_text())
    assert out["segment"] == "01_production"
    assert out["dcd_size_bytes"] == 0
    assert out["total_size_bytes"] > 0
    assert not (tmp_path / "output" / "live_metrics.json.tmp").exists()


def test_file_sizes_sums_dcd_and_whole_remote_tree(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "input.psf").write_bytes(b"p" * 7)
    (tmp_path / "output" / "a.dcd").write_bytes(b"a" * 11)
    (tmp_path / "output" / "b.DCD").write_bytes(b"b" * 13)
    assert rlm.file_sizes(str(tmp_path)) == (24, 31)


def test_module_is_python36_safe():
    # Check CODE lines only — the module docstring names these very constructs in
    # order to warn about them.
    code = [ln.strip() for ln in Path(rlm.__file__).read_text().splitlines()]
    assert not any(
        ln.startswith("from __future__") for ln in code
    )  # SyntaxError on 3.6
    assert not any(
        ln.startswith(("from dataclasses", "import dataclasses")) for ln in code
    )
    assert not any(ln.startswith("@dataclass") for ln in code)
    for banned in ("import numpy", "import scipy", "import MDAnalysis"):
        assert not any(ln.startswith(banned) for ln in code)  # stdlib only
