import numpy as np
import pytest
from scipy.sparse import csr_matrix, diags
from backend.physics.snupi_timestep import estimate_timestep, mass_scaled, frequency_bound, round_down


@pytest.mark.parametrize("seed", range(12))
def test_bound_against_independent_dense_generalized_spectrum(seed):
    rng = np.random.default_rng(seed)
    r = rng.normal(size=(24, 24))
    k = r.T @ r * 1e6
    mass = np.exp(rng.uniform(-5, 5, 24))
    a = k / np.sqrt(mass[:, None] * mass[None, :])
    exact = np.linalg.eigvalsh(a)[-1]
    sparse = csr_matrix(k)
    original = sparse.copy()
    result = estimate_timestep(sparse, mass)
    assert result["core_lambda_upper"] >= exact
    assert result["dt_ns"] <= min(0.005, 0.8 / np.sqrt(exact))
    assert (sparse != original).nnz == 0
    assert frequency_bound(mass_scaled(sparse, mass), 8) <= frequency_bound(
        mass_scaled(sparse, mass), 0
    )


@pytest.mark.parametrize("diagonal", [[0, 0, 0], [0, 1e8, 2e8], [1e-6, 1e-6, 1e-6]])
def test_disconnected_and_zero_modes(diagonal):
    result = estimate_timestep(diags(diagonal), np.ones(3))
    assert 0 < result["dt_ns"] <= 0.005
    assert result["core_lambda_upper"] >= max(diagonal)


def test_anchor_spring_and_tails_bound_the_step():
    base = diags([1e6, 2e6])
    anchored = base + diags([1e10, 0])
    assert (
        estimate_timestep(anchored, [1, 1])["dt_ns"]
        < estimate_timestep(base, [1, 1])["dt_ns"]
    )
    assert estimate_timestep(base, [1, 1], tail_omega_max=1e8)["dt_ns"] <= 0.8e-8


def test_signed_couplings_and_progress_bound():
    a = csr_matrix([[3.0, -2.0, 0], [-2.0, 3.0, 0], [0, 0, 0]])
    calls = []
    upper = frequency_bound(a, 3, lambda *args: calls.append(args))
    assert upper >= 5
    assert len(calls) == 4


@pytest.mark.parametrize("mass", [[0, 1], [-1, 1], [np.nan, 1], [np.inf, 1], [1]])
def test_invalid_mass_refused(mass):
    with pytest.raises(ValueError):
        estimate_timestep(diags([1, 1]), mass)


@pytest.mark.parametrize("x", [0.005, 0.001987, 1e-8, 1.999e-8, 999.999])
def test_rounding_never_increases_step(x):
    assert 0 < round_down(x) <= x
    assert round_down(x) >= x * 0.90


def test_gjf_amplification_is_stable_at_selected_step():
    # Independent deterministic amplification matrix, no molecular structure/trajectory.
    rng = np.random.default_rng(31)
    r = rng.normal(size=(8, 8))
    k = (r.T @ r + np.eye(8)) * 1e7
    mass = np.exp(rng.uniform(-2, 2, 8))
    gamma = np.exp(rng.uniform(-1, 3, 8))
    dt = estimate_timestep(csr_matrix(k), mass)["dt_ns"]
    half = gamma * dt / (2 * mass)
    b = 1 / (1 + half)
    a = (1 - half) * b
    # GJF deterministic map assembled directly from its equations.
    qq = np.eye(8) - np.diag(b * dt * dt / (2 * mass)) @ k
    qv = np.diag(b * dt)
    vq = -np.diag(dt / (2 * mass)) @ (np.diag(a) @ k + k @ qq)
    vv = np.diag(a) - np.diag(dt / (2 * mass)) @ k @ qv
    assert (
        np.max(np.abs(np.linalg.eigvals(np.block([[qq, qv], [vq, vv]])))) <= 1 + 1e-10
    )


@pytest.mark.parametrize("axial", [False, True])
@pytest.mark.parametrize("batch_size", [1, 7, 32768])
def test_vectorized_electro_matches_original_scalar_assembly(axial, batch_size):
    from backend.physics.snupi_electrostatics import ESParams, assemble_electrostatics
    from backend.physics.snupi_electro_vectorized import electro_sparse
    from scipy.sparse import coo_matrix

    pos = np.random.default_rng(14).normal(size=(25, 3))
    pos[1] = pos[0]  # Coincident nodes follow existing exclusion.
    hid = [f"h{i % 4}" for i in range(len(pos))]
    prm = ESParams.for_conditions()
    rows, cols, vals, force = assemble_electrostatics(
        hid, pos, prm, axial_only=axial, scale=0.7
    )
    expected = coo_matrix((vals, (rows, cols)), shape=(150, 150)).toarray()
    actual, f = electro_sparse(
        hid, pos, prm, axial_only=axial, scale=0.7, batch_size=batch_size
    )
    np.testing.assert_allclose(actual.toarray(), expected, rtol=2e-13, atol=2e-12)
    np.testing.assert_allclose(f, force, rtol=2e-13, atol=2e-12)
