"""Full concentric dielectric-shell Mie coefficients and shell-region fields.

Nonmagnetic, nonoverlapping spheres. Tangential E/H continuity is solved at both
interfaces for every multipole; the exterior remains the ordinary coupled GMMT.
Thickness is an explicit polymer-size proxy, not an optical calibration.
"""
import numpy as np
from scipy.special import spherical_jn, spherical_yn


def shell_parameters(particles, settings):
    model = settings.get('model', 'none')
    if model not in ('none', 'ssdna_wlc', 'manual'):
        raise ValueError('Unknown DNA shell model.')
    index = float(settings.get('refractive_index', 1.7))
    length = float(settings.get('oligo_length_nt', 20))
    persistence = float(settings.get('persistence_length_nm', 2.5))
    manual = float(settings.get('thickness_nm', 2.5))
    if not all(np.isfinite(v) for v in (index, length, persistence, manual)):
        raise ValueError('Shell parameters must be finite.')
    if not (1 <= index <= 2.5 and 1 <= length <= 200 and 0.1 <= persistence <= 10 and 0 <= manual <= 100):
        raise ValueError('Shell parameters are outside supported bounds.')
    # Falabella et al., DOI 10.1021/la100761f: 0.59 nm/dT, WLC Eq. 9.
    # RMS end-to-end distance is used as a tunable radial-size proxy only.
    contour = .59 * length
    rms = np.sqrt(2 * persistence * contour - 2 * persistence**2 * (-np.expm1(-contour / persistence)))
    thickness = 0. if model == 'none' else manual if model == 'manual' else float(rms)
    return {'model': model, 'coverage': 'full spherical coverage independent of explicit conjugate count',
            'oligo_length_nt': length, 'persistence_length_nm': persistence,
            'contour_nm_per_nt': .59, 'thickness_nm': thickness,
            'refractive_index': index, 'thickness_by_particle_nm': [thickness] * len(particles),
            'interpretation': 'WLC RMS size proxy; hydrodynamic size is not a measured optical shell thickness.'}


def coefficients(core_radius, outer_radius, core_index, shell_index, medium_index, wavelength, order):
    """Return [electric/magnetic,degree,(scattering,regular-shell,irregular-shell,core)]."""
    k0 = 2 * np.pi / wavelength
    result = np.empty((2, order, 4), complex)
    def radial(n, index, radius, kind):
        x = k0 * index * radius
        j, dj = spherical_jn(n, x), spherical_jn(n, x, derivative=True)
        y, dy = spherical_yn(n, x), spherical_yn(n, x, derivative=True)
        z, dz = (j, dj) if kind == 'j' else (y, dy) if kind == 'y' else (j + 1j*y, dj + 1j*dy)
        return z, (z + x * dz) / x
    for n in range(1, order + 1):
        for pol in (0, 1):
            def boundary(index, radius, kind):
                z, d = radial(n, index, radius, kind)
                return np.array([d, index*z] if pol == 0 else [z, index*d])
            matrix = np.zeros((4, 4), complex)
            matrix[:2, 0] = boundary(medium_index, outer_radius, 'h')
            matrix[:2, 1] = boundary(shell_index, outer_radius, 'j')
            matrix[:2, 2] = boundary(shell_index, outer_radius, 'y')
            matrix[2:, 1] = boundary(shell_index, core_radius, 'j')
            matrix[2:, 2] = boundary(shell_index, core_radius, 'y')
            matrix[2:, 3] = -boundary(core_index, core_radius, 'j')
            rhs = np.r_[boundary(medium_index, outer_radius, 'j'), [0, 0]]
            result[pol, n-1] = np.linalg.solve(matrix, rhs)
    if not np.all(np.isfinite(result)):
        raise ValueError('Nonfinite coated-sphere coefficients.')
    return result


def apply_shell(cluster, thicknesses, shell_index):
    """Replace single-sphere responses then recompute all interparticle coupling."""
    cluster.shell_coefficients = []
    for i, thickness in enumerate(thicknesses):
        response = coefficients(cluster.radius[i], cluster.radius[i] + thickness,
            np.sqrt(cluster.material_data.eps[i]), shell_index, 1.333, cluster.wavelength, cluster.lmax)
        cluster.mie_scat[i] = response[:, :, 0]
        cluster.shell_coefficients.append(response)
    cluster.solve()


def coated_field(cluster, points, thicknesses, shell_index, exterior):
    """Total E outside metal, including dielectric shells; no fictitious water gaps."""
    import miepy
    points = np.asarray(points)
    owners = np.full(len(points), -1)
    for i, (center, radius, thickness) in enumerate(zip(cluster.position, cluster.radius, thicknesses)):
        owners[np.linalg.norm(points - center, axis=1) < radius + thickness] = i
    result = np.zeros((3, len(points)), complex)
    outside = owners == -1
    if np.any(outside):
        result[:, outside] = exterior(cluster, points[outside])
    degrees = np.array([n-1 for _, n, _ in miepy.mode_indices(cluster.lmax)])
    for i in range(len(cluster.position)):
        selected = owners == i
        if not np.any(selected):
            continue
        response = cluster.shell_coefficients[i]
        u = response[:, :, 1][:, degrees] * cluster.p_inc[i]
        v = response[:, :, 2][:, degrees] * cluster.p_inc[i]
        from backend.physics.em_field_evaluator import vsh_electric_field
        k = 2 * np.pi * shell_index / cluster.wavelength
        # Direct regular/irregular evaluation avoids cancellation and unstable
        # high-order regular Bessel recurrence in the reference field helper.
        result[:, selected] = vsh_electric_field(points[selected], cluster.position[i], k,
            cluster.lmax, -u, spherical_jn)
        result[:, selected] += vsh_electric_field(points[selected], cluster.position[i], k,
            cluster.lmax, -v, spherical_yn)
    return result
