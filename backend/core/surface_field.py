"""Figure-quality continuous field for display surfaces.

Regularize the closed SES occupancy locally before extracting its 0.5 isosurface.
Sigma is fixed in physical units: 0.0425 nm, independent of strand role or grid.
This is filtered occupancy, not an analytical SES or Gaussian atom envelope.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


CONTINUOUS_SIGMA_NM = 0.0425


def continuous_surface_field(
    occupancy: np.ndarray, *, grid_spacing: float = 0.05
) -> np.ndarray:
    """Separable float32 convolution, bounded to three sigma, with empty exterior.

    Never mutate occupancy. One float32 output volume is reused by the separable
    filter; no distance-transform float64 volumes or extra polygon subdivision.
    """
    if grid_spacing <= 0:
        raise ValueError("grid_spacing must be positive")
    return gaussian_filter(
        occupancy,
        sigma=CONTINUOUS_SIGMA_NM / grid_spacing,
        output=np.float32,
        mode="constant",
        cval=0.0,
        truncate=3.0,
    )
