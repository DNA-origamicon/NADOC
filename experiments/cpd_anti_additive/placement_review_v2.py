"""Shared-frame rejection evidence for rigid anti placement with fixed DNA sugars."""

import json
from pathlib import Path
import sys

import numpy as np
from openmm import app, unit
from scipy.spatial import cKDTree

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import checked, read, source
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from backend.core.cpd_product import _proper_kabsch
from backend.core.atomistic import VDW_RADIUS
from backend.core.ring_piercing import _scan, ring_names_for
from backend.core.photoproduct_chemistry import audit_product_chirality

ART=REPO/'.development-artifacts'


def audit(x, bonds, rings, moved, elements, labels):
    ns=[set() for _ in x]
    for i,j in bonds:ns[i].add(j);ns[j].add(i)
    excluded=[]
    for i in moved:
        seen={i};front={i}
        for _ in range(3):
            front={j for k in front for j in ns[k]}-seen
            seen.update(front)
        excluded.append(seen)
    heavy=np.array([i for i,e in enumerate(elements) if e!='H'])
    tree=cKDTree(x[heavy])
    clashes=[];pairs=set();minimum=1e6
    for i,skip in zip(moved,excluded):
        if elements[i]=='H':continue
        for h in tree.query_ball_point(x[i],4.):
            j=int(heavy[h]);pair=tuple(sorted((i,j)))
            if j in skip or pair in pairs:continue
            pairs.add(pair)
            distance=float(np.linalg.norm(x[i]-x[j]))
            ratio=distance/(10*(VDW_RADIUS[elements[i]]+VDW_RADIUS[elements[j]]))
            minimum=min(minimum,ratio)
            if ratio<.5:clashes.append(dict(indices=[i,j],atoms=[labels[i],labels[j]],distance_A=distance,vdw_ratio=ratio))
    clashes.sort(key=lambda r:r['vdw_ratio'])
    heavybonds=[b for b in bonds if all(elements[i]!='H' for i in b)]
    piercings=_scan(x/10,heavybonds,rings,max_report=1000)
    target=[p for p in piercings if set(p['bond_serials']+p['ring_serials']).intersection(moved)]
    return dict(severe_clashes=clashes,severe_clash_count=len(clashes),minimum_target_vdw_ratio=minimum,
        target_piercings=target,target_piercing_count=len(target),all_piercing_count=len(piercings),
        detector='Existing ring_piercing._scan and cpd_product severe-contact threshold; exclude 1-2/1-3/1-4 graph pairs')


