from pathlib import Path

from backend.core import md_protocols as M
from backend.core.namd_runner import _write_probe_conf
from backend.core.remote_resume_conf import build_resume_conf


def test_large_minimization_is_chunked_with_hard_ceiling_and_fail_safe_callback():
    atoms = 3_243_630
    maximum = M.minimize_steps_for_atoms(atoms)
    text = M._min_conf(
        "demo_00_min", "demo", (100.0, 100.0, 100.0), False, maximum, 0.5,
        n_atoms=atoms,
    )

    params = M.adaptive_minimization_parameters(atoms, maximum)
    assert f"set nadoc_min_max {maximum}" in text
    assert f"set nadoc_min_min {params['minimum_steps']}" in text
    assert f"set nadoc_min_chunk {params['chunk_steps']}" in text
    assert "lsearch -exact $labels TOTAL" in text
    assert "set nadoc_min_reason maximum" in text
    assert "NADOC_ADAPTIVE_MIN_STOP" in text
    # NAMD's config interpreter misclassifies Tcl's mathfunc::min as an unknown config
    # variable before startup. A plain ternary is accepted by both Tcl and NAMD.
    assert "min($nadoc_min_chunk" not in text
    assert "$nadoc_min_left < $nadoc_min_chunk ?" in text
    assert "minimize           324380" not in text


def test_small_minimization_keeps_legacy_single_command():
    text = M._min_conf(
        "demo_00_min", "demo", (100.0, 100.0, 100.0), False, 4_800, 0.5,
        n_atoms=10_000,
    )
    assert "minimize           4800" in text
    assert "NADOC_ADAPTIVE_MIN" not in text


def test_adaptive_minimization_can_be_disabled():
    text = M._min_conf(
        "demo_00_min", "demo", (100.0, 100.0, 100.0), False, 20_000, 0.5,
        n_atoms=200_000, adaptive_minimization=False,
    )
    assert "minimize           20000" in text
    assert "NADOC_ADAPTIVE_MIN" not in text


def test_adaptive_parameters_are_cycle_aligned_and_bounded():
    params = M.adaptive_minimization_parameters(3_243_630, 324_380)
    assert params["minimum_steps"] == 64_880
    assert params["chunk_steps"] == 10_140
    assert params["stable_chunks"] == 3
    assert params["energy_delta"] == 648.726
    assert params["minimum_steps"] <= 324_380
    assert params["chunk_steps"] % M.AKSIMENTIEV_STEPS_PER_CYCLE == 0


def test_gpu_probe_replaces_entire_adaptive_loop(tmp_path: Path):
    source = tmp_path / "min.conf"
    source.write_text(
        M._min_conf(
            "demo_00_min", "demo", (100.0, 100.0, 100.0), False, 20_000, 0.5,
            n_atoms=200_000,
        )
    )
    probe = tmp_path / "probe.conf"
    _write_probe_conf(source, probe, "_probe")
    text = probe.read_text()
    assert "minimize           20" in text
    assert "NADOC_ADAPTIVE_MIN" not in text
    assert "while {$nadoc_min_done" not in text
    assert "outputName         _probe" in text


def test_prepared_legacy_conf_is_upgraded_idempotently(tmp_path: Path):
    conf = tmp_path / "old.conf"
    conf.write_text("outputName output/demo_00_min\nminimize 324380\n")
    assert M.upgrade_minimization_conf_adaptive(
        conf, min_name="demo_00_min", n_atoms=3_243_630, max_steps=324_380
    )
    once = conf.read_text()
    assert "set nadoc_min_max 324380" in once
    assert "output/demo_00_min.adaptive_min.txt" in once
    assert not M.upgrade_minimization_conf_adaptive(
        conf, min_name="demo_00_min", n_atoms=3_243_630, max_steps=324_380
    )
    assert conf.read_text() == once


def test_adaptive_minimization_resume_keeps_minimizing_and_subtracts_paid_work():
    conf = M._min_conf(
        "demo_00_min", "demo", (100.0, 100.0, 100.0), False, 324_380, 0.5,
        n_atoms=3_243_630,
    )
    resumed = build_resume_conf(conf, "demo_00_min", 48_000, 324_380)
    assert "set nadoc_min_max 276380" in resumed
    assert "set nadoc_min_min 16880" in resumed
    assert "binCoordinates     output/demo_00_min.restart.coor" in resumed
    assert "firsttimestep      48000" in resumed
    assert "temperature        0" in resumed
    assert "run                " not in resumed
    assert "binVelocities" not in resumed
    assert "minimize $nadoc_min_this" in resumed
    assert resumed.index("temperature        0") < resumed.index("minimize $nadoc_min_this")


def test_generated_tcl_distinguishes_roundoff_from_energy_rise(tmp_path):
    import shutil
    import subprocess
    import pytest

    tclsh = shutil.which("tclsh")
    if not tclsh:
        pytest.skip("tclsh unavailable")
    (tmp_path / "output").mkdir()
    conf = M._min_conf("min", "demo", (100., 100., 100.), False, 47280, 0.5,
                       n_atoms=472636)
    block = conf.split("# NADOC_ADAPTIVE_MIN_BEGIN", 1)[1].split("# NADOC_ADAPTIVE_MIN_END", 1)[0]
    for delta, expected in [(0.0002, "plateau"), (1.0, "maximum")]:
        # Replay the measured energy magnitude, alternately rising/falling by delta.
        # A real 1 kcal/mol rise must still reset stability; only roundoff is tolerated.
        harness = f"""
set energy -2095747.56
set iteration 0
proc callback {{name}} {{}}
proc print {{message}} {{puts $message}}
proc minimize {{steps}} {{
    global energy iteration
    incr iteration
    set e [expr {{$energy + ($iteration % 2) * {delta}}}]
    nadoc_min_callback {{TOTAL}} [list $e]
}}
"""
        result = subprocess.run([tclsh], input=harness + block, text=True,
                                capture_output=True, cwd=tmp_path, check=True)
        assert not result.stderr, result.stderr
        report = (tmp_path / "output/min.adaptive_min.txt").read_text()
        assert f"reason={expected}" in report
        if expected == "plateau":
            assert "steps=19200" in report
        else:
            assert "steps=47280" in report
