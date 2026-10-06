"""Read completed native evidence only; write a physical-ensemble review report."""
import json, os, sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.gpu_longbox_startup_v3 import ROOT, dimensions, read_binary, parse_log
from experiments.cpd_anti_additive.validation_gate import read,source
from experiments.cpd_anti_additive.sella_pilot import now

def run(output):
 box,n,nw=dimensions(); records=[]
 cases=[('anti',1,4,None),('anti',3,3,[46.,40.,12.]),('anti',3,4,None),('control',1,1,[62.,14.,36.]),('control',1,2,None),('control',2,4,None)]
 for case,rep,seg,witness in cases:
  p=ROOT/case/f'replica-{rep}/validation/segment-{seg:02d}'
  assert read(p/'native_exit.json')['returncode']==0
  rows=parse_log(p/'run.log');first=rows[0]['TS'];sample=[r for r in rows if r['TS']>first]
  assert len(sample)==100
  end=read_binary(p/'result.coor',n);assert np.array_equal(end,read_binary(p/'result.restart.coor',n))
  ref=parse_log(p/'endpoint-reference/run.log');de=abs(ref[-1]['POTENTIAL']-rows[-1]['POTENTIAL'])
  r=dict(case=case,replica=rep,segment=seg,samples=len(sample),first_step=first,last_step=rows[-1]['TS'],mean_temperature_K=float(np.mean([v['TEMP'] for v in sample])),mean_pressure_bar=float(np.mean([v['PRESSURE'] for v in sample])),mean_group_pressure_bar=float(np.mean([v['GPRESSURE'] for v in sample])),mean_interval_group_pressure_bar=float(np.mean([v['GPRESSAVG'] for v in sample])),endpoint_reference_error_kcal=de,endpoint_reference_limit_kcal=max(.01,1e-6*abs(rows[-1]['POTENTIAL'])),checkpoint_coordinates_identical=True,inputs=[source(p/f) for f in ['run.log','run.conf','result.coor','result.restart.coor','native_exit.json','endpoint-reference/run.log']])
  if witness is not None:
   distance,index=cKDTree(end%box,boxsize=box).query(witness)
   r.update(void_witness_A=witness,nearest_any_atom_A=float(distance),nearest_atom_index=int(index))
   assert distance>15,'Expected independently identified cavity absent'
  records.append(r)
 result=dict(at=now(),source=source(Path(__file__)),box_A=box.tolist(),records=records,interpretation='Large atom-free pockets and sustained negative pressures: current fixed-volume preparation does not qualify ambient aqueous production. Endpoint replay passes, so this evidence is not explained by the earlier saved-state corruption. Cause still needs diagnosis; no inference that CPD parameters themselves are wrong.',scope='Targeted read-only review of completed segments, not all-frame cavity audit or new numerical acceptance threshold.',simulation_ready=False,minimum_certified=False)
 Path(output).write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps([dict(case=r['case'],replica=r['replica'],segment=r['segment'],mean_group_pressure_bar=r['mean_group_pressure_bar'],nearest_any_atom_A=r.get('nearest_any_atom_A')) for r in records]))
if __name__=='__main__':run(sys.argv[1])
