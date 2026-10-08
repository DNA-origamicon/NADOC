"""Small, rigid-motion-equivariant displacement regression for Exp pilots.

Six shared strain modes are a pipeline baseline, not a local DNA force field.
Future motif/extra-base encoders can supply additional vector basis columns under
a new feature schema without changing the dataset's keyed coordinate targets.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FEATURE_SCHEMA = "bundle-strain-v1"
FEATURE_NAMES = ["radial", "radial_end", "axial", "axial_end", "twist", "twist_end"]
MODEL_PATH = Path(__file__).resolve().parents[1] / "data/exp/strain_v1.json"


def vector_basis(positions):
    x = np.asarray(positions, dtype=float)
    if x.ndim != 2 or x.shape[1] != 3 or len(x) < 3 or not np.isfinite(x).all():
        raise ValueError("Exp needs at least three finite nucleotide positions")
    q = x - x.mean(axis=0)
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    axis = vt[0]
    z = q @ axis
    axial = z[:, None] * axis
    radial = q - axial
    u = z / max(float(np.max(np.abs(z))), 1e-8)
    twist = np.cross(axis, radial) * u[:, None]
    basis = np.stack(
        [
            radial,
            radial * u[:, None] ** 2,
            axial,
            axial * u[:, None] ** 2,
            twist,
            twist * u[:, None] ** 2,
        ],
        axis=-1,
    )
    return basis - basis.mean(axis=0, keepdims=True)


def fit(samples, alpha=0.01):
    """Equal total weight per design; no random frame split or fitted intercept."""
    a, b = [], []
    for sample in samples:
        basis = vector_basis(sample["input_nm"])[sample["mapped_rows"]]
        target = sample["target_nm"] - sample["input_nm"][sample["mapped_rows"]]
        weight = 1 / np.sqrt(len(target))
        a.append(basis.reshape(-1, len(FEATURE_NAMES)) * weight)
        b.append(target.reshape(-1) * weight)
    a, b = np.concatenate(a), np.concatenate(b)
    # Column norms preserve design weighting and ridge strength when identical
    # rows are repeated (e.g. a denser trajectory/geometry representation).
    scale = np.sqrt(np.sum(a * a, axis=0) / len(samples))
    scale = np.where(scale > 1e-12, scale, 1.0)
    scaled = a / scale
    coef = np.linalg.solve(scaled.T @ scaled + alpha * np.eye(len(scale)), scaled.T @ b)
    return coef / scale


def predict_positions(positions, coefficients):
    return np.asarray(positions) + vector_basis(positions) @ np.asarray(coefficients)


def load_adapter(path=MODEL_PATH):
    if not path.exists():
        return None, None
    model = json.loads(path.read_text())
    if model["feature_schema"] != FEATURE_SCHEMA or model["features"] != FEATURE_NAMES:
        raise ValueError("Unsupported Exp feature schema")
    coefficients = np.asarray(model["coefficients"], dtype=float)
    if (
        coefficients.shape != (len(FEATURE_NAMES),)
        or not np.isfinite(coefficients).all()
    ):
        raise ValueError("Invalid Exp regression coefficients")

    def predict(design, progress, cancel):
        from backend.core.atomistic_to_nadoc import build_active_design_reference

        progress(0.1, "Building native NADOC geometry")
        reference = build_active_design_reference(design)
        keys = sorted(reference)
        x = np.array([reference[k] for k in keys])
        progress(0.65, "Applying trained CPU regression")
        positions = predict_positions(x, coefficients)
        extras = sum(len(co.extra_bases or "") for co in design.crossovers)
        label = (
            "0×T strain pilot; finite production-window mean, not validated equilibrium"
        )
        if extras:
            label += "; extra bases are outside training coverage"
        progress(0.95, "Preparing screening preview")
        return {"positions_nm": positions.tolist(), "label": label}

    return predict, model["model_card"]
