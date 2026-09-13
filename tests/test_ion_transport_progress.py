import asyncio
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from backend.api import routes_md
from backend.core import ion_transport_progress as progress


def test_progress_is_scoped_to_request_and_retains_failed_stage():
    progress.start('job', 'old')
    progress.start('job', 'new')
    progress.update('job', 'old', 'topology')
    progress.update('job', 'new', 'frames', 5, 10)
    progress.finish('job', 'old', 'Unreadable topology')
    assert progress.snapshot('job', 'old')['stages'][0]['state'] == 'error'
    current = progress.snapshot('job', 'new')
    assert current['state'] == 'running'
    assert current['stages'][0]['done'] == 5
    current['stages'][0]['done'] = 999
    assert progress.snapshot('job', 'new')['stages'][0]['done'] == 5


@pytest.mark.parametrize('fail', [False, True])
def test_route_reports_completion_or_error(monkeypatch, fail):
    monkeypatch.setattr(routes_md, '_load_job', lambda _: object())

    def analyze(job, report):
        report('topology', 0, 0)
        if fail:
            raise ValueError('Broken PSF')
        report('topology', 1, 1)
        return {'frames': 3}

    monkeypatch.setattr(routes_md, '_analyze_ion_transport_package', analyze)
    if fail:
        with pytest.raises(ValueError, match='Broken PSF'):
            asyncio.run(routes_md.analyze_headless_ion_transport('test', 'request'))
    else:
        assert asyncio.run(routes_md.analyze_headless_ion_transport('test', 'request')) == {'frames': 3}
    state = routes_md.ion_transport_analysis_progress('test', 'request')
    assert state['state'] == ('error' if fail else 'done')


def test_analysis_reports_each_frame_and_finalization(tmp_path, monkeypatch):
    meta = {'direction': [0, 0, 1], 'voltage_mV': 100, 'current_estimator': 'test',
            'plane_point_nm': [0, 0, 0], 'pore_center_nm': [0, 0, 0], 'pore_diameter_nm': 2}
    (tmp_path / 'manifest.json').write_text(json.dumps({'ion_transport': meta, 'name_stem': 'test'}))
    positions = [np.array([[0., 0., z]]) for z in [-1., 1., 2.]]

    class Trajectory:
        def __len__(self):
            return 3

        def __iter__(self):
            for frame in range(3):
                universe.frame = frame
                yield SimpleNamespace(time=float(frame), dimensions=[100., 100., 100., 90., 90., 90.])

    class Group:
        def __len__(self):
            return 1

        @property
        def positions(self):
            return positions[universe.frame]

    universe = SimpleNamespace(trajectory=Trajectory(), frame=0,
                               select_atoms=lambda query: Group() if query == 'resname SOD' else [])
    monkeypatch.setitem(sys.modules, 'MDAnalysis', SimpleNamespace(Universe=lambda *a: universe))
    monkeypatch.setattr(routes_md, '_md_segment_dcds', lambda _: [('p', 'p', tmp_path / 'test.dcd')])
    job = SimpleNamespace(job_id='sample', package_dir=lambda _: tmp_path)
    updates = []
    result = routes_md._analyze_ion_transport_package(job, lambda *args: updates.append(args))
    assert result['frames'] == 3
    assert result['species']['Na+']['crossings_positive'] == 1
    for stage in ['frames', 'current', 'crossings', 'occupancy']:
        assert [u[1] for u in updates if u[0] == stage] == [0, 1, 2, 3]
    for stage in ['validate', 'inventory', 'topology', 'select', 'statistics', 'save']:
        final = [u for u in updates if u[0] == stage][-1]
        assert final[1] == final[2] > 0
    assert (tmp_path / 'ion_transport_analysis.json').exists()
