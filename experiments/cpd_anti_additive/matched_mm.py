"""Matched constrained MM relaxation against existing QM points; no fitting."""
import argparse,json,os,shutil,sys
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR,RUNTIME
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees
import geometric.engine,geometric.molecule,geometric.optimize
ART=REPO/'.development-artifacts';EH=627.5094740631


def prepare(root):
    root.mkdir(exist_ok=False);shutil.copyfile(__file__,root/'executed_source.py')
    old=json.loads((ART/'cpd-anti-relaxed-glycosidic-v1/plan.json').read_text());points=[]
    for r in old['records']:
        label=r['label'];e=r['endpoint']
        folder={'endpoint-1--15':ART/'cpd-anti-relaxed-glycosidic-v1/endpoint-1--15', 'endpoint-1-+15':ART/'cpd-anti-geometric-endpoint1-v2', 'endpoint-2--15':ART/'cpd-anti-geometric-pair-v1/endpoint-2--15', 'endpoint-2-+15':ART/'cpd-anti-geometric-pilot-v1'}[label]
        if label=='endpoint-1--15':
            report=json.loads((folder/'geometry_audit.json').read_text());assert report['passed'];checked(report['native']);xyz=checked(report['optimized_xyz']);energy=report['energy_hartree'];evidence=source(folder/'geometry_audit.json')
        else:
            report=json.loads((folder/'assessment.json').read_text());assert report['native_optimizer_converged'] and report['geometry_audit']['passed'];xyz=checked(report['optimized']);row=json.loads((folder/'progress.json').read_text())['evaluations'][-1];result=json.loads(checked(row['result']).read_text());checked(result['native']);energy=result['energy'];evidence=source(folder/'assessment.json')
        atoms,_=parse_xyz(xyz.read_text());x=np.array([a[1:] for a in atoms])/BOHR
        points.append(dict(label=label,endpoint=e,record=r,elements=[a[0] for a in atoms],geometry_bohr=x.tolist(),qm_energy=energy,qm_source=evidence,geometry_source=source(xyz)))
    refs=json.loads((ART/'cpd-anti-glycosidic-probes-v1/plan.json').read_text())['references']
    for ref in refs:
        e=ref['endpoint'];d=json.loads(checked(ref['input']).read_text());rr=json.loads(checked(ref['result']).read_text());checked(rr['native']);r=dict(next(r for r in old['records'] if r['endpoint']==e));x=np.array(d['geometry_bohr']);r['target_degrees']=_dihedral_degrees(*x[r['torsion_indices']])
        points.append(dict(label=f'endpoint-{e}-reference',endpoint=e,record=r,elements=d['elements'],geometry_bohr=x.tolist(),qm_energy=rr['energy_hartree'],qm_source=ref['result'],geometry_source=ref['input']))
    candidates=[dict(label='baseline',folder=str(ART/'cpd-anti-ordered-fit-v1'))]+[dict(label=f'charge-{n}',folder=str(ART/f'cpd-anti-ordered-coupled-v1/geometry-{n}')) for n in (1,10,100)]
    for c in candidates:c['systems']={str(e):source(Path(c['folder'])/f'endpoint-{e}/system.xml') for e in (1,2)}
    for p in points:assert screen(np.array(p['geometry_bohr']),p)['passed']
    write(root/'plan.json',dict(points=points,candidates=candidates,scope='Matched fixed-torsion local MM relaxations from QM seeds, including reference torsions; not exhaustive conformational minima',minimum_certified=False,runtime_sources=[source(p) for p in sorted((RUNTIME/'geometric').glob('*.py'))]))


