"""CUDA acceleration of the existing discrete surface closing, with CPU fallback.

Enabled by default and warmed during backend startup when CUDA PyTorch is installed.
NADOC_SURFACE_GPU=0 explicitly selects CPU for diagnostics and paired benchmarks.
This is a count convolution of the existing Boolean stencil, not a Gaussian
surface or a change in grid resolution. Cold CUDA startup can cost seconds.
"""

from functools import lru_cache
import os
import threading

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion

_gpu_lock = threading.Lock()


def initialize_surface_cuda() -> bool:
    """Warm import, CUDA context and convolution before serving requests.

    A small synthetic volume exercises the same operation as real surfaces;
    no design state is loaded or modified. Unavailable CUDA retains CPU support.
    """
    if os.environ.get("NADOC_SURFACE_GPU", "1") == "0":
        return False
    x, y, z = np.mgrid[-3:4, -3:4, -3:4]
    structure = x * x + y * y + z * z <= 2.8**2
    return _try_cuda_closing(np.zeros((64, 64, 64), dtype=bool), structure) is not None


@lru_cache(maxsize=1)
def _cuda_torch():
    try:
        import torch

        return torch if torch.cuda.is_available() else None
    except (ImportError, OSError, RuntimeError):
        return None


def _try_cuda_closing(grid: np.ndarray, structure: np.ndarray) -> np.ndarray | None:
    # Small stencils/volumes favor CPU, especially including transfers. Restrict
    # counts to small exactly representable integers with a half-integer margin.
    count = int(structure.sum())
    if grid.size < 256_000 or not 33 <= count <= 512:
        return None
    torch = _cuda_torch()
    if torch is None:
        return None
    # Concurrent surface requests must not each reserve a convolution workspace.
    # Do not change global Torch precision, device, allocator, or thread settings.
    with _gpu_lock:
        try:
            free, _ = torch.cuda.mem_get_info()
            if grid.size * 32 + 256 * 1024**2 > free:
                return None
            with torch.inference_mode():
                kernel = torch.as_tensor(structure.astype(np.float32), device="cuda")[
                    None, None
                ]
                volume = torch.as_tensor(grid.astype(np.float32), device="cuda")[
                    None, None
                ]
                padding = tuple(s // 2 for s in structure.shape)
                conv = torch.nn.functional.conv3d
                dilated = (conv(volume, kernel, padding=padding) > 0.5).float()
                closed = conv(dilated, kernel, padding=padding) > count - 0.5
                return closed[0, 0].cpu().numpy()
        except (RuntimeError, OSError):
            # Missing driver support, workspace allocation failure, or a CUDA
            # error must not make a previously supported surface unavailable.
            return None


def close_volume(grid: np.ndarray, structure: np.ndarray) -> np.ndarray:
    """Same zero-border Boolean closing on CUDA when available, otherwise CPU."""
    if os.environ.get("NADOC_SURFACE_GPU", "1") != "0":
        result = _try_cuda_closing(grid, structure)
        if result is not None:
            return result
    return binary_erosion(
        binary_dilation(grid, structure=structure), structure=structure
    )
