# CPD cis-anti-I validation closeout — 10 October 2026

All six registered 10 ns trajectories passed their native and finite-context
audits: 60 ns total, 6,000 distinct saved frames. The final control3 run completed
normally in 9.09 service hours, below its15h cap. Its independent audit verified
1,000 DCD cells,100 periodic checkpoint triples,30 stratified chemistry frames,
10 binary endpoints and1,010 worker geometry records. Independent chemistry
replay is sampled; worker all-frame checks must not be described as independent
all-frame replay. Split-run audits preserve pauses and exclude uncheckpointed tails.

The authorized preliminary validation and research restart packaging endpoint is
complete. Full production readiness,minimum certification and equilibrium are
not established. No force-field registry or application capability was changed.
No further MD or long production run was launched.

## Structural interpretation

The same28 preregistered atom-contact identities and3.5A descriptive cutoff were
used across allsix runs. Fractions below average correlated trajectory samples;
frames and1ns blocks are not independent experimental replicates.

| Run | Prepared | Full10ns | First5ns | Last5ns |
|---|---:|---:|---:|---:|
| anti 1 | 0.643 | 0.530 | 0.541 | 0.520 |
| control 1 | 0.679 | 0.836 | 0.834 | 0.838 |
| anti 2 | 0.821 | 0.778 | 0.790 | 0.766 |
| control 2 | 0.571 | 0.707 | 0.709 | 0.706 |
| anti 3 | 0.786 | 0.790 | 0.778 | 0.802 |
| control 3 | 0.821 | 0.771 | 0.794 | 0.749 |

Matched anti-minus-control means are−0.305,+0.071,+0.019. The ordering changes
between replicas and prepared baselines differ. Anti1's lower retention remains
part of the evidence; anti2/anti3 do not erase it. Control3 retention decreases
between halves. No consistent causal lesion effect,mechanical response,convergence
or transferability is established. Keep all six outcomes; no selective refit or
extension is justified by these results alone.

## Physical and numerical scope

Across replicas,late5ns temperatures span299.185–299.231K,group pressures
+0.192–+2.146bar,densities1.022883–1.022959g/cm3,and addedNaCl149.833–149.844mM.
AddedNaCl excludes93 neutralizing sodium and is not total ionic strength.
Fresh large-cube force-switch NPT checks address the previously observed gross
solvent-cavity/pressure failure within the sampled evidence. No favorable posthoc
pressure/density cutoff or equilibrium claim is introduced. Control3 minimum
image clearance37.991A and maximum sampled endpoint void3.331A passed the
registered finite-context checks. Its native rate was27.08ns/day.

Earlier image-clearance and physical-solvent failures remain archived as failures.
Anti2's startup bad_any_cast remains unresolved despite subsequent successful
bounded recovery. Native optimizer convergence and directional curvature do not
certify an all-mode energy minimum.

## Restart package and evidence

[Portable archive](../.development-artifacts/cpd-anti-restart-package-v17.tar.gz)
contains six final coor/vel/fullXSC states,PSF/PDB inputs,forcefields,relocatable
static and continuation configurations,a standalone hash-checking runner,review
receipts and provenance. NAMD itself is not included. Allsix relocated endpoints
passed real NAMD static restart-energy checks with zero MD steps; the relocation
path contained spaces. Tests also cover hash tampering,bounds and refusal to
overwrite an existing run directory.

[Package instructions](../.development-artifacts/cpd-anti-restart-package-v17/README.md)
default to static checks. Explicit continuation is limited to1ns per invocation
and a2h timeout; no automatic chaining. The runner's native/energy pass is not a
replacement for full checkpoint,chemistry,solvent and structural review.
Full Langevin bitwise continuity is not promised; fresh seeds are declared.

[Closeout receipt](../.development-artifacts/cpd-anti-gpu-cube-context-v5/campaign_closeout_v17.json)
pins the archive,manifest and relocated native validation.
[All-six review](../.development-artifacts/cpd-anti-gpu-cube-context-v5/campaign_review_v17.json)
and [comparison](../.development-artifacts/cpd-anti-gpu-cube-context-v5/replicate_comparison_v17.json)
retain per-replica evidence.
[Provenance crosswalk](../.development-artifacts/cpd-anti-gpu-cube-context-v5/provenance_errata_v17.json)
corrects inherited least_squares/trf attribution to the executed finite-difference/
SLSQP v3 method,distinguishes historical receipt date from actual execution time,
and separates inherited source-QM constraint fields from executed MM constraints.
Original metadata and failed native outputs were not rewritten.

No cloud spending. No simulation remains authorized for automatic launch after
this closeout. Further research should specify its question and applicability
before extending the trajectories.
