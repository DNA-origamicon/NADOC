"""Statistical gate regressions: correlated frames cannot substitute for seeds."""

from copy import deepcopy
import pytest
from scripts.validation.compare_fixed_gold_metrics import compare, MARGINS, KICK_CHECKS


def reports(deltas):
    cpu = {}
    gpu = {}
    for i, delta in enumerate(deltas):
        c = {
            "particles": 1,
            "inputs_sha256": {"conf": "same"},
            "kick": [[1.0, 0, 0, 0, 1.0, 0]],
            "stages": {"3_equil": {"means": dict.fromkeys(MARGINS, 1.0)}},
        }
        c["stages"]["3_equil"]["means"].update(
            dna_rotational_per_particle=0.148,
            dna_translational_per_particle=0.148,
            protein_rotational_per_particle=0.0,
        )
        g = deepcopy(c)
        g["stages"]["3_equil"]["means"]["tether_distance_nm"] += delta
        cpu[f"ads5_s{i}"] = c
        gpu[f"ads5_s{i}"] = g
    kicks = {"ads5": dict.fromkeys(KICK_CHECKS, 0.0001)}
    return cpu, gpu, kicks


def test_uncertain_zero_mean_difference_does_not_establish_equivalence():
    report = compare(*reports([-0.2, 0, 0.2]))
    assert report["deterministic_pass"]
    assert not report["pass"]
    assert not report["groups"]["ads5"]["metrics"]["tether_distance_nm"][
        "equivalence_pass"
    ]


def test_tightly_matched_independent_replicas_pass():
    assert compare(*reports([-0.01, 0, 0.01, -0.01, 0, 0.01, -0.01, 0, 0.01]))["pass"]


def test_matching_trajectories_cannot_hide_bad_or_missing_force_audit():
    cpu, gpu, kicks = reports([0, 0, 0])
    kicks["ads5"]["DNA_linear_1e-06"] = 0.1
    assert not compare(cpu, gpu, kicks)["pass"]
    del kicks["ads5"]["DNA_linear_1e-06"]
    with pytest.raises(ValueError, match="Incomplete stressed-kick"):
        compare(cpu, gpu, kicks)


def test_different_physical_inputs_are_not_comparable():
    cpu, gpu, kicks = reports([0, 0, 0])
    gpu["ads5_s0"]["inputs_sha256"]["conf"] = "different"
    with pytest.raises(ValueError, match="physical inputs differ"):
        compare(cpu, gpu, kicks)


def test_collector_rejects_partial_or_repeated_trajectories():
    from scripts.validation.collect_fixed_gold_metrics import _stage

    def frame(step):
        return (
            "t = %d\nb = 20 20 20\nE = 0 0 0\n2 0 0 1 0 0 0 0 1 0 0 0 0 0 0\n3 0 0 1 0 0 0 0 1 0 0 0 0 0 0\n"
            % step
        )

    files = {
        "input": "steps = 2\nprint_conf_interval = 1\n",
        "last_conf.dat": frame(2),
        "trajectory.dat": frame(1) + frame(2),
        "energy.dat": "0 1 2 3\n0.0002 1 2 3\n",
    }

    def metrics():
        return _stage(
            files.__getitem__,
            "",
            2,
            1,
            1,
            [(0, [2, 0, 0])],
            [(0, 1, 1)],
            [(0, 1, 1)],
            True,
        )

    assert metrics()["frames"] == 2
    files["trajectory.dat"] = frame(1)
    with pytest.raises(ValueError, match="Incomplete trajectory"):
        metrics()
    files["trajectory.dat"] = frame(1) + frame(1)
    with pytest.raises(ValueError, match="Repeated or unordered"):
        metrics()
    files["trajectory.dat"] = frame(1) + frame(2)
    files["last_conf.dat"] = frame(1)
    with pytest.raises(ValueError, match="Incomplete stage"):
        metrics()


def test_collector_rejects_nonfinite_and_wrong_particle_counts():
    from scripts.validation.collect_fixed_gold_metrics import _configuration

    text = "t = 1\nb = 20 20 20\nE = 0 0 0\n2 0 0 1 0 0 0 0 1 0 0 0 0 0 0\n"
    assert len(_configuration(text, 1)) == 1
    with pytest.raises(ValueError, match="census"):
        _configuration(text, 2)
    with pytest.raises(ValueError, match="nonfinite"):
        _configuration(text.replace("2 0 0", "nan 0 0"), 1)


