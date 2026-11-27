"""Audit against pinned upstream scoring code and summarize the CPD-pair screen."""
import ast,hashlib,json,math
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.distances import calc_bonds,calc_dihedrals
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
O=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 r=json.loads((O/'summary.json').read_text());z=np.load(O/'timeseries.npz');pairs=r['pairs'];params=r['parameters']
 assert r['n_candidates']==153 and r['n_sampled_frames']==r['n_total_frames']==10000
 assert len(set(z['pair_ids']))==153 and np.array_equal(z['frame_indices'],np.arange(10000))
 assert np.isfinite(z['upstream_propensity']).all()
 schema=json.loads((O/'upstream_kimmdy-yaml-schema.json').read_text())['properties']
 values=[schema[k]['default'] for k in ['k1','k2','d0','n0']]
 assert values==[params[k] for k in ['k1_per_nm','k2_per_deg','d0_nm','eta0_deg']]
 # Execute only the inspected pure scalar function from the pinned official source.
 tree=ast.parse((O/'upstream_reaction.py').read_text());fun=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='calculate_rate')
 scope={'math':math};exec(compile(ast.Module(body=[fun],type_ignores=[]),'pinned_upstream_calculate_rate','exec'),scope)
 direct=np.fromiter((scope['calculate_rate'](*values,float(d),float(e)) for d,e in zip(z['d_mid_nm'].flat,z['eta_deg'].flat)),dtype=float,count=z['d_mid_nm'].size).reshape(z['d_mid_nm'].shape)
 np.testing.assert_allclose(direct,z['upstream_propensity'],rtol=1e-14,atol=1e-15)
 intended=next(i for i,p in enumerate(pairs) if p['intended_weld'])
 u=mda.Universe(r['topology'],r['trajectories'][0]);geometry_checks=[]
 ids=sorted(set([0,5000,9999]+[p['representative_max_propensity']['frame'] for p in pairs[:5]]+[pairs[intended]['representative_max_propensity']['frame']]))
 ix=np.array([[p['site_a']['c5_serial'],p['site_a']['c6_serial'],p['site_b']['c6_serial'],p['site_b']['c5_serial']] for p in pairs])
 for fi in ids:
  ts=u.trajectory[fi];x=u.atoms.positions[ix]
  d=calc_bonds(x[:,:2].mean(1),x[:,2:].mean(1),box=ts.dimensions)/10
  e=np.degrees(calc_dihedrals(x[:,0],x[:,1],x[:,2],x[:,3],box=ts.dimensions))
  np.testing.assert_allclose(d,z['d_mid_nm'][:,fi],atol=3e-6)
  error=np.abs((e-z['eta_deg'][:,fi]+180)%360-180);assert error.max()<.01,error.max()
  geometry_checks.append(dict(frame=fi,max_distance_error_nm=float(np.max(abs(d-z['d_mid_nm'][:,fi]))),max_angle_error_deg=float(error.max())))
 old=np.load(O.parent/'2bc15e9e2531/series.npz')
 mid=np.linalg.norm(old['coordinates_ang'][:,1:3].mean(1)-old['coordinates_ang'][:,7:9].mean(1),axis=1)/10
 np.testing.assert_allclose(mid,z['d_mid_nm'][intended],atol=3e-6)
 angle_error=np.abs(z['eta_deg']-params['eta0_deg']);angle_error=np.minimum(angle_error,360-angle_error)
 corner=(z['d_mid_nm']<.45)&(angle_error<45)
 assert np.array_equal(corner.sum(1),[p['reactive_frames'] for p in pairs])
 summaries=[]
 for i,p in enumerate(pairs):
  quarters=[]
  for indices in np.array_split(np.arange(10000),4):
   quarters.append(dict(upstream_mean=float(z['upstream_propensity'][i,indices].mean()),periodic_mean=float(z['periodic_propensity'][i,indices].mean()),reactive_frames=int(corner[i,indices].sum())))
  summaries.append(dict(pair=p['id'],rank=p['rank'],same_strand=p['same_strand'],intended=p['intended_weld'],quarters=quarters))
 m=json.loads((O.parent/'2bc15e9e2531/summary.json').read_text())
 for f in m['files']:
  st=Path(f['path']).stat();assert (st.st_size,st.st_mtime_ns)==(f['bytes'],f['mtime_ns'])
 assert sha(Path(r['topology']))==m['topology_sha256']
 audit=dict(upstream_commit=json.loads((O/'upstream_provenance.json').read_text())['commit'],upstream_scalar_evaluations=int(direct.size),scalar_scores_match=True,geometry_checks=geometry_checks,intended_distance_matches_previous_analysis=True,source_size_mtime_unchanged=True,code_hashes={str(p):sha(p) for p in [Path('backend/core/kimmdy_analysis.py'),Path('backend/core/cpd_metrics.py'),O/'upstream_reaction.py',O/'upstream_kimmdy-yaml-schema.json',O/'run.py',O/'assess.py']},blocks=summaries)
 (O/'verification.json').write_text(json.dumps(audit,indent=2)+'\n')
 rows=[]
 for p in pairs[:10]:
  rows.append(f"| {p['rank']} | {p['id']} | {'same strand' if p['same_strand'] else 'cross-strand'} | {p['upstream_propensity_mean']:.5f} | {p['periodic_propensity_mean']:.5f} | {10*p['d_mid_min_nm']:.2f} | {p['reactive_frames']} |")
 ip=pairs[intended];cross=next(p for p in pairs if not p['same_strand'])
 hits=[p for p in pairs if p['reactive_frames']]
 fig,ax=plt.subplots(2,1,figsize=(11,8))
 n=10;y=np.arange(n);ax[0].barh(y-.18,[p['upstream_propensity_mean'] for p in pairs[:n]],height=.36,label='Original KIMMDY angle convention');ax[0].barh(y+.18,[p['periodic_propensity_mean'] for p in pairs[:n]],height=.36,label='Periodic-angle correction');ax[0].set_yticks(y,[p['id'] for p in pairs[:n]]);ax[0].invert_yaxis();ax[0].legend(fontsize=8);ax[0].set_xlabel('Mean geometric propensity (dimensionless)')
 chosen=list(dict.fromkeys([0,pairs.index(cross),intended]))
 for i in chosen:
  times=z['times_ps'].reshape(200,50).mean(1)/1000;scores=z['upstream_propensity'][i].reshape(200,50).mean(1)
  ax[1].plot(times,scores,label=pairs[i]['id']+(' (intended)' if i==intended else ''))
 ax[1].set_xlabel('Time (ns)');ax[1].set_ylabel('1 ns block mean propensity');ax[1].legend(fontsize=8);fig.tight_layout();fig.savefig(O/'pair_scores.png',dpi=150)
 report=f'''# KIMMDY CPD-pair scoring: 2hb_1xT, created 2026-11-11 09:56 MST

Applied KIMMDY's published geometric scoring expression through NADOC's existing PSF/DCD adapter, using all **18 thymines, 153 unordered pairs and 10,000 frames (200 ns)**. Both same-strand and cross-strand candidates are included, without a proximity prefilter, frame cap, or structural-pairing gate. This is pair scoring on the saved unwelded trajectory, not a KIMMDY reactive-MD run or stochastic reaction selection.

The original upstream score is the primary ranking. The separately labeled periodic-angle correction is also retained. The full score matrix was independently evaluated using the pure scalar function extracted from official upstream commit `{audit['upstream_commit']}`: all **1,530,000 evaluations agree**. The four parameters also match its configuration defaults. Independent MDAnalysis geometry checks passed, and the intended-pair distances agree with the preceding eight-isomer analysis.

[Ranked pair table](pairs.tsv) · [Plots](pair_scores.png) · [Full summary](summary.json) · [Verification and 50 ns blocks](verification.json)

| Rank | Pair | Relationship | Mean upstream score | Mean periodic score | Minimum midpoint distance (Å) | Close/aligned frames |
|---|---|---|---:|---:|---:|---:|
{chr(10).join(rows)}

The intended inserted-T pair **{ip['id']}** ranks **{ip['rank']}/153** by mean upstream score: mean **{ip['upstream_propensity_mean']:.6f}**, maximum **{ip['upstream_propensity_max']:.6f}**, periodic mean **{ip['periodic_propensity_mean']:.6f}**, minimum midpoint separation **{10*ip['d_mid_min_nm']:.3f} Å**, **{ip['reactive_frames']} close/aligned frames**. Its score is ≥0.1 in {ip['pct_primary_ge_0_1']:.2f}% of frames. That percentage is a score-threshold statistic, not a reaction probability.

The highest-scoring cross-strand pair is **{cross['id']}** (overall rank {cross['rank']}); its mean upstream score is {cross['upstream_propensity_mean']:.6f}, minimum midpoint distance {10*cross['d_mid_min_nm']:.3f} Å, and close/aligned count {cross['reactive_frames']}.

Across all pairs, **{len(hits)} pairs** have any close/aligned frames, totaling **{int(corner.sum())} pair-frame observations** in **{int(corner.any(0).sum())} distinct saved frames**. These are correlated observations, not independent reactions. The close/aligned diagnostic uses NADOC's existing `midpoint distance <4.5 Å` and circular angular offset from 16.74365° `<45°`; it is not the preceding eight-isomer classifier, and is not asserted to be the paper's quantum-yield calibration threshold.

## What this score means

The upstream function is `exp[-2.017017 |d_nm−0.157177| −0.03003003 |eta_deg−16.743652|]`. It has no hard distance cutoff, so even well-separated bases have a nonzero score. A high rank or a score above 0.1 alone does not demonstrate two feasible forming C–C bonds. Distances, close/aligned occupancy and stereochemical feasibility must be read alongside the score.

The earlier screen requires both proposed bonds to lie between 2.5 and 4 Å, plus face and torsional compatibility with a specified CPD stereoisomer. Its zero encounters therefore need not imply zero KIMMDY scores. This KIMMDY expression does not supply an eight-isomer branching model; it cannot settle cis-anti-I versus cis-syn-II from pair rankings. The KIMMDY study specifically notes that anti and 6–4 products are outside the implemented plugin's scope. [Hartmann et al., 2026](https://doi.org/10.1038/s41467-026-71955-2)

The model/source is pinned at [the official dimerization plugin](https://github.com/graeter-group/kimmdy-dimerization/tree/{audit['upstream_commit']}). NADOC supplies segment-safe atom mapping, CHARMM thymine names and local periodic imaging for the NAMD trajectory; no topology mutation, KMC selection, new MD or product formation was run. No absolute yield or kinetic rate is inferred.

## Reproduce

From the repository root, run `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261112/kimmdy/run.py`, then the same interpreter on `assess.py`. The exact CLI argument list is retained in `command.json`. The upstream source and schema are pinned and retained beside these scripts. Original molecular structures and trajectories were unchanged.
'''
 (O/'review.md').write_text(report)
 print(json.dumps({'intended':ip,'top_cross_strand':cross,'corner_pairs':[{'id':p['id'],'frames':p['reactive_frames']} for p in hits]},indent=2))
if __name__=='__main__':main()
