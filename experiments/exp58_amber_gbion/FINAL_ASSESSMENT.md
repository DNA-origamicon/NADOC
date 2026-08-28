# exp58 final assessment — Amber GBION for curved-origami equilibration

Status: **closed for production use; do not repeat the exp58 protocol as-is.**

The campaign established that Amber26 can execute OL15/GBneck2/GBION-v3 on a
resident NVIDIA GPU and that a relaxed 656-nt 6HB remains numerically intact for
0.1 ns. It also established a serious nominal-throughput penalty at origami scale.
It did **not**, however, measure the project's actual target: wall-clock time to a
converged curved-origami ensemble. The experiment must therefore be recorded as:

- a **negative result for raw physical-time throughput**;
- a **positive basic execution/topology result**;
- **inconclusive for effective equilibration speed**; and
- insufficient to authorize GBION for production origami simulations.

This distinction matters because implicit solvent can make conformational motion
faster per nominal nanosecond by removing explicit-water viscosity. A slower
ns/day rate can still yield more statistically independent conformations per day.
exp58 neither measured that effect nor used the low-friction protocol under which
the published acceleration was demonstrated.

## Question and practical decision

The intended question was not simply whether deleting water increases `ns/day`.
It was whether implicit water plus explicit 150 mM NaCl could reduce the wall time
needed to relax or equilibrate the global curvature of DNA origami while preserving
a defensible atomistic DNA ensemble.

The practical decision is to **park GBION and keep explicit-solvent NAMD as the
production path**. Do not spend more compute on long GBION origami trajectories
from the exp58 configuration. Reopen the method only as a new, preregistered
effective-sampling experiment meeting all of the criteria near the end of this
document. A nominal `ns/day` benchmark alone is not a valid reopen test.

## Reproducible evidence ledger

| Gate | System and hardware | Result | Interpretation |
|---|---|---:|---|
| Duplex GBION | 21 bp, 1,392 atoms, RTX 4090 | 633.65 ns/day | Native GPU execution and 1 ns basic stability passed |
| Duplex explicit control | 21 bp, 38,882 atoms, RTX 4090 | 604.06 ns/day | GBION was only 1.049x faster on the same engine/GPU |
| Relaxed 6HB GBION | 656 nt, 22,444 atoms, RTX 4090, 2 fs | 18.284 ns/day | Stable short run, severe scale-dependent throughput loss |
| Archived 6HB explicit | 182,801 atoms, RTX 3080 Ti, 4 fs HMR | 90.903 ns/day | NAMD produced 4.97x more nominal ns/day |

The 6HB GBION step took about 9.45 ms, versus about 3.80 ms for the NAMD
GPU-resident step. The 2 fs versus 4 fs timestep then doubled the number of GBION
steps required per nominal nanosecond. The measured throughput ratio was 0.2011.
At 2 fs, GBION conformational motion would therefore have to be **more than 4.97x
faster per nominal nanosecond** merely to break even in conformational sampling per
wall day. A validated 4 fs HMR protocol would lower that break-even requirement to
approximately 2.49x, but HMR was not tested here.

Authoritative artifacts:

- duplex: `/media/jojo/Archive/nadoc_amber_exp58/duplex_runpod/result.json`,
  SHA-256 `8c2a4d88a716daa3ec50282237d0d6df264d633f8dcedddfe201c7fd57cd39fa`
- failed raw-geometry 6HB attempt:
  `/media/jojo/Archive/nadoc_amber_exp58/origami_6hb_runpod/partial_analysis.json`,
  SHA-256 `467e4a9456f7fe4f87ffa924b7147591f9422c175cef915fe06eaf10b63b6bee`
- relaxed-seed 6HB:
  `/media/jojo/Archive/nadoc_amber_exp58/origami_6hb_relaxed_runpod/result.json`,
  SHA-256 `bdd921892ec07520fc0a12dbf9a6e1447ea674f7e73d84db1169a08cef346305`
- NAMD reference configuration and timing:
  `/media/jojo/Archive/NADOC_archive/cb616816195f/package/6hb_2xT_namd_solvated/`

