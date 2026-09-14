from __future__ import annotations

import pytest

from backend.parameterization.photoproduct_relative_energy import relative_energy_metrics


def test_relative_energy_metrics_apply_only_preregistered_region() -> None:
    metrics = relative_energy_metrics(
        [0.0, 1.0, 15.0],
        [0.0, 1.5, 200.0],
        [True, True, False],
    )

    assert metrics["point_count"] == 2
    assert metrics["rmse_kcal_mol"] == pytest.approx(0.3535533906)
    assert metrics["maximum_absolute_error_kcal_mol"] == 0.5
    assert metrics["passed"] is True


def test_relative_energy_metrics_fail_closed_on_shape_or_sparse_data() -> None:
    with pytest.raises(ValueError, match="differ in length"):
        relative_energy_metrics([0.0], [0.0, 1.0], [True])
    with pytest.raises(ValueError, match="at least two"):
        relative_energy_metrics([0.0, 4.0], [0.0, 4.0], [True, False])
