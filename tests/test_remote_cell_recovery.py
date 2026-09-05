"""Exercise the node helper with real binary checkpoints, without running MD."""

import ast
import struct
from pathlib import Path

import pytest

from backend.core import remote_cell_recovery as recovery


CONF = """structure system.psf
coordinates system.pdb
GPUresident on
timestep 4
rigidBonds all
constraints on
consref restraints_settle.pdb
conskfile restraints_combined.pdb
conskcol B
constraintScaling 1
extraBonds on
extraBondsFile enm.extra
eFieldOn yes
eField 0 0 1
langevinPiston on
langevinPistonPeriod 1000
langevinPistonDecay 500
restartfreq 5000
outputName output/settle
binCoordinates output/min.coor
binVelocities output/min.vel
extendedSystem output/min.xsc
dcdFile output/settle.dcd
xstFile output/settle.xst
run 125000
"""


def xsc(step, side=100):
    return f"# cell\n{step} {side} 0 0 0 {side} 0 0 0 {side} 0 0 0\n"


@pytest.fixture
def package(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "settle.conf").write_text(CONF)
    (tmp_path / "output/min.xsc").write_text(xsc(0))
    return tmp_path


def checkpoint(package, step=500, side=98):
    out = package / "output"
    (out / "settle.restart.xsc").write_text(xsc(step, side))
    for ext in ("coor", "vel"):
        (out / ("settle.restart." + ext)).write_bytes(struct.pack("<i3d", 1, 1, 2, 3))


def retry(package, attempt=1):
    name = recovery.recover(package, "settle", "settle", 125000, attempt)
    return (package / (name + ".conf")).read_text()


def test_precheckpoint_failure_gets_one_gentler_retry(package):
    text = retry(package)
    assert "langevinPistonPeriod 10000.0" in text
    assert "restartfreq 100" in text
    assert "run 125000" in text
    assert (package / "settle.conf").read_text() == CONF
    with pytest.raises(ValueError, match="no complete checkpoint"):
        retry(package, 2)


def test_checkpoint_preserves_physics_and_remaining_duration(package):
    checkpoint(package)
    text = retry(package)
    assert "output/settle.restart.xsc" in text
    assert "firsttimestep      500" in text
    assert "run                124500" in text
    for line in CONF.splitlines()[:14]:
        assert line in text
    checkpoint(package, step=1000, side=97)
    text = retry(package, 2)
    assert "langevinPistonPeriod 10000.0" in text
    assert "run                124000" in text


def test_refuses_stale_checkpoint(package):
    checkpoint(package)
    retry(package)
    with pytest.raises(ValueError, match="no progress"):
        retry(package, 2)


def test_refuses_cumulative_collapse(package):
    checkpoint(package)
    retry(package)
    checkpoint(package, step=1000, side=94)
    with pytest.raises(ValueError, match="85%"):
        retry(package, 2)


@pytest.mark.parametrize("ext", ["coor", "vel"])
def test_refuses_torn_restart(package, ext):
    checkpoint(package)
    (package / ("output/settle.restart." + ext)).write_bytes(struct.pack("<i", 10))
    with pytest.raises(ValueError, match="incomplete"):
        retry(package)


def test_preserves_partial_trajectory_on_every_retry(package):
    checkpoint(package)
    path = package / "output/settle.dcd"
    path.write_bytes(b"partial first trajectory")
    retry(package)
    assert (
        package / "output/settle.cell_archive1.dcd"
    ).read_bytes() == path.read_bytes()
    checkpoint(package, step=1000)
    path.write_bytes(b"second trajectory")
    retry(package, 2)
    assert (
        package / "output/settle.cell_archive2.dcd"
    ).read_bytes() == b"second trajectory"
    assert (
        package / "output/settle.cell_archive1.dcd"
    ).read_bytes() == b"partial first trajectory"


def test_retry_limit_and_non_npt_fail_closed(package):
    with pytest.raises(ValueError, match="limit"):
        retry(package, 5)
    (package / "settle.conf").write_text(
        CONF.replace("langevinPiston on", "langevinPiston off")
    )
    with pytest.raises(ValueError, match="NPT"):
        retry(package)


def test_helper_parses_on_alpine_python36():
    ast.parse(Path(recovery.__file__).read_text(), feature_version=(3, 6))


@pytest.mark.parametrize(
    "fatal, expected",
    [
        ("Periodic cell has become too small", 0),
        ("Constraint failure in RATTLE algorithm", 134),
    ],
)
def test_generated_alpine_loop_runs_only_cell_recovery(package, fatal, expected):
    import subprocess
    from backend.core import cluster_config, slurm_script, remote_resume_conf

    profile = cluster_config.alpine_profile()
    (package / "output/min.coor").touch()
    script = slurm_script.generate_sbatch(
        {
            "name_stem": "demo",
            "minimization": {"name": "min"},
            "segments": [{"name": "settle", "steps": 125000}],
        },
        profile,
        {
            "partition": "ah200",
            "cores": 1,
            "walltime": "01:00:00",
            "mem_gb": 4,
            "qos": "gpu-normal",
        },
        str(package),
    )
    # Execute the emitted ladder itself, with the real staged helpers and a tiny
    # fake NAMD process. No modules, scheduler, GPU, or molecular simulation.
    ladder = script[script.index("# NADOC MD ladder:") :]
    namd = profile.namd_command(True)
    ladder = ladder.replace(namd + " +p", "./fake_namd +p")
    fake = package / "fake_namd"
    fake.write_text(
        "#!/bin/bash\n"
        "if [ ! -f invoked ]; then\n"
        "  touch invoked\n"
        f'  echo "FATAL ERROR: {fatal}"\n'
        "  exit 134\nfi\n"
        "touch output/settle.coor\n"
    )
    fake.chmod(0o755)
    (package / slurm_script.CELL_RECOVERY_NAME).write_text(
        Path(recovery.__file__).read_text()
    )
    (package / slurm_script.RESUME_CONF_NAME).write_text(
        Path(remote_resume_conf.__file__).read_text()
    )
    result = subprocess.run(
        ["bash", "-euc", ladder], cwd=package, capture_output=True, text=True
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert (package / "settle.cell_retry.conf").exists() == (expected == 0)
