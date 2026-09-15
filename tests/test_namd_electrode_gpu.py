"""Managed GPU conversion preserves force ownership and restart initialization."""

import json

import pytest
from backend.core.namd_electrode_gpu import (
    CLIENT,
    configure_package,
    convert_config,
    order_initialization,
    sha,
    validate_package,
)

BASE = """GPUresident on
langevinPiston off
tclForces on
tclForcesScript electrode_forces.tcl
structure system.psf
outputname output/stage
timestep 4
run 100
"""


def test_conversion_preserves_integrator_and_places_all_settings_before_run():
    conf = convert_config(BASE)
    assert "tclForces" not in conf and "timestep 4" in conf
    assert conf.index("GPUAtomMigration") < conf.index(CLIENT) < conf.index("run 100")
    assert conf.index("twoAwayZ") < conf.index(CLIENT)
    assert convert_config(conf) == conf


def test_resume_reorders_client_after_new_restart_settings():
    conf = convert_config(BASE).replace(
        "run 100", "binCoordinates output/restart.coor\nfirsttimestep 40\nrun 60"
    )
    conf = order_initialization(conf)
    assert conf.index("firsttimestep") < conf.index(CLIENT) < conf.index("run 60")


@pytest.mark.parametrize(
    "text",
    [
        BASE.replace("off", "on"),
        BASE.replace("GPUresident on", "GPUresident off"),
        BASE.replace("electrode_forces.tcl", "extra.tcl"),
        BASE + "tclForcesScript extra.tcl\n",
    ],
)
def test_unsupported_force_paths_rejected(text):
    with pytest.raises(ValueError):
        convert_config(text)


def test_managed_install_is_pinned_and_tampering_blocks_restart(tmp_path, monkeypatch):
    import backend.core.namd_electrode_gpu as gpu
    import numpy as np

    package = tmp_path / "package"
    package.mkdir()
    registry = tmp_path / "registry"
    registry.mkdir()
    binary = tmp_path / "namd"
    binary.write_bytes(b"engine")
    (registry / "electrode.so").write_bytes(b"plugin")
    (registry / "provenance.json").write_text(
        json.dumps(
            dict(
                installed_engine_sha256=sha(binary),
                plugin_sha256=sha(registry / "electrode.so"),
                correction_sha256="source",
            )
        )
    )
    (package / "manifest.json").write_text(
        json.dumps(dict(two_electrodes={"enabled": True}, segments=[{"name": "stage"}]))
    )
    (package / "stage.conf").write_text(BASE)
    (package / "min.conf").write_text("minimize 100\n")
    (package / "system.psf").write_text("psf")
    (package / "electrode_forces.tcl").write_text("reference")
    monkeypatch.setattr(
        gpu, "parameter_data", lambda _: (np.zeros((1, 6)), [1, 1.0, 0.0, 10.0, 5.0])
    )
    configure_package(package, binary, "0", registry=registry)
    assert (package / "min.conf").read_text() == "minimize 100\n"
    assert "tclForces" not in (package / "stage.conf").read_text()
    assert (package / "stage.conf.cpu-reference").read_text() == BASE
    configure_package(package, binary, "0", registry=registry)
    original_params=(package / "electrode_gpu.params").read_text()
    (package / "electrode_gpu.params").write_text("tampered")
    with pytest.raises(ValueError, match="checksum changed"):
        validate_package(package, binary, "0")

    (package/'electrode_gpu.params').write_text(original_params)
    gpu.restore_cpu_correction(package)
    restored=(package/'stage.conf').read_text()
    assert 'gpuGlobal' not in restored
    assert 'tclForcesScript electrode_forces.tcl' in restored
    assert 'timestep 4' in restored
    assert not json.loads((package/'manifest.json').read_text())['electrode_gpu']['enabled']


def test_missing_plugin_records_portable_cpu_backend(tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps({'two_electrodes':{'enabled':True}}))
    configure_package(tmp_path,'unused','0',registry=tmp_path/'missing')
    meta=json.loads((tmp_path/'manifest.json').read_text())['electrode_gpu']
    assert not meta['enabled'] and 'No validated GPU' in meta['reason']
