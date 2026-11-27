import numpy as np
import pytest
from types import SimpleNamespace
from backend.rendering.optix_emitters import expand_cloud, cloud_update_kind, cloud_emission, cloud_illumination
from backend.rendering.optix_sampling import configure_sampling, configure_emission


def cloud():
    return dict(centers=np.array([[1., 2., 3.], [4., 5., 6.]]), radii=np.array([.1, .2]),
                colors=np.array([[1., 0., 0.], [0., 0., 1.]], dtype=np.float32), opacity=.24,
                template=dict(position=np.tile([1., 0., 0.], (60, 1)), normal=np.tile([1., 0., 0.], (60, 1))))


def test_expansion_preserves_centers_radius_palette_and_opacity():
    spec = expand_cloud(cloud())
    np.testing.assert_array_equal(spec['position'][[0, 60]], np.array([[1.1, 2, 3], [4.2, 5, 6]], dtype=np.float32))
    np.testing.assert_array_equal(spec['emission'][[0, 60]], [[1, 0, 0, 1], [0, 0, 1, 1]])
    assert len(spec['index']) == 120
    assert spec['materials'][0]['opacity'] == .24


@pytest.mark.parametrize('key,value', [('radii', np.array([-1., 2.])), ('colors', np.array([[np.nan, 0, 0], [1, 1, 1]])), ('opacity', 2)])
def test_invalid_cloud_rejects(key, value):
    with pytest.raises(ValueError):
        expand_cloud({**cloud(), key: value})


def test_sampling_capabilities_and_explicit_emission_on_old_and_new_cycles():
    for supported in (False, True):
        cycles = SimpleNamespace(**({'use_light_tree': False} if supported else {}))
        result = configure_sampling(SimpleNamespace(cycles=cycles), 'test')
        assert result['light_tree_enabled'] is supported
        mat = SimpleNamespace(cycles=SimpleNamespace(**({'emission_sampling': 'AUTO'} if supported else {'use_multiple_importance_sampling': False})))
        configure_emission(mat)
        assert (mat.cycles.emission_sampling == 'FRONT_BACK') if supported else mat.cycles.use_multiple_importance_sampling


def test_updates_distinguish_shading_from_geometry_and_validate_attributes():
    prior = dict(centers='centers', radii='radii', template={}, colors='red', opacity=.2)
    assert cloud_update_kind(prior, None) == 'geometry'
    assert cloud_update_kind(dict(prior), prior) == 'unchanged'
    assert cloud_update_kind({**prior, 'colors': 'blue'}, prior) == 'attributes'
    assert cloud_update_kind({**prior, 'opacity': .8}, prior) == 'attributes'
    assert cloud_update_kind({**prior, 'centers': 'moved'}, prior) == 'geometry'
    emission, opacity = cloud_emission(cloud())
    np.testing.assert_array_equal(emission, expand_cloud(cloud())['emission'])
    assert opacity == .24
    with pytest.raises(ValueError):
        cloud_emission({**cloud(), 'opacity': float('nan')})


def test_illumination_preserves_power_across_marker_radius_without_changing_visible_emission():
    value = cloud()
    value['template']['position'] = np.tile([[1., 0, 0], [0, 1., 0], [0, 0, 1.]], (20, 1))
    value['power'] = np.array([[.2, .1, 0], [0, .1, .2]], dtype=np.float32)
    small = expand_cloud(value)
    large = expand_cloud({**value, 'radii': value['radii'] * 2})
    np.testing.assert_array_equal(small['emission'], large['emission'])
    np.testing.assert_allclose(small['illumination'][:, :3], large['illumination'][:, :3] * 4)
    assert small['materials'][0]['normalized_em']
    assert cloud_illumination(cloud()) is None
