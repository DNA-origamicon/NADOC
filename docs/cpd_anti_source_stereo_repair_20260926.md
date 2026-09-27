# Source sugar stereochemistry repair and bounded construction

**Outcome:** corrected anti and control now pass the isolated full-system100ps
NAMD engineering test. See the [native report and bundle](cpd_anti_full_dna_engine_20260926.md).
The construction stationarity/product screens and scientific qualification remain
failed/incomplete; the history below preserves how this milestone was reached.

The delayed fitted-conditioning wake `8f4a206c-9f01-42fa-a115-dbd4a56a044e`
was acknowledged at2026-09-26 21:40:33UTC. Its completion audit independently
recomputed the final Reference force, checked20 saved geometries and replayed
1002 objective log records plus the three counted preflight evaluations.
The1000-iteration failure remains: maximum mobile force1.3606541kcal/mol/Å,
base displacement14.0514908Å; unconstrained phase never ran. The later discovery
of an incorrect source sugar reference is attached without rewriting that result.

## Correcting the reference and preparation coordinates

The [solvent/control diagnostic](cpd_anti_solvated_construction_20260926.md)
identified near-planar D000:7:C3′ and opposite-handed D002:26:C3′. Sugar references
now use consistently ordered neighbors mapped to both original QM deoxyriboses:

| Center | Canonical neighbors | Required sign in this ordering |
|---|---|---:|
| C1′ | O4′, C2′, glycosidic N, H1′ | Negative |
| C3′ | C2′, C4′, O3′, H3′ | Positive |
| C4′ | C3′, C5′, O4′, H4′ | Positive |

The glycosidic N is N1 for pyrimidines and N9 for purines. These are explicit
geometric neighbor conventions, not an uncomputed assignment of CIP labels.
Both QM references agree. All288 source sugar centers are assessed against this
mapping; anti also retains all ten direct local QM comparisons. Historical
source-relative reports remain intact and retain their stated, narrower meaning.

