"""Independent replay of the first exposed torsion fit and retained residuals."""
from pathlib import Path
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app,unit as u

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from backend.parameterization.photoproduct_qm import _dihedral_degrees
from experiments.cpd_anti_additive.validation_gate import read,source,checked,geometry_match
from experiments.cpd_anti_additive.sella_pilot import save,now,projected_metrics,BOHR
from experiments.cpd_anti_additive.conformational_fit_v2 import relative
from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-conformational-fit-v2-r1'


def main():
    plan=read(ART/'cpd-anti-conformational-inputs-v2/receipt.json')
    for s in plan['artifacts']:checked(s)
    records=read(checked(plan['inventory']))['records']
    result=read(ROOT/'assessment.json');checked(result['candidate'])
    fit=read(checked(result['fit']));after=read(checked(result['profile_results']))
    assert [r['case_id'] for r in after]==plan['case_ids']
    assert len(after)==19 and len(fit['coefficients'])==12
    assert all(-5.-1e-10<=c['shift_kcal']<=5.+1e-10 for c in fit['coefficients'])
    candidate=ROOT/'candidate'; rows=[]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params=app.CharmmParameterSet(str(candidate/'comparator_last.prm'))
    for p,claimed in zip(records,after):
        endpoint=p['endpoint'];folder=candidate/f'endpoint-{endpoint}'
        psf=app.CharmmPsfFile(str(folder/'fragment.psf'))
        names=read(folder/'atom_map.json')
        assert names==p['atom_map']
        x=np.loadtxt(checked(claimed['final_geometry']))
        cached=np.load(checked(claimed['raw_evaluations']))
        assert np.array_equal(x,cached['coordinates_A'][-1])
        system=psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        integ=mm.VerletIntegrator(.001);ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
        ctx.setPositions(x*u.angstrom);state=ctx.getState(getEnergy=True,getForces=True)
        energy=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
        gradient=-np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
        de=float(abs(energy-claimed['energy_kcal']));dg=float(np.max(abs(gradient-cached['gradients_kcal_A'][-1])))
        assert de<1e-5 and dg<1e-4
        idx=p['record']['torsion_indices'];q=np.array(p['geometry_bohr'])*BOHR
        if claimed['constraint_applied']:
            force_checks=[projected_metrics(x,gradient,idx,h)['max_projected_atom_gradient'] for h in (1e-4,1e-5,1e-6)]
            assert max(force_checks)<.001
            assert abs((_dihedral_degrees(*x[idx])-p['actual_dihedral_deg']+180)%360-180)<.01
        else:
            force_checks=[float(np.linalg.norm(gradient,axis=1).max())];assert force_checks[0]<.001
        chemistry=geometry_check(psf,q,x)
        assert chemistry['stereo_preserved'] and chemistry['graph_distances_passed']
        match=geometry_match(q,x,p['elements'],p['heavy_torsion_indices'])
        torsion_errors=[]
        for ids in p['heavy_torsion_indices']:
            err=abs((_dihedral_degrees(*x[ids])-_dihedral_degrees(*q[ids])+180)%360-180)
            labels=[names[i] for i in ids]
            torsion_errors.append(dict(names=labels,error_deg=err,
                pure_sugar=all("'" in name for name in labels)))
        torsion_errors.sort(key=lambda r:r['error_deg'],reverse=True)
        rows.append(dict(case_id=p['case_id'],energy_kcal=energy,energy_replay_error=de,gradient_replay_error=dg,
            independent_projected_force_checks=force_checks,branch_descriptors=match,
            largest_torsion_errors=torsion_errors[:5],chemistry_passed=True))
        del ctx,integ
    delta=relative([r['energy_kcal'] for r in rows],records)
    error=delta-np.array([p['qm_relative_kcal_mol'] for p in records])
    assert abs(np.sqrt(np.mean(error**2))-result['relaxed_energy']['rmse_kcal'])<1e-6
    assert abs(abs(error).max()-result['relaxed_energy']['max_abs_kcal'])<1e-6
    same_angle=[]
    for p in records:
        if p['branch']!='lower-basin':continue
        matches=[r for r in records if r['endpoint']==2 and r['branch']=='historical-original' and
            abs((r['actual_dihedral_deg']-p['actual_dihedral_deg']+180)%360-180)<.01]
        for other in matches:
            ia=plan['case_ids'].index(p['case_id']);ib=plan['case_ids'].index(other['case_id'])
            x=np.loadtxt(checked(after[ia]['final_geometry']));y=np.loadtxt(checked(after[ib]['final_geometry']))
            qm_match=geometry_match(np.array(p['geometry_bohr']),np.array(other['geometry_bohr']),p['elements'],p['heavy_torsion_indices'])
            # RMSD requires A, rather than bohr, for the QM pair.
            qm_match['basin_rmsd_A']*=BOHR
            mm_match=geometry_match(x,y,p['elements'],p['heavy_torsion_indices'])
            same_angle.append(dict(lower=p['case_id'],original=other['case_id'],qm_pair=qm_match,mm_pair=mm_match,
                qm_original_minus_lower_kcal=other['qm_relative_kcal_mol']-p['qm_relative_kcal_mol'],
                mm_original_minus_lower_kcal=rows[ib]['energy_kcal']-rows[ia]['energy_kcal']))
    summary=dict(replay_passed=True,reviewed_at=now(),assessment=source(ROOT/'assessment.json'),reviewer=source(Path(__file__)),
        cases=rows,rmse_kcal=float(np.sqrt(np.mean(error**2))),max_abs_kcal=float(abs(error).max()),
        geometry_descriptor_matches=sum(r['branch_descriptors']['basin_rmsd_A']<=.25 and
            r['branch_descriptors']['basin_max_torsion_deg']<=20 for r in rows),case_count=19,
        same_angle_pairs=same_angle,prospective_validation_complete=False,
        conformational_stage_passed=False,simulation_ready=False,
        interpretation='Exposed relaxed-energy regression and three representative geometries pass. Seven profile shape descriptors fail; no relabeling, second fit or validation acquisition.')
    save(ROOT/'independent_review.json',summary)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    colors={'historical-original':'#27639c','lower-basin':'#b35517','remote-unconstrained':'#6d428c'}
    for e,ax in zip((1,2),axes):
        ref=next(p for p in records if p['case_id']==plan['common_references'][str(e)])
        for branch,color in colors.items():
            ids=[i for i,p in enumerate(records) if p['endpoint']==e and p['branch']==branch]
            ids.sort(key=lambda i:(records[i]['actual_dihedral_deg']-ref['actual_dihedral_deg']+180)%360-180)
            if not ids:continue
            angles=[(records[i]['actual_dihedral_deg']-ref['actual_dihedral_deg']+180)%360-180 for i in ids]
            ax.plot(angles,[records[i]['qm_relative_kcal_mol'] for i in ids],'-o',color=color,label=branch+' QM',lw=1.4)
            ax.plot(angles,delta[ids],'--s',color=color,label=branch+' MM',lw=1.2,mfc='white')
        ax.axhline(0,color='0.7',lw=.6);ax.set(title=f'Endpoint {e}',xlabel='Glycosidic offset from fixed reference (degrees)',ylabel='Relative energy (kcal/mol)')
        ax.legend(fontsize=7)
    fig.suptitle('19 exposed conformers: relaxed-energy RMS 0.542, maximum 1.010 kcal/mol\nGeometry-branch and prospective validation remain incomplete',fontsize=11)
    fig.savefig(ROOT/'energy_profiles.png',dpi=170);fig.savefig(ROOT/'energy_profiles.svg');plt.close(fig)
    print({k:v for k,v in summary.items() if k not in ('cases','same_angle_pairs')})


if __name__=='__main__':main()