def one(root,p,c):
    import openmm as mm
    from openmm import unit as u
    folder=root/c['label']/p['label'];folder.mkdir(parents=True,exist_ok=False)
    x=np.array(p['geometry_bohr']);sp=checked(c['systems'][str(p['endpoint'])]);system=mm.XmlSerializer.deserialize(sp.read_text());integrator=mm.VerletIntegrator(.001);ctx=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    assert system.getNumParticles()==len(x)
    def evaluate(coords):
        ctx.setPositions(np.asarray(coords).reshape(-1,3)*BOHR*u.angstrom);state=ctx.getState(getEnergy=True,getForces=True)
        e=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)/EH;g=-np.asarray(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))*BOHR/EH
        assert np.isfinite(e) and np.isfinite(g).all();return e,g.ravel()
    e0,g0=evaluate(x);i=int(np.argmax(abs(g0)));a=x.ravel().copy();b=a.copy();a[i]+=1e-4;b[i]-=1e-4;fd=(evaluate(a)[0]-evaluate(b)[0])/2e-4
    assert abs(fd-g0[i])<max(1e-7,abs(g0[i])*1e-4)
    M=geometric.molecule.Molecule();M.elem=p['elements'];M.xyzs=[x*BOHR];M.bonds=[tuple(b['indices']) for b in json.loads(checked(p['record']['model_graph']).read_text())['bonds']];M.top_settings['read_bonds']=True;M.build_topology(force_bonds=False);M.write(str(folder/'starting.xyz'))
    constraint=folder/'constraints.txt';constraint.write_text('$freeze\ndihedral '+' '.join(str(i+1) for i in p['record']['torsion_indices'])+'\n');records=[]
    class Engine(geometric.engine.Engine):
        def calc_new(self,coords,dirname):
            if len(records)>=200:raise RuntimeError('MM evaluation budget reached')
            xyz=np.asarray(coords).reshape(-1,3);audit=screen(xyz,p)
            if not audit['passed']:raise RuntimeError('MM geometry screen failed')
            e,g=evaluate(xyz);np.savez(folder/f'evaluation-{len(records)+1:03d}.npz',geometry_bohr=xyz,gradient=g,energy=e);records.append(dict(energy=e));return dict(energy=e,gradient=g)
    try:
        result=geometric.optimize.run_optimizer(customengine=Engine(M),input=str(folder/'starting.xyz'),constraints=str(constraint),prefix=str(folder/'geometric'),coordsys='tric',trust=.02,tmax=.05,enforce=.1,conmethod=1,convergence_set='GAU_TIGHT',convergence_grms=2e-7,convergence_gmax=5e-7,maxiter=200)
        final=np.asarray(result.xyzs[-1])/BOHR;audit=screen(final,p);assert audit['passed'];ef,g=evaluate(final);result[-1].write(str(folder/'optimized.xyz'))
        report=dict(candidate=c['label'],point=p['label'],endpoint=p['endpoint'],converged=True,energy_kcal_mol=ef*EH,mm_at_qm_kcal_mol=e0*EH,qm_energy_hartree=p['qm_energy'],evaluations=len(records),geometry_audit=audit,force_conversion_fd_error=abs(fd-g0[i]),system=source(sp),qm_source=p['qm_source'],minimum_certified=False)
    except Exception as exc:
        report=dict(candidate=c['label'],point=p['label'],endpoint=p['endpoint'],converged=False,error=repr(exc),evaluations=len(records),minimum_certified=False)
    write(folder/'assessment.json',report);del ctx,integrator;return report


def run(root):
    os.chdir(root);os.sched_setaffinity(0,set(range(4)));plan=json.loads((root/'plan.json').read_text())
    for src in plan['runtime_sources']:checked(src)
    for p in plan['points']:checked(p['qm_source']);checked(p['geometry_source'])
    records=[]
    for c in plan['candidates']:
        for p in plan['points']:
            records.append(one(root,p,c));write(root/'progress.json',dict(records=records,total=len(plan['candidates'])*len(plan['points'])))
    comparisons=[]
    for r in records:
        if not r['converged'] or r['point'].endswith('reference'):continue
        ref=next(rr for rr in records if rr['candidate']==r['candidate'] and rr['point']==f"endpoint-{r['endpoint']}-reference")
        if not ref['converged']:continue
        q=(r['qm_energy_hartree']-ref['qm_energy_hartree'])*EH;m=r['energy_kcal_mol']-ref['energy_kcal_mol'];comparisons.append(dict(candidate=r['candidate'],point=r['point'],qm_relative_kcal_mol=q,mm_relaxed_relative_kcal_mol=m,error_kcal_mol=m-q))
    write(root/'assessment.json',dict(records=records,comparisons=comparisons,simulation_ready=False,minimum_certified=False,scope=plan['scope'],caveat='Endpoint1−15 uses older default electronic tolerance; other QM points use tighter SCF/response; no fine-precision equivalence or full torsion-profile claim'))
    if any(not r['converged'] for r in records):raise RuntimeError('Some matched MM relaxations failed; independent successful results preserved')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['prepare','run']);a.add_argument('root',type=Path);p=a.parse_args();globals()[p.action](p.root.resolve())
