# Biotin-TEG–DNA junction candidate

The isolated implementation provides a 60-atom `BTE` ligand residue and a
two-residue `BTE5` patch joining ligand O4T to the existing DNA 5′ phosphate.
It uses the user-supplied CGenFF program 4.0/library 5.0 assignment unchanged
within the ligand. Gold is outside this package. Production NAMD guards remain.

## Charge and parameter transfer

The original BTMP model has a methyl-capped phosphate. The candidate transfers
its phosphate/O5 charges and converts cap C5C into DNA C5′ by adding one of the
three equivalent cap-hydrogen charges to C5C. The remaining two hydrogens map
to DNA H5′/H5″. This gives C5′ charge −0.079 e; the ligand remains −0.465 e.
There is no charge spreading over biotin, integer normalization of its residue,
or guessed compensating charge. The assembled modified nucleotide totals −1 e.

This follows the modular capping approach described by the
[CGenFF force-field paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/).
It is a parameter-transfer hypothesis requiring physical validation, not a
new QM fit of the actual junction.

DNA retains its CHARMM atom types, including the DNA-specific P2 type, and all
atoms beyond the explicitly listed 5′ group retain their original charges.
The standard `5TER` patch is excluded because it removes the phosphate;
`first NONE` and `DEOX` preserve the correct deoxyribose/phosphate graph.
The candidate contains no methyl-cap atoms and adds no protein–biotin bond.

