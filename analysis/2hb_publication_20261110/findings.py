"""Render numerical tables from machine-readable results."""
import json
from pathlib import Path
O=Path(__file__).resolve().parent
R=json.loads((O/'results.json').read_text());D=json.loads((O/'replica_diagnostics.json').read_text())
s=['Numerical findings','',f'Analyzed {len(R)} jobs and {sum(r["sampled_frames"] for r in R):,} structural samples. All statistics below use each run\'s last 75% of available sampled frames; they are not claimed to be equilibrated estimates.','', 'Short replicas (three 20 ns runs per condition; 2 fs)', '', 'Values are mean of replica means ± between-replica SD, not confidence intervals and not within-run fluctuation amplitudes. Rhat is the largest classical split-Rhat among centroid separation, helix tilt and Rg.','', '| Condition | Separation (Å) | Tilt (degrees) | WC fraction | Largest shape Rhat |','|---|---:|---:|---:|---:|']
for name,e in D.items():
 def fmt(k):
  v=e['metrics'][k];return f'{v["mean_of_replica_means"]:.2f} ± {v["between_replica_sd"]:.2f}'
 rh=max(e['metrics'][k]['split_Rhat'] for k in ['helix_centroid_sep_A','helix_tilt_deg','Rg_A'])
 s.append(f'| {name} | {fmt("helix_centroid_sep_A")} | {fmt("helix_tilt_deg")} | {fmt("wc_fraction")} | {rh:.2f} |')
s+=['','Longer runs and retained historical coverage','','Values are within-run mean ± temporal SD. ESS is an autocorrelation diagnostic, not an equilibrium certificate. Times are America/Denver. Duration is actual DCD coverage, including resume files, not the name in the requested run.','','| Design / created | DCD time range (ns) | Separation (Å) | Tilt (degrees) | WC fraction | Tilt ESS |','|---|---:|---:|---:|---:|---:|']
for r in R:
 if r['created'].startswith('2026-10'):continue
 def fmt(k):
  v=r['statistics'][k];return f'{v["mean"]:.2f} ± {v["sd"]:.2f}'
 lo=min(f['first_ns'] for f in r['files']);hi=max(f['last_ns'] for f in r['files'])
 s.append(f'| {r["design"]} / {r["created"][:16].replace("T"," ")} | {lo:.2f}–{hi:.2f} | {fmt("helix_centroid_sep_A")} | {fmt("helix_tilt_deg")} | {fmt("wc_fraction")} | {r["statistics"]["helix_tilt_deg"]["ess"]:.1f} |')
s+=['','Coverage and integrity','','| Design / created | Sampled frames | Timestep (fs) | Largest sampled bond (Å) | Chirality failures |','|---|---:|---:|---:|---:|']
for r in R:s.append(f'| {r["design"]} / {r["created"][:16].replace("T"," ")} | {r["sampled_frames"]} | {r["config"]["timestep"]} | {r["max_dna_bond_A"]:.3f} | {r["chirality_failures"] if r["chirality_failures"] is not None else "N/A"} |')
(O/'numerical_findings.md').write_text('\n'.join(s)+'\n')
