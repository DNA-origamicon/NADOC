from __future__ import annotations

import json
import os
from pathlib import Path

from backend.core.md_import import _latest_existing_dcd, resolve_md_config


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
    manifest.write_text(
        json.dumps(
            {
                "package_dir": str(package),
                "name_stem": "tube",
                "stages": [
                    {"name": "equil_k0.5"},
                    {"name": "equil_k0.1"},
                    {"name": "equil_k0.01"},
                    {"name": "equil_k0"},
                ],
            }
        )
    )

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
    manifest.write_text(
        json.dumps(
            {
                "nadoc_md_run_manifest_version": 1,
                "package_dir": str(package),
                "name_stem": "ignored",
                "files": {
                    "topology": "topology.psf",
                    "coordinates": "coords.pdb",
                    "output_dir": "traj",
                },
                "stages": [{"name": "stage_a"}],
            }
        )
    )

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
    manifest.write_text(
        json.dumps(
            {
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
            }
        )
    )

    source = resolve_md_config(manifest)

    assert source.trajectory_path == (output / "tube_02_k0_p10.dcd").resolve()
    assert source.stage_name == "tube_02_k0_p10"
    assert source.dt_ps == 0.001
    assert source.nstxout_comp == 5000
    assert source.ns_per_day == 9.75
    assert source.temperature_k == 310.1


# ── .contN.dcd continuation preference ───────────────────────────────────────
# A resumed segment writes its continuation frames to <seg>.contN.dcd and leaves
# the pre-checkpoint <seg>.dcd intact. The stream resolver must follow the newest
# continuation so live Display MD shows the active trajectory — matching
# routes_md._latest_display_segment. Regression for the resolver mismatch where
# _latest_existing_dcd ignored .contN.dcd and streamed the stale base DCD.


def _touch(path: Path, mtime: float) -> None:
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))


def test_latest_existing_dcd_prefers_newest_continuation(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir(parents=True)
    _touch(output / "prod.dcd", 1000)  # pre-checkpoint base
    _touch(output / "prod.cont1.dcd", 2000)  # first resume
    _touch(output / "prod.cont2.dcd", 3000)  # latest resume (newest)

    dcd, stage = _latest_existing_dcd(tmp_path, ["prod"], output)

    assert dcd == (output / "prod.cont2.dcd").resolve()
    assert stage == "prod"


def test_latest_existing_dcd_falls_back_to_base_when_no_continuation(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir(parents=True)
    _touch(output / "prod.dcd", 1000)

    dcd, stage = _latest_existing_dcd(tmp_path, ["prod"], output)

    assert dcd == (output / "prod.dcd").resolve()
    assert stage == "prod"


def test_latest_existing_dcd_base_wins_when_newer_than_continuation(
    tmp_path: Path,
) -> None:
    # If the base DCD is somehow newer (e.g. continuation was an aborted stub that
    # got truncated to zero and rewritten earlier), the newest non-empty file wins.
    output = tmp_path / "output"
    output.mkdir(parents=True)
    _touch(output / "prod.cont1.dcd", 1000)
    _touch(output / "prod.dcd", 2000)

    dcd, _ = _latest_existing_dcd(tmp_path, ["prod"], output)

    assert dcd == (output / "prod.dcd").resolve()


def test_resolve_manifest_streams_continuation_dcd(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    output = package / "output"
    output.mkdir(parents=True)
    (package / "tube.psf").write_text("PSF\n")
    (package / "tube.pdb").write_text("CRYST1\n")
    _touch(output / "prod.dcd", 1000)
    _touch(output / "prod.cont1.dcd", 5000)
    manifest = package / "nadoc_md_run.json"
    manifest.write_text(
        json.dumps(
            {
                "package_dir": str(package),
                "name_stem": "tube",
                "stages": [{"name": "prod"}],
            }
        )
    )

    source = resolve_md_config(manifest)

    assert source.trajectory_path == (output / "prod.cont1.dcd").resolve()
    assert source.stage_name == "prod"
