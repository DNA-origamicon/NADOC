import numpy as np
import pytest
from backend.rendering.optix_volumes import decode_volume


def fixture():
    return dict(positions=[np.array(p, dtype='f4') for p in [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]]],
                values=np.array([119, 4, 3, 2], dtype='f4'), palette=np.ones((256, 4), dtype='f4'),
                minimum=3, colorLow=.1, colorHigh=100, weight=.37)


def test_volume_transport_retains_peak_and_validates_transfer():
    spec = fixture()
    points, values, palette = decode_volume(spec)
    assert len(points) == 4 and values[0, 0] == 119 and palette.shape == (256, 4)
    for key, value in [('weight', 2), ('colorLow', 0), ('colorHigh', .01), ('minimum', float('nan'))]:
        with pytest.raises(ValueError):
            decode_volume({**spec, key: value})
    with pytest.raises(ValueError):
        decode_volume({**spec, 'positions': spec['positions'][:3]})


def test_affine_cells_preserve_shear_and_translation():
    from backend.rendering.optix_volume_instances import affine_transforms
    points = [np.array([p]) for p in [(3, 2, 4), (2, 5, 4), (1, 3, 8), (1, 2, 4)]]
    matrix = affine_transforms(points)[0]
    for p, unit in zip(points, [(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (0, 0, 0, 1)]):
        np.testing.assert_allclose((matrix @ unit)[:3], p[0])


def test_procedural_instance_transform_retains_shear_and_reflection():
    from scipy.spatial.transform import Rotation
    from backend.rendering.optix_volume_nodes import instance_transforms
    from backend.rendering.optix_volume_instances import affine_transforms
    rng = np.random.default_rng(14)
    points = [rng.normal(size=(64, 3)) for _ in range(4)]
    before, scales, after, offsets = instance_transforms(points)
    actual = Rotation.from_euler('xyz', after).as_matrix() @ (scales[:, :, None] * Rotation.from_euler('xyz', before).as_matrix())
    expected = affine_transforms(points)
    np.testing.assert_allclose(actual, expected[:, :3, :3], atol=1e-12)
    np.testing.assert_allclose(offsets, expected[:, :3, 3])
