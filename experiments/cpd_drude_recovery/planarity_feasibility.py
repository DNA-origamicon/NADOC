"""Training-minimum span test for six inherited planar-improper stiffnesses."""
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import unit

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,checked,write
from backend.parameterization.photoproduct_qm import parse_xyz

stage=Path('.development-artifacts/cpd-drude-bonded-h6-endpoints-v1').resolve()
root=Path('.development-artifacts/cpd-planarity-span-diagnostic-v1').resolve()
root.mkdir(exist_ok=False)
manifest_path=stage/'responses/minimum/linear_response_manifest.json'
m=json.loads(manifest_path.read_text())
with np.load(checked(m['outputs']['linear_response_arrays'])) as f:
    arrays=dict(f)
spec_path=stage/'quantitative_fit_specification.json'
parameters=json.loads(spec_path.read_text())['parameters']
xyz=np.array([a[1:] for a in parse_xyz(checked(m['sources']['target_geometry']).read_text())[0]])
names=[r['stable_atom_key'] for r in json.loads(checked(m['sources']['stable_atom_map']).read_text())]
fixed_path=stage/'nuclear_fixed_bonded.xml'
fixed=mm.XmlSerializer.deserialize(fixed_path.read_text())
prior=next(f for f in fixed.getForces() if isinstance(f,mm.CustomTorsionForce))
columns=[]
records=[]
for t in range(prior.getNumTorsions()):
    a,b,c,d,p=prior.getTorsionParameters(t)
    system=mm.System()
    for mass in arrays['masses_amu']:
        system.addParticle(float(mass))
    force=mm.CustomTorsionForce(prior.getEnergyFunction())
    force.addPerTorsionParameter('k')
    force.addPerTorsionParameter('theta0')
    force.addTorsion(a,b,c,d,[4.184,float(p[1])])
    system.addForce(force)
    integrator=mm.VerletIntegrator(0.001)
    context=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    context.setPositions(xyz*0.1)
    gradient=-np.array(context.getState(getForces=True).getForces(asNumpy=True).value_in_unit(unit.kilojoule_per_mole/unit.nanometer)).ravel()/41.84
    columns.append(arrays['rigid_body_projector']@(gradient/np.repeat(np.sqrt(arrays['masses_amu']),3)))
    records.append({'atoms':[names[i] for i in (a,b,c,d)],'native_k_kcal_mol_rad2':float(p[0])/4.184,'equilibrium_radians':float(p[1])})
    del context,integrator
base=arrays['projected_design_gradient']*np.array([p['scale'] for p in parameters])
extra=np.array(columns).T*20
rhs=arrays['projected_residual_gradient']
rows=[]
for label,a in [('existing_180',base),('plus_six_planarity_stiffnesses',np.column_stack((base,extra)))]:
    for cutoff in (1e-8,1e-10,1e-12):
        coefficient,_,rank,_=np.linalg.lstsq(a,rhs,rcond=cutoff)
        residual=a@coefficient-rhs
        rows.append({'basis':label,'relative_cutoff':cutoff,'rank':int(rank),'mass_weighted_residual_rms':float(np.sqrt(np.mean(residual**2))),'cartesian_residual_max':float(abs(residual*np.repeat(np.sqrt(arrays['masses_amu']),3)).max())})
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','scope':'Unbounded training-minimum gradient-span test only. Added columns permit changes to six native planar stiffnesses with fixed planar equilibria; no asymmetric improper equilibria, fitted parameters or validation data used. This is a necessary representability diagnostic, not an acceptance test.','extra_terms':records,'results':rows,'sources':[source(p) for p in (manifest_path,spec_path,fixed_path,Path(__file__))]})
print(json.dumps(rows,indent=2))
