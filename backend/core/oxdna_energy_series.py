"""Read-only energy snapshots for the oxDNA metrics card (including active jobs)."""
from backend.core.oxdna_thermal_metrics import energy_history
from backend.core.oxdna_temperature_markers import input_temperature_c


def energy_series(jobs, workspace, scope='latest'):
    values, times, temperatures, stages, job_ids, boundaries = [], [], [], [], [], []
    offset = 0.0
    for job in jobs:
        for stage in job.stages:
            if stage.kind not in ('production', 'field'):
                continue
            directory = job.stage_dir(workspace, stage.name)
            history = energy_history(directory, complete_lines_only=True)
            points = history['points']
            if not points:
                continue
            temperature = input_temperature_c(directory)
            boundaries.append({'start_x': offset, 'start_sample': len(values),
                               'temperature_c': temperature, 'stage': stage.name,
                               'job_id': job.job_id})
            for point in points:
                times.append(offset + point[0])
                values.append(point[1])
                temperatures.append(temperature)
                stages.append(stage.name)
                job_ids.append(job.job_id)
            offset += max(point[0] for point in points)
    return {'ready': bool(values), 'scope': scope,
            'reason': '' if values else 'No production energy samples recorded yet.',
            'jobs': list(dict.fromkeys(job_ids)),
            'oxdna_energy': {'temporal': {'per_frame': values, 'x_values': times,
                'temperature_c': temperatures, 'stage_names': stages, 'job_ids': job_ids,
                'boundaries': boundaries}}}