def render(root, x, y, bonds_a, bonds_b, ids, elements, moved, labels, report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    center=(x[[ids[k] for k in ('1:C5','1:C6','2:C5','2:C6')]].mean(axis=0)+
            y[[ids[k] for k in ('1:C5','1:C6','2:C5','2:C6')]].mean(axis=0))/2
    selected=[i for i,e in enumerate(elements) if e!='H' and (np.linalg.norm(x[i]-center)<11 or np.linalg.norm(y[i]-center)<11)]
    focus=set(selected);move=set(moved);glys=[(ids[f"{e}:C1'"],ids[f'{e}:N1']) for e in (1,2)]
    fig,axes=plt.subplots(1,3,figsize=(17,6),subplot_kw={'projection':'3d'},layout='constrained')
    for ax,title,sets in zip(axes,['Frozen source geometry','Rigid anti placement — REJECTED','Shared-frame displacement overlay'],
        [[(x,bonds_a,'#aa6138')],[(y,bonds_b,'#087ea4')],[(x,bonds_a,'#aa6138'),(y,bonds_b,'#087ea4')]]):
        for pos,bonds,color in sets:
            for i,j in bonds:
                if i not in focus or j not in focus:continue
                active=i in move or j in move
                ax.plot(*pos[[i,j]].T,color=color if active else '#aeb7bd',lw=2.4 if active else .7,alpha=.95 if active else .45)
            for i,j in glys:
                ax.plot(*pos[[i,j]].T,color='#dc4b21',lw=4)
                ax.text(*pos[[i,j]].mean(axis=0),f'{np.linalg.norm(pos[i]-pos[j]):.2f} Å',color='#b12a0c',fontsize=10)
            if pos is y:
                for clash in report['candidate']['severe_clashes'][:3]:
                    ii=clash['indices'];ax.plot(*pos[ii].T,color='#bf36a4',lw=2,ls=':')
        if len(sets)==2:
            for i in selected:
                if i in move:ax.plot(*np.vstack((x[i],y[i])).T,color='#545b64',lw=.6,ls='--')
        for key in ("1:C1'","2:C1'",'1:C5','2:C5'):
            i=ids[key];pos=y if len(sets)==1 and sets[0][0] is y else x
            ax.text(*pos[i],key,fontsize=9)
        ax.set(xlim=(center[0]-8,center[0]+8),ylim=(center[1]-8,center[1]+8),zlim=(center[2]-8,center[2]+8),title=title)
        ax.set_box_aspect([1,1,1]);ax.view_init(elev=24,azim=-65)
        ax.set_xlabel('Å');ax.set_ylabel('Å');ax.set_zlabel('Å')
    fig.suptitle("Fixed sugars cannot accommodate this rigid anti template: C1′ separation 4.08 Å versus 7.13 Å",fontsize=15)
    fig.savefig(root/'comparison.png',dpi=170)
    plt.close(fig)
    payload=dict(current=x.tolist(),candidate=y.tolist(),bondsCurrent=bonds_a,bondsCandidate=bonds_b,
        moved=moved,labels=labels,elements=elements,center=center.tolist(),near=selected,
        glycosidic=glys,clashes=[c['indices'] for c in report['candidate']['severe_clashes']],report=report)
    template=Path(__file__).with_name('placement_review_viewer.html').read_text()
    (root/'review.html').write_text(template.replace('__DATA__',json.dumps(payload)))


def main():
    _,receipt=require('engine')
    root=ART/'cpd-anti-placement-review-v2'
    root.mkdir(exist_ok=False)
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    dna=ART/'cpd-anti-dna-topology-v2b'
    topology=read(dna/'assessment.json');independent=read(dna/'independent_review.json')
    assert independent['passed'] and independent['assessment']==source(dna/'assessment.json')
    for record in topology['outputs'].values():checked(record)
    psf=app.CharmmPsfFile(str(dna/'anti.psf'))
    x=np.array(app.PDBFile(str(dna/'anti.pdb')).positions.value_in_unit(unit.angstrom))
    elements=[a.element.symbol for a in psf.topology.atoms()]
    labels=[f'{a.system}:{a.residue.idx}:{a.name}' for a in psf.atom_list]
    endpoints=topology['endpoints']
    ids={f'{e["endpoint"]}:{a.name}':a.idx for e in endpoints for a in psf.atom_list
         if (a.system,a.residue.idx)==(e['segid'],e['resid'])}
    fragment=Path(receipt['candidate'])/'two-nucleosides'
    names=read(fragment/'atom_map.json');t=np.loadtxt(fragment/'minimum_A.txt')
    save(root/'plan.json',dict(scope='Isolated rigid placement rejection diagnostic; no minimization, dynamics or promotion',
        sources=[source(p) for p in (dna/'assessment.json',dna/'independent_review.json',dna/'anti.psf',dna/'anti.pdb',
                                    fragment/'minimum_A.txt',fragment/'atom_map.json')],
        inherited_screen=dict(max_anchor_rms_A=1.2,max_glycosidic_error_A=.4,max_base_displacement_A=3.5,severe_clash_ratio=.5),
        moved_atoms='Both complete bases including hydrogens; all sugars/backbones fixed',
        method='Four C1-prime/N1 anchors, proper rigid Kabsch; no reflection; no parameter fit',
        source_code=source(Path(__file__)),viewer=source(Path(__file__).with_name('placement_review_viewer.html')),
        geometry_safe_for_dynamics=False,simulation_ready=False))
    keys=[f'{e}:{n}' for e in (1,2) for n in ("C1'",'N1')]
    rotation,translation,rms=_proper_kabsch(t[[names.index(k) for k in keys]],x[[ids[k] for k in keys]])
    y=x.copy();moved=[]
    for key in names:
        if "'" in key:continue
        moved.append(ids[key]);y[ids[key]]=rotation@t[names.index(key)]+translation
    assert len(moved)==28 and np.linalg.det(rotation)>.99999999
    untouched=sorted(set(range(len(x)))-set(moved));assert np.array_equal(x[untouched],y[untouched])
    basebonds=[tuple(sorted((b.atom1.idx,b.atom2.idx))) for b in psf.bond_list]
    anti=[tuple(sorted((ids['1:C5'],ids['2:C6']))),tuple(sorted((ids['1:C6'],ids['2:C5'])))]
    syn=[tuple(sorted((ids['1:C5'],ids['2:C5']))),tuple(sorted((ids['1:C6'],ids['2:C6'])))]
    currentbonds=sorted(set(basebonds)-set(anti)|set(syn))
    rings=[]
    for residue in psf.residue_list:
        named={a.name:a.idx for a in residue.atoms}
        for kind,cycle in ring_names_for(named):
            rings.append((f'{residue.system}:{residue.idx}/{kind}',kind,[named[n] for n in cycle]))
    ring_a=[ids[k] for k in ('1:C5','1:C6','2:C6','2:C5')]
    ring_b=[ids[k] for k in ('1:C5','1:C6','2:C5','2:C6')]
    old=audit(x,currentbonds,rings+[('lesion','cyclobutane',ring_a)],moved,elements,labels)
    new=audit(y,basebonds,rings+[('lesion','cyclobutane',ring_b)],moved,elements,labels)
    glyco=[]
    for e in (1,2):
        a,b=ids[f"{e}:C1'"],ids[f'{e}:N1']
        reference=float(np.linalg.norm(t[names.index(f"{e}:C1'")]-t[names.index(f'{e}:N1')]))
        glyco.append(dict(endpoint=e,indices=[a,b],current_A=float(np.linalg.norm(x[a]-x[b])),
            candidate_A=float(np.linalg.norm(y[a]-y[b])),reference_A=reference,
            candidate_error_A=abs(float(np.linalg.norm(y[a]-y[b]))-reference)))
    definition_path=REPO/'backend/data/forcefield/photoproducts/tt-cpd-cis-anti-i/chemical_definition.json'
    definition=read(definition_path)
    chirality=audit_product_chirality(definition,{key:y[i].tolist() for key,i in ids.items()})
    displacement=np.linalg.norm(y-x,axis=1)
    report=dict(status='rejected_rigid_base_only_placement',anchor_rms_A=rms,rotation_determinant=float(np.linalg.det(rotation)),
        source_C1_separation_A=float(np.linalg.norm(x[ids["1:C1'"]]-x[ids["2:C1'"]])),
        template_C1_separation_A=float(np.linalg.norm(t[names.index("1:C1'")]-t[names.index("2:C1'")])) ,
        max_base_displacement_A=float(displacement.max()),glycosidic=glyco,current=old,candidate=new,
        lesion_chirality=chirality,chemical_definition=source(definition_path),
        sugars_backbone_fixed=True,parameter_fit=False,geometry_safe_for_dynamics=False,simulation_ready=False,
        source_geometry='Frozen design source with declared syn connectivity; not a qualified MD control',
        candidate_geometry='Rigid base placement from independently tested anti MM two-nucleoside fixture',
        conclusion='Rigid base-only placement fails existing limits. Requires explicit local backbone adjustment and a new isolated audit; no automatic integration.',
        displacements=[dict(index=i,atom=labels[i],distance_A=float(displacement[i])) for i in moved],
        plan=source(root/'plan.json'))
    assert rms>1.2 and max(g['candidate_error_A'] for g in glyco)>.4 and displacement.max()>3.5
    np.savetxt(root/'current_A.txt',x);np.savetxt(root/'rejected_candidate_A.txt',y)
    save(root/'assessment.json',report)
    render(root,x,y,currentbonds,basebonds,ids,elements,moved,labels,report)
    print(json.dumps({k:report[k] for k in ('status','anchor_rms_A','source_C1_separation_A','template_C1_separation_A',
                                         'max_base_displacement_A','glycosidic')},indent=2))
    print('clashes/piercings',[(side,report[side]['severe_clash_count'],report[side]['target_piercing_count']) for side in ('current','candidate')])


if __name__=='__main__':main()
