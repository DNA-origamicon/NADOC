"""Pure parametric layouts for named assembly attachment interfaces.

The returned sites are instance-local declarations.  This module does not mutate an
Assembly and does not infer DNA polarity or molecular placement; the API/headless
layer lowers each site through the existing connector service.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from backend.core.models import ConnectionType

Vec3Tuple = tuple[float, float, float]


@dataclass(frozen=True)
class AttachmentSite:
    """One fully declared, named attachment interface in a part-local frame."""

    label: str
    position: Vec3Tuple
    normal: Vec3Tuple
    connection_type: ConnectionType
    clearance_nm: float

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "position": list(self.position),
            "normal": list(self.normal),
            "connection_type": self.connection_type.value,
            "clearance_nm": self.clearance_nm,
        }


def _vec3(value: Sequence[float], *, name: str) -> Vec3Tuple:
    if len(value) != 3:
        raise ValueError(f"{name} must contain exactly 3 values")
    out = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in out):
        raise ValueError(f"{name} must contain only finite values")
    return out  # type: ignore[return-value]


def _unit(value: Sequence[float], *, name: str) -> Vec3Tuple:
    x, y, z = _vec3(value, name=name)
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 1e-12:
        raise ValueError(f"{name} must be non-zero")
    return (x / length, y / length, z / length)


def linear_attachment_layout(
    count: int,
    *,
    pitch_nm: float,
    origin: Sequence[float] = (0.0, 0.0, 0.0),
    direction: Sequence[float] = (1.0, 0.0, 0.0),
    normal: Sequence[float] = (0.0, 0.0, 1.0),
    label_prefix: str = "site",
    connection_types: Sequence[ConnectionType | str] = (ConnectionType.COVALENT,),
    clearances_nm: Sequence[float] = (0.0,),
) -> list[AttachmentSite]:
    """Generate a deterministic, mixed-composition linear interface layout.

    ``connection_types`` and ``clearances_nm`` repeat cyclically, allowing patterns
    such as alternating biotin/toehold sites without duplicating placement logic.
    Direction and normal are normalized; the normal is stored as the interface
    orientation and is deliberately not inferred from strand geometry.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    pitch = float(pitch_nm)
    if not math.isfinite(pitch) or pitch <= 0:
        raise ValueError("pitch_nm must be a positive finite number")
    if not label_prefix:
        raise ValueError("label_prefix must not be empty")
    if not connection_types or not clearances_nm:
        raise ValueError("connection_types and clearances_nm must not be empty")

    o = _vec3(origin, name="origin")
    step = _unit(direction, name="direction")
    nrm = _unit(normal, name="normal")
    chemistries = [
        value if isinstance(value, ConnectionType) else ConnectionType(value)
        for value in connection_types
    ]
    clearances = [float(value) for value in clearances_nm]
    if any(not math.isfinite(value) or value < 0 for value in clearances):
        raise ValueError("clearances_nm must contain finite, non-negative values")

    return [
        AttachmentSite(
            label=f"{label_prefix}_{i}",
            position=tuple(o[j] + i * pitch * step[j] for j in range(3)),  # type: ignore[arg-type]
            normal=nrm,
            connection_type=chemistries[i % len(chemistries)],
            clearance_nm=clearances[i % len(clearances)],
        )
        for i in range(count)
    ]
