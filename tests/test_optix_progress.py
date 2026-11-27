"""Native status reflects Cycles samples, with no clock-derived estimates."""
import pytest
from backend.rendering.optix_progress import render_progress


@pytest.mark.parametrize('line', ['Fra:1 | Rendering 32 / 64 samples', 'Fra:1 | Sample 32/64'])
def test_measured_native_samples(line):
    assert render_progress(line) == {'stage': 'tracing', 'samples': 32, 'target': 64,
                                     'fraction': .5, 'label': 'OptiX · 32/64 samples'}


def test_preparation_has_no_invented_denominator():
    assert render_progress('NADOC_STAGE Building OptiX acceleration structures')['fraction'] is None
    assert render_progress('Fra:1 | Time:00:30.00 | Remaining:00:15.00') is None
    assert render_progress('Sample 1/0') is None


def test_structured_geometry_progress_and_unmeasurable_driver_work():
    assert render_progress('NADOC_PROGRESS {"stage":"geometry","label":"Mesh 2/4","fraction":0.5}') == {
        'stage': 'geometry', 'label': 'Mesh 2/4', 'fraction': .5}
    assert render_progress('NADOC_PROGRESS {"stage":"acceleration","label":"Building tree","fraction":null}')['fraction'] is None


@pytest.mark.parametrize('payload', ['{}', 'null', '{bad', '{"stage":"geometry","label":"bad","fraction":2}',
                                   '{"stage":"geometry","label":"bad","fraction":NaN}'])
def test_malformed_worker_progress_is_ignored(payload):
    assert render_progress('NADOC_PROGRESS ' + payload) is None
