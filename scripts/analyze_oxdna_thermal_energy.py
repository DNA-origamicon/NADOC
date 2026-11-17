"""Backfill full energy curves/fits without changing historical simulation verdicts."""
import argparse
import json
from pathlib import Path

from backend.core.oxdna_thermal_ramp import ThermalRamp
from backend.core.oxdna_thermal_metrics import energy_metrics


def analyze(directory):
    directory=Path(directory)
    job=json.loads((directory/'job.json').read_text())
    if job['status'] in {'running','queued'}:
        raise ValueError('Analyze an idle job; running workers own their metric artifacts.')
    specs=json.loads((directory/'stages_spec.json').read_text());results=[]
    for spec in specs:
        if not spec.get('thermal_ramp') or not (directory/spec['name']/'energy.dat').exists():
            continue
        complete=next(s for s in job['stages'] if s['name']==spec['name'])['status']=='done'
        fit,_=energy_metrics(directory/spec['name'],ThermalRamp.model_validate(spec['thermal_ramp']),evaluated_steps=spec['steps'] if complete else None)
        results.append({'stage':spec['name'],'temperature':spec['temperature'],'fit':fit})
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    print(json.dumps(analyze(parser.parse_args().directory),indent=2))
