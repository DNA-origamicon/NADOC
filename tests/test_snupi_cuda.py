"""Optional CUDA oracle tests; no physical sampling campaign is run here."""

import numpy as np
import pytest
from scipy.sparse import csr_matrix

pytestmark = [pytest.mark.slow, pytest.mark.cando]


def _solver():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA device unavailable")
    from backend.physics.snupi_cuda import LinearGJF

    k = csr_matrix([[3.0, -0.5], [-0.5, 2.0]])
    m, g, ext, anchor = (
        np.array([1.0, 2.0]),
        np.array([2.0, 3.0]),
        np.array([0.3, -0.1]),
        np.array([0.2, 0.0]),
    )
    return LinearGJF(k, m, g, ext, anchor), k, m, g, ext, anchor


def test_cuda_matches_cpu_with_identical_impulses_and_external_load():
    from backend.physics.snupi_dynamics import gjf_integrate

    solver, k, m, g, ext, anchor = _solver()
    q = np.array([0.1, -0.2])
    kwargs = dict(kT=4.142, dt=0.02, n_steps=1000, n_equil=100, sample_every=17)
    expected, ev = gjf_integrate(
        lambda x: ext - k @ x - anchor * x,
        q,
        m,
        g,
        **kwargs,
        rng=np.random.default_rng(2),
    )
    got, gv = solver.integrate(q, **kwargs, rng=np.random.default_rng(2))
    np.testing.assert_allclose(got, expected, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(gv, ev, rtol=1e-11, atol=1e-12)


def test_cuda_seed_and_sample_schedule_are_repeatable():
    solver, *_ = _solver()
    kwargs = dict(kT=4.142, dt=0.02, n_steps=123, n_equil=20, sample_every=17, seed=9)
    a, av = solver.integrate(np.zeros(2), **kwargs)
    b, bv = solver.integrate(np.zeros(2), **kwargs)
    assert len(a) == len(range(20, 123, 17))
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(av, bv)


def test_cuda_divergence_is_detected_before_returning_output():
    from backend.physics.snupi_dynamics import _GJFDiverged

    solver, *_ = _solver()
    with pytest.raises(_GJFDiverged):
        solver.integrate(
            np.array([np.nan, 0]),
            kT=4.142,
            dt=0.02,
            n_steps=2,
            n_equil=0,
            sample_every=1,
        )


def test_translation_only_transfer_preserves_observables():
    from scipy.sparse import eye
    from backend.physics.snupi_cuda import LinearGJF

    _solver()  # portable CUDA skip
    solver = LinearGJF(
        eye(12, format="csr"), np.ones(12), np.ones(12), np.zeros(12), np.zeros(12)
    )
    kwargs = dict(kT=4.142, dt=0.02, n_steps=123, n_equil=20, sample_every=17, seed=9)
    full, _ = solver.integrate(np.zeros(12), **kwargs)
    translations, _ = solver.integrate(np.zeros(12), translation_only=True, **kwargs)
    np.testing.assert_array_equal(translations, full.reshape(len(full), 2, 6)[:, :, :3])
