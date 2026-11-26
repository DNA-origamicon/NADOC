"""Run in the optional isolated MiePy interpreter (no pytest dependency)."""
import numpy as np
import miepy
from backend.physics.em_analysis import gold_permittivity
from backend.physics.em_field_evaluator import exterior_electric_field

rng = np.random.default_rng(20261124)
maximum = 0.
for order in (4, 6, 8, 10, 12):
    for polarization in ([1, 0], [0, 1], [1, 1j]):
        cluster = miepy.sphere_cluster(position=[[-13, 1, -2], [13, -1, 2]], radius=[10, 12],
            material=miepy.constant_material(eps=gold_permittivity()),
            source=miepy.sources.plane_wave(polarization), wavelength=520., lmax=order,
            medium=miepy.constant_material(index=1.333))
        points = rng.uniform(-45, 45, (80, 3))
        points = points[np.all(np.linalg.norm(points[:, None] - cluster.position[None], axis=-1) > cluster.radius + .05, axis=1)]
        # Exact and near poles, equatorial axes, near-surface and far samples.
        points = np.vstack([points, cluster.position[0] + np.array([
            [0, 0, 10.051], [0, 0, -10.051], [1e-8, 0, 20], [1e-4, 0, -20],
            [0, 20, 0], [-20, 0, 0], [1000, -2000, 3000]])])
        for synthetic in (False, True):
            if synthetic:
                # Exercise every electric/magnetic +/-m coefficient, including
                # modes whose physical scattering coefficient is nearly zero.
                cluster.p_scat = rng.normal(size=cluster.p_scat.shape) + 1j*rng.normal(size=cluster.p_scat.shape)
            expected = cluster.E_field(*points.T, interior=False)
            actual = exterior_electric_field(cluster, points)
            error = np.max(np.linalg.norm(actual - expected, axis=0) / np.maximum(1., np.linalg.norm(expected, axis=0)))
            maximum = max(maximum, float(error))
            assert error < 1e-10, (order, polarization, synthetic, error)
print(f'Maximum normalized complex vector error: {maximum:.3g}')
