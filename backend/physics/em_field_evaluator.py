"""Batched exterior electric fields with MiePy's outgoing VSH convention.

Reuse radial functions per degree and angular functions across electric/magnetic
terms and +/-m. Coefficients, source, truncation order and material solve remain
MiePy's. No dipole approximation or coefficient thresholding is used.

Conventions: MiePy v1.1.0 vsh/vsh_functions.py and cpp/src/special.cpp
(https://github.com/johnaparker/miepy/tree/v1.1.0). scipy.lpmv includes
Condon–Shortley phase; MiePy's associated Legendre function does not.
"""
from math import factorial
import numpy as np
from scipy.special import lpmv


def exterior_electric_field(cluster, points):
    """Evaluate a sphere cluster at exterior Cartesian points, shape (3,N)."""
    from miepy.vsh import special

    if cluster.interface is not None:
        raise ValueError('The optimized EM evaluator does not support interfaces.')
    points = np.asarray(points, dtype=float)
    result = np.zeros((3, len(points)), dtype=complex)
    k = cluster.material_data.k_b
    for particle, center in enumerate(cluster.position):
        result += vsh_electric_field(points, center, k, cluster.lmax,
                                    cluster.p_scat[particle], special.spherical_hn)
    return result + cluster.E_source(*points.T, far=False, spherical=False)


def vsh_electric_field(points, center, k, lmax, coefficients, radial_function):
    """Cartesian +i-convention VSH expansion for supplied radial basis."""
    import miepy
    from miepy.vsh import special
    from miepy.cpp.vsh_functions import Emn
    points = np.asarray(points)
    radius, theta, phi = miepy.coordinates.cart_to_sph(*points.T, origin=center)
    kr = k * radius
    cosine, sine = np.cos(theta), np.sin(theta)
    # Preserve MiePy's explicit pole convention and its near-pole behavior.
    polar = np.abs(sine) < 1e-5
    safe_sine = np.where(polar, 1., sine)
    phases = {m: np.exp(1j * m * phi) for m in range(-lmax, lmax + 1)}
    field = np.zeros((3, len(points)), dtype=complex)
    for n in range(1, lmax + 1):
        radial = radial_function(n, kr)
        derivative = radial_function(n, kr, derivative=True)
        tangential = (radial + kr * derivative) / kr
        angular = {}
        for m in range(n + 1):
            legendre = (-1)**m * lpmv(m, n, cosine)
            previous = (-1)**m * lpmv(m, n - 1, cosine) if m < n else np.zeros_like(cosine)
            pi = m * legendre / safe_sine
            tau = (n * cosine * legendre - (n + m) * previous) / safe_sine
            if np.any(polar):
                legendre[polar] = special.associated_legendre(n, m, cosine[polar])
                pi[polar] = special.pi_func(n, m, theta[polar])
                tau[polar] = special.tau_func(n, m, theta[polar])
            angular[m] = legendre, pi, tau
        for m in range(-n, n + 1):
            legendre, pi, tau = angular[abs(m)]
            if m < 0:
                scale = (-1)**m * factorial(n + m) / factorial(n - m)
                legendre, pi, tau = scale * legendre, -scale * pi, scale * tau
            index = n * n + n + m - 1
            electric, magnetic = coefficients[:, index]
            factor = 1j * Emn(m, n) * phases[m]
            field[0] += factor * electric * n * (n + 1) * legendre * radial / kr
            field[1] += factor * (electric * tau * tangential + magnetic * 1j * pi * radial)
            field[2] += factor * (electric * 1j * pi * tangential - magnetic * tau * radial)
    return miepy.coordinates.vec_sph_to_cart(field, theta, phi)
