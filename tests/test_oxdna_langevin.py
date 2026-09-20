"""Native Langevin accepts exactly one explicit diffusion/friction parameter."""
import pytest
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input


@pytest.mark.parametrize('parameters,key', [({'gamma_trans': 1.13}, 'gamma_trans'),
                                          ({'diff_coeff': 2.5}, 'diff_coeff')])
def test_langevin_renders_one_explicit_bath_parameter(parameters, key):
    stage = OxdnaStageSpec('test', 'production', 'MD', 1, 'CPU',
                           thermostat='langevin', **parameters)
    text = render_stage_input(stage, 'topology.top', 'conf.dat')
    assert f'{key} = {parameters[key]}' in text
    other = 'diff_coeff' if key == 'gamma_trans' else 'gamma_trans'
    assert f'{other} =' not in text


@pytest.mark.parametrize('parameters', [{}, {'gamma_trans': 0}, {'gamma_trans': -1},
    {'gamma_trans': float('nan')}, {'gamma_trans': float('inf')},
    {'gamma_trans': 1, 'diff_coeff': 1}])
def test_langevin_rejects_ambiguous_or_invalid_bath(parameters):
    stage = OxdnaStageSpec('test', 'production', 'MD', 1, 'CPU',
                           thermostat='langevin', **parameters)
    with pytest.raises(ValueError):
        render_stage_input(stage, 'topology.top', 'conf.dat')
