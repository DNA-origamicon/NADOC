from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend.core.oxdna_thermal_scope import thermal_stage_names


def test_thermal_scope_is_bound_to_actual_job_stages():
    job=SimpleNamespace(run_config={'thermal_ramp':{}}, stages=[SimpleNamespace(name='1_thermal'),SimpleNamespace(name='2_thermal')])
    job.run_config['thermal_ramp']={'start_c':25}
    assert thermal_stage_names(job,'thermal')=={'1_thermal','2_thermal'}
    assert thermal_stage_names(job,'thermal:2_thermal')=={'2_thermal'}
    assert thermal_stage_names(job,'job') is None
    for scope in ('thermal:3_thermal','thermal:../../other','bad'):
        with pytest.raises(HTTPException): thermal_stage_names(job,scope)
    job.run_config={}
    with pytest.raises(HTTPException): thermal_stage_names(job,'thermal')
