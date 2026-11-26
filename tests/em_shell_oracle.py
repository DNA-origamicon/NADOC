"""Run in isolated MiePy interpreter: independent coefficients and interface tests."""
import miepy
import numpy as np
from backend.physics.em_analysis import gold_permittivity
from backend.physics.em_shell import coefficients, apply_shell, coated_field
from backend.physics.em_field_evaluator import exterior_electric_field

metal = miepy.constant_material(eps=gold_permittivity())
water = miepy.constant_material(index=1.333)
for index in (1.333, 1.45, 1.7):
    response = coefficients(10, 12, np.sqrt(gold_permittivity()), index, 1.333, 520, 12)
    oracle = miepy.single_mie_core_shell(10, 12, metal, miepy.constant_material(index=index), 520, 12, medium=water)
    a, b = oracle.solve()
    np.testing.assert_allclose(response[:, :, 0], np.array([a[0], b[0]]), rtol=1e-9, atol=1e-15)
    cluster = miepy.sphere_cluster(position=[[0, 0, 0]], radius=[10], material=metal,
        source=miepy.sources.plane_wave([1, 0]), wavelength=520, lmax=12, medium=water)
    points = np.array([[10.5, 0, 0], [0, 0, 11], [3, 10.5, 1], [0, 0, -11.9], [20, 2, 3]])
    bare = exterior_electric_field(cluster, points)
    apply_shell(cluster, [2], index)
    coated = coated_field(cluster, points, [2], index, exterior_electric_field)
    if index == 1.333:
        np.testing.assert_allclose(coated, bare, rtol=1e-9, atol=1e-10)
    # Tangential E and normal D continuity at outer dielectric interface.
    inside = coated_field(cluster, [[12-1e-7, 0, 0]], [2], index, exterior_electric_field)[:, 0]
    outside = coated_field(cluster, [[12+1e-7, 0, 0]], [2], index, exterior_electric_field)[:, 0]
    np.testing.assert_allclose(inside[1:], outside[1:], rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(index**2*inside[0], 1.333**2*outside[0], rtol=1e-5, atol=1e-6)
print('Coated coefficients, transparent-shell limit, and dielectric boundary continuity passed.')
