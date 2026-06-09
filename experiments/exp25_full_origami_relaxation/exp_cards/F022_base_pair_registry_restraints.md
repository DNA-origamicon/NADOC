# F022: Replace Positional Restraints with Watson-Crick + Dense Intra-Helical ENM

## Hypothesis

The structural collapse at F020_16 is caused by releasing all positional support
simultaneously. A chemistry-aware restraint set — dense intra-helical ENM at
k=0.1 kcal/mol/Å² plus explicit Watson-Crick H-bond proxy restraints at
k=1–2 kcal/mol/Å² — will maintain base-pair geometry while allowing backbone and
inter-helix rearrangement to proceed, bridging the gap between k=0.05 positional
restraints and fully unrestrained dynamics.

The claim: replacing k=0.05 positional with ENM+WC chemistry-aware restraints
gives >=85% WC ref-relative retention over 20+ ps where F020_16 unrestrained fails.

## Motivation

The canonical Aksimentiev protocol (Maffeo, Yoo & Aksimentiev 2016 NAR 44:3013;
Yoo et al. 2018 Methods Mol Biol) explicitly transitions from Cartesian positional
restraints (k=1 kcal/mol/Å², 3 ns) to dense intra-helical ENM (k=0.1, within 5 Å,
~15 ns), then optionally to weak Watson-Crick restraints (k=0.1) before
unrestrained production. The rationale is that base stacking and WC hydrogen bond
geometry are maintained by the local-order ENM, while the origami is free to relax
globally (the well-known "chickenwire" relaxation in XY).

The F015–F017 data showed that abruptly switching from k=5 positional to weak ENM/WC
fails within the first ps. However, those tests started from k=5 and jumped directly
to k=0.1. The current F020 approach reaches k=0.05 through a 15-stage ramp, meaning
the system coordinates are much closer to a self-consistent state. The F022 test
specifically targets the handoff from k~0.05 positional to an ENM+WC state, not a
jump from k=5.

Key difference from F015–F017: the transition point here is after 800+ ps of gradual
restraint reduction at full temperature. The starting geometry is significantly more
relaxed relative to the original F001 template.

The WC restraints should be at k=1–2, not k=0.1, because the F017 test showed
k=0.1 WC alone does not preserve geometry. The combination of dense ENM (structure
memory) + higher WC k (active H-bond enforcement) should be stronger than either alone.

Dense ENM bond count reference: the existing `generate_dense_enm_restraints.py`
produces ~3.48 million restraints at 5 Å cutoff for the full B_tube DNA atoms.
This is the correct artifact to use.

## Starting Point

`output/F020_15_310K_NPT_k0p05_50ps_p100.coor` — the last F020 stage before
unrestrained release (assuming F020_15 passes the health check).

If F020 fails earlier, use the last passing stage with k <= 0.2.

## Protocol

**Step 1: Build combined ENM + WC extraBonds file**

The dense ENM file from F016 (`results/runs/F016.../dense_enm_k0p1.extrabonds`)
needs to be scaled to the full-strength literature value k=0.1 — this file already
exists. In addition, generate WC-specific extraBonds at k=1.5 using
`generate_wc_restraints.py` with the F020 reference PDB (`B_tube.pdb` in the run dir).

Merge files:
```
cat dense_enm_k0p1.extrabonds wc_k1p5.extrabonds > enm_wc_combined.extrabonds
```

**Step 2: Generate transition conf (F022_00)**

Copy an F020_15 conf template and make these changes:
```
extraBondsFile     enm_wc_combined.extrabonds
constraints        off         # remove positional restraints entirely
# OR start with constraintScaling 0.02 and remove in F022_01
langevinDamping    1
langevinPiston     on          # keep NPT
run                50000       # 50 ps
dcdFreq            1000
```

**Step 3: Gate — if F022_00 >=85% WC ref-relative at 50 ps:**

Run F022_01: extend to 500 ps under same ENM+WC restraints.
Then F022_02: remove WC restraints, retain ENM only, run 500 ps.
Then F022_03: remove ENM, fully unrestrained 20 ps (target production).

**Step 4: Diagnostic if F022_00 fails**

If WC drops below 85% within the first 50 ps:
- Check whether failure is at crossover sites or at interior helix positions (the
  Aksimentiev counterion study found crossovers are the main hotspots for H-bond
  disruption — Bai et al. 2012 / Shi et al. 2019 ACS Nano 13:12443)
- If crossover-localized: add crossover-specific ENM terms with k=0.5 between the
  four nucleotide pairs at each crossover junction

## Measurable Metrics

- Primary: WC ref-relative fraction at >=20 ps after removing all chemistry-aware
  restraints (F022_03 unrestrained target: >=85%)
- Secondary: C1'-C1' paired fraction (threshold: >=90%)
- Tertiary: WC ref-relative per-frame drift under combined ENM+WC restraints —
  if still degrading at 50 ps, the ENM+WC combination is insufficient
- Quaternary: localization of WC failures — crossover vs interior helix — to
  guide targeted restraint placement

## Expected Outcome If Correct

The combined ENM+WC restraint state is stable at 50+ ps WC >=85%, and after removing
WC (retaining ENM only), the structure holds for at least 500 ps. After full restraint
removal, 20+ ps of unrestrained production passes the WC >=85% gate. This would
establish the literature-standard ENM-to-unrestrained path as viable for this system.

## Expected Outcome If Wrong

The system still fails within the first 10–50 ps after removing positional restraints,
even with ENM+WC support. This would indicate the collapse is not primarily a base-pair
registry failure (which ENM+WC directly addresses) but rather a global architectural
collapse — likely helix-helix XY separation driven by the absence of any force
constraining inter-helix distances. In that case, F023 (helix-axis restraints) becomes
the primary hypothesis.

## Priority

High. This is the direct implementation of the published Aksimentiev transition path,
adapted to the F020 starting point. It has the strongest literature support of any
approach in this set. The key unknowns are: (1) whether the F020 k=0.05 starting
coordinates are better-prepared than the F013/F015 k=5/k=1 starting points, and
(2) whether k=1.5 WC is strong enough to substitute for k=5 positional.

Requires building the merged extraBonds file (~10 min) and no new system builds.
