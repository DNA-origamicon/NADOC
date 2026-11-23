"""Numerical contracts for storage-only and exact scalar-clustering optimizations."""
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from scipy.cluster import hierarchy

from backend.parameterization.mrdna_clustering import bead_size_clustering
from backend.physics import snupi_dynamics as dyn
from backend.physics.trajectory_storage import allocate_samples


@pytest.mark.parametrize("steps,equil,every", [(17, 3, 4), (10, 0, 3), (4, 9, 2),
                                               (0, 0, 1), (9, -3, 2)])
def test_sample_allocation_matches_sampling_schedule(steps, equil, every):
    indices = [s for s in range(steps) if s >= equil and (s-equil) % every == 0]
    samples = allocate_samples(np.zeros(6), steps, equil, every)
    assert samples.shape == ((len(indices), 6) if indices else (0,))


class _DiagonalFriction:
    def prepare_gjf(self, dt):
        pass

    def apply_b_inv(self, x, dt):
        return x / (1 + dt)

    def apply_Ztilde(self, x):
        return 2 * x

    def sample_beta(self, kT, dt, rng):
        return np.sqrt(4 * kT * dt) * rng.standard_normal(2)


@pytest.mark.parametrize("integrator", [dyn.gjf_integrate, dyn.gjf_modified_integrate,
                                        dyn.gjf_integrate_operator_friction])
def test_direct_storage_preserves_sampling_and_final_velocity(integrator):
    friction = (_DiagonalFriction() if integrator is dyn.gjf_integrate_operator_friction
                else np.ones(2))
    args = (lambda q: -2*q, [0.2, -0.1], np.ones(2), friction)
    full, v_full = integrator(*args, n_steps=17, n_equil=0, sample_every=1,
                             rng=np.random.default_rng(10))
    sparse, v_sparse = integrator(*args, n_steps=17, n_equil=3, sample_every=4,
                                 rng=np.random.default_rng(10))
    np.testing.assert_array_equal(sparse, full[3::4])
    np.testing.assert_array_equal(v_sparse, v_full)
    assert not np.shares_memory(sparse[0], sparse[1])


@pytest.mark.parametrize("seed", range(8))
def test_scalar_clustering_matches_scipy_membership_and_bead_means(seed):
    rng = np.random.default_rng(seed)
    data = np.round(rng.uniform(0.1, 5, (100, 1)), 2)
    for threshold in [0, 0.01, 0.05, 0.2, 10]:
        expected = hierarchy.fclusterdata(data, threshold, criterion="distance")
        with bead_size_clustering():
            actual = hierarchy.fclusterdata(data, threshold, criterion="distance")
        np.testing.assert_array_equal(actual[:, None] == actual, expected[:, None] == expected)
        means = lambda labels: np.array([data[labels == k].mean() for k in labels])
        np.testing.assert_array_equal(means(actual), means(expected))


def test_scalar_clustering_threshold_boundaries_and_duplicate_values():
    for gap in [np.nextafter(0.25, 0), 0.25, np.nextafter(0.25, 1)]:
        data = np.array([[gap], [0], [0], [2]])
        expected = hierarchy.fclusterdata(data, 0.25, criterion="distance")
        with bead_size_clustering():
            actual = hierarchy.fclusterdata(data, 0.25, criterion="distance")
        np.testing.assert_array_equal(actual[:, None] == actual, expected[:, None] == expected)


def test_clustering_scope_restores_and_does_not_adapt_other_threads_or_methods():
    original = hierarchy.fclusterdata
    data = np.array([[0.], [0.1], [4.], [4.1]])
    expected = original(data, 0.2, criterion="distance")
    with pytest.raises(RuntimeError), bead_size_clustering():
        with ThreadPoolExecutor(1) as pool:
            actual = pool.submit(hierarchy.fclusterdata, data, 0.2, criterion="distance").result()
        np.testing.assert_array_equal(actual, expected)  # original label numbering too
        np.testing.assert_array_equal(hierarchy.fclusterdata(data, 0.2, method="complete"),
                                      original(data, 0.2, method="complete"))
        raise RuntimeError("model preparation failed")
    assert hierarchy.fclusterdata is original


@pytest.mark.parametrize("linearized", [False, True])
@pytest.mark.parametrize("dtype", [np.float64, np.float32, np.int64])
def test_rmsf_analysis_preserves_readonly_inputs(linearized, dtype):
    rng = np.random.default_rng(81)
    ref = (rng.normal(size=(12, 3)) * 10).astype(dtype)
    frames = (ref + rng.normal(size=(8, 12, 3))).astype(dtype)
    original = frames.copy()
    frames.flags.writeable = False
    result = dyn.trajectory_rmsf(frames, ref, linearized=linearized)
    assert result.shape == (12,)
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(frames, original)
