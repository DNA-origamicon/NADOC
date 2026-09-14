"""Production protocol contracts established by the native physics A/B audit."""

from dataclasses import replace
import subprocess

import pytest
from backend.core.oxdna_protocol import (
    AVERAGE_SEQUENCE_FILE,
    AVERAGE_SEQUENCE_PATH,
    apply_stage_overrides,
    build_relaxation_stages,
    render_stage_input,
)
from backend.core.oxdna_runner import oxdna_supports_physics_v3
from backend.core.runpod_oxdna import stage_inputs


@pytest.mark.parametrize("thermostat", ["john", "brownian", "langevin"])
def test_explicit_local_bath_and_velocity_handoff(thermostat):
    original = build_relaxation_stages()
    with pytest.raises(ValueError, match="diffusion coefficient"):
        apply_stage_overrides(original, {"3_equil": {"thermostat": thermostat}})
    stages = apply_stage_overrides(
        original,
        {
            "3_equil": {
                "thermostat": thermostat,
                "diff_coeff": "0.1",
                "refresh_vel": False,
                "max_backbone_force": None,
                "max_backbone_force_far": None,
            }
        },
    )
    text = render_stage_input(stages[2], "topology.top", "conf.dat")
    assert f"thermostat = {thermostat}\n" in text
    assert "diff_coeff = 0.1\n" in text and "refresh_vel = false\n" in text
    assert "bussi_tau" not in text and "max_backbone_force" not in text
    assert stages[1].thermostat == "bussi" and stages[1].refresh_vel


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_diffusion_rejected(value):
    with pytest.raises(ValueError, match="diffusion coefficient"):
        render_stage_input(
            replace(build_relaxation_stages()[1], thermostat="john", diff_coeff=value),
            "t",
            "c",
        )


def test_average_DNA2_parameters_are_portable_and_hybrid_is_unchanged(tmp_path):
    specs = build_relaxation_stages()
    local = render_stage_input(specs[1], "topology.top", "conf.dat")
    assert "use_average_seq = false\n" in local
    assert f"seq_dep_file = {AVERAGE_SEQUENCE_PATH}\n" in local
    remote = stage_inputs(tmp_path, specs, "/remote/job")
    assert remote[AVERAGE_SEQUENCE_FILE] == AVERAGE_SEQUENCE_PATH.read_text()
    assert (
        f"seq_dep_file = /remote/job/{AVERAGE_SEQUENCE_FILE}\n"
        in remote["2_md_relax/input.txt"]
    )
    hybrid = render_stage_input(build_relaxation_stages(protein=True)[1], "t", "c")
    assert "interaction_type = DNANM\n" in hybrid and "seq_dep_file" not in hybrid


def test_capability_tracks_library_replacement(tmp_path):
    executable = tmp_path / "bin/oxDNA"
    executable.parent.mkdir()
    executable.write_bytes(b"executable")
    lib = tmp_path / "lib/liboxdna_common.so"
    lib.parent.mkdir()
    lib.write_bytes(b"old engine")
    assert not oxdna_supports_physics_v3(str(executable))
    lib.write_bytes(b"NADOC physics corrections v3")
    assert oxdna_supports_physics_v3(str(executable))
    lib.write_bytes(b"old")
    assert not oxdna_supports_physics_v3(str(executable))


def test_build_shells_are_valid_and_require_new_marker():
    from backend.core.cluster_oxdna_build import build_sbatch
    from backend.core.runpod_oxdna import render_build_script

    for script in [
        build_sbatch(
            build_dir="/tmp/build", source_name="source", tar_name="source.tar.gz"
        ),
        render_build_script("90", "/tmp/patch"),
    ]:
        result = subprocess.run(
            ["bash", "-n"], input=script, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr
        assert "physics-corrections" in script and "v3" in script


def test_old_engine_cannot_start_even_a_DNA_only_job(tmp_path, monkeypatch):
    import asyncio
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job

    specs = build_relaxation_stages(backend="CPU")
    job = new_oxdna_job("old-engine", [s.to_status() for s in specs])
    job.job_dir(tmp_path).mkdir(parents=True)
    monkeypatch.setattr(runner, "find_oxdna", lambda: "/missing/old-oxDNA")
    asyncio.run(runner.run_job(job, tmp_path, specs))
    assert (
        job.status == OxdnaStatus.failed and "current physics corrections" in job.error
    )
