# Water target convention audit

The historical cis-anti-I P3 score is not sufficient for Drude release. Besides
the independently established incorrect covalent graph, it compares against
1.16-scaled HF/6-31G* interaction energies. A subsequent input-level audit
confirmed these historical energies are **not counterpoise-corrected**, contrary
to the old P3 policy label (see below). The 1.16 multiplier is
specified for polar neutral **additive** CHARMM targets in
[FFParam (2020)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7323454/).

The directly relevant Drude nucleobase development used MP2/6-31G(d) minimum
interaction geometries and counterpoise-corrected RI-MP2/cc-pVQZ single-point
energies. See [nucleobase parameters (2011)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3166616/)
and [DNA refinement (2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5484419/).
These are primary studies; they support a correlated, large-basis target for
this validation track, not automatic reuse of scaled additive HF energies.

Decision for this recovery: retain the existing HF calculations as historical
and lower-level diagnostics. Do not simply remove their 1.16 multiplier and
call the result validated Drude reference data. Before fitting or accepting
water NBFIX, register a new target-method policy using unscaled,
counterpoise-corrected RI-MP2/cc-pVQZ energies, explicitly define the monomer
geometries and water geometry, and assess computational feasibility. Freeze
training/validation orientation and distance partitions before inspecting the
new target values. Preserve all existing acceptance limits; a method correction
requires new evidence, not retroactive promotion of the old score.

The fourth-orientation HF job 32610248 remains useful as a raw QM diagnostic;
its collector has no authority to fit or promote P3. A correlated-energy pilot
and full CPD-water target campaign still need to be prepared and executed.


The input-level audit examined all 216 cis-anti-I job manifests and hash-verified
inputs across the canonical, alternate-plane, +120 and +240 campaigns. Every
manifest states `counterpoise_corrected: false`; every input computes separate
unghosted complex/solute/water HF energies. The old P3 loader reads those series
and also subtracts 0.2 Å from its target minimum distance. Thus the old policy's
counterpoise label is contradicted by the actual calculations, not just
insufficiently documented. No withheld QM energy values were read for this audit.
Evidence: `.development-artifacts/cpd-drude-water-correlated-pilot-v1/historical_bsse_audit.json`.
This correction strengthens the need for replacement reference calculations;
it does not alter or rehabilitate any archived P3 fit.

The bounded pilot is now submitted as Slurm job **32612082**, using eight CPUs,
64 GiB Slurm memory (48 GiB in Psi4), and a two-hour limit. It was confirmed
RUNNING on `c3cpu-c15-u3-1`. `water_pilot.py` generated its input from the predefined
canonical endpoint-1 O4 acceptor contact at 1.8 Å; the archived solute coordinates
match the current audited QM minimum within 1e-8 Å. The rigid water retains
0.9572 Å OH bonds and 104.52 degrees HOH. This is a feasibility/training pilot,
not an independently withheld target or proof of the complete geometry protocol.
The valence DF-MP2/cc-pVQZ calculation explicitly freezes core orbitals and calls
Psi4's counterpoise interaction-energy driver with no energy scale or distance
offset. The original solute geometry is reused; no MP2 reoptimization is claimed.

The raw collector `nadoc-cpd-water-correlated-pilot-collect-v1.service` polls the
recorded job, checks terminal scheduler state, copies outputs and verifies the
result's input/policy hashes. It cannot fit NBFIX or promote any gate. After
collection, inspect the actual CP components, SCF/MP2 convergence, basis/core
settings and resource usage before defining the complete target campaign.
