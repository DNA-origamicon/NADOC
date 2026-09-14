"""Independent physical-unit reference for the Chudoba 2017 oxDNA port.

Lengths: nm; energies: kJ/mol; temperatures: K. This is a validation oracle,
not the simulation backend. DOI 10.1021/acs.jctc.7b00560, equations 1 and 12.
"""
import math

import numpy as np

BOND_NM = 0.33
BOND_K = 17000.0
ANGLE_COS = math.cos(math.radians(130))
ANGLE_K = 85.0
TORSION_K = (1.96, 0.18, 0.33, 0.12)
CUTOFF_NM = 0.9


def parameters(temperature):
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("Temperature must be positive and finite")
    result = dict(n=8.0, m=54 * 0.9943**temperature,
                sigma=0.367 + 0.000139 * temperature,
                epsilon=1.372, mu=0.604 + 0.00029 * temperature,
                gamma=0.4841, delta=0.1064)
    # Section 4.3: outside 294–381 K, use SI Table S1 directly.
    for t, m, sigma, mu in [(270,10.74,.4039,.6818),(396,5.94,.4238,.7154),
                            (422,5.24,.4277,.7219),(450,5.09,.4312,.7277)]:
        if abs(temperature-t)<1e-4:
            result.update(m=m,sigma=sigma,mu=mu)
    return result


def pair_energy_derivative(r, temperature, *, truncate=True, shifted=False, zero_tail=False):
    """Return U and dU/dr, with the finite n=m limit evaluated stably.

    Truncation follows the stated U(r >= 0.9 nm)=0 convention. No unreported
    potential/force shift is introduced. A cutoff crossing is discontinuous;
    finite-difference checks must not straddle it.
    """
    if shifted and zero_tail:
        raise ValueError("Shift and zero-tail conventions are mutually exclusive")
    if not math.isfinite(r) or r <= 0:
        raise ValueError("Separation must be positive and finite")
    if truncate and r >= CUTOFF_NM:
        return 0.0, 0.0
    p = parameters(temperature)
    n, m = p['n'], p['m']
    d = n - m
    log_sr = math.log(p['sigma'] / r)
    if abs(d) < 1e-8:
        norm = n * math.e * p['epsilon']
        divided_difference = log_sr
    else:
        norm = n * math.exp(m * math.log1p(d / m) / d) * p['epsilon']
        divided_difference = math.expm1(d * log_sr) / d
    power = math.exp(m * log_sr)
    mie = norm * power * divided_difference
    derivative = -norm * power * (m * divided_difference + math.exp(d * log_sr)) / r
    displacement = (r - p['mu']) / p['delta']
    gaussian = p['gamma'] * math.exp(-displacement**2)
    if zero_tail and r > p['mu'] and mie + gaussian < 0:
        return 0., 0.
    shift = pair_energy_derivative(CUTOFF_NM, temperature, truncate=False)[0] if shifted else 0.
    return mie + gaussian - shift, derivative - 2 * displacement * gaussian / p['delta']


def bonded_energy(xyz):
    """One unwrapped linear chain. Trans dihedral has phi=pi.

    Independent vector geometry intentionally avoids engine conventions.
    Angles and torsions use chemical neighbor ordering. Collinear torsions
    are undefined and rejected instead of silently assigning zero energy.
    """
    xyz = np.asarray(xyz, dtype=float)
    bonds = np.diff(xyz, axis=0)
    lengths = np.linalg.norm(bonds, axis=1)
    if np.any(lengths <= 0):
        raise ValueError("Coincident bonded beads")
    energy = 0.5 * BOND_K * np.sum((lengths - BOND_NM)**2)
    for i in range(len(bonds) - 1):
        cosine = -np.dot(bonds[i], bonds[i+1]) / (lengths[i] * lengths[i+1])
        energy += 0.5 * ANGLE_K * (cosine - ANGLE_COS)**2
    for i in range(len(bonds) - 2):
        a = np.cross(bonds[i], bonds[i+1])
        b = np.cross(bonds[i+1], bonds[i+2])
        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        if denominator < 1e-15:
            raise ValueError("Collinear dihedral")
        cosine = np.clip(np.dot(a, b) / denominator, -1, 1)
        phi = math.acos(cosine)
        for n, k in enumerate(TORSION_K, 1):
            phase = math.pi if n == 1 else 0
            energy += k * (1 + math.cos(n * phi - phase))
    return float(energy)


def chain_energy(xyz, temperature, *, shifted=False, zero_tail=False):
    xyz = np.asarray(xyz, dtype=float)
    energy = bonded_energy(xyz)
    for i in range(len(xyz)):
        for j in range(i + 2, len(xyz)):
            energy += pair_energy_derivative(np.linalg.norm(xyz[j] - xyz[i]), temperature, shifted=shifted, zero_tail=zero_tail)[0]
    return energy


def finite_difference_forces(xyz, temperature, step=1e-6):
    xyz = np.array(xyz, dtype=float, copy=True)
    forces = np.zeros_like(xyz)
    for i in range(len(xyz)):
        for axis in range(3):
            xyz[i, axis] += step
            plus = chain_energy(xyz, temperature)
            xyz[i, axis] -= 2 * step
            minus = chain_energy(xyz, temperature)
            xyz[i, axis] += step
            forces[i, axis] = -(plus - minus) / (2 * step)
    return forces
