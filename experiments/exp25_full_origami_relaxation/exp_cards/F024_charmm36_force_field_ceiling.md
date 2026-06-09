# F024: CHARMM36 Force Field Stability Ceiling — OL15/AMBER Comparison

## Hypothesis

The observed collapse is a force field artifact: CHARMM36 has documented instability
for B-form DNA at microsecond timescales (base-pair opening, B→A distortion), and
this instability manifests at much shorter timescales in the compressed B_tube
context due to the high local stress at crossover junctions and the unusually
packed helical geometry. OL15 (AMBER) would not produce equivalent collapse from
the same starting coordinates under identical restraint removal conditions.

This is a long-horizon, high-setup-cost experiment and is labeled "future" — it
requires rebuilding the full explicit-solvent package with AMBER topology. It is
included here as a planning document so the hypothesis is formally registered before
its cost makes it non-obvious to pursue.

## Motivation

Multiple independent benchmarks have established that CHARMM36 cannot preserve B-form
DNA duplex stability at >1 μs timescale (Galindo-Murillo et al. 2016 JCTC 12:4114;
C-B-A test of DNA force fields, PMC10034787). In long CHARMM36 trajectories, up to
30% of frames show irreversible base-pair distortion even for thermodynamically
stable GC/CG pairs. The failure mode involves ε/ζ backbone torsion imbalance
producing B→intermediate form distortions.

The B_tube simulation operates nominally at picosecond timescales during the
restraint-removal phase. CHARMM36's known instabilities are reported for >1 μs,
so the timescale appears mismatched. However, two factors may lower the effective
threshold:

1. The crossover junction geometry places significant local torsional strain on
   backbone atoms. A force field that incompletely models ε/ζ torsion balance may
   produce locally strained configurations that accelerate melting at crossovers
   versus a simple duplex benchmark.

2. The F001 atomistic model is built from template coordinates that are not
   relaxed to any force field's local minimum. CHARMM36 may have a larger
   effective energy gradient at template-built crossover geometries than OL15,
   making the early-ps collapse rate force-field-dependent.

3. A comparison study (Bro et al. 2019 J Phys Chem B 123:9331) found CHARMM36
   gives ~1.3 Å RMSD from NMR reference for short DNA duplexes versus <1 Å for
   OL15. For the tightly packed origami geometry, this systematic offset could
   compound at crossovers.

The Aksimentiev group uses CHARMM36 exclusively (with CUFIX), and their published
origami simulations appear stable — but they use nanosecond-scale pre-equilibration
that this project has not yet reproduced. It is therefore ambiguous whether the
current collapse is a CHARMM36 artifact or an equilibration artifact.

## Starting Point

This experiment requires a full system rebuild and cannot branch from the F020
checkpoint:

1. Convert B_tube.pdb/psf to AMBER topology using `tleap` with OL15 parameter set
   (ff14SB for any protein residues, OL15 for DNA, TIP3P for water, ion parameters
   from Joung-Cheatham or Li-Merz).
2. Solvate with equivalent explicit water box, 150 mM NaCl + 3.5 mM MgCl2.
3. Note: CUFIX parameters are specific to CHARMM36. OL15 requires separate Mg2+
   parameters; use Allnér et al. 2012 JCTC 8:1493 or Li & Merz 2017 JCTC 13:4490
   Mg2+ parameters.
4. MGH hexahydrate model must be reconstructed for the OL15 parameter set
   (or omitted and replaced by bare Mg2+ + appropriate NBFIX).
5. Use GROMACS rather than NAMD for the AMBER path, or use NAMD with
   `paraTypeAmber on` and OL15 `.frcmod` file.

**Estimated setup time: 3–5 days.**

## Protocol

Once the OL15 explicit package is built, run an equivalent F020 protocol:

1. Minimization, cold start at 50K, ramp to 310K under k=5 restraints
2. Staged restraint reduction from k=5 → k=0.05 at 50 ps/step (matching F020)
3. Unrestrained 20 ps at F020_16 equivalent — measure WC ref-relative retention

Compare WC ref-relative and C1' metrics to the F020 CHARMM36 results at each stage.

If OL15 also collapses at F020_16: force field is not the primary problem.
If OL15 survives F020_16: CHARMM36 instability is a major contributing factor.

Secondary test: if OL15 survives, check whether the CHARMM36 system can be
stabilized by switching to OL15 DNA parameters mid-trajectory (a parameter swap
is non-trivial but conceptually distinguishes "starting geometry problem" from
"ongoing force field problem").

## Measurable Metrics

- Primary: WC ref-relative fraction at 20+ ps unrestrained under OL15 (threshold: >=85%)
- Secondary: C1'-C1' paired fraction (threshold: >=90%)
- Tertiary: per-stage structural drift (RMSD from reference) under OL15 vs CHARMM36
  at matching k levels — a divergence at early k-stages would indicate the force
  fields produce structurally distinct equilibrated states even before unrestrained
- Quaternary: crossover junction geometry (backbone torsion ε, ζ, χ at crossover
  vs interior helix positions) — comparing OL15 vs CHARMM36 histograms at k=0.5
  would isolate whether the torsion-imbalance hypothesis is supported

## Expected Outcome If Correct

OL15 achieves >=85% WC ref-relative at unrestrained F020-equivalent stage while
CHARMM36 fails. Crossover-localized WC failures in CHARMM36 but not OL15 would
confirm the ε/ζ torsion imbalance mechanism.

## Expected Outcome If Wrong

Both force fields fail at comparable rates. This definitively rules out CHARMM36
as the primary cause and points to structural (template geometry, crossover strain)
or equilibration (insufficient timescale) origins.

## Priority

Low-to-Medium. The setup cost is high (3–5 days) and the hypothesis has a plausible
alternative explanation (insufficient equilibration). This experiment should be
deferred until F021–F023 have been tested:

- If F021 (ns equilibration) fails: force field becomes more likely; promote F024
- If F022 (ENM+WC) fails: same
- If F023 (helix COM restraints) fails: same
- If any of F021–F023 succeeds: the CHARMM36 question becomes less urgent

The force field comparison is, however, the only experiment in this set that
can definitively settle whether CHARMM36 is a ceiling on this approach, and
the answer has implications for all future origami MD work in this project.
