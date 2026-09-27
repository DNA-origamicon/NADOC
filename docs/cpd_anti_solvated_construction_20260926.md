# Cis-anti paired solvent construction diagnostic

The native-fragment wake `b9d98b9c-40cb-4729-80a5-d760ea8c5d15` was received
and acknowledged at 2026-09-26 21:13:47 UTC. Its new
`completion_delivery_verified.json` replays all ten native energy/force comparisons
from saved logs/force binaries and the frozen OpenMM systems. Maximum errors are
0.000558056 kcal/mol and 0.000709668 kcal/mol/Å. All ten original-QM stereocenters
survive 101 DCD frames plus the final binary coordinates; covalent-radius ratios
span 0.81549–1.12751. This is a 100 ps fragment engineering pass, not minimum
certification or full-DNA qualification. The acknowledgment did not repeat dynamics.

## Registered construction attempt

The [construction-method review](cpd_anti_construction_method_review_20260926.md)
is now implemented as an isolated, bounded native NAMD minimization experiment.
Frozen inputs and the executable plan are in
`cpd-anti-solvated-construction-v1c`; the external service and watcher are
`cpd-anti-solvated-construction-service-v1c`. There is no parameter fit or MD in
this attempt. The current campaign policy and earlier failures remain unchanged.

**Terminal result:** both cases stopped at750 total minimization steps on the
same unmodified sugar inversion, D000:7:C3′. Neither reached the k=1 or
unrestrained stage; no dynamics followed. Native evidence was independently
replayed. The attempt failed its original stereochemistry rule.

| Item | Frozen choice |
|---|---|
| Solute | Same ordered D001:15/D000:8 site; 3043 atoms, 96 nucleotides, three strands |
| Anti seed | Earlier source-conditioning endpoint used for the successful fitted-DNA static check; bond/stereo integrity passes, placement still fails at 7.52176 Å |
| Control | Frozen unpatched reactant PSF/PDB; source coordinates exactly match the prior frozen source; known bond defects and four severe contacts retained for repair |
| Parameters | Existing parent DNA/CGenFF plus fitted CPD overlay; no coefficient or charge changes |
| Solvent | Standard CHARMM modified TIP3P and water/ion stream from the official February 2026 archive, including its own documented NBFIX; no application CUFIX substitution |
| Shared cell | 44.930 × 67.438 × 112.763 Å, at least 12 Å padding around the union of the two seeds |
| Shared solvent/ions | 9223 waters, 124 Na⁺, 31 Cl⁻; 31 excess salt pairs give 150.662 mM by total cell volume, plus 93 neutralizing Na⁺ |
| Total | 30,867 atoms in each system; net charge within 1e−12 e of zero |
| Electrostatics/LJ | Periodic PME, tolerance 1e−6, ≤1 Å mesh spacing; LJ switch 10–12 Å, 14 Å pair list |
| Construction | 500 steps with solute fixed; 1500 with solute-heavy positional k=5; 2000 at k=1; 6000 unrestrained |
| Restraints | NAMD convention U=kΣ(r−r_seed)², k in kcal/mol/Å²; seed PDB references rounded to 0.001 Å; water rigid, DNA unconstrained |
| Budget | ≤10,000 minimization steps per case, ≤2 hours total, eight local workers, 12 GiB limit; no continuation or automatic MD |
| Checkpoints | 250-step chunks; stop the affected case on inversion, new severe contact, or ring piercing; preserve every output |
| Final checks | All restraints removed; maximum solute force component ≤0.01 kcal/mol/Å; retained bond/contact/stereo screens; anti displacement ≤3.5 Å |

The control is an **unpatched source construction control**, not an equilibrated
undamaged structure. Its seed has a bond-length/equilibrium ratio as high as
2.65406 and four severe contacts. Its pre-existing defects may be repaired during
the restrained phases; final acceptance requires their removal. The anti seed
has no severe contacts or ring piercings. All 288 source sugar centers are checked
in both cases, with ten additional original-QM comparisons for anti.

The identical solvent/ion coordinates exclude the union of both seeds, preventing
one case from starting with an extra solvent overlap. GROMACS SPC216 supplies
oxygen packing and orientation; hydrogen coordinates are reconstructed to exact
TIP3P 0.9572 Å/104.52° geometry. DNA coordinates receive one shared translation
only, retained in the manifest. Binary double-precision coordinates drive NAMD.
Solute PSF atom records—including 12-decimal fitted charges—and all solute bond,
angle, proper and improper records are unchanged. Full parameter coverage passes.
Adding the water/ion file leaves the solute-only OpenMM System exactly unchanged.

