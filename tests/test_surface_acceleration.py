"""GPU is optional; all unaccelerated and failure paths retain SciPy semantics."""

import numpy as np
import pytest
from scipy.ndimage import binary_dilation, binary_erosion
from backend.core import surface_acceleration as accel
from backend.core.surface import _sphere_struct


def test_explicit_cpu_mode_never_initializes_cuda(monkeypatch):
    monkeypatch.setenv("NADOC_SURFACE_GPU", "0")

    def forbidden(*args):
        raise AssertionError(
            "explicit CPU mode must not import Torch or initialize CUDA"
        )

    monkeypatch.setattr(accel, "_try_cuda_closing", forbidden)
    grid = np.random.default_rng(3).random((8, 9, 10)) > 0.5
    struct = _sphere_struct(2.8)
    expected = binary_erosion(binary_dilation(grid, structure=struct), structure=struct)
    np.testing.assert_array_equal(accel.close_volume(grid, struct), expected)


def test_unavailable_acceleration_falls_back_exactly(monkeypatch):
    monkeypatch.setenv("NADOC_SURFACE_GPU", "1")
    monkeypatch.setattr(accel, "_cuda_torch", lambda: None)
    grid = np.zeros((65, 65, 65), bool)
    grid[20:45, 20:45, 20:45] = True
    struct = _sphere_struct(2.8)
    expected = binary_erosion(binary_dilation(grid, structure=struct), structure=struct)
    np.testing.assert_array_equal(accel.close_volume(grid, struct), expected)


@pytest.mark.parametrize("failure", [False, True])
def test_insufficient_memory_or_cuda_error_falls_back(monkeypatch, failure):
    from types import SimpleNamespace

    monkeypatch.setenv("NADOC_SURFACE_GPU", "1")

    def memory():
        if failure:
            raise RuntimeError("CUDA allocation failed")
        return 0, 8 * 1024**3

    monkeypatch.setattr(
        accel,
        "_cuda_torch",
        lambda: SimpleNamespace(cuda=SimpleNamespace(mem_get_info=memory)),
    )
    grid = np.zeros((65, 65, 65), bool)
    grid[20:45, 20:45, 20:45] = True
    struct = _sphere_struct(2.8)
    expected = binary_erosion(binary_dilation(grid, structure=struct), structure=struct)
    np.testing.assert_array_equal(accel.close_volume(grid, struct), expected)


@pytest.mark.slow
@pytest.mark.atomistic
def test_cuda_closing_matches_scipy_boundaries_and_density():
    if accel._cuda_torch() is None:
        pytest.skip("optional CUDA Torch unavailable")
    rng = np.random.default_rng(42)
    for probability in [0.0, 0.001, 0.1, 0.9, 1.0]:
        grid = rng.random((65, 67, 69)) < probability
        for radius in [2.0, 2.8, 3.4, 4.9]:
            struct = _sphere_struct(radius)
            expected = binary_erosion(
                binary_dilation(grid, structure=struct), structure=struct
            )
            actual = accel._try_cuda_closing(grid, struct)
            if actual is None:
                pytest.skip("CUDA workspace unavailable")
            np.testing.assert_array_equal(actual, expected)


def test_default_attempts_cuda_without_environment_flag(monkeypatch):
    monkeypatch.delenv("NADOC_SURFACE_GPU", raising=False)
    expected = np.ones((2, 3, 4), dtype=bool)
    monkeypatch.setattr(accel, "_try_cuda_closing", lambda *args: expected)
    assert accel.close_volume(np.zeros_like(expected), _sphere_struct(2.8)) is expected


@pytest.mark.parametrize("available", [False, True])
def test_startup_warms_real_closing_operation_and_preserves_fallback(
    monkeypatch, available
):
    monkeypatch.delenv("NADOC_SURFACE_GPU", raising=False)

    def warm(grid, structure):
        assert grid.dtype == bool and grid.size >= 256_000
        assert not grid.any()
        np.testing.assert_array_equal(structure, _sphere_struct(2.8))
        return grid if available else None

    monkeypatch.setattr(accel, "_try_cuda_closing", warm)
    assert accel.initialize_surface_cuda() is available


def test_startup_respects_explicit_cpu_override(monkeypatch):
    monkeypatch.setenv("NADOC_SURFACE_GPU", "0")

    def forbidden(*args):
        raise AssertionError("CPU override must not warm CUDA")

    monkeypatch.setattr(accel, "_try_cuda_closing", forbidden)
    assert accel.initialize_surface_cuda() is False
