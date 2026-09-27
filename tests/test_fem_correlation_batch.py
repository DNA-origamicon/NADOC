"""Generalized correlation batching preserves the scalar Gaussian MI formula."""

import numpy as np
import pytest
from backend.physics import fem_solver as fem


def scalar_pair(W, i, j):
    sii = np.einsum("dm,em->de", W[i], W[i]) + 1e-12 * np.eye(3)
    sjj = np.einsum("dm,em->de", W[j], W[j]) + 1e-12 * np.eye(3)
    sij = W[i] @ W[j].T
    joint = np.block([[sii, sij], [sij.T, sjj]])
    mi = 0.5 * (
        np.log(max(np.linalg.det(sii), 1e-300))
        + np.log(max(np.linalg.det(sjj), 1e-300))
        - np.log(max(np.linalg.det(joint), 1e-300))
    )
    return np.sqrt(max(0.0, 1.0 - np.exp(-2.0 * max(mi, 0.0) / 3.0)))


@pytest.mark.parametrize("rank", [1, 3, 11])
def test_generalized_correlation_matches_scalar(monkeypatch, rank):
    n = 9
    lam = np.geomspace(0.1, 10.0, rank)
    phi = np.random.default_rng(7).normal(size=(6 * n, rank))
    # Exact-zero fluctuations exercise determinant floors and regularization.
    phi[:6] = 0
    monkeypatch.setattr(fem, "_nma_modes", lambda *args: (lam, phi))
    actual = fem.compute_generalized_correlation_matrix(None, n)
    W = phi.reshape(n, 6, rank)[:, :3] / np.sqrt(lam)
    expected = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            expected[i, j] = expected[j, i] = scalar_pair(W, i, j)
    np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-9)
    np.testing.assert_array_equal(actual, actual.T)
    np.testing.assert_array_equal(np.diag(actual), np.ones(n))
    assert np.isfinite(actual).all()
    assert actual.min() >= 0 and actual.max() <= 1


def test_generalized_correlation_crosses_batch_boundary(monkeypatch):
    n, modes = 2051, 8
    phi = np.random.default_rng(8).normal(size=(6 * n, modes))
    monkeypatch.setattr(fem, "_nma_modes", lambda *args: (np.ones(modes), phi))
    actual = fem.compute_generalized_correlation_matrix(None, n)
    W = phi.reshape(n, 6, modes)[:, :3]
    for i, j in [(0, 2048), (0, 2049), (0, 2050), (1, 2050)]:
        assert actual[i, j] == pytest.approx(scalar_pair(W, i, j), abs=1e-12)
        assert actual[i, j] == actual[j, i]


def test_generalized_correlation_failed_nma(monkeypatch):
    monkeypatch.setattr(fem, "_nma_modes", lambda *args: (None, None))
    np.testing.assert_array_equal(
        fem.compute_generalized_correlation_matrix(None, 3), np.eye(3)
    )