def test_thermometry_detects_fictitious_protein_rotation():
    from scripts.validation.collect_fixed_gold_metrics import _frame_metrics

    rows = [
        [2, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0],
        [3, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 3, 0, 0],
    ]
    m = _frame_metrics(rows, 1, 1, [(0, [2, 0, 0])], [(0, 1, 1)], [(0, 1, 1)])
    assert m["protein_rotational_per_particle"] == 2
    assert m["dna_rotational_per_particle"] == 4.5
    assert m["dna_translational_per_particle"] == 0.5


def test_bussi_capability_tracks_library_replacement(tmp_path):
    from backend.core.oxdna_runner import oxdna_supports_rigid_bussi

    binary = tmp_path / "bin/oxDNA"
    binary.parent.mkdir()
    binary.write_bytes(b"engine")
    lib = tmp_path / "lib/liboxdna_common.so"
    lib.parent.mkdir()
    lib.write_bytes(b"old")
    assert not oxdna_supports_rigid_bussi(str(binary))
    lib.write_bytes(b"Bussi rigid-body DOF fix v1")
    assert oxdna_supports_rigid_bussi(str(binary))
    lib.unlink()
    assert not oxdna_supports_rigid_bussi(str(binary))


@pytest.mark.slow
@pytest.mark.oxdna
def test_real_dnanm_thermostat_cpu_cuda(tmp_path):
    import subprocess
    import shutil
    import sys
    from pathlib import Path
    from backend.core.oxdna_runner import (
        find_oxdna,
        oxdna_supports_cuda,
        oxdna_supports_rigid_bussi,
    )

    binary = find_oxdna()
    if not binary or not oxdna_supports_cuda(binary):
        pytest.skip("CUDA oxDNA required")
    if (
        not shutil.which("nvidia-smi")
        or subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, timeout=10
        ).returncode
    ):
        pytest.skip("GPU unavailable")
    assert oxdna_supports_rigid_bussi(binary), (
        "Rebuild oxDNA with the protein thermostat fix"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1]
                / "scripts/validation/check_dnanm_thermostat.py"
            ),
            "--binary",
            binary,
            "--out",
            str(tmp_path),
            "--seeds",
            "202",
            "303",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def test_matching_backends_with_wrong_dna_temperature_are_rejected():
    cpu, gpu, kicks = reports([0, 0, 0])
    for data in (cpu, gpu):
        for c in data.values():
            c["stages"]["3_equil"]["means"]["dna_rotational_per_particle"] = 0.01
    report = compare(cpu, gpu, kicks)
    assert report["stochastic_equivalence_pass"]
    assert not report["thermometry_pass"]
    assert not report["pass"]


def test_protocol_audit_allows_cuda_options_but_rejects_physics_changes():
    from scripts.validation.audit_fixed_gold_protocol import matching_protocol

    cpu = "backend = CPU\nsim_type = MD\nsteps = 100\nseed = 7\nT = 296K\ninteraction_type = DNANM\nsalt_concentration = .5\nexternal_forces = true\ndt = .0001\nthermostat = bussi\n"
    gpu = cpu.replace(
        "backend = CPU",
        "backend = CUDA\nbackend_precision = mixed\nCUDA_list = verlet\nuse_edge = true",
    )
    assert matching_protocol(cpu, gpu)
    for before, after in [
        ("dt = .0001", "dt = .001"),
        ("seed = 7", "seed = 8"),
        ("external_forces = true", "external_forces = false"),
    ]:
        with pytest.raises(ValueError, match="settings differ"):
            matching_protocol(cpu, gpu.replace(before, after))


def test_matched_rng_capability_is_distinct_from_rotational_fix(tmp_path):
    from backend.core.oxdna_runner import (
        oxdna_supports_rigid_bussi,
        oxdna_supports_matched_bussi_rng,
    )

    binary = tmp_path / "oxDNA"
    binary.write_bytes(b"Bussi rigid-body DOF fix v1")
    assert oxdna_supports_rigid_bussi(str(binary))
    assert not oxdna_supports_matched_bussi_rng(str(binary))
    binary.write_bytes(b"Bussi rigid-body DOF fix v1 CUDA Bussi CPU-matched RNG v1")
    assert oxdna_supports_rigid_bussi(str(binary))
    assert oxdna_supports_matched_bussi_rng(str(binary))
