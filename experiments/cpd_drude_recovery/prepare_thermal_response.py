"""Freeze signed point-charge response probes at two thermal failure geometries."""
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded,checked,source,write
from experiments.cpd_drude_recovery.run_fresh_esp import read_result

root=Path('.development-artifacts/cpd-thermal-response-v2').resolve()
root.mkdir(exist_ok=False)
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
frozen=recovery/'corrected_parameters.training_frozen.json'
physical=AdiabaticNonbonded(recovery,frozen)
m=physical.model
bohr=.529177210903
cases=[]
sources=[]

def predict(xyz,grid,charge,position):
    m.base_positions[m.external_index]=position/10
    m.set_external_charge(charge)
    error=None
    try:physical.energy_gradient(xyz)
    except ValueError as exc:error=str(exc)
    state=m.context.getState(getPositions=True,getForces=True)
    pos=np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    force=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    assert abs(force[m.drude_indices]).max()<1e-4
    q=np.array([m.nonbonded.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in range(m.external_index)])
    solute=pos[:m.external_index]
    esp=bohr*(1/np.linalg.norm(grid[:,None,:]-solute[None,:,:],axis=2))@q
    dip=(q[:,None]*solute).sum(axis=0)/bohr
    disp=float(np.linalg.norm(pos[m.drude_indices]-xyz[:20],axis=1).max())
    return esp,dip,disp,error

for geometry,label in [('cpd-thermal-conformer-qm-v1','thermal1'),('cpd-both-thermal-conformer-qm-v1','thermal2')]:
    origin=Path('.development-artifacts')/geometry
    baseline_plan=json.loads((origin/'plan.json').read_text())
    for item in baseline_plan['sources']:
        if Path(item['path']).name=='prepare_thermal_qm.py' and (origin/'original_preparation_snapshot.py').exists():
            historical={'path':str((origin/'original_preparation_snapshot.py').resolve()),'sha256':item['sha256']}
            checked(historical)
            sources.append(historical)
        else:
            checked(item)
    read_result(origin)
    xyz=np.loadtxt(origin/'nuclear_coordinates_angstrom.txt')
    grid=np.loadtxt(origin/'grid.dat')
    zero_esp,zero_dip,_,_=predict(xyz,grid,0,np.array([100.,100.,100.]))
    sources.extend(source(origin/f) for f in ('plan.json','assessment.json','input.dat','output.dat','grid.dat','grid_esp.dat','nuclear_coordinates_angstrom.txt'))
    for endpoint in (1,2):
        oxygen=physical.d.ATOM_NAMES.index(f'{endpoint}:O2')
        carbon=physical.d.ATOM_NAMES.index(f'{endpoint}:C2')
        direction=xyz[oxygen]-xyz[carbon]
        position=xyz[oxygen]+(2.2*1.52)*direction/np.linalg.norm(direction)
        nearest=float(np.linalg.norm(xyz-position,axis=1).min())
        assert nearest>2.0
        for sign in (-1,1):
            name=f'{label}_endpoint{endpoint}_{"minus" if sign<0 else "plus"}'
            folder=root/name;folder.mkdir();(folder/'scratch').mkdir()
            charge=sign*.5
            esp,dip,disp,error=predict(xyz,grid,charge,position)
            np.savetxt(folder/'model_delta_esp_au.txt',esp-zero_esp,fmt='%.14e')
            shutil.copy2(origin/'grid.dat',folder/'grid.dat')
            text=(origin/'input.dat').read_text()
            field='import numpy as np\nexternal_potentials = np.array([['+', '.join(map(repr,[charge,*map(float,position)]))+']], dtype=float)\nexternal_potentials[:,1:4] /= psi_bohr2angstroms\n'
            text=text.replace('set {',field+'\nset {',1).replace("energy('b3lyp', return_wfn=True)","energy('b3lyp', return_wfn=True, external_potentials=external_potentials)")
            text=text.replace('NADOC_PERTURBATION none','NADOC_PERTURBATION signed_external_charge')
            (folder/'input.dat').write_text(text)
            cases.append({'id':name,'charge_e':charge,'position_angstrom':position.tolist(),'nearest_nucleus_angstrom':nearest,
                'baseline':str(origin.resolve()),'model_delta_dipole_au':(dip-zero_dip).tolist(),'model_max_drude_angstrom':disp,'model_domain_error':error,
                'inputs':[source(folder/f) for f in ('input.dat','grid.dat','model_delta_esp_au.txt')]})
write(root/'plan.json',{'simulation_ready':False,'gate_effect':'none','scope':'Prospective diagnostic response at two previously exposed thermal geometries. Original frozen model predictions; signed probes placed 2.2 times oxygen Bondi radius along C2-to-O2 direction. Development data for future multi-conformer fitting, not a release validation set.',
    'cases':cases,'threads':4,'psi4_memory_gb':4,'cgroup_memory_gib':8,'deadline_seconds':5400,'sources':sources+[source(frozen),source(Path(__file__))]})
print('Frozen',len(cases),'signed thermal response probes')