All mixed terms have explicit source records. Phosphate-centered angles and
torsions around P–O5′ use CHARMM DNA. Linker-side O4T-centered angles and torsions
use CGenFF. All Fourier terms are retained from one family per central bond;
Urey–Bradley terms are retained. No bonded value is fitted or invented here.
The [CGenFF covalent-linkage guidance](https://mackerell.umaryland.edu/cgenff_faq.php)
supports transferring mixed terms from the appropriate parent force field and
keeping central-bond torsion families consistent.

## Checks and retained evidence

The full [validation record](validation/biotin_dna_junction_2026-09-16.json)
contains source hashes, native controls, complete-complex checks, GPU evidence
and test outcomes.

`experiments/strep_biotin_namd/build_dna_junction.py` builds the topology,
parameter supplement, atom-level provenance and native PSF controls. All four
bases and an ACGT strand pass parameter coverage and charge checks: attachment
adds exactly −1 e compared with the corresponding 5′-OH control. Phosphate has
four oxygen neighbors. Other DNA atom types/charges remain unchanged.

`build_junction_complex.py` applies the candidate to the retained tetramer plus
eight-nucleotide DNA fixture and completes ligand hydrogens. Its 7,291 atoms
have charge −16 e; all 3,796 source heavy atoms map uniquely and have zero
coordinate displacement at PDB precision. All 7,400 bonds, 13,190 angles,
19,306 proper dihedrals, 1,280 impropers and 476 CMAP terms resolve.

The full build exposed and fixed ligand C7 being renamed by a DNA C7→C5M alias.
A regression test checks all ligand atom names. The isolated complex builder
also explicitly preserves resolved terminal protein O coordinates as OT1
before hydrogen/terminal-atom completion, preventing psfgen from rebuilding
an existing heavy atom.

`check_junction_gpu.py` prepares explicit TIP3P water and 150 mM NaCl, neutralizes
the complex and requests GPU-resident NAMD on the local RTX 2080 SUPER. The
bounded check uses 2,000 minimization steps and 20 ps at 1 fs, without a
protein–ligand spring. It is a short numerical check, not an affinity or lifetime
measurement. The rectangular box has 1.5 nm initial padding; a longer trajectory
requires renewed periodic-image and equilibration checks.

The completed local run contains 94,121 atoms and passed all 20,000 MD steps
in GPU-resident mode. Median MD throughput was approximately 244 steps/s
(21 ns/day at the conservative 1 fs step); initialization, minimization and
MD together took 113 seconds. Across 200 MD samples the junction O–P distance
was 1.500–1.664 Å, mean 1.581 Å. The biotin ring moved at most 1.14 Å RMSD
relative to its first MD sample after alignment on protein Cα atoms. This is
a short-time structural diagnostic, not a binding affinity measurement.

Two earlier local CUDA attempts stopped during parameter initialization on
unused NBFIX type references. Neither ran MD. No CPU fallback or RunPod job
was used. Their compact failure evidence is retained; redundant solvated inputs
are deleted. The successful run retains its inputs, final state, reduced solute
trajectory with preserved DCD timing, and junction-distance time series.

NAMD requires Lennard-Jones definitions even for types mentioned solely in an
unused NBFIX entry. The isolated runner removes only NBFIX pairs whose types
cannot both occur in its PSF, preserving every applicable correction and
recording source/output hashes. It does not add dummy force-field types.

The durable evidence paths are:

- `experiments/strep_biotin_namd/ws/junction_v1/`: BTE/BTE5 topology, mixed
  parameters, provenance and nucleotide controls.
- `experiments/strep_biotin_namd/ws/junction_complex_final/`: complete isolated
  PSF/PDB, final atom mapping and source-coordinate audit.
- `experiments/strep_biotin_namd/ws/junction_gpu_final/`: GPU input, log and
  numerical-check evidence. Consult its actual result before claiming success.

No application placement or geometry lock was changed. Parameter coverage and
integer charge do not establish conformational accuracy; ring/pocket energetics
and longer junction validation remain separate qualification work.

## Reproduce the isolated preparation

Run from the repository root, using new output directories:

```bash
.venv/bin/python experiments/strep_biotin_namd/build_dna_junction.py --output experiments/strep_biotin_namd/ws/junction_new
PYTHONPATH=experiments/strep_biotin_namd/ws/tool_dependencies .venv/bin/python experiments/strep_biotin_namd/build_junction_complex.py --source experiments/strep_biotin_namd/ws/preparation_final/source.nadoc --package experiments/strep_biotin_namd/ws/parameterization_final --junction experiments/strep_biotin_namd/ws/junction_new --output experiments/strep_biotin_namd/ws/complex_new
```

The explicit GPU command additionally requires `--complex`, `--package`,
`--junction`, a fresh `--output`, and `--namd` pointing to the CUDA executable.
It is deliberately separate from normal application simulation/export paths.

Focused regression checks: 4 passed. `just test-smart` selected FAST and had
8,615 passed, 29 failed, 43 skipped and 9 errors; the broad suite is not clean.
Its wrapper reported 95 seconds with no per-test time-budget violator while
native development work was also running. Applying the `triage-slow-tests`
guidance did not justify relegating tests or changing budgets.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

## Alpine continuation (2026-09-16)

Submitted Slurm **32611941** on `ah200`, one H200, using the configured private
CUDA NAMD build and `GPUresident on`. This is a **5 ns additional NVT trajectory
at 300 K and 1 fs**, continuing the validated 20 ps checkpoint without resetting
velocities or minimizing again. The system has 94,121 atoms. Restart files are
written every 100 ps and trajectory frames every 10 ps; the walltime limit is
8 hours. Submission passed `sbatch --test-only`; latest observation was **PENDING
(Priority)**, so no Alpine throughput or trajectory validation is claimed yet.

Remote directory:
`/scratch/alpine/jojo6687/nadoc_validation/biotin_dna_5ns_20260916`.
Local submission, SHA-256 input ledger, exact batch/configuration and validation
logs: `experiments/strep_biotin_namd/ws/junction_alpine_5ns/`. The submit script
refuses to submit again when its submission receipt exists. No RunPod spending.
When complete, check the GPU-resident log, final step 5,022,000, finite energies,
O4T–P and adjacent bond distributions, pocket-aligned biotin motion and periodic
self-contacts before interpreting the trajectory. Stability does not establish
binding affinity or qualify transferred parameters against QM.

## Terminal extension representation

Biotin-TEG handles now receive a modification-only `StrandExtension` at their
chemical **5′ end** on creation and when old designs are parsed. It contributes
one extension and **zero DNA nucleotides**. The existing extension display,
spreadsheet bracket notation and terminal extension editor use that same record.
Its strand ID remains stable through overhang duplex relocation/reversion; the
DNA pairing register is unchanged. Generic 3′ biotin extension records retain
their 3′ identity, but this does not introduce a 3′ Biotin-TEG atomistic patch.
Explicit existing extensions are preserved rather than overwritten. Removing a
handle or its nanoparticle removes its extensions, with undo restoring them.
Modification-only extensions no longer hide the terminal nucleotide's 5′ flag.

Validation: 59 targeted backend checks passed; live browser review of a bound,
reverse-direction handle confirmed one biotin bead and a prefilled 5′ Biotin-TEG
extension editor with no page errors. Browser writes were blocked and no review
design was persisted in the main workspace. `main.js` change: **0 lines**.
`just test-smart`: FAST, 8,619 passed, 29 failed, 43 skipped, 9 errors (same failure
counts as before this change); 89 seconds. `just lint` reports 7 existing errors;
new modules pass Ruff.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

### RTX Pro 6000 replacement

At the user’s request, H200 job **32611941** was canceled (confirmed by Slurm),
and replacement **32620740** submitted on `artxpro6000` with one whole RTX Pro
6000. The 5 ns protocol, starting checkpoint and molecular inputs are unchanged;
GPU-resident NAMD remains enabled. Input hashes and scheduler preflight passed.
Latest status: PENDING (Priority). The replacement receipt, exact batch and
checks are in `experiments/strep_biotin_namd/ws/junction_alpine_5ns_rtx6000/`.

### Alpine status correction before commit

Replacement job **32620740 failed after 6 seconds**, before NAMD launched: the
RTX Pro 6000 node could not load `gcc/11.2.0`. No MD steps ran. The batch
environment needs correction before another submission; no retry has been
submitted. The earlier H200 job 32611941 remains canceled.