The checksums above were recomputed during the final audit and matched the existing
result notes. All three exp58 pods recorded successful termination. A fresh,
read-only RunPod account query on 2026-08-28 returned no live pods. Total estimated
campaign spend was `$1.740592`, below the `$5` authorization. The long local NAMD
job was still running and was not touched by this audit.

## What the experiments established

1. **Native GPU support is real.** Amber26 `pmemd.cuda` emitted the CUDA banner and
   `gbion=3`; the relaxed 6HB CPU/GPU one-step energy difference was within the
   preregistered relative tolerance.
2. **The topology conversion can be made sound.** The relaxed 6HB topology had 656
   DNA residues in 9 strands, all 647 expected consecutive O3'-P links, no
   inter-strand covalent bonds, no initial bond outside 0.8–2.0 A, and the final
   22,403 bonds all remained within 0.08–0.20 nm.
3. **Raw CAD coordinates are not a dynamics seed.** The raw 6HB geometry contains
   105 heavy-atom pairs below 0.8 A and 136 NAMD-PSF bonds outside 0.8–2.0 A.
   Restraining that geometry during preparation trapped the defects and caused the
   first Amber attempt to diverge. The relaxed NAMD coordinates removed them.
4. **Short duplex stability transfers only weakly to origami.** The 1 ns duplex
   remained paired. The relaxed 6HB also remained base-paired over 0.1 ns, but its
   aligned C1' RMSD reached 0.497 nm, radial RMS increased 12.8%, and radial p90
   increased 14.2%. Those values are near the preregistered limits and represent
   substantial global movement, not proof of a converged or faithful ensemble.
5. **Standard all-pairs GB scales poorly at this solute size.** The GPU GB path
   evaluates effectively uncut pair interactions; 22,444 atoms imply roughly 252
   million unique atom pairs. Explicit NAMD instead used a 10 A local cutoff plus
   GPU PME. Removing water reduced the atom count by 8.1x but replaced a local/mesh
   calculation with a much more expensive calculation per retained solute atom.
6. **Ion confinement was operational despite a bookkeeping gate failure.** A
   center-definition mismatch made the registered gate fail. Reanalysis using the
   actual restraint center found a maximum radius only 0.025 A beyond the 126.5 A
   threshold. This is not the reason for the throughput result.

## What was not established

exp58 cannot answer whether GBION equilibrates curved origami faster, because:

- the 6HB was seeded from an already relaxed NAMD coordinate rather than a common,
  valid nonequilibrium curved-origami state;
- only one 0.1 ns trajectory was sampled, with no replicas or convergence test;
- no curvature reaction coordinate, autocorrelation time, effective sample size,
  or wall-time-to-stationarity metric was preregistered;
- the explicit and implicit comparisons changed engine, DNA force field, salt
  chemistry, GPU, and timestep simultaneously; and
- fast movement could be either desired low-viscosity relaxation or drift to a
  different OL15/GBION equilibrium. The short trajectory cannot distinguish them.

The published GBION paper's direct two-orders-of-magnitude convergence result is
for the **ion atmosphere around restrained duplex DNA**, not for relaxation of an
origami's global curvature. Its broader conformational-sampling claim relies on
the established low-viscosity behavior of GB simulations and should not be applied
to this 6HB without a system-specific measurement.

## Final protocol audit: exp58 did not test the published sampling regime

Three differences discovered in the final audit are material and must not be lost:

1. **Langevin friction:** exp58 used `gamma_ln=1.0 ps^-1`. The GBION DNA paper used
   `0.05 ps^-1`; the systematic GB/PME conformational-sampling study used
   `0.01 ps^-1`. That study found that sampling acceleration increases as friction
   decreases. Our higher damping was a conservative stability choice but worked
   against the project's acceleration objective.
2. **NaCl GBION coefficients:** exp58 used `intdiel_ion_1_n=10` and the corresponding
   anion-involving pair coefficients of 10. The GBION paper and Amber25 manual both
   specify 8 for NaCl. The exp58 values are therefore a tested implementation
   variant, not the published NaCl parameter set.
3. **Nonpolar term:** exp58 enabled GPU `gbsa=3`. Amber permits this, but the GBION
   paper's monovalent-ion and unrestrained dodecamer protocol used `gbsa=0` unless
   otherwise specified. The paper reports little effect on the measured ion
   distributions, but that does not establish equivalence for an origami structural
   ensemble.

