"""Execution-gate checks for fresh quantum targets without running Psi4."""

import numpy as np
import pytest

from experiments.cpd_drude_recovery.run_fresh_esp import (
    read_result,
    portability_metrics,
)


def test_portability_rejects_nonfinite_targets():
    with pytest.raises(ValueError):
        portability_metrics(np.array([np.nan]), np.zeros(3), np.ones(1), np.zeros(3))


def test_portability_uses_vector_error():
    metrics = portability_metrics(
        np.array([1.0, 2.0]),
        np.array([1.0, 0, 0]),
        np.array([1.0, 2.0]),
        np.array([-1.0, 0, 0]),
    )
    assert metrics["esp_rms_au"] == 0
    assert metrics["dipole_vector_error_au"] == 2


def test_rejects_dipole_marker_without_successful_scf(tmp_path):
    (tmp_path / "output.dat").write_text(
        "NADOC_DIPOLE_AU 1 2 3\nPsi4 exiting successfully\n"
    )
    with pytest.raises(ValueError, match="did not complete"):
        read_result(tmp_path)
