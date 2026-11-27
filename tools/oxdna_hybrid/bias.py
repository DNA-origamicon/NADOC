"""Frozen tabulated biases and synchronous well-tempered training (oxDNA units)."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BiasSpec:
    coordinate: str = "mixed"
    minimum: float = -1.0
    maximum: float = 9.0
    spacing: float = 0.025
    width: float = 0.25
    height_kbt: float = 0.1
    bias_factor: float = 10.0
    mixed_weight: float = 0.7
    contact_radius: float = 0.5

    def __post_init__(self):
        if self.coordinate not in {"com", "hb_cutoff", "mixed"}:
            raise ValueError("Unsupported coordinate")
        values = [self.minimum, self.maximum, self.spacing, self.width,
                  self.height_kbt, self.bias_factor, self.mixed_weight, self.contact_radius]
        if not np.isfinite(values).all() or not self.maximum > self.minimum:
            raise ValueError("Invalid bias domain")
        if min(self.spacing, self.width, self.height_kbt) <= 0 or self.bias_factor <= 1:
            raise ValueError("Invalid well-tempered settings")
        if not 0 <= self.mixed_weight <= 1:
            raise ValueError("Invalid mixing weight")
        if self.contact_radius <= 0:
            raise ValueError("Contact radius must be positive")
        if not np.isclose((self.maximum-self.minimum)/self.spacing,
                          round((self.maximum-self.minimum)/self.spacing)):
            raise ValueError("Grid spacing must divide domain")

    @property
    def grid(self):
        return np.linspace(self.minimum, self.maximum,
                           round((self.maximum-self.minimum)/self.spacing)+1)

    @property
    def settings(self):
        return (f"coordination_type = {self.coordinate}\nmixed_weight = {self.mixed_weight}\n"
                "hb_energy_cutoff = -0.2\nhb_transition_width = 0.1\n"
                f"d0 = 0.4\nr0 = {self.contact_radius}\nn = 6\n")


def evaluate(spec, bias, values):
    bias = np.asarray(bias, dtype=float)
    values = np.asarray(values, dtype=float)
    if bias.shape != spec.grid.shape or not np.isfinite(bias).all():
        raise ValueError("Invalid bias table")
    if not np.isfinite(values).all() or np.any(values < spec.minimum) or np.any(values >= spec.maximum):
        raise ValueError("Coordinate outside bias domain")
    return np.interp(values, spec.grid, bias)


def deposit(spec, bias, endpoints, thermal_energy):
    """All walkers see the same old table; fixed total hill budget per epoch.

    Bias is an energy, not beta*energy. Do not shift its zero during training:
    the absolute accumulated height enters the well-tempered attenuation.
    """
    if not np.isfinite(thermal_energy) or thermal_energy <= 0:
        raise ValueError("Invalid thermal energy")
    endpoints = np.asarray(endpoints, dtype=float)
    if endpoints.ndim != 1 or not len(endpoints):
        raise ValueError("Need walker endpoints")
    old = evaluate(spec, bias, endpoints)
    heights = (spec.height_kbt * thermal_energy / len(endpoints)
               * np.exp(-old / (thermal_energy * (spec.bias_factor-1))))
    increments = np.exp(-0.5*((spec.grid[:, None]-endpoints)/spec.width)**2) @ heights
    return np.asarray(bias) + increments


def force_text(spec, bias, op_file, a, b):
    evaluate(spec, bias, [max(0, spec.minimum)])
    table = ','.join(f'{x:.16g}' for x in bias)
    common = f"group_name = hybrid\nN_grid = {len(bias)}\npotential_grid = {table}\n"
    if spec.coordinate != "com":
        return ("{\ntype = meta_coordination\n" + common
                + f"coord_min = {spec.minimum}\ncoord_max = {spec.maximum}\nop_file = {op_file}\n"
                + spec.settings + "}\n")
    common += (f"type = meta_com_trap\nxmin = {spec.minimum}\nxmax = {spec.maximum}\n"
               f"p1a = {','.join(map(str,a))}\np2a = {','.join(map(str,b))}\nPBC = true\n")
    return ''.join("{\n" + common + f"mode = {mode}\n}}\n" for mode in (1, 2))
