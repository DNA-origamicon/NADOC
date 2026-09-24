"""Self-consistent constrained charge fit across two development geometries."""
import importlib
import json
from pathlib import Path
import re
import sys

import numpy as np
from openmm import unit as u
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded, checked, source, write
from experiments.cpd_drude_recovery.run_fresh_esp import read_result

root = Path('.development-artifacts/cpd-selfconsistent-charge-fit-v1').resolve()
root.mkdir(exist_ok=False)
recovery = Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
frozen = recovery/'corrected_parameters.training_frozen.json'
physical = AdiabaticNonbonded(recovery, frozen)
helpers = importlib.import_module('fit_permanent')
parameters = json.loads(frozen.read_text())
q0 = np.array([json.loads(checked(parameters['permanent_charges']).read_text())['charges_e'][n] for n in helpers.NAMES])
folders = [Path('.development-artifacts/cpd-fresh-esp-validation-v1/case-000').resolve(),
           Path('.development-artifacts/cpd-thermal-conformer-qm-v1').resolve()]
sources = [source(p/f) for p in folders for f in ('input.dat','output.dat','grid.dat','grid_esp.dat')]
write(root/'plan.json', {'simulation_ready': False, 'gate_effect': 'none',
    'scope': 'Self-consistent charge-only fit at two development geometries. Every evaluation relaxes Drudes. Hard displacement constraints, no response refit or release acceptance.',
    'maximum_iterations': 80, 'drude_domain_angstrom': .2, 'equal_geometry_weights': True, 'esp_sigma_au': .001, 'dipole_sigma_au': .1,
    'prior_weight': .1, 'atom_charge_bounds': [-1.2,1.2], 'lp_charge_bounds': [-.5,0],
    'excluded_pending_qm': 'cpd-both-thermal-conformer-qm-v1',
    'sources': sources+[source(frozen), source(Path(helpers.__file__)), source(Path(__file__))]})
bohr = helpers.BOHR_ANGSTROM
cases = []
for folder in folders:
    text = (folder/'input.dat').read_text()
    block = re.search(r'molecule model \{(.*?)\}', text, re.S)[1]
    xyz = np.array([[float(v) for v in line.split()[1:]] for line in block.splitlines() if len(line.split()) == 4 and line.split()[0] in ('C','N','O','H')])
    assert xyz.shape == (36,3)
    esp, dip = read_result(folder)
    grid = np.loadtxt(folder/'grid.dat')
    try:
        physical.energy_gradient(xyz)
    except ValueError:
        pass  # Domain failure is retained below; stationarity must still hold.
    m = physical.model
    state = m.context.getState(getPositions=True,getForces=True)
    positions = np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    forces = np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    assert abs(forces[m.drude_indices]).max() < 1e-4
    qd = np.array([m.nonbonded.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in m.drude_indices])
    induced_esp = bohr*((1/np.linalg.norm(grid[:,None,:]-positions[m.drude_indices][None,:,:],axis=2)-1/np.linalg.norm(grid[:,None,:]-xyz[None,:20,:],axis=2))@qd)
    induced_dip = (qd[:,None]*(positions[m.drude_indices]-xyz[:20])).sum(axis=0)/bohr
    A = bohr/np.linalg.norm(grid[:,None,:]-positions[None,:44,:],axis=2)
    D = positions[:44].T/bohr
    cases.append({'xyz':xyz,'grid':grid,'esp':esp,'dip':dip,'A':A,'D':D,'adjusted_esp':esp-induced_esp,'adjusted_dip':dip-induced_dip})
prior = np.array([helpers.MTHY[n.split(':')[1]] for n in helpers.NAMES])
sigma = np.array([.2 if n.split(':')[1] in ('C5','C6') else .1 for n in helpers.NAMES])
C, d = helpers.equality_constraints()
# Update the live model's 1-4 charge products alongside particle charges.
# All pre-existing excluded pairs remain zero; only the nuclear distance-three
# exceptions added by AdiabaticNonbonded acquire nonzero products.
m = physical.model
graph = physical.d._graph_distances()
exceptions = []
for k in range(m.nonbonded.getNumExceptions()):
    a,b,qprod,sig,eps = m.nonbonded.getExceptionParameters(k)
    if int(a)<36 and int(b)<36 and graph[int(a),int(b)] == 3:
        exceptions.append((k,int(a),int(b),sig,eps))
