# Cis-anti-I full-DNA NAMD engineering result

**The isolated NAMD-testable milestone passes.** Both the cis-anti interstrand
model and its undamaged control completed 100 ps of native NAMD. Independent
review recomputed the four static comparisons, replayed 200 saved trajectory
frames plus both final binary geometries, checked 202 finite energy records and
verified frozen input hashes. Neither system is scientifically qualified for
preliminary structural research or promoted into the normal application.

The [portable NAMD bundle](../.development-artifacts/cpd-anti-solvated-namd-bundle-v2-r1/README.md)
contains runnable configurations, PSFs, double-precision coordinates, all parameter
files and native evidence. Its paths are portable; input verification and a SHA-256
manifest accompany it. Run a disposable copy, preserving the archived evidence.

## Fixed protocol and actual observations

Each system contains 30,867 atoms: 96 nucleotides / 3,043 solute atoms, 9,223
CHARMM modified TIP3P waters, 124 Na+ and 31 Cl−. The shared fixed box is
44.930 × 67.438 × 112.763 Å, with 150.66 mM excess salt and neutralizing counterions.
The protocol uses ordinary masses, 1 fs, rigid water, PME, a 300 K Langevin target
and seed 41017. There are no artificial positional/chirality restraints and no
additional minimization. CPU bonded terms (`bondedGPU 0`) and GPU nonbonded/PME
are used consistently for static validation and dynamics.

| Native result | Cis-anti | Control |
|---|---:|---:|
| Dynamics completed | 100,000 steps / 100 ps | 100,000 steps / 100 ps |
| Saved 1 ps frames + final binary geometry checked | 100 + 1 | 100 + 1 |
| Chemical stereo comparisons per geometry | 298 | 288 |
| Bond/equilibrium ratio envelope | 0.88470–1.12761 | 0.87823–1.12516 |
| Saved-frame stereo inversions / severe solute contacts / ring piercings | 0 / 0 / 0 | 0 / 0 / 0 |
| Recorded temperature range, K | 204.77–303.46 | 203.57–304.40 |
| Final temperature, K | 302.27 | 299.37 |
| Maximum base displacement from original source across checked MD geometries, Å | 9.7637 | 8.5098 |

The temperature ranges include the initial velocity/rigid-water constraint
transient. This is a bounded NVT startup/smoke, not an equilibrated production
segment. Geometry checks cover saved frames and final coordinates; they do not
prove behavior between frames. The control has a different earlier conditioning
history, so this pair does not establish a causal lesion effect.

![Native smoke evidence](../.development-artifacts/cpd-anti-solvated-engine-v2e/native_smoke_evidence.png)

Native service: `cpd-anti-solvated-engine-service-v2e`, completed 2026-09-26
22:25:57 UTC, return code zero. The two-case job took about 517 seconds. Together
with the 388-second protected construction and short implementation diagnostics,
this remains within the frozen two-hour engine allowance. The requested delayed
fitted-conditioning failure was acknowledged separately and remains failed.

## Implementation checks and retained failures

Static comparisons use identical double coordinates, OpenMM Reference NoCutoff,
and unswitched NAMD with a 1,000 Å cutoff covering every pair. The existing v2
rule is absolute **or relative**: max(0.001, 10⁻⁴ × reference scale), separately
for energy and maximum force component. No numerical criterion was changed.

| Fixture | Energy error / allowance, kcal/mol | Max force error / allowance, kcal/mol/Å |
|---|---:|---:|
| Anti full solute | 0.010497 / 4.487507 | 0.0017993 / 0.0041325 |
| Control full solute | 0.113625 / 4.458843 | 0.0015512 / 0.0045965 |
| Anti two-water/Na/Cl | 0.0000050 / 0.001 | 0.00002503 / 0.001 |
| Control two-water/Na/Cl | 0.0000863 / 0.001 | 0.00002430 / 0.001 |

These verify solute and solvent/ion implementation; they are not an independent
full periodic-PME equivalence test. Full-system coverage and parameter-export
equivalence were checked during assembly; the periodic trajectory is native NAMD.

V2's empty solvent-fixture PSF title caused native rejection before energy.
V2b/v2c preparation checks caught ineffective title/group serialization changes
before launch. V2d corrected the format, then failed the solvent-force comparison
at 0.001587/0.001767 versus the unchanged 0.001 limit. No earlier version ran MD.
A separately registered, identical-input CPU-bonded diagnostic reduced those
errors to 0.00002503/0.00002430. This supports a GPU bonded-arithmetic explanation.
The [NAMD GPU guide](https://www.ks.uiuc.edu/Research/namd/cvs/ug/node103.html)
documents the execution control and GPU/CPU force differences. V2e changes this
execution option in both validation and MD; parameters and coordinates are unchanged.
All failed versions, logs, forces and diagnoses remain archived.

## What this does and does not complete

The [source repair and construction report](cpd_anti_source_stereo_repair_20260926.md)
documents the actual preparation advance: chemically mapped sugar references,
explicit reconstruction at D000:7 and D002:26, staged phosphate repair with temporary
sugar protection, and 5,000 final minimization steps without artificial restraints.
It corrected the chemical-source blocker without fitting new force-field terms.

The immutable [v2 policy](../experiments/cpd_anti_additive/preliminary_policy_v2.json)
explicitly allows isolated engine tests with failed/incomplete scientific stages.
The existing 0.01 kcal/mol/Å stationarity and 3.5 Å product-placement screens remain
failed and separately reported. No optimizer completion is called minimum
certification. No Hessian or full-DNA minimum certificate exists.

The next scientific stage remains the preregistered four prospective ±22.5° QM
targets against the locked first-round candidate, with the seven exposed profile
geometry mismatches still visible. The native smoke does not justify an automatic
refit, longer trajectory, research qualification or product promotion. No fit
round, policy hash, threshold, normal application asset or saved design changed.
All work used local resources; no cloud spending.

The delayed v2e completion wake was received and acknowledged at 2026-09-26
23:01:16 UTC. A read-only replay reproduced the native static comparisons and all
202 trajectory/final geometry checks without changing the archived review or
running new energy calculations or dynamics. All 104 bundle files still match
their manifest. The completion and bundle verification receipts are under
`cpd-anti-solvated-engine-service-v2e`. The separately registered prospective QM
batch remains active under its original caps; this receipt does not alter any
scientific verdict or acceptance criterion.
