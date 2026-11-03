"""The analytic arc bound is the uniform-curvature case of the actual Sweep warning."""
import json
from pathlib import Path
import numpy as np
import pytest
from backend.core.sweep_feasibility import sweep_feasibility
from backend.core.loop_skip_calculator import CELL_BP_DEFAULT, MAX_DELTA_PER_CELL, SQ_SKIP_PERIOD_DEFAULT
from backend.core.constants import BDNA_RISE_PER_BP


def test_browser_constants_follow_native_sweep():
    data = json.loads(Path('frontend/src/design/yggdnasil_limits.json').read_text())
    assert data['cell_bp'] == CELL_BP_DEFAULT
    assert data['max_delta_per_cell'] == MAX_DELTA_PER_CELL
    assert data['square_skip_period'] == SQ_SKIP_PERIOD_DEFAULT
    assert data['rise_nm'] == BDNA_RISE_PER_BP


@pytest.mark.parametrize('fraction,warning', [(0.9, False), (1.1, True)])
def test_analytic_uniform_arc_density_matches_sweep_warning(fraction, warning):
    radius = 40
    angle = 176 * BDNA_RISE_PER_BP / radius
    points = tuple((radius * (1 - np.cos(t)), 0., radius * np.sin(t)) for t in np.linspace(0, angle, 65))
    frames = tuple(tuple(np.array([[np.cos(t), 0., np.sin(t)], [0., 1., 0.], [-np.sin(t), 0., np.cos(t)]]).ravel()) for t in np.linspace(0, angle, 65))
    offset = MAX_DELTA_PER_CELL * radius / CELL_BP_DEFAULT * fraction
    actual = sweep_feasibility(points, None, np.eye(3), np.array([0., 0., 1.]), frames,
                               [np.array([offset, 0., 0.]), np.array([-offset, 0., 0.])],
                               176, np.linspace(0, radius * angle, 65))
    assert (actual['status'] == 'warning') is warning
    assert actual['max_delta_per_cell'] == pytest.approx(MAX_DELTA_PER_CELL * fraction, rel=0.025)
