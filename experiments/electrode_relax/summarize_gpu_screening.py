"""Summarize native completion and timestep diagnostics from preserved evidence."""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from backend.core.namd_peg_evidence import read_energy_logs
from backend.core.namd_electrode_gpu import validate_package


def main():
    ap=argparse.ArgumentParser();ap.add_argument('campaign',type=Path);a=ap.parse_args();out=a.campaign
    jobs=json.loads((out/'jobs.json').read_text());native=[];energies={}
    binary=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')
    for job in jobs:
        if not job.get('status'):continue
        pkg=Path(job['package']);m=json.loads((pkg/'manifest.json').read_text());spec=m['segments'][0]
        validate_package(pkg,binary,'0')
        epochs,texts=read_energy_logs([pkg/f"{job['segment']}.log"]);values=list(epochs[0].values());energies[job['job_id']]=epochs[0]
        assert 'End of program' in texts[0] and values[-1]['TS']==spec['steps']
        timings=[float(x) for x in re.findall(r'TIMING:.*?Wall:.*?, ([\d.e+-]+)/step',texts[0])]
        median=float(np.median(timings[len(timings)//2:]))
        temperatures=[r['TEMP'] for r in values if r['TS']>0]
        native.append(dict(job_id=job['job_id'],series=job['series'],dt_fs=job['timestep_fs'],duration_ns=job['duration_ns'],
            normal_exit=True,finite_energy_records=len(values),temperature_mean_K=float(np.mean(temperatures)),
            temperature_range_K=[min(temperatures),max(temperatures)],ms_per_step=median*1000,
            ns_per_day=job['timestep_fs']*.0864/median,native_wall_seconds=job.get('native_wall_seconds'),
            health_passed=job['health']['passed'],density_nm3=job['health']['bulk_water_density_nm3'],
            profile_drift=job['health']['profile_drift'],gpu_provenance_validated=True))
    mode_rows=[json.loads(line) for line in (out/'water_modes.jsonl').read_text().splitlines()]
    errors=[];mode_summary={}
    for row in mode_rows:
        energy=energies.get(row['job_id'],{}).get(row['step'])
        if energy:errors.append(abs(row['total_kinetic_kcal_mol']/energy['KINETIC']-1))
    for dt in (2,4):
        rows=[r for r in mode_rows if r['timestep_fs']==dt and r['series']!='pilot' and r['time_ns']>.24]
        if not rows:continue
        mode_summary[str(dt)]=dict(snapshots=len(rows),translational_K=float(np.mean([r['translational_K'] for r in rows])),
            rotational_K=float(np.mean([r['rotational_K'] for r in rows])),
            translation_minus_rotation_K=float(np.mean([r['translational_K']-r['rotational_K'] for r in rows])),
            note='COM/relative kinetic temperature diagnostic from complete restart snapshots, not a dielectric measurement.')
    result=dict(native=native,water_modes=mode_summary,velocity_energy_audit=dict(samples=len(errors),max_relative_error=max(errors) if errors else None))
    (out/'native_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
