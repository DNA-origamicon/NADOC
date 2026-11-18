"""Live progress regression: explicit thermal sampling cadence and resumed budgets."""
from dataclasses import replace
import pytest
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_protocol import build_production_stage, expected_energy_lines
from backend.core.oxdna_runner import job_overall_fraction, job_progress
from backend.core.oxdna_thermal_ramp import ThermalRamp, ramp_stages


@pytest.mark.parametrize('banked,rows,expected', [(0,3500,.0875), (1000000000,3500,.5875)])
def test_thermal_progress_respects_energy_cadence_and_restart_bank(tmp_path, banked, rows, expected):
    specs = ramp_stages(build_production_stage(), ThermalRamp())
    assert expected_energy_lines(specs[0]) == 40000
    assert expected_energy_lines(replace(specs[0],steps=1000000000)) == 20000
    job = new_oxdna_job('progress fixture', [s.to_status() for s in specs])
    job.stages[0].status='running'
    job.stages[0].completed_steps=banked
    job.save(tmp_path)
    stage_dir=job.stage_dir(tmp_path, specs[0].name)
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir/'energy.dat').write_text('0 -1 0.3 -0.7\n'*rows)
    progress=job_progress(job,tmp_path,specs)
    assert progress['stage_fraction'] == pytest.approx(expected)
    assert progress['overall'] == pytest.approx(expected/13)
    assert job_overall_fraction(job,tmp_path,specs) == pytest.approx(expected/13)
    assert job.stages[0].status == 'running' and job.current_stage_idx == 0