The two seed conditioning histories differ. This experiment can test whether
each construction behaves acceptably in a common environment; it cannot isolate
a causal solvent effect or provide an equilibrium lesion/control comparison.
The force criterion concerns the mobile solute. Neither passing it nor completing
the step budget would certify a minimum of the entire constrained solvent system.

## Literature and implementation boundaries

[Hart et al.'s CHARMM36 DNA study](https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/)
supports counterion-neutralized TIP3P preparation with restrained and unrestrained
stages. The particular budget and intermediate k=1 stage here are registered
engineering choices, not acceptance thresholds derived from that paper. The
prior 0.01 kcal/mol/Å and 3.5 Å criteria are retained, not attributed to Hart.

The [GROMACS solvate documentation](https://manual.gromacs.org/documentation/2024.3/onlinehelp/gmx-solvate.html)
describes packing water boxes; this use does not transfer GROMACS force-field
parameters. The [MacKerell distribution](https://mackerell.umaryland.edu/charmm_ff.shtml)
is the source of the water/ion records. Acquisition URL, archive/member hashes and
the HTTP transport limitation are recorded in `cpd-anti-solvent-reference-v1`.

V1 native startup rejected CHARMM `set` directives before any energy evaluation
or minimization. V1b's parameter conversion then failed its OpenMM preparation
check on a second-block title line, also before native calculations. Both failed
directories remain. The corrected parameter-only file retains the two original
parameter blocks and numerical records; exact full-system OpenMM equivalence
passes for both cases. V1c coordinates, topology, masks and coverage systems are
byte-identical to V1. These are format repairs, not extensions of a consumed
physical calculation budget.

The seven exposed profile geometry mismatches, four missing prospective QM
points, and prior failed full-DNA constructions remain unresolved. No normal
application geometry, saved design, scientific qualification or cloud resource
was changed. Review terminal native evidence before any next calculation.

## Terminal evidence and a source-reference defect

The corrected service completed its failed assessment at21:31:52UTC after11.3s.
Each case ran a native run-0 preflight,500 solvent-only steps and250 steps with
solute-heavy k=5 restraints. Independent review replays eight native logs, eight
coordinate/force binaries and30 DCD frames, with no new energy calculation.
Both sources had valid sugar signs relative to their frozen source before release.

| Result | Anti | Unpatched source control |
|---|---:|---:|
| First saved frame with D000:7:C3′ inverted | Step550 | Step650 |
| Stop checkpoint | Step750 | Step750 |
| Final solute bond/equilibrium ratio | 0.95780–1.06379 | 0.95502–1.16795 |
| Final severe contacts / ring piercings | 0 / 0 | 0 / 0 |
| Final maximum restrained solute force component, kcal/mol/Å | 44.0460 | 80.5546 |
| Final lesion-site base displacement, Å | 7.56871 | 1.99740 |

These forces include positional restraints; unrestrained stationarity was never
measured. Zero solute force exports during the fixed-solute phase are not evidence
of stationarity. Whole-system minimum certification remains false.

![Shared sugar inversion](../.development-artifacts/cpd-anti-solvated-construction-v1c/shared_sugar_failure.png)

Canonical C3′ neighbor ordering `[C2′, C4′, O3′, H3′]` reveals an additional,
independent reference problem. Both original-QM sugar fragments have positive
signed neighbor volumes,8.29755 and8.15956Å³. Of96 source sugars,95 have positive
volume and **D002:26 has negative volume,−11.92081Å³**, with a3.44176Å C3′–O3′
distance. The earlier source-conditioned anti seed shortened the bond but retained
the opposite handedness (volume−9.14757Å³). This is outside the CPD site.

D000:7 is a different defect: it starts close to the zero-volume boundary,
0.28328Å³ in the source and0.29718Å³ in the anti seed. Both cases move to negative
volume after release, ending at−8.24168 and−9.28613Å³. The shared inversion supports
investigating source construction rather than attributing this failure uniquely
to the CPD potential. It does not establish that the CPD parameters are adequate
or prove a particular causal mechanism.

Earlier “all288 source sugars preserved” results establish **source-relative
sign preservation only**. They do not establish chemically correct chirality at
every sugar. Those immutable reports remain intact; this new audit records the
limitation instead of silently changing their reference signs or verdicts.

The next method preparation must repair and review the source sugar geometry
against chemically consistent references before another bounded construction.
It should explicitly address D000:7 and D002:26, retain the unchanged strand graph,
show the corrective coordinates in the shared frame, and remove any temporary
construction restraints before claiming stationarity. No further minimization,
torsion fit, prospective QM or DNA dynamics is launched by this terminal review.
The original acceptance thresholds and all failures remain; no cloud spending.