Consequently, the measured 18.284 ns/day remains valid for the exact exp58 input,
but neither its structural trajectory nor its effective sampling rate should be
presented as a validation or falsification of the published GBION protocol.

## Literature reconciliation

The results are consistent with the literature rather than paradoxical:

- Standard uncut GB is quadratic in solute atoms and can have lower nominal
  ns/day than explicit PME for large solutes. This behavior was explicitly noted
  for nucleosome-sized systems before GBION existed.
- A systematic Amber study found generic GB effective speedups ranging from about
  0.7x to 60x after combining nominal throughput with transition-specific
  conformational acceleration. Large motions ranged from no acceleration to nearly
  100x and were strongly friction-dependent. This range spans both failure and
  success for our 4.97x break-even requirement.
- The GBION paper validates duplex ion distributions, microsecond stability of a
  12-bp duplex, and rapid ion-atmosphere convergence. It does not validate NaCl
  DNA-origami curvature ensembles, divalent Mg2+, or physical kinetic times.

Primary sources:

- Kolesnikov, Xiong, and Onufriev, *Implicit Solvent with Explicit Ions Generalized
  Born Model in Molecular Dynamics: Application to DNA*, JCTC 2024,
  <https://doi.org/10.1021/acs.jctc.4c00833>.
- Anandakrishnan et al., *Speed of Conformational Change: Comparing Explicit and
  Implicit Solvent Molecular Dynamics Simulations*, Biophysical Journal 2015,
  <https://doi.org/10.1016/j.bpj.2014.12.047>.
- Goetz et al., *Routine Microsecond Molecular Dynamics Simulations with AMBER on
  GPUs. 1. Generalized Born*, JCTC 2012,
  <https://doi.org/10.1021/ct200909j>.
- Amber25 Reference Manual, archived locally at
  `/media/jojo/Archive/nadoc_amber_exp58/reference_packages/Amber25.pdf`.

## Rules that prevent repeating this campaign

Do **not**:

- rerun the raw CAD geometry or restrain unresolved clashes;
- cite the duplex's 1.049x nominal speedup as an origami result;
- infer effective equilibration from nominal `ns/day` alone;
- infer correct equilibration from rapid RMSD or radius change;
- interpret GBION nominal time as physical aqueous kinetics;
- use the exp58 coefficient set as the published NaCl set;
- claim Mg2+ behavior from a NaCl parameterization; or
- launch a longer version of exp58 without a curved-observable convergence design.

Retain the current experiment code and archives for provenance. The
`GBION_NACL_NAMELIST` constant reproduces the tested exp58 variant; it is not a
template for a future literature-matched study.

## Conditions required to reopen GBION

A future experiment is scientifically justified only if all of the following are
accepted in advance:

1. Use a valid, common nonequilibrium starting structure for a genuinely curved
   origami, with all overlaps and bonds cleared before either solvent model starts.
2. Use the same Amber OL15 solute and hardware for GBION and explicit-water controls;
   keep a NAMD production comparison as a secondary engineering reference.
3. Test the published NaCl coefficients (`8`, not `10`) and published low-friction
   `gamma_ln=0.05 ps^-1`. Treat `gbsa=0` versus `gbsa=3` as a declared model
   sensitivity, not a hidden implementation choice.
4. Run at least three independent replicas per model. Choose duration from
   convergence behavior, not a fixed short survival gate.
5. Preregister global bend/curvature, contour shape, bundle radius and length,
   interhelix spacing, twist, base-pair occupancy, and bond integrity. Compute
   autocorrelation times and effective sample size per wall day.
6. Require agreement of stationary structural distributions with explicit solvent
   or experiment. Faster arrival at a different ensemble is failure.
7. Require more than 4.97x conformational acceleration at the tested 2 fs
   throughput, or more than 2.49x if a separately validated 4 fs HMR protocol is
   used. Otherwise explicit NAMD remains faster in wall time to useful sampling.

Until such a study is deliberately commissioned, exp58 is complete and GBION is
not a production equilibration engine for NADOC curved origami.
