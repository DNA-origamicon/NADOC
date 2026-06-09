from __future__ import annotations

import json
from pathlib import Path

from backend.core.md_import import resolve_md_config


def test_resolve_namd_manifest_picks_latest_existing_stage(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    output = package / "output"
    output.mkdir(parents=True)

    (package / "tube.psf").write_text("PSF\n")
    (package / "tube.pdb").write_text("CRYST1\n")
    (output / "equil_k0.5.dcd").write_bytes(b"old")
    (output / "equil_k0.01.dcd").write_bytes(b"new")
    (package / "equil_k0.01.namd").write_text("timestep 2\nDCDfreq 9600\n")
    (package / "equil_k0.01.log").write_text(
        "PERFORMANCE: 4953600  averaging 1.83424 ns/day, 0.094 sec/step\n"
        "ENERGY: 4953600 0 0 0 0 0 0 0 0 0 0 299.7859 0 0 0 0 0 0 0 0\n"
    )
    manifest = package / "manifest.json"
    manifest.write_text(json.dumps({
        "package_dir": str(package),
        "name_stem": "tube",
        "stages": [
            {"name": "equil_k0.5"},
            {"name": "equil_k0.1"},
            {"name": "equil_k0.01"},
            {"name": "equil_k0"},
        ],
    }))

    source = resolve_md_config(manifest)

    assert source.topology_path == (package / "tube.psf").resolve()
    assert source.coordinate_path == (package / "tube.pdb").resolve()
    assert source.trajectory_path == (output / "equil_k0.01.dcd").resolve()
    assert source.stage_name == "equil_k0.01"
    assert source.dt_ps == 0.002
    assert source.nstxout_comp == 9600
    assert source.ns_per_day == 1.83424
    assert source.temperature_k == 299.7859


def test_resolve_nadoc_run_manifest_uses_files_block(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    output = package / "traj"
    output.mkdir(parents=True)

    (package / "topology.psf").write_text("PSF\n")
    (package / "coords.pdb").write_text("CRYST1\n")
    (output / "stage_a.dcd").write_bytes(b"frame")
    (package / "stage_a.namd").write_text("timestep 1\nDCDfreq 100\n")
    manifest = package / "nadoc_md_run.json"
    manifest.write_text(json.dumps({
        "nadoc_md_run_manifest_version": 1,
        "package_dir": str(package),
        "name_stem": "ignored",
        "files": {
            "topology": "topology.psf",
            "coordinates": "coords.pdb",
            "output_dir": "traj",
        },
        "stages": [{"name": "stage_a"}],
    }))

    source = resolve_md_config(manifest)

    assert source.topology_path == (package / "topology.psf").resolve()
    assert source.coordinate_path == (package / "coords.pdb").resolve()
    assert source.trajectory_path == (output / "stage_a.dcd").resolve()


def test_resolve_nadoc_segments_manifest_uses_conf_metadata(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    output = package / "output"
    output.mkdir(parents=True)

    (package / "tube.psf").write_text("PSF\n")
    (package / "tube.pdb").write_text("CRYST1\n")
    (output / "tube_01_k0p05_p100.dcd").write_bytes(b"old")
    (output / "tube_02_k0_p10.dcd").write_bytes(b"new")
    (package / "tube_02_k0_p10.conf").write_text("timestep 1\nDCDfreq 5000\n")
    (package / "tube_02_k0_p10.log").write_text(
        "PERFORMANCE: 10000 averaging 9.75 ns/day, 0.008 sec/step\n"
        "ENERGY: 10000 0 0 0 0 0 0 0 0 0 0 310.1 0 0 0 0 0 0 0 0\n"
    )
    manifest = package / "nadoc_md_run.json"
    manifest.write_text(json.dumps({
        "nadoc_md_run_manifest_version": 1,
        "package_dir": str(package),
        "name_stem": "tube",
        "files": {
            "topology": "tube.psf",
            "coordinates": "tube.pdb",
            "output_dir": "output",
        },
        "segments": [
            {"name": "tube_01_k0p05_p100"},
            {"name": "tube_02_k0_p10"},
        ],
    }))

    source = resolve_md_config(manifest)

    assert source.trajectory_path == (output / "tube_02_k0_p10.dcd").resolve()
    assert source.stage_name == "tube_02_k0_p10"
    assert source.dt_ps == 0.001
    assert source.nstxout_comp == 5000
    assert source.ns_per_day == 9.75
    assert source.temperature_k == 310.1
