# exp57 — OpenMM implicit-solvent DNA origami validation

Status: **duplex RunPod smoke passed; paired crossover-2HB production gate
failed; local execution remains deferred**. See `RESULTS.md`. The current
salt-only GBn2 protocol must not advance to 6HB. The active NAMD production run
is the later curved-origami reference and still owns the local GPU. The local runner has a second, runtime
heavy-simulation guard so `run` and `resume` refuse to create an OpenMM CUDA
Context while NAMD (or another supported engine) is active.

## Scientific claim being tested

AMBER OL15 DNA plus GBn2 at 0.150 M generic monovalent ionic strength may be a
useful, GPU-resident surrogate for explicit-water origami dynamics when the
question is large-scale DNA shape and fluctuations. "0.150 M" is Debye screening
inside the continuum model—not 150 mM of spatially resolved Na and Cl ions. This
model cannot validate ion condensation, groove occupancy, Mg-mediated bundle
contacts, or ion-specific kinetics.

The initial production protocol is deliberately conservative: 300 K,
Langevin-middle, 1/ps friction, 2 fs, HBond constraints, mixed CUDA precision,
and no HMR. No-cutoff electrostatics is the correctness reference. A 3.0 nm
non-periodic cutoff is only promoted if the staged cutoff ladder agrees on
forces and structural ensembles while delivering a material speedup.

## Why this is a separate path from BLADE

BLADE remains a short CHARMM36/OBC2 relaxer. This experiment uses OL15/GBn2,
fails rather than silently falling back to CPU, records its seed and every
protocol value, writes checkpoints, and supports restart. Most importantly, it
does not pass origami through PDB: PDB wraps after 62 chain IDs and NADOC then
uses multiple `MODEL` records, which OpenMM interprets as coordinate frames.
`backend.core.openmm_implicit.build_openmm_topology` creates chains, residues,
atoms, positions, and all covalent bonds directly, preserving hundreds of
strands and crossover backbone bonds.

## Validation gates

Use `validation_matrix.json` in order. Do not advance on runtime alone.

1. The duplex must parameterize with no unmatched residues, minimize to finite
   energy, retain base pairing, and restart bit-for-bit from a checkpoint over a
   short deterministic continuation.
2. The double-crossover motif must have the same expected covalent edges before
   and after hydrogen addition, with no broken O3'-P junctions.
3. Three 6HB seeds must preserve distributions of pairing, inter-helix spacing,
   rise/twist, RMSF, and global shape against explicit NAMD—not merely RMSD to
   the ideal starting structure.
4. The curved 6HB must preserve the explicit-solvent bend-radius and tangent-angle
   distributions within uncertainty. A single average structure is insufficient.
5. Only then run the 18HB scale/performance case. The implicit path succeeds as a
   compute strategy only if wall-clock savings survive the long-range GB cost.

Quantitative tolerances should be frozen after measuring sampling uncertainty in
the three explicit-NAMD reference blocks. Suggested preregistration floors are:
no persistent WC occupancy loss over 5 percentage points, median inter-helix
spacing shift under 0.15 nm, median rise shift under 0.02 nm, and bend-radius
distribution overlap sufficient that the 95% bootstrap intervals intersect.
These are proposed gates, not validated facts.

## Commands to use after NAMD finishes

Preparation parameterizes and writes `input.cif` plus `manifest.json`, but does
not create a CUDA Context:

```bash
uv run python experiments/exp57_openmm_implicit_origami/run.py prepare \
  path/to/design.nadoc workspace/openmm_implicit/curved_6hb_seed1
```

Launch only after the NAMD run and the deferred test suite complete:

```bash
uv run python experiments/exp57_openmm_implicit_origami/run.py run \
  path/to/design.nadoc workspace/openmm_implicit/curved_6hb_seed1 \
  --seed 20260827 --nonbonded-mode no_cutoff --confirm-namd-finished
```

Resume from the rolling checkpoint:

```bash
uv run python experiments/exp57_openmm_implicit_origami/run.py resume \
  path/to/design.nadoc workspace/openmm_implicit/curved_6hb_seed1 \
  --confirm-namd-finished
```

## Deferred verification order

When the GPU is free:

1. run the pure/unit tests in `tests/test_openmm_implicit.py`;
2. run the OpenMM checker integration tests and correct any OL15 template issue;
3. perform a CUDA mixed-precision Context smoke test;
4. execute the duplex and crossover rungs;
5. compare cutoff arms on 6HB; and
6. start the replicated curved-origami comparison against NAMD.

No manual force-field download is required. OpenMM ships `amber14-all.xml`
(including OL15) and `implicit/gbn2.xml`; the locked `openmm[cuda12]` dependency
supplies the CUDA platform libraries. The NVIDIA host driver remains external.

Primary methods: Nguyen et al., *JCTC* 2015, 11, 3714–3728,
DOI 10.1021/acs.jctc.5b00271 (nucleic-acid GBn2 refinement); Zgarbová et al.,
*JCTC* 2015, 11, 5723–5736, DOI 10.1021/acs.jctc.5b00716 (OL15).
