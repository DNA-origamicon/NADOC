"""Replay a hash-verified MM prefix to restore the same Sella state before new work.

The optimizer, stopping checks and total per-case counters are copied from the
frozen conformational-v2 helper. Only the energy/force provider adds cached replay.
Use replay_only=True to stop before any new energy evaluation.
"""
import time
import traceback
from pathlib import Path
import numpy as np
from backend.parameterization.photoproduct_qm import _dihedral_degrees
from experiments.cpd_anti_additive.validation_gate import source,geometry_match
from experiments.cpd_anti_additive.sella_pilot import save,BOHR,projected_metrics
from experiments.cpd_anti_additive.conformational_fit_v2 import EV_KCAL

def relax_point(folder, point, system, plan, deadline, replay_frames=(), replay_only=False):
    import openmm as mm
    from openmm import unit as u
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella, Constraints
    from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check
    from openmm import app
    folder.mkdir(parents=True,exist_ok=False)
    x0 = np.array(point['geometry_bohr'])*BOHR
    indices = point['record']['torsion_indices']
    constrained = point['branch']!='remote-unconstrained'
    integrator = mm.VerletIntegrator(.001)
    context = mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    psf = app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{point['endpoint']}"/'fragment.psf'))
    evaluations = []
    class MMCalculator(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self, atoms=None, properties=None, system_changes=all_changes):
            super().calculate(atoms,properties,system_changes)
            if len(evaluations)>=plan['mm']['max_evaluations'] or time.monotonic()>deadline:
                raise RuntimeError('Declared MM evaluation/wall budget reached')
            x=atoms.positions.copy()
            index=len(evaluations)
            if index<len(replay_frames):
                cached=replay_frames[index]
                if cached.get_chemical_symbols()!=point['elements'] or np.max(abs(cached.positions-x))>=1e-9:
                    raise RuntimeError('Cached Sella path diverged; no substitution or automatic fresh start')
                ase_energy=float(cached.get_potential_energy())
                ase_forces=cached.get_forces(apply_constraint=False).copy()
                energy=ase_energy*EV_KCAL
                gradient=-ase_forces*EV_KCAL
            else:
                if replay_only:
                    save(folder/'replay_boundary.json',dict(cached_evaluations=index,next_positions_A=x.tolist(),no_new_energy=True))
                    raise RuntimeError('Saved native cache exhausted; replay-only boundary')
                context.setPositions(x*u.angstrom)
                state=context.getState(getEnergy=True,getForces=True)
                energy=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
                gradient=-np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
                ase_energy=energy/EV_KCAL
                ase_forces=-gradient/EV_KCAL
            if not np.isfinite(energy) or not np.isfinite(gradient).all():
                raise RuntimeError('Nonfinite MM evaluation')
            evaluations.append(dict(energy=energy,x=x,gradient=gradient))
            self.results=dict(energy=ase_energy,forces=ase_forces)
    atoms=Atoms(point['elements'],positions=x0)
    atoms.calc=MMCalculator()
    constraints=Constraints(atoms)
    if constrained: constraints.fix_dihedral(tuple(indices))
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces))
            gradient=-atoms.get_forces(apply_constraint=False)*EV_KCAL
            if constrained:
                force=projected_metrics(atoms.positions,gradient,indices)['max_projected_atom_gradient']
            else: force=float(np.linalg.norm(gradient,axis=1).max())
            return native and force<plan['mm']['projected_max_atom_force_kcal_A']
    error=None
    converged=False
    try:
        opt=AuditedSella(atoms,constraints=constraints,order=0,internal=True,eig=False,
            delta0=.1,constraints_tol=1e-8,refine_initial_hessian=False,max_cpu_threads=1,
            logfile=str(folder/'sella.log'),trajectory=str(folder/'sella.traj'))
        converged=bool(opt.run(fmax=plan['mm']['projected_max_atom_force_kcal_A']/EV_KCAL,
                               steps=plan['mm']['max_steps']))
    except Exception as exc:
        error=repr(exc)
        (folder/'failure_traceback.txt').write_text(traceback.format_exc())
    if not evaluations: raise RuntimeError(error or 'No MM evaluation')
    # Always assess an actually evaluated geometry, never an unevaluated last step.
    last=evaluations[-1]
    x=last['x']; gradient=last['gradient']
    np.savez_compressed(folder/'evaluations.npz',coordinates_A=np.array([r['x'] for r in evaluations]),
        gradients_kcal_A=np.array([r['gradient'] for r in evaluations]),energies_kcal=np.array([r['energy'] for r in evaluations]))
    np.savetxt(folder/'final_A.txt',x)
    geometry=geometry_check(psf,x0,x)
    metrics=(projected_metrics(x,gradient,indices) if constrained else
             dict(max_projected_atom_gradient=float(np.linalg.norm(gradient,axis=1).max())))
    difference=abs((_dihedral_degrees(*x[indices])-point['actual_dihedral_deg']+180)%360-180)
    match=geometry_match(x0,x,point['elements'],point['heavy_torsion_indices'])
    branch=match['basin_rmsd_A']<=.25 and match['basin_max_torsion_deg']<=20
    passed=bool(converged and metrics['max_projected_atom_gradient']<.001 and
        (not constrained or difference<.01) and geometry['stereo_preserved'] and geometry['graph_distances_passed'])
    result=dict(case_id=point['case_id'],branch=point['branch'],native_optimizer_converged=converged,
        independent_stationarity_and_chemistry_passed=passed,energy_kcal=last['energy'],
        error=error,evaluations=len(evaluations),constraint_applied=constrained,
        torsion_difference_deg=difference,geometry=geometry,projection=metrics,
        branch_descriptors=match,branch_descriptor_match=bool(branch),
        minimum_certified=False,final_geometry=source(folder/'final_A.txt'),
        raw_evaluations=source(folder/'evaluations.npz'))
    result.update(cached_evaluations=min(len(evaluations),len(replay_frames)),new_evaluations=max(0,len(evaluations)-len(replay_frames)))
    save(folder/'assessment.json',result)
    del context,integrator
    print(point['case_id'],'passed',passed,'evaluations',len(evaluations),'branch',bool(branch),flush=True)
    return result,x
