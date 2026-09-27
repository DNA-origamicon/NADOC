"""Analytic repair of two C3' neighborhoods using unchanged parent geometry.

This creates reviewable seeds, not equilibrated or accepted product coordinates.
"""
from pathlib import Path
import sys,shutil
import numpy as np
import openmm as mm
from openmm import app,unit as u
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import source,read,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import binary,read_binary
from experiments.cpd_anti_additive.review_source_conditioning_v1 import signed_volume
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry
from experiments.cpd_anti_additive.repair_source_stereo_v1 import ORDER
from backend.parameterization.photoproduct_bonded_fit_plan import _angle,_dihedral
ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-source-stereo-explicit-v2'
PRIOR=ART/'cpd-anti-solvated-construction-v1c'
GUESS=ART/'cpd-anti-source-stereo-repair-v1b'


def reconstruct(center,left,right,bond_O,bond_H,theta_left,theta_right,sign):
    a=left-center;a=a/np.linalg.norm(a)
    b=right-center;b=b/np.linalg.norm(b)
    basis=np.column_stack([a,b]);coeff=np.linalg.solve(basis.T@basis,np.cos(np.radians([theta_left,theta_right])))
    plane=basis@coeff;normal=np.cross(a,b);normal/=np.linalg.norm(normal)
    height2=1-float(plane@plane)
    if height2<=0:raise ValueError('Fixed ring angle cannot realize the two native O3 bond angles')
    choices=[]
    for orientation in [-1,1]:
        o=plane+orientation*np.sqrt(height2)*normal
        # The fourth substituent is opposite the three heavy substituents.
        h=-(a+b+o);h/=np.linalg.norm(h)
        oxygen=center+bond_O*o;hydrogen=center+bond_H*h
        volume=signed_volume(np.array([left,right,oxygen,hydrogen]))
        if volume*sign>0:choices.append((oxygen,hydrogen,volume))
    assert len(choices)==1
    return choices[0]


def main():
    ROOT.mkdir(exist_ok=False);shutil.copyfile(Path(__file__),ROOT/'executed_source.py')
    refs=read(GUESS/'chemical_references.json')['references']
    sources=[GUESS/'assessment.json',GUESS/'chemical_references.json',ROOT/'executed_source.py']
    for label in ['anti','control']:
        sources.extend(PRIOR/label/n for n in ['start.coor','solute.psf','coverage_system.xml','geometry_reference.json','source_A.txt'])
        sources.append(GUESS/label/'assessment.json');sources.append(GUESS/label/'psfgen.log')
    save(ROOT/'plan.json',dict(created_at=now(),sources=[source(p) for p in sources],
        method='Solve O3 unit-vector projections onto existing C3-C2/C3-C4 axes to reproduce both native C2-C3-O3/C4-C3-O3 equilibrium angles. Choose the mirror solution with QM canonical chirality; H3 points opposite the three heavy neighbors at native C3-H3 length.',
        sites=['D000:7','D002:26'],changed_atoms_per_case=4,
        invariant='All other double-precision solute and solvent coordinates, topology, charges, masses and coefficients unchanged',
        gate='All chemically mapped sugar/CPD signs correct, exact repaired bond/angle construction; remaining phosphate/bond/contact defects reported, not waived or called minimized',
        limits=dict(analytic_constructions_per_case=1,new_energy_evaluations=0,new_minimization=0),
        failed_psfgen='Native guesscoord gave poor O3 guesses. Keep that failed candidate; reconstruct only the same four coordinates explicitly.',
        simulation_ready=False))
    reports=[]
    for label in ['anti','control']:
        folder=ROOT/label;folder.mkdir()
        psf=app.CharmmPsfFile(str(PRIOR/label/'solute.psf'));x=read_binary(PRIOR/label/'start.coor',30867).copy();y=x.copy()
        system=mm.XmlSerializer.deserialize((PRIOR/label/'coverage_system.xml').read_text())
        lengths={};angles={}
        for f in system.getForces():
            if isinstance(f,mm.HarmonicBondForce):
                for i in range(f.getNumBonds()):
                    a,b,r,k=f.getBondParameters(i)
                    if a<3043 and b<3043:lengths[min((a,b),(b,a))]=r.value_in_unit(u.angstrom)
            if isinstance(f,mm.HarmonicAngleForce):
                for i in range(f.getNumAngles()):
                    a,b,c,theta,k=f.getAngleParameters(i)
                    if max(a,b,c)<3043:angles[min((a,b,c),(c,b,a))]=theta.value_in_unit(u.degree)
        edits=[];targets=[]
        for seg,res in [('D000',7),('D002',26)]:
            ids={a.name:a.idx for a in psf.atom_list if (a.system,a.residue.idx)==(seg,res)}
            c,l,r,o,h=[ids[n] for n in ["C3'","C2'","C4'","O3'","H3'"]]
            native=[lengths[min((c,o),(o,c))],lengths[min((c,h),(h,c))],angles[min((l,c,o),(o,c,l))],angles[min((r,c,o),(o,c,r))]]
            oxygen,hydrogen,volume=reconstruct(x[c],x[l],x[r],*native,np.sign(refs[0]['centers']["C3'"]['volume_A3']))
            y[o]=oxygen;y[h]=hydrogen;targets.extend([o,h])
            observed=[np.linalg.norm(y[o]-y[c]),np.linalg.norm(y[h]-y[c]),_angle(y[l],y[c],y[o]),_angle(y[r],y[c],y[o])]
            assert np.max(abs(np.array(observed)-native))<1e-9
            edits.append(dict(site=f'{seg}:{res}',indices=[o,h],native_C3_O3_H3_lengths_A=native[:2],native_C2_C3_O3_C4_C3_O3_angles_deg=native[2:],
                original_volume_A3=signed_volume(x[[l,r,o,h]]),candidate_volume_A3=volume,
                displacement_A=np.linalg.norm(y[[o,h]]-x[[o,h]],axis=1).tolist()))
        assert np.array_equal(y[np.setdiff1d(np.arange(len(y)),targets)],x[np.setdiff1d(np.arange(len(x)),targets)])
        for name in ['geometry_reference.json','source_A.txt']:
            shutil.copyfile(GUESS/label/name,folder/name)
        binary(folder/'candidate.coor',y);np.savetxt(folder/'candidate_solute_A.txt',y[:3043]);np.savetxt(folder/'seed_solute_A.txt',x[:3043])
        result=geometry(folder,y);assert result['stereo_passed']
        spec=read(folder/'geometry_reference.json');bad=[]
        for a,b,eq in spec['bonds_equilibrium_A']:
            length=float(np.linalg.norm(y[a]-y[b]));ratio=length/eq
            if ratio<.7 or ratio>1.3:bad.append(dict(indices=[a,b],labels=[spec['labels'][a],spec['labels'][b]],length_A=length,equilibrium_A=eq,ratio=ratio))
        report=dict(case=label,edits=edits,only_four_atoms_changed=True,chemical_stereo_passed=True,geometry=result,remaining_bond_violations=bad,
            construction_passed=False,new_energy_evaluations=0,minimum_certified=False,simulation_ready=False)
        save(folder/'assessment.json',report);reports.append(report)
        print(label,edits,'remaining bad bonds',len(bad),'clashes',result['contacts']['severe_clash_count'],flush=True)
    save(ROOT/'assessment.json',dict(created_at=now(),plan=source(ROOT/'plan.json'),cases=[source(ROOT/r['case']/'assessment.json') for r in reports],
        local_stereo_seed_repair_passed=True,construction_passed=False,new_energy_evaluations=0,simulation_ready=False))


if __name__=='__main__':main()
