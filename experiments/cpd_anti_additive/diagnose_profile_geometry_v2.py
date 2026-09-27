"""Localize retained QM/MM shape mismatches using saved coordinates only."""
from pathlib import Path
import sys
import shutil
import numpy as np

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked,geometry_match
from experiments.cpd_anti_additive.sella_pilot import save,now,BOHR
from backend.parameterization.photoproduct_qm import _dihedral_degrees

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-profile-geometry-diagnosis-v1'
FIT=ART/'cpd-anti-conformational-fit-v2-r1'


def angle(x,ids):
    a,b,c=x[list(ids)];v=a-b;w=c-b
    return float(np.degrees(np.arccos(np.clip(v@w/np.linalg.norm(v)/np.linalg.norm(w),-1,1))))


def aligned_rmsd(q,m,ids):
    if len(ids)<3:return None
    x=q[ids]-q[ids].mean(0);y=m[ids]-m[ids].mean(0)
    u,_,vt=np.linalg.svd(x.T@y);s=np.eye(3);s[2,2]=np.linalg.det(u@vt)
    return float(np.sqrt(np.mean(np.sum((x@(u@s@vt)-y)**2,axis=1))))


def examine(point,claimed,psf):
    names=point['atom_map'];elements=point['elements']
    q=np.array(point['geometry_bohr'])*BOHR;m=np.loadtxt(checked(claimed['final_geometry']))
    match=geometry_match(q,m,elements,point['heavy_torsion_indices'])
    assert all(abs(match[k]-claimed['branch_descriptors'][k])<1e-10 for k in match)
    bond=[];angles=[];torsions=[]
    for b in psf.bond_list:
        ids=[b.atom1.idx,b.atom2.idx]
        if any(elements[i]=='H' for i in ids):continue
        a=float(np.linalg.norm(q[ids[0]]-q[ids[1]]));c=float(np.linalg.norm(m[ids[0]]-m[ids[1]]))
        bond.append(dict(names=[names[i] for i in ids],qm_A=a,mm_A=c,error_A=abs(c-a)))
    for b in psf.angle_list:
        ids=[b.atom1.idx,b.atom2.idx,b.atom3.idx]
        if any(elements[i]=='H' for i in ids):continue
        a=angle(q,ids);c=angle(m,ids)
        angles.append(dict(names=[names[i] for i in ids],qm_deg=a,mm_deg=c,error_deg=abs(c-a)))
    for ids in point['heavy_torsion_indices']:
        a=_dihedral_degrees(*q[ids]);c=_dihedral_degrees(*m[ids])
        torsions.append(dict(names=[names[i] for i in ids],qm_deg=a,mm_deg=c,error_deg=abs((c-a+180)%360-180)))
    groups={
        'sugar':[i for i,n in enumerate(names) if "'" in n and elements[i]!='H'],
        'lesion_bases':[i for i,n in enumerate(names) if "'" not in n and n.split(':')[1]!='CM' and elements[i]!='H']}
    n1=[]
    for e in [1,2]:
        center=names.index(f'{e}:N1');attachment=f"{e}:C1'" if f"{e}:C1'" in names else f'{e}:CM'
        if attachment not in names:continue
        ids=[names.index(f'{e}:C2'),names.index(f'{e}:C6'),names.index(attachment)]
        vals=[]
        for x in [q,m]:
            a,b,c=x[ids];normal=np.cross(b-a,c-a);normal/=np.linalg.norm(normal)
            vals.append(dict(signed_height_A=float((x[center]-a)@normal),
                angle_sum_deg=sum(angle(x,[ids[i],center,ids[j]]) for i,j in [(0,1),(1,2),(2,0)])))
        n1.append(dict(atom=f'{e}:N1',plane_atoms=[names[i] for i in ids],qm=vals[0],mm=vals[1],
            height_difference_A=vals[1]['signed_height_A']-vals[0]['signed_height_A']))
    return dict(case_id=point['case_id'],branch_descriptors=match,branch_descriptor_match=claimed['branch_descriptor_match'],
        independently_aligned_group_rmsd_A={k:aligned_rmsd(q,m,v) for k,v in groups.items()},
        largest_heavy_bond_errors=sorted(bond,key=lambda r:r['error_A'],reverse=True)[:5],
        largest_heavy_angle_errors=sorted(angles,key=lambda r:r['error_deg'],reverse=True)[:5],
        largest_heavy_torsion_errors=sorted(torsions,key=lambda r:r['error_deg'],reverse=True)[:5],
        N1_pyramidalization=n1,MM_assessment_geometry=claimed['final_geometry'])


def main():
    from openmm import app
    ROOT.mkdir(exist_ok=False);shutil.copyfile(Path(__file__),ROOT/'worker.py')
    fit=read(FIT/'assessment.json');checked(fit['candidate'])
    profiles=read(checked(fit['profile_results']))
    old_review=read(FIT/'independent_review.json');checked(old_review['assessment'])
    receipt=read(ART/'cpd-anti-conformational-inputs-v2/receipt.json')
    points=read(checked(receipt['inventory']))['records']
    assert [p['case_id'] for p in points]==[r['case_id'] for r in profiles]
    selected=read(checked(fit['fit']))['coefficients']
    outputs=[]
    for point,row in zip(points,profiles):
        psf=app.CharmmPsfFile(str(FIT/f"candidate/endpoint-{point['endpoint']}/fragment.psf"))
        outputs.append(examine(point,row,psf))
    assert sum(not r['branch_descriptor_match'] for r in outputs)==7
    report=dict(at=now(),worker=source(ROOT/'worker.py'),sources=[source(FIT/name) for name in ['assessment.json','independent_review.json','candidate_progress.json','fit.json']],
        inventory=receipt['inventory'],cases=outputs,retained_mismatch_count=7,
        current_fitted_central_bonds=sorted({tuple(v['names'][1:3]) for v in selected}),
        caveat='Signed N1 heights use the explicit C2,C6,attachment neighbor order; they are local shape descriptors, not CIP assignments or newly imposed success thresholds.',
        no_new_energy_or_optimization=True,no_parameter_changes=True,old_verdicts_unchanged=True,simulation_ready=False)
    save(ROOT/'assessment.json',report)
    for row in outputs:
        if not row['branch_descriptor_match']:
            print(row['case_id'],row['branch_descriptors'], 'largest angle',row['largest_heavy_angle_errors'][0],
                'N1 heights',[(p['atom'],round(p['qm']['signed_height_A'],4),round(p['mm']['signed_height_A'],4)) for p in row['N1_pyramidalization']],flush=True)


if __name__=='__main__':main()