The first reconstruction used native psfgen `guesscoord` with only O3′/H3′ missing
at the two sites. The original segment graph, patches and CHARMM topology were
retained. Psfgen reported poorly guessed heavy coordinates; anti passed local
signs but had bond defects, and the control still had the wrong D002:26 sign.
Those files are retained in `cpd-anti-source-stereo-repair-v1b`. Its initial v1
preparation stopped before native work on OpenMM/native atom-name normalization.
The [psfgen guide](https://www.ks.uiuc.edu/Research/vmd/plugins/psfgen/ug.pdf)
describes internal-coordinate guessing; it does not guarantee good coordinates
for a strained, multiply anchored phosphate connection.

The explicit alternative in `cpd-anti-source-stereo-explicit-v2` changes exactly
four coordinates per case: O3′ and H3′ at D000:7 and D002:26. C3′, C2′ and C4′
remain fixed. The O3′ unit vector is solved from its projections onto the existing
C3′–C2′ and C3′–C4′ axes to reproduce the two parent equilibrium angles,109.7°.
The QM sign selects one of the two mirror solutions. H3′ points opposite the
three heavy substituents. Native C3′–O3′/H3′ lengths1.433/1.111Å are retained.
This is an analytic seed construction using existing coefficients, not a fit.

| Canonical C3′ neighbor volume, Å³ | Anti seed → reconstructed | Control seed → reconstructed |
|---|---:|---:|
| D000:7 | 0.29718 →8.57962 | 0.28328 →8.28444 |
| D002:26 | −9.14757 →9.02072 | −11.92081 →8.27573 |

All chemically mapped signs pass afterward. Every other double-precision atom
coordinate, including solvent and ions, is unchanged. Topology, charges, masses
and force-field coefficients are unchanged. Closest changed-atom/solvent distances
exceed3.36Å. No new QM or MM energy was evaluated for this reconstruction.

**This is not a completed coordinate repair.** Anti still has two stretched
O3′–P links (2.985/2.870Å versus1.600Å equilibrium); the control has six bond
violations, including a7.652Å O3′–P link, and two severe contacts. Those explicit
failures motivate rebuilding the adjoining phosphate positions while temporarily
holding the corrected sugar frames. They are not acceptable dynamics inputs.

![Same-frame coordinate proposal](../.development-artifacts/cpd-anti-source-stereo-explicit-v2/repair_review.png)

The actual four-coordinate proposal was visually inspected in the same frame;
the strained adjoining phosphate bonds are visible. This artifact is isolated,
not product-geometry authorization. No saved design or normal application path
has changed.

## Frozen protected-construction method

`cpd-anti-stereo-protected-construction-v2` contains the new plan, worker and input
hashes; `cpd-anti-stereo-protected-construction-service-v2` supplies the external
watcher. Both cases retain the30,867-atom paired solvent boxes,150mM excess NaCl
plus counterions, and exact native parameter-only files from the preceding attempt.

| Stage | Maximum steps per case | Temporary controls |
|---|---:|---|
| Solvent relaxation | 500 | All solute fixed |
| Phosphate repair | 1500 | Ten atoms defining the two repaired C3′ frames fixed; heavy positional k=5; sugar improper k=50 |
| Release repaired frames | 1500 | No fixed atoms; heavy positional k=1; sugar improper k=50 |
| Weaken sugar restraints | 1500 | No positional restraints; sugar improper k=10 |
| Unrestrained construction | 5000 | All artificial restraints removed; water remains rigid |

Positional k is in kcal/mol/Å². Improper k is in kcal/mol/radian², with the
nonperiodic harmonic NAMD convention and wrapped angular differences. Temporary
four-neighbor impropers cover all288 sugar centers, with targets from the circular
mean of the two original QM neighbor-dihedral values. They are **construction
restraints**, not newly fitted or exported CHARMM coefficients. The
[NAMD restraint documentation](https://www-s.ks.uiuc.edu/Research/namd/3.0/ug/node29.html)
specifies this extra-bonded-term mechanism. The numerical strengths and budget
are prospective engineering choices, not literature accuracy certificates.

Before minimization, native extra-minus-baseline energies and forces must match
an independent OpenMM calculation of the added harmonic torsions under the
unchanged v2 absolute-or-relative limits. Every50-step checkpoint and saved frame
is checked for chirality; endpoints also receive bond/contact/ring-crossing
checks. A new inversion, severe contact or piercing terminates the affected case.
Known starting contacts may be repaired but cannot remain at final acceptance.
The two cases ran sequentially, at most10,000 minimization steps each, two hours
total, eight local native workers and12GiB. There was no continuation or chained MD.

Both cases completed10,000 steps. Independent read-only replay verified400 native
logs,400 saved frames, all frozen input hashes and every saved binary endpoint.
The last5000 steps per case ran without fixed atoms, positional restraints or
temporary impropers. All298 anti/288 control chemical stereo checks passed in
each saved frame. Final geometries have no severe solute contacts or ring piercings.

| Final construction metric | Anti | Control |
|---|---:|---:|
| Bond/equilibrium ratio range |0.96291–1.04978|0.96300–1.04912|
| Maximum native solute force, kcal/mol/Å |36.30125|38.56782|
| Maximum base displacement from source, Å |8.25360|3.50504|
| Chemical geometry eligible for engine review |Yes|Yes|
| Stationarity at0.01 / product displacement at3.5 |Both fail|Both fail|

![Completed construction, same-frame comparison](../.development-artifacts/cpd-anti-stereo-protected-construction-v2/completed_geometry_review.png)

Both complete solutes and all four repaired neighborhoods were visually inspected.
The adjoining O3′–P lengths are now1.584/1.583Å in anti and1.592/1.565Å in control.

The native extra-restraint preflight also passed the existing absolute-or-relative
energy/force limits. This validates the temporary improper convention, not a full
independent periodic-PME comparison. Its energy errors0.002214/0.000479kcal/mol
and force errors0.000114/0.000491kcal/mol/Å remain in the native reports. The anti
energy check uses its relative allowance0.003072, not an absolute0.001 pass.

## Isolated full-system engine test

After this review, `cpd-anti-solvated-engine-v2e` freezes a separate, watched engine
test. It uses the corrected final30,867-atom coordinates, unchanged PSFs/parameters
and solvent boxes. First compare the3043-atom solute and a two-water/Na/Cl fixture
against OpenMM Reference using unswitched full interactions. Then run at most100ps
per case at300K, ordinary masses,1fs, rigid water, fixed-cell PME/Langevin; no
further minimization or artificial restraints. Check saved1ps frames and final
coordinates for chemical signs, bond integrity, severe contacts and piercings.
5960 seconds total plus prior construction/startup time remains below the2h cap;
no continuation. No independent full-periodic-PME equivalence is claimed.

The first engine service passed both full-solute static comparisons but rejected
the small solvent fixtures before energy because ParmEd wrote an empty PSF title
record. V2b's prelaunch check caught that its exporter discarded the attempted
title fix; V2c's caught a changed charge-group listing. V2d sets the title after
conversion to the PSF class; exact diff proves only that title line changes.
These failures are retained, consume zero MD steps, and do not extend
the physical budget. `cpd-anti-solvated-engine-service-v2e` subsequently completed
both100ps tests; independent replay verified four E/F comparisons and202 saved/final
geometries. Full results and limitations are in the native report linked above.

V2d then failed its solvent-force comparison:0.001587/0.001767kcal/mol/Å
exceeded the unchanged0.001 limit. Neither case entered dynamics. A separately
registered diagnostic repeated only those two static evaluations with CPU bonded
terms (`bondedGPU 0`), giving0.00002503/0.00002430 at identical coordinates and
parameters. The [native GPU documentation](https://www.ks.uiuc.edu/Research/namd/cvs/ug/node103.html)
describes this offload control and numerical force differences. This measured
result supports a GPU bonded-arithmetic explanation, not a solvent-parameter
change. V2e uses CPU bonded terms in **both** comparisons and MD, retaining GPU
nonbonded/PME. Exact file/configuration diff verifies unchanged physical inputs;
only the execution option changes. The old failed force verdict remains.

## Keeping the acceptance stages separate

Reinspection of the immutable [v2 policy](../experiments/cpd_anti_additive/preliminary_policy_v2.json)
and [protocol](cpd_preliminary_protocol_v2.md) found that the engine stage requires
correct graph/charge/stereochemistry, complete implementation, finite native
behavior and bond integrity. It does **not** require proving an unconstrained
minimum of the full solvated DNA or satisfying a product-placement displacement.
The original local-placement script already reported its0.01 force criterion and
3.5Å product screen separately. Later construction attempts combined those checks
more broadly; their registered failed verdicts remain unchanged.

This version restores that distinction prospectively: after all artificial
restraints are removed, it separately reports chemical coordinate integrity,
stationarity at the unchanged0.01kcal/mol/Å criterion, and product placement at
the unchanged3.5Å screen. Geometry eligibility only permits a subsequent isolated
engine review; it is not itself a NAMD dynamics pass, minimum certificate,
preliminary research qualification or normal app promotion. No policy hash,
threshold, fit round or old verdict was altered.

The [CHARMM36 DNA study](https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/)
supports neutralized TIP3P preparation with restraint staging, while supplying
no universal whole-DNA0.01 force or3.5Å placement requirement. The seven exposed
profile geometry mismatches and missing prospective QM validation remain.
No cloud resources were used.
