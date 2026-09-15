"""Fast contracts for the isolated CUDA electrode config generator."""

from pathlib import Path

import pytest

from experiments.electrode_relax.gpu_correction.validate import render


BASE = """outputname output/system_validation_p3
outputEnergies 5000
dcdFreq 5000
tclForces on
tclForcesScript electrode_forces.tcl
run 5000
"""


def test_gpu_conversion_removes_cpu_callback_and_initializes_last():
    conf = render(BASE, "candidate", Path("/plugin.so"), Path("/params"), 100)
    assert "tclForces" not in conf
    assert conf.count("run ") == 1
    assert (
        conf.index("outputTiming")
        < conf.index("gpuGlobalCreateClient")
        < conf.index("run 100")
    )
    assert "outputname output/candidate" in conf


@pytest.mark.parametrize(
    "base",
    [
        BASE.replace("electrode_forces.tcl", "unrelated.tcl"),
        BASE + "tclForcesScript additional.tcl\n",
        BASE + "gpuGlobal on\n",
    ],
)
def test_gpu_conversion_refuses_to_drop_other_forces_or_duplicate_client(base):
    with pytest.raises(ValueError, match="exactly the generated"):
        render(base, "candidate", Path("/plugin.so"), Path("/params"), 100)


def test_cpu_control_preserves_callback():
    conf = render(BASE, "control", None, None, 100, "cpu")
    assert "tclForcesScript electrode_forces.tcl" in conf
    assert "gpuGlobal" not in conf
