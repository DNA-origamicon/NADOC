"""Read-only trajectory selection within one managed temperature-ramp job."""
from fastapi import HTTPException


def thermal_stage_names(job, scope):
    if scope in ('job', 'lineage'):
        return None
    if scope != 'thermal' and not scope.startswith('thermal:'):
        raise HTTPException(422, 'Unknown trajectory scope.')
    if not (job.run_config or {}).get('thermal_ramp'):
        raise HTTPException(422, 'This job is not a thermal ramp.')
    names = {s.name for s in job.stages if s.name.endswith('_thermal')}
    if scope == 'thermal':
        return names
    name = scope.removeprefix('thermal:')
    if name not in names:
        raise HTTPException(422, 'Temperature stage does not belong to this job.')
    return {name}
