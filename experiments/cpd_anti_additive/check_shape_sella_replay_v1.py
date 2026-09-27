"""Exercise complete and interrupted Sella prefixes using saved energies only."""
from pathlib import Path
import os,sys,time,resource
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
import numpy as np
from ase.io import read as read_atoms
from openmm import app
from experiments.cpd_anti_additive.sella_cached_mm_replay_v1 import relax_point
from experiments.cpd_anti_additive.shape_fit_protocol_v2 import require_fit_ready
from experiments.cpd_anti_additive.shape_fit_v2 import OUT,parameters
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now

_,plan=require_fit_ready();points=read(checked(plan['points']));model=OUT/'model-034'
dest=REPO/'.development-artifacts/cpd-anti-shape-recovery-preparation-v1b';dest.mkdir(exist_ok=True)
par=parameters(model/'candidate.prm');rows=[]
for index in (0,16):
    point=points[index];folder=model/point['case_id'];frames=read_atoms(folder/'sella.traj',index=':')
    psf=app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{point['endpoint']}"/'fragment.psf'))
    system=psf.createSystem(par,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
    out=dest/('complete_prefix' if index==0 else 'interrupted_prefix')
    result,x=relax_point(out,point,system,plan,time.monotonic()+120,replay_frames=frames,replay_only=True)
    assert result['new_evaluations']==0 and result['cached_evaluations']==len(frames)
    if index==0:
        old=read(folder/'assessment.json')
        assert result['independent_stationarity_and_chemistry_passed']
        assert np.max(abs(x-np.loadtxt(checked(old['final_geometry']))))<1e-9
        assert abs(result['energy_kcal']-old['energy_kcal'])<1e-8
    else:
        assert (out/'replay_boundary.json').exists() and not result['independent_stationarity_and_chemistry_passed']
        assert 'replay-only boundary' in result['error']
    rows.append(dict(case_id=point['case_id'],saved_trajectory=source(folder/'sella.traj'),review=source(out/'assessment.json'),
        cached_evaluations=len(frames),new_evaluations=0))
save(dest/'sella_replay_verified.json',dict(at=now(),verifier=source(Path(__file__)),helper=source(Path(__file__).with_name('sella_cached_mm_replay_v1.py')),
    cases=rows,peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    complete_case_reproduced=True,interrupted_eight_step_prefix_reproduced=True,no_new_energy_or_fit=True,minimum_certified=False))
print(dict(cases=rows,peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
