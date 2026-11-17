"""Temperature metadata is read-only; these tests launch no native simulations."""
import pytest
from backend.core.oxdna_temperature_markers import input_temperature_c, temperature_markers


@pytest.mark.parametrize('value, expected', [('298.15K',25), ('25C',25), ('0.1',26.85), ('-5c',-5), ('bad',None), ('0K',None)])
def test_recorded_input_temperature(tmp_path, value, expected):
    (tmp_path/'input.txt').write_text(f'# T = 999K\nT = {value} # setpoint\n')
    assert input_temperature_c(tmp_path) == expected


def test_missing_input_is_not_a_guessed_temperature(tmp_path):
    assert input_temperature_c(tmp_path) is None


def test_first_physical_frame_and_subsequent_stage_ranges():
    stages = [dict(name='seeded',kind='equil',n_frames=3,temperature_c=25,temperature_start=1),
              dict(name='hot',kind='production',n_frames=4,temperature_c=35)]
    markers = [dict(frame=3,label='run 2',kind='production')]
    result = temperature_markers(stages,markers)
    assert [(m['frame'],m['end_frame'],m['temperature_c']) for m in result] == [(1,2,25),(3,6,35)]
    assert result[1]['label'] == 'run 2'
    assert 'temperature_c' not in markers[0]
    assert temperature_markers([dict(stages[0],n_frames=1)],[]) == []


def test_resumed_frames_keep_their_own_temperature(tmp_path):
    from backend.core.oxdna_runner import _archive_partial_outputs
    from backend.core.oxdna_temperature_markers import trajectory_temperature_c
    (tmp_path/'input.txt').write_text('T = 298.15K\n')
    (tmp_path/'trajectory.dat').write_text('t = 0\n')
    _archive_partial_outputs(tmp_path)
    (tmp_path/'input.txt').write_text('T = 308.15K\n')
    assert trajectory_temperature_c(tmp_path/'trajectory.r1.dat') == 25
    assert trajectory_temperature_c(tmp_path/'trajectory.dat') == 35
    assert trajectory_temperature_c(tmp_path/'trajectory.r2.dat') is None
