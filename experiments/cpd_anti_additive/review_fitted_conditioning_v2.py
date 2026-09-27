"""Replay the failed DNA construction and render its shared-frame evidence."""
import json
from pathlib import Path
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app,unit as u

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.review_source_conditioning_v1 import adjacency,signed_volume
from experiments.cpd_anti_additive.condition_fitted_dna_v2 import ROOT,MODEL,ART,inputs
from experiments.cpd_anti_additive.relax_dna_placement_v2 import contact_check


def main():
    result=read(ROOT/'assessment.json');plan=read(checked(result['plan']))
    for s in plan['sources']:checked(s)
    d,_,_,_=inputs();x=d['x'];y=np.loadtxt(checked(result['coordinates']))
    psf=app.CharmmPsfFile(str(MODEL/'anti.psf'));neighbors=adjacency(psf)
    model_plan=read(MODEL/'plan.json')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params=app.CharmmParameterSet(*(str(checked(p)) for p in model_plan['parent_forcefields']),str(MODEL/'anti_dna_overlay.prm'))
    system=psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
    integ=mm.VerletIntegrator(.001);ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
    ctx.setPositions(y*u.angstrom);state=ctx.getState(getEnergy=True,getForces=True)
    forces=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    energy=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
    cached=read(ROOT/'final_reference_force.json');mobile=plan['mobile_indices']
    assert abs(energy-cached['energy_kcal'])<1e-5
    assert np.max(abs(forces[mobile]+np.array(cached['gradient_kcal_A'])))<1e-4
    sugars=[]
    for atom in psf.atom_list:
        if atom.name not in ("C1'","C3'","C4'"):continue
        ns=neighbors[atom.idx]
        sugars.append(dict(atom=d['labels'][atom.idx],preserved=bool(signed_volume(x[ns])*signed_volume(y[ns])>0)))
    centers=[]
    for e in (1,2):
        folder=ART/'cpd-anti-conformational-fit-v2-r1/candidate'/f'endpoint-{e}'
        names=read(folder/'atom_map.json');q=np.loadtxt(folder/'starting_A.txt')
        ns=adjacency(app.CharmmPsfFile(str(folder/'fragment.psf')))
        for name in ('C5','C6',"C1'","C3'","C4'"):
            key=f'{e}:{name}';ids=ns[names.index(key)]
            mapped=[d['ids'][names[i]] for i in ids]
            centers.append(dict(atom=key,preserved=bool(signed_volume(q[ids])*signed_volume(y[mapped])>0)))
    assert len(sugars)==288 and len(centers)==10 and all(r['preserved'] for r in sugars+centers)
    fixed=np.setdiff1d(np.arange(len(y)),mobile);assert np.array_equal(y[fixed],x[fixed])
    contacts=contact_check(d,y)
    assert not contacts['severe_clash_count'] and not contacts['all_piercing_count']
    indices=np.argsort(np.max(abs(forces[mobile]),axis=1))[-10:][::-1]
    largest=[dict(index=mobile[i],atom=d['labels'][mobile[i]],force_kcal_A=forces[mobile[i]].tolist()) for i in indices]
    qm_keys=[k for k in d['ids'] if "'" not in k and k in d['names']]
    maxbase=float(max(np.linalg.norm(y[d['ids'][k]]-x[d['ids'][k]]) for k in qm_keys))
    force=float(np.max(abs(forces[mobile])))
    assert abs(force-result['max_mobile_reference_force_kcal_A'])<1e-8
    assert abs(maxbase-result['max_base_displacement_A'])<1e-8
    report=dict(replay_passed=True,assessment=source(ROOT/'assessment.json'),reviewed_at=now(),
        max_mobile_reference_force_kcal_A=force,mobile_stationary=force<=.01,
        source_sugar_centers=sugars,original_QM_centers=centers,fixed_coordinates_exactly_retained=True,
        contacts=contacts,largest_mobile_forces=largest,max_base_displacement_A=maxbase,
        inherited_base_displacement_screen_passed=maxbase<=3.5,
        terminal_iteration_cap=1000,chirality_constraints_removed=False,scientific_verdict='Failed construction',
        full_DNA_dynamics_tested=False,simulation_ready=False,reviewer=source(Path(__file__)))
    save(ROOT/'independent_review.json',report)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=d['labels'];elements=d['elements'];bonds=d['bonds']
    anti=[tuple(sorted((d['ids'][a],d['ids'][b]))) for a,b in [('1:C5','2:C6'),('1:C6','2:C5')]]
    syn=[tuple(sorted((d['ids'][f'1:{a}'],d['ids'][f'2:{a}']))) for a in ('C5','C6')]
    oldbonds=sorted({tuple(sorted(b)) for b in bonds}-set(anti)|set(syn))
    center=x[[d['ids']["1:C1'"],d['ids']["2:C1'"]]].mean(axis=0)
    radius=20.;moving=set(mobile)
    selected={i for i,el in enumerate(elements) if el!='H' and min(np.linalg.norm(x[i]-center),np.linalg.norm(y[i]-center))<radius}
    fig,axes=plt.subplots(1,3,figsize=(16,5.5),subplot_kw={'projection':'3d'},layout='constrained')
    for ax,sets,title in zip(axes,[[(x,oldbonds,'#a75e32')],[(y,bonds,'#087da1')],[(x,oldbonds,'#a75e32'),(y,bonds,'#087da1')]],
        ['Frozen source','Fitted-potential construction: FAILED','Same-frame comparison']):
        for coords,graph,color in sets:
            for a,b in graph:
                if a in selected and b in selected:ax.plot(*coords[[a,b]].T,color=color if a in moving or b in moving else '#aaa',lw=1)
        if len(sets)==2:
            for i in selected & moving:ax.plot(*np.array([x[i],y[i]]).T,color='#777',ls='--',lw=.3)
        ax.set(title=title,xlim=(center[0]-radius,center[0]+radius),ylim=(center[1]-radius,center[1]+radius),zlim=(center[2]-radius,center[2]+radius))
        ax.set_box_aspect([1,1,1]);ax.view_init(elev=25,azim=-60)
    fig.suptitle(f'1000-step cap; maximum mobile force {force:.3f} > 0.01 kcal/mol/Å; maximum base displacement {maxbase:.3f} > 3.5 Å\nBonds, stereo and saved-frame contact/piercing screens pass; no full-DNA dynamics',fontsize=11)
    fig.savefig(ROOT/'comparison.png',dpi=160);plt.close(fig)
    template=Path(__file__).with_name('placement_review_viewer.html').read_text()
    template=template.replace('Cis-anti placement diagnostic — rigid placement rejected','Fitted cis-anti DNA — construction failed')
    start=template.index('<p>The source sugars');end=template.index('</p>',start)+4
    template=template[:start]+f'<p>The 1000-step constrained optimization stopped at its cap. Maximum mobile force {force:.3f} kcal/mol/Å exceeds 0.01; lesion base displacement {maxbase:.3f} Å exceeds the retained 3.5 Å product screen. Stereo and covalent/contact integrity pass, but constraints were never removed. This candidate is isolated, rejected for dynamics, and has not changed the saved design.</p>'+template[end:]
    template=template.replace('Rigid anti candidate — rejected','Fitted-potential candidate — FAILED')
    template=template.replace('href="current_A.txt"','href="../cpd-anti-placement-review-v2/current_A.txt"').replace('rejected_candidate_A.txt','candidate_A.txt')
    glyco=[[d['ids'][f'{e}:C1\''],d['ids'][f'{e}:N1']] for e in (1,2)]
    table=[['Metric','Source','Candidate'],['Maximum mobile force','—',f'{force:.6f} kcal/mol/Å (limit 0.01)'],
        ['Maximum base displacement','—',f'{maxbase:.3f} Å (limit 3.5)'],['Constrained / free steps','—','1000 / 0'],
        ['Sugar / local QM stereocenters','—','288 / 10 preserved']]
    for e,(a,b) in enumerate(glyco,1):table.append([f'Endpoint {e} glycosidic length',f'{np.linalg.norm(x[a]-x[b]):.4f} Å',f'{np.linalg.norm(y[a]-y[b]):.4f} Å'])
    html=''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in table)
    start=template.index('let r=D.report;');end=template.index('redraw();</script>',start)
    template=template[:start]+f"document.getElementById('metrics').innerHTML={json.dumps(html)};"+template[end:]
    payload=dict(current=x.tolist(),candidate=y.tolist(),bondsCurrent=oldbonds,bondsCandidate=bonds,moved=mobile,
        labels=labels,elements=elements,center=center.tolist(),near=sorted(selected),glycosidic=glyco,clashes=[],report=result)
    (ROOT/'review.html').write_text(template.replace('__DATA__',json.dumps(payload)))
    save(ROOT/'viewer_manifest.json',dict(renderer=source(Path(__file__)),assessment=source(ROOT/'assessment.json'),
        outputs=[source(ROOT/p) for p in ('review.html','comparison.png')],saved_design_changed=False,browser_interaction_tested=False))
    print('Independent failure review and shared-frame A/B retained; no new calculations.')


if __name__=='__main__':main()
