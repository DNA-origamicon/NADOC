"""Publish measured screening evidence; no automatic physical qualification."""
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiments.gold_interfaces.screening.campaign import ROOT


def publish():
    data=json.loads((ROOT/'comparison.json').read_text());rows=data['gold']
    fig,axs=plt.subplots(2,3,figsize=(15,8),layout='constrained')
    for j,r in enumerate(rows):
        z=np.load(ROOT/r['case']/'screening_samples.npz');times=z['times_ns'];use=(times>.1+1e-9)&(times<=.3+1e-9)
        x=z['x_nm'];area=r['area_nm2'];label=r['case'];color=f'C{j}'
        axs[0,0].plot(x,z['water_counts'][use].mean(axis=0)/(area*.1),label=label,color=color)
        for species,style in ((0,'-'),(1,':')):
            axs[0,1].plot(x,z['ion_counts'][use,species].mean(axis=0)/(area*.1*.602214076),style,color=color,label=label+(' Na' if species==0 else ' Cl'))
        axs[0,2].plot(times,z['halfcell_excess_e'],alpha=.6,label=label,color=color)
        phi=z['potential_components_V'][use].mean(axis=0)
        axs[1,0].plot(z['grid_nm'],phi[0],label=label,color=color)
        axs[1,1].plot(times,z['density_nm3'],label=label,color=color,alpha=.6)
        if r['model']['surface_charge_e_nm2']:
            blocks=r['blocks_100ps'];axs[1,2].plot([b['end_ns'] for b in blocks],[b['fit'].get('lambda_nm',np.nan) for b in blocks],'o-',label=label,color=color)
    old=data['historical_abstract_wall'];late=old['matched_windows'][1]['fit']['lambda_nm']
    axs[1,2].axhline(late,color='k',ls='--',label='Old wall, late 20 ns')
    axs[0,0].set(xlabel='Distance from lower inner Au plane (nm)',ylabel='Water / nm³',title='Water layering and central density')
    axs[0,1].set(xlabel='Distance (nm)',ylabel='NaCl species concentration (M)',title='Solid Na; dotted Cl; sparse pilot statistics')
    axs[0,2].set(xlabel='Time (ns)',ylabel='Na − Cl in lower half (e)',title='Ionic compensation builds over time')
    axs[1,0].set(xlabel='Distance (nm)',ylabel='All-charge potential (V)',title='Explicit water included; midplane gauge')
    axs[1,1].set(xlabel='Time (ns)',ylabel='Central water / nm³',title='Central 0.8 nm; no fitted density threshold')
    axs[1,2].set(xlabel='End of 100 ps window (ns)',ylabel='Fitted length (nm)',title='Exploratory fits; boundary results retained')
    for ax in axs.ravel():ax.grid(alpha=.2);ax.legend(fontsize=6)
    fig.suptitle('Explicit Au screening pilots — physical validation remains open')
    fig.savefig(ROOT/'screening_comparison.png',dpi=160);plt.close(fig)
    paired=[]
    for seed in (317,719):
        selected={r['case'].split('_')[0]:r for r in rows if r['case'].endswith(str(seed))}
        if set(selected)!={'neutral','charged'}:continue
        n,c=selected['neutral'],selected['charged'];charge=c['model']['electrode_charge_magnitude_e']
        nz=np.load(ROOT/n['case']/'screening_samples.npz');cz=np.load(ROOT/c['case']/'screening_samples.npz')
        use=(cz['times_ns']>.1+1e-9)&(cz['times_ns']<=.3+1e-9);delta=cz['potential_components_V'][use].mean(axis=0)-nz['potential_components_V'][use].mean(axis=0)
        np.savetxt(ROOT/f'charge_response_{seed}.csv',np.c_[cz['grid_nm'],delta.T],delimiter=',',header='distance_nm,total_V,gold_V,ions_V,water_V',comments='')
        paired.append(dict(seed=seed,neutral_subtracted_central_field_mV_nm=c['central_field_mV_nm']-n['central_field_mV_nm'],neutral_subtracted_halfcell_compensation=(c['halfcell_ionic_excess_e']-n['halfcell_ionic_excess_e'])/charge,
            note='Paired exploratory difference; nonlinear response, no independent-block confidence interval'))
    (ROOT/'paired_response.json').write_text(json.dumps(paired,indent=2))
    table=['| Control | Water / nm³ | Central salt, mM | Half-cell ion excess, e | Compensation | Fitted length, nm |',
           '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in rows:
        fit=r['fits'][1];neutral=not r['model']['surface_charge_e_nm2'];comp='—' if neutral else f"{r['compensation']:.3f}"
        length='Not interpretable (neutral)' if neutral else f"{fit.get('lambda_nm',float('nan')):.3f}"+(' (at bound)' if fit.get('at_bound') else '')
        table.append(f"| {r['case']} | {r['water_density_nm3']:.3f} | {r['center_ionic_strength_mM']:.1f} | {r['halfcell_ionic_excess_e']:.2f} | {comp} | {length} |")
    cost=sum(json.loads(p.read_text()).get('wall_s',0) for p in ROOT.glob('*/*.run.json'))
    report=f'''# Explicit gold versus existing Debye screening tests

## Verdict

**The fixed-charge screening experiment ran; gold screening is not yet physically
validated.** These 300 ps pilots supply neutral controls and charge-response data.
They cannot establish a converged Debye length, specific adsorption or conducting
metal behavior. The neutral production gold implementation remains unchanged.

The charged seeds give **5.000 nm (optimizer upper bound)** and **0.434 nm**.
The upper-bound value is not a measured 5 nm screening length. Raw ionic
compensation is **81.8% / 64.1%**, or **72.0% / 46.3%** after subtracting each
paired neutral background. These differences remain unresolved by the pilot.
All four central water densities are 33.77–33.84 waters/nm³ and no water or ions
leave the compartment. Stable water density therefore does not establish stationary
ion screening. The central-field response also differs across seeds; no zero-field
claim is made from a midplane potential gauge.

## Measured primary window: 100–300 ps

{chr(10).join(table)}

Compensation divides the lower-half Na−Cl excess by the imposed lower-electrode
charge magnitude. It is undefined for neutral controls. The same seed's neutral
background is also subtracted in [paired_response.json](paired_response.json).
Neither raw nor subtracted compensation is an automatic acceptance score.

The old abstract-wall RunPod trajectory gives **0.655 nm** in its matched early
200 ps window and **0.556 nm** over its late 20 ns. Its central ionic strength
changes from **276.2 to 320.3 mM** between those windows. Gold cannot be required
to match the late result on a much shorter timescale or with unmeasured dielectric
response. Area, timestep, contact forces, solvent inventory and normal cell size
also differ; see the [declared protocol](../README.md).

Even within the historical late 20 ns, individual 200 ps windows yield fitted
lengths whose empirical 2.5th–97.5th percentiles span **0.314–1.667 nm**. This is
window-to-window variability, not a confidence interval or an acceptance band.
It demonstrates how weakly a single new 200 ps fit can constrain model agreement.

The historical analysis uses 300 ps bootstrap blocks. The new 200 ps primary
window contains **zero complete blocks**, so no screening confidence interval is
reported. Density intervals in the JSON are conditional sampling estimates, not
physical acceptance limits. Separate 100 ps fits and exclusion sensitivity are
retained, including fit boundaries and optimizer results for neutral null controls.

## Evidence

- [Profiles, time evolution and window fits](screening_comparison.png)
- [All measurements and historical comparison](comparison.json)
- [Input and native-run integrity](integrity_audit.json)
- [Deterministic PB estimator check](estimator_reference.json)
- [Historical early/late reanalysis](historical_comparison.json)
- [Historical 200 ps window variability](historical_short_window_variability.json)

Per-frame water/ion counts, temperatures and potential components remain in local
`screening_samples.npz` files. The microscopic potential includes explicit water,
ions and charged Au separately; their sum reproduces the all-charge calculation.
Neutral-subtracted potential component CSVs are retained for each paired seed.
Per-case profile CSVs include water density, ion concentrations and dipole orientation;
the JSON also reports the central all-charge field slope without claiming zero field.
Water polarization is why ionic screening agreement alone cannot validate the
full double-layer potential: [Limaye et al.](https://doi.org/10.1039/D3FD00114H).

## What was implemented

An isolated experiment assigns prescribed equal/opposite charges to the inner Au
layers while retaining neutral-IFF LJ contact parameters. PSF and EW3DC charges
are identical, total charge is zero, and the experimental manifests are rejected
by the registered neutral-gold verifier. There is **no constant-potential solve,
induced/image response, voltage conversion or production API change**.

Both gold arms use 1 fs steps. This avoids simply inheriting the old 4 fs choice;
[timestep-dependent rigid-water errors](https://doi.org/10.1039/D4SC08437C) remain
an independent validation question, along with the electrolyte dielectric response.

## Next steps supported by these data

1. Assess independent longer stationary windows at this geometry and controlled
   inventory; estimate uncertainty from block-length sensitivity before comparing
   a gold screening length with continuum or historical values.
2. Add a same-integrator abstract-wall comparison and a salt series. Use measured
   central ionic strength and a force-field-specific dielectric assessment.
3. Validate matched published gold hydration/ion contact separately. The present
   prescribed-charge Au model is an intermediate screening diagnostic, not a
   conducting-metal or adsorption benchmark.
4. Proceed with the source-audited constant-potential design only after choosing
   its charge-width/hardness model and independent energy/force reference.

## Cost and checks

{len(rows)} completed 300 ps dynamics controls; recorded native wall time including
minimizations: **{cost/60:.2f} minutes**. Local GPU only. Prior calibration/restart
work plus this campaign remains within the four-hour ceiling. The existing Debye
and gold unit checks passed (29 tests). Native integrity checks are recorded
separately from physical qualification. Scoped Ruff checks and `git diff --check`
passed. No application/backend behavior changed, so app/browser suites were not
rerun for this isolated experiment.
'''
    (ROOT/'RESULTS.md').write_text(report.replace('(../README.md)', '(../../experiments/gold_interfaces/screening/README.md)'))
    dest=Path(__file__).resolve().parent/'results';dest.mkdir(exist_ok=True)
    for name in ('RESULTS.md','comparison.json','integrity_audit.json','historical_comparison.json','historical_short_window_variability.json','estimator_reference.json','paired_response.json','screening_comparison.png'):
        source=ROOT/name
        if source.exists():
            if name=='RESULTS.md':(dest/name).write_text(report)
            else:shutil.copy2(source,dest/name)
    for source in ROOT.glob('charge_response_*.csv'):shutil.copy2(source,dest/source.name)
    for r in rows:shutil.copy2(ROOT/r['case']/'screening_profiles.csv',dest/f"{r['case']}_profiles.csv")
    print(table,cost/60)

if __name__=='__main__':publish()
