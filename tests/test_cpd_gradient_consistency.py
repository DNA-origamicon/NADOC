"""Assessment regression: flattened checkpoints and configurable finite steps."""
import json
import numpy as np
import pytest
from experiments.cpd_anti_additive.gradient_consistency import assess
from experiments.cpd_anti_additive.core_baseline import source


def test_quadratic_derivative_with_flat_reference_and_reuse(tmp_path):
    q=np.zeros(147);q[0]=1
    g=2*q
    data=tmp_path/'input.json';data.write_text('{}')
    native=tmp_path/'output.dat';native.write_text('synthetic fixture')
    cases=[]
    for name,h in [('reference',0),('plus-full',.02),('minus-full',-.02),('plus-half',.01),('minus-half',-.01)]:
        folder=tmp_path/name;folder.mkdir()
        result=dict(energy=2*h+1.5*h*h,gradient=((2+3*h)*q).reshape(49,3).tolist(),input=source(data),native=source(native))
        (folder/'result.json').write_text(json.dumps(result))
        if name!='reference':cases.append(dict(label=name))
    plan=dict(cases=cases,reuse_reference=source(tmp_path/'reference/result.json'),sources=[],direction=q.tolist(),reference_gradient=g.tolist(),reference_energy=0,finite_steps=[.02,.01],scope='test')
    (tmp_path/'plan.json').write_text(json.dumps(plan));assess(tmp_path)
    a=json.loads((tmp_path/'assessment.json').read_text())
    assert a['reference_gradient_max_difference']==0
    assert a['analytic_directional_derivative']==2
    for fd in a['finite_differences']:
        assert fd['energy_derivative']==pytest.approx(2)
        assert fd['gradient_curvature']==pytest.approx(3)
    assert not a['minimum_certified']
