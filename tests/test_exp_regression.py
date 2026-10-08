"""Regression math and installed adapter contract, separate from MD validation."""

import json
from threading import Event

import numpy as np
import pytest

from backend.core.exp_regression import (
    fit,
    load_adapter,
    predict_positions,
    vector_basis,
)
from backend.core.models import Design


def points():
    rng = np.random.default_rng(73)
    return rng.normal(size=(80, 3)) * [1, 1.4, 8]


def test_rigid_equivariance_and_centroid_preservation():
    x = points()
    coeff = np.array([0.05, 0.03, -0.04, 0.02, 0.01, -0.03])
    q, _ = np.linalg.qr(np.random.default_rng(12).normal(size=(3, 3)))
    translation = np.array([12, -6, 7])
    y = predict_positions(x, coeff)
    transformed = predict_positions(x @ q + translation, coeff)
    np.testing.assert_allclose(transformed, y @ q + translation, atol=1e-10)
    np.testing.assert_allclose(y.mean(0), x.mean(0), atol=1e-10)


def test_recovers_known_strain_with_missing_terminal_phosphates():
    x = points()
    coeff = np.array([0.05, 0.03, -0.04, 0.02, 0.01, -0.03])
    rows = np.arange(3, len(x) - 4)
    y = predict_positions(x, coeff)[rows]
    sample = dict(input_nm=x, mapped_rows=rows, target_nm=y)
    estimated = fit([sample], alpha=1e-9)
    np.testing.assert_allclose(estimated, coeff, atol=1e-9)


def test_doubling_nucleotides_does_not_double_design_weight():
    x = points()
    y = predict_positions(x, np.array([0.02, 0, 0.01, 0, 0, 0]))
    sample = dict(input_nm=x, mapped_rows=np.arange(len(x)), target_nm=y)
    doubled = dict(
        input_nm=np.tile(x, (2, 1)),
        mapped_rows=np.arange(2 * len(x)),
        target_nm=np.tile(y, (2, 1)),
    )
    np.testing.assert_allclose(fit([sample]), fit([doubled]), atol=1e-7)


def test_installed_model_uses_native_geometry_without_mutating_design(monkeypatch):
    x = points()
    reference = {("h", i, "FORWARD"): row for i, row in enumerate(x)}
    monkeypatch.setattr(
        "backend.core.atomistic_to_nadoc.build_active_design_reference",
        lambda _: reference,
    )
    adapter, card = load_adapter()
    design = Design()
    before = design.model_dump_json()
    phases = []
    result = adapter(design, lambda fraction, _: phases.append(fraction), Event())
    assert card["trained_extra_base_counts"] == [0]
    assert len(result["positions_nm"]) == len(x)
    assert not np.allclose(result["positions_nm"], x)
    assert "not validated equilibrium" in result["label"]
    assert phases == sorted(phases)
    assert design.model_dump_json() == before


def test_missing_or_incompatible_model_is_not_silently_accepted(tmp_path):
    assert load_adapter(tmp_path / "missing.json") == (None, None)
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"feature_schema": "unknown"}))
    with pytest.raises(ValueError, match="schema"):
        load_adapter(path)


def test_invalid_geometry_fails_before_regression():
    with pytest.raises(ValueError):
        vector_basis([[0, 0, float("nan")]] * 4)
