"""Summarize replay logs and independently compute the wall restraint energy."""
import json
from pathlib import Path
import numpy as np
from MDAnalysis.coordinates.DCD import DCDReader
HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1] / 'workspace/md_jobs/7aa73d7afe93/package/small_plate_namd_solvated'
summary = {}
for folder in HERE.iterdir():
    log = folder / 'run.log'
    if not log.is_file():
        continue
    text = log.read_text()
    rows = [list(map(float, line.split()[1:])) for line in text.splitlines() if line.startswith('ENERGY:')]
    if not rows:
        continue
    e = np.array(rows)
    summary[folder.name] = {'last_energy_step': int(e[-1, 0]), 'completed': 'End of program' in text and 'FATAL ERROR' not in text, 'boundary_min_max': [float(e[:, 7].min()), float(e[:, 7].max())], 'temperature_min_max': [float(e[:, 11].min()), float(e[:, 11].max())], 'volume_min_max': [float(e[:, 17].min()), float(e[:, 17].max())], 'fatal': next((l for l in text.splitlines() if l.startswith('FATAL ERROR:')), None)}
    np.savetxt(folder / 'energies.csv',e,delimiter=',',header='TS,BOND,ANGLE,DIHED,IMPRP,ELECT,VDW,BOUNDARY,MISC,KINETIC,TOTAL,TEMP,POTENTIAL,TOTALAVG,TEMPAVG,PRESSURE,GPRESSURE,VOLUME,PRESSAVG,GPRESSAVG')
reference=[]
indices=[]
for line in (PACKAGE/'small_plate.pdb').read_text().splitlines():
    if line.startswith(('ATOM','HETATM')):
        if line[17:21].strip()=='GRP':indices.append(len(reference))
        reference.append([float(line[30:38]),float(line[38:46]),float(line[46:54])])
reference=np.array(reference);indices=np.array(indices)
frames=[]
with DCDReader(str(HERE/'trace/replay.dcd')) as trajectory:
    for ts in trajectory:
        delta=ts.positions[indices].astype(float)-reference[indices]
        box=ts.dimensions[:3]
        delta-=np.rint(delta/box)*box
        energy=float(50*np.square(delta).sum())
        frames.append({'step':ts.frame+1,'graphene_restraint_kcal':energy,'graphene_rms_reference_A':float(np.sqrt(np.square(delta).sum(axis=1).mean()))})
summary['independent_trace_graphene']=frames
(HERE/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
