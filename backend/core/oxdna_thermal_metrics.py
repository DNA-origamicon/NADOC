"""Persist complete per-temperature energy histories and display-ready fitted curves."""
import hashlib
import json
import math
import time
from pathlib import Path


CURVE_FILE = 'thermal_energy_curve.json'


def energy_history(directory, *, complete_lines_only=False):
    directory=Path(directory)
    paths=sorted(directory.glob('energy.r*.dat'),key=lambda p:int(p.stem.split('.r')[-1]))
    paths.append(directory/'energy.dat')
    attempts={}
    for p in directory.glob('thermal_attempt_*_retry*.json'):
        record=json.loads(p.read_text());attempts[record['seed']]=record
    points=[]; sources=[]; invalid=[]; offset=0.; last=None; fit_times=[]; fit_energy_values=[]
    for index,path in enumerate(paths):
        if not path.exists():
            continue
        try:
            raw=path.read_bytes()
        except FileNotFoundError:
            continue  # A live runner may rotate an output between listing and reading.
        settings={}
        input_path=path.with_name(path.name.replace('energy','input').replace('.dat','.txt'))
        if input_path.exists():
            settings={k.strip():v.strip() for line in input_path.read_text().splitlines()
                      if '=' in line and not line.lstrip().startswith('#') for k,v in [line.split('=',1)]}
        attempt=attempts.get(int(settings.get('seed','-1')))
        known=attempt is not None and 'dt' in settings
        if known:
            offset=attempt['banked_steps']*float(settings['dt'])
        sources.append({'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),
                        'time_offset':offset,'offset_source':'attempt_receipt' if known else 'previous_segment_end'})
        segment_end=offset
        readable = raw if not complete_lines_only or raw.endswith(b'\n') else raw.rpartition(b'\n')[0]
        for lineno,line in enumerate(readable.decode(errors='replace').splitlines(),1):
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            try:
                values=line.split();local=float(values[0]);energy=float(values[1])
                if not math.isfinite(local) or not math.isfinite(energy) or local<0:
                    raise ValueError('nonfinite energy or invalid time')
            except (ValueError,IndexError):
                invalid.append({'file':path.name,'line':lineno,'text':line})
                continue
            current=offset+local
            extra=[]
            for column in (2,3):
                value=None
                if len(values)>column:
                    try:
                        value=float(values[column])
                        if not math.isfinite(value):
                            raise ValueError('nonfinite auxiliary energy')
                    except ValueError:
                        invalid.append({'file':path.name,'line':lineno,'text':line,'reason':'invalid auxiliary energy'})
                        value=None
                extra.append(value)
            points.append([current,energy,index,local,*extra])
            # Keep repeated boundary samples in the stored curve, but do not give
            # a resumed checkpoint extra weight in the fit.
            if last is None or current>last:
                fit_times.append(current);fit_energy_values.append(energy);last=current
            elif current<last:
                invalid.append({'file':path.name,'line':lineno,'text':line,'reason':'time moved backwards'})
            segment_end=max(segment_end,current)
        offset=segment_end
    return {'columns':['time','potential_energy_per_particle','segment','segment_time','kinetic_energy_per_particle','total_energy_per_particle'],
            'points':points,'sources':sources,'invalid_records':invalid,
            'fit_times':fit_times,'fit_energies':fit_energy_values}


def energy_metrics(directory, cfg, *, evaluated_steps=None, persist=True):
    # Explicit offline analysis only; simulation progression never calls this.
    from backend.core.oxdna_energy_fit import fit_energy, fitted_values
    curve=energy_history(directory)
    fit=fit_energy(curve['fit_times'],curve['fit_energies'],cfg.energy_tolerance,cfg.min_effective_samples)
    if curve['invalid_records']:
        fit.update(passed=False,reason='invalid records in complete energy history')
    fit.update(curve_file=CURVE_FILE,raw_samples=len(curve['points']),invalid_records=len(curve['invalid_records']))
    curve.update(schema='nadoc.thermal-energy-curve.v1',computed_at=time.time(),
                 time_units='oxDNA_time', energy_units='oxDNA_energy_per_particle',
                 evaluated_steps=evaluated_steps,fit=fit,
                 fitted_energy=fitted_values(curve['fit_times'],fit))
    if persist:
        target=Path(directory)/CURVE_FILE;temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(curve,indent=2,allow_nan=False)+'\n');temporary.replace(target)
    return fit,curve


def energy_observations(directory, *, evaluated_steps=None):
    """Persist all observations and descriptive statistics, without fitting a model."""
    import statistics
    curve = energy_history(directory)
    values = [point[1] for point in curve['points']]
    summary = {'status': 'recorded' if values else 'no_samples', 'samples': len(values),
               'invalid_records': len(curve['invalid_records'])}
    if values:
        summary.update(mean=statistics.fmean(values), minimum=min(values), maximum=max(values),
                       standard_deviation=statistics.pstdev(values))
    curve.update(schema='nadoc.thermal-energy-observations.v1', computed_at=time.time(),
                 time_units='oxDNA_time', energy_units='oxDNA_energy_per_particle',
                 evaluated_steps=evaluated_steps, summary=summary, fit=None, fitted_energy=[])
    target = Path(directory) / CURVE_FILE
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(curve, indent=2, allow_nan=False) + '\n')
    temporary.replace(target)
    return summary, curve


def read_metrics(job,workspace):
    """Read-only API: expose persisted fits, including original gate decisions.

    Older jobs retain raw energies but have no saved full-history fit. Report that
    explicitly rather than retroactively replacing their historical verdicts.
    """
    directory=job.job_dir(workspace);stages=[]
    for stage in job.stages:
        d=directory/stage.name
        report=(job.run_config or {}).get('thermal_progress',{}).get(stage.name)
        if report is None:
            continue
        curve=d/CURVE_FILE
        stages.append({'stage':stage.name,'temperature':report['temperature'],'decision':report,
                       'energy_curve':json.loads(curve.read_text()) if curve.exists() else None,
                       'energy_curve_status':'available' if curve.exists() else 'not_computed_by_this_version'})
    return {'job_id':job.job_id,'stages':stages}
