"""Acceleration preserves linear projection and backend selection contracts."""

import numpy as np
import pytest
from scipy.sparse import eye

from backend.physics.snupi_analysis import linear_rmsf
from backend.physics.snupi_cuda import required_bytes, CudaUnavailable


@pytest.mark.parametrize("collinear", [False, True])
@pytest.mark.parametrize("batch", [1, 7, 128])
def test_batched_rmsf_matches_full_projection(collinear, batch):
    rng = np.random.default_rng(11)
    ref = rng.normal(size=(20, 3))
    if collinear:
        ref[:, 1:] = 0
    frames = ref + rng.normal(size=(31, 20, 3))
    before = frames.copy()
    centered = ref - ref.mean(axis=0)
    rigid = np.column_stack(
        [np.tile(a, (20, 1)).ravel() for a in np.eye(3)]
        + [np.cross(a, centered).ravel() for a in np.eye(3)]
    )
    b, s, _ = np.linalg.svd(rigid, full_matrices=False)
    b = b[:, s > s.max() * max(rigid.shape) * np.finfo(float).eps]
    disp = (frames - ref).reshape(31, -1)
    aligned = (disp - (disp @ b) @ b.T).reshape(frames.shape)
    expected = np.sqrt(
        np.mean(np.sum((aligned - aligned.mean(axis=0)) ** 2, axis=2), axis=0)
    )
    np.testing.assert_allclose(linear_rmsf(frames, ref, batch), expected, atol=1e-14)
    np.testing.assert_array_equal(frames, before)


def test_gpu_memory_estimate_accounts_for_sparse_storage_and_work_vectors():
    k = eye(24, format="csr")
    assert (
        required_bytes(k)
        > k.data.nbytes + k.indices.nbytes + k.indptr.nbytes + 24 * 8 * 32
    )


def test_auto_backend_falls_back_before_integrating(monkeypatch):
    from backend.physics import snupi_cuda

    def unavailable(*args):
        raise CudaUnavailable("no test device")

    monkeypatch.setattr(snupi_cuda, "LinearGJF", unavailable)
    args = (eye(6, format="csr"), np.ones(6), np.ones(6), np.zeros(6), np.zeros(6))
    solver, execution = snupi_cuda.select_backend("auto", *args, supported=True)
    assert solver is None and execution["backend"] == "cpu"
    assert execution["fallback_reason"] == "no test device"
    with pytest.raises(CudaUnavailable, match="no test device"):
        snupi_cuda.select_backend("cuda", *args, supported=True)


def test_cuda_refuses_insufficient_headroom_before_allocating(monkeypatch):
    import sys
    from types import SimpleNamespace
    from backend.physics.snupi_cuda import LinearGJF

    fake = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True, mem_get_info=lambda: (1024, 8 * 1024**3)
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake)
    with pytest.raises(CudaUnavailable, match="headroom"):
        LinearGJF(
            eye(6, format="csr"), np.ones(6), np.ones(6), np.zeros(6), np.zeros(6)
        )


def test_unsupported_models_keep_cpu_backend(monkeypatch):
    from backend.physics import snupi_cuda

    def forbidden(*args):
        raise AssertionError("unsupported force model sent to CUDA")

    monkeypatch.setattr(snupi_cuda, "LinearGJF", forbidden)
    args = (eye(6, format="csr"), np.ones(6), np.ones(6), np.zeros(6), np.zeros(6))
    solver, execution = snupi_cuda.select_backend("auto", *args, supported=False)
    assert solver is None and execution["backend"] == "cpu"
    assert "linear Stokes" in execution["fallback_reason"]
    with pytest.raises(ValueError, match="linear Stokes"):
        snupi_cuda.select_backend("cuda", *args, supported=False)