cache = {}
evaluations = 0
def evaluate(q):
    global evaluations
    key = np.asarray(q,dtype=float).tobytes()
    if key in cache:
        return cache[key]
    m.update(dict(zip(helpers.NAMES,map(float,q))), parameters['parameters']['alpha_angstrom3'],
             parameters['parameters']['thole'],parameters['parameters']['anisotropy'])
    for k,a,b,sig,eps in exceptions:
        qa = m.nonbonded.getParticleParameters(a)[0]
        qb = m.nonbonded.getParticleParameters(b)[0]
        m.nonbonded.setExceptionParameters(k,a,b,qa*qb,sig,eps)
    m.nonbonded.updateParametersInContext(m.context)
    value = .1*np.mean(((q-prior)/sigma)**2)
    displacements = []
    metrics = []
    for c in cases:
        try:
            physical.energy_gradient(c['xyz'])
        except ValueError:
            pass
        state = m.context.getState(getPositions=True,getForces=True)
        pos = np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
        forces = np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
        assert np.isfinite(pos).all() and abs(forces[m.drude_indices]).max()<1e-4
        charges = m.charges
        esp = bohr*(1/np.linalg.norm(c['grid'][:,None,:]-pos[None,:,:],axis=2))@charges
        dip = (charges[:,None]*pos).sum(axis=0)/bohr
        er = esp-c['esp']; dr = dip-c['dip']
        value += (np.mean(er**2)/.001**2+np.mean(dr**2)/.1**2)/len(cases)
        disp = np.linalg.norm(pos[m.drude_indices]-c['xyz'][:20],axis=1)
        displacements.extend(disp)
        metrics.append({'esp_rms_au':float(np.sqrt(np.mean(er**2))),
                        'dipole_vector_error_au':float(np.linalg.norm(dr)),
                        'max_drude_angstrom':float(disp.max())})
    result = (float(value), .2-np.asarray(displacements), metrics)
    cache[key] = result
    evaluations += 1
    if evaluations % 100 == 0:
        write(root/'progress.json',{'evaluations':evaluations,'objective':value,'metrics':metrics,'simulation_ready':False})
    return result
opt = minimize(lambda q:evaluate(q)[0],q0,jac='2-point',method='SLSQP',
    bounds=[(-1.2,1.2)]*36+[(-.5,0)]*8,
    constraints=[{'type':'eq','fun':lambda q:C@q-d,'jac':lambda q:C},
                 {'type':'ineq','fun':lambda q:evaluate(q)[1]}],
    options={'maxiter':80,'ftol':1e-9,'finite_diff_rel_step':1e-5})
write(root/'solver.json',{'success':bool(opt.success),'message':str(opt.message),
    'iterations':int(opt.nit),'evaluations':evaluations,'objective':float(opt.fun),
    'charge_constraint_error':float(abs(C@opt.x-d).max()),
    'minimum_domain_margin_angstrom':float(evaluate(opt.x)[1].min())})
assert abs(C@opt.x-d).max()<1e-8
write(root/'charges.json', {'charges_e':dict(zip(helpers.NAMES,map(float,opt.x))), 'simulation_ready':False})
# Reconstruct the complete model so changed charges also rebuild 1-4 products.
candidate = {'simulation_ready':False,'gate_effect':'none','parameters':parameters['parameters'], 'permanent_charges':source(root/'charges.json')}
write(root/'candidate_parameters.json',candidate)
new = AdiabaticNonbonded(recovery,root/'candidate_parameters.json')
records = []
for index,c in enumerate(cases):
    error = None
    try:
        new.energy_gradient(c['xyz'])
    except ValueError as exc:
        error = str(exc)
    m = new.model
    state = m.context.getState(getPositions=True,getForces=True)
    positions = np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    forces = np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    residual = float(abs(forces[m.drude_indices]).max())
    assert residual < 1e-4
    charges = np.array([m.nonbonded.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in range(m.system.getNumParticles())])
    esp = bohr*(1/np.linalg.norm(c['grid'][:,None,:]-positions[None,:,:],axis=2))@charges
    dip = (charges[:,None]*positions).sum(axis=0)/bohr
    disp = float(np.linalg.norm(positions[m.drude_indices]-c['xyz'][:20],axis=1).max())
    records.append({'geometry':str(folders[index]),'esp_rms_au':float(np.sqrt(np.mean((esp-c['esp'])**2))),
        'dipole_vector_error_au':float(np.linalg.norm(dip-c['dip'])),'max_drude_angstrom':disp,
        'max_drude_force':residual,'domain_error':error})
live_metrics=evaluate(opt.x)[2]
for live,rebuilt in zip(live_metrics,records):
    for key in ('esp_rms_au','dipole_vector_error_au','max_drude_angstrom'):
        assert abs(live[key]-rebuilt[key])<1e-8, 'Live updates disagree with rebuilt model'
write(root/'assessment.json', {'simulation_ready':False,'gate_effect':'none','records':records,
    'optimizer_success':bool(opt.success),'iterations':int(opt.nit),'constraint_error':float(abs(C@opt.x-d).max()),
    'maximum_charge_change_e':float(abs(opt.x-q0).max()),'policy':source(root/'plan.json'),
    'candidate':source(root/'candidate_parameters.json')})
print(json.dumps(records,indent=2))
