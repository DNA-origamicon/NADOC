# F026: ENM-Assisted k-Ramp — Dense ENM Introduced Alongside Positional Restraint Reduction

## Hypothesis

Rather than removing positional restraints and then adding ENM (F022), or extending
equilibration at low k (F021), the optimal path is to introduce dense intra-helical
ENM gradually during the k-ramp itself, so the ENM takes over the local-order
maintenance role from the positional restraints before those restraints are removed.
By the time k reaches 0.0, the ENM is already active and the system has had time
to equilibrate with ENM as its structural scaffold.

Falsifiable claim: introducing dense ENM at k=1 (during the F020 k-ramp) and
running the ENM alongside decreasing positional k through k=0.05, then removing
positional restraints while retaining ENM, gives >=85% WC ref-relative at 20+ ps
unrestrained.

## Motivation

The Aksimentiev protocol (Maffeo & Aksimentiev 2016 NAR 44:3013) transitions from
positional restraints (k=1, 3 ns) to ENM (k=0.1, 15 ns), not from positional to
ENM simultaneously. However, the simultaneous ramp addresses a specific failure mode
observed in F022's anticipated use case: if ENM is introduced after positional
removal, there is a gap where neither positional nor ENM restraints are active, and
the structure collapses in that gap. An overlapping introduction eliminates the gap.

The F016 result (dense ENM k=0.1, no positional) showed 90.94% C1' but only 42.24%
WC ref-relative from a k=5 starting point — indicating that ENM alone at the point
of positional removal is insufficient. However, that test used the same abrupt
handoff. If ENM is already active and the system has equilibrated under ENM+positional
for 50+ ps before positional is reduced below k=0.1, the ENM scaffold has had time
to become the effective structural constraint.

The key procedural distinction from F022: F022 adds ENM only after completing F020_15;
F026 adds ENM earlier in the ramp (at k=1 stage) and carries it through to unrestrained.

## Starting Point

Branch from F020_11 (310K NPT k=1 50ps p100 checkpoint):
`output/F020_11_310K_NPT_k1_50ps_p100.coor`

This is the stage where positional restraints are weak enough that ENM can
begin to contribute meaningfully without fighting against strong positional forces.

## Protocol

**Step 1: Build the dense ENM file**

Use `scripts/generate_dense_enm_restraints.py` with the F020 reference PDB
(`restraints_dna_heavy.pdb`) at 5 Å cutoff, k=0.1 kcal/mol/Å², filtered to
exclude PSF-bonded pairs (as in F016). Output: `dense_enm_k0p1.extrabonds`.

If the existing F016 dense ENM file is compatible with the F020 PSF/PDB reference,
reuse it directly. Verify atom index range matches.

**Step 2: Generate overlapping ramp stages (F026_00 through F026_06)**

For each stage from k=0.5 to unrestrained, use both positional restraints AND ENM:

| Stage | k (positional) | ENM | Steps | Notes |
|-------|----------------|-----|-------|-------|
| F026_00 | 0.5 | k=0.1 | 50,000 (50 ps) | First ENM introduction |
| F026_01 | 0.2 | k=0.1 | 50,000 | |
| F026_02 | 0.1 | k=0.1 | 50,000 | |
| F026_03 | 0.05 | k=0.1 | 50,000 | |
| F026_04 | off | k=0.1 | 20,000 (20 ps) | Target: ENM only |

NAMD conf additions for F026_00:
```
extraBonds         on
extraBondsFile     mgh_extrabonds.txt
extraBondsFile     dense_enm_k0p1.extrabonds    # second extraBondsFile is additive
constraints        on
consref            restraints_dna_heavy.pdb
conskfile          restraints_dna_heavy.pdb
conskcol           B
constraintScaling  0.5
```

Note: NAMD allows multiple `extraBondsFile` directives; they are additive.
Confirm this behavior with a 0-step test run before committing to production.

**Step 3: Gate at each stage with C1' + WC monitors**

If WC ref-relative drops below 85% at any stage, halt and record:
- Which stage failed
- Whether failure is localized (crossovers, specific helix pairs) or global

**Step 4: After ENM-only stage (F026_04)**

If F026_04 passes (>=85% WC ref-relative at 20 ps under ENM only):
- Run F026_05: ENM k=0.05, 200 ps (reduce ENM strength)
- Run F026_06: ENM k=0.01, 200 ps
- Run F026_07: fully unrestrained 20 ps (final target)

If F026_04 passes but F026_07 fails: the ENM is necessary for stability. This
is a valid long-term production protocol (ENM-permanent production), consistent
with how the Aksimentiev group uses ENM-guided MD for structural studies.

## Measurable Metrics

- Primary: WC ref-relative fraction at 20+ ps under ENM-only restraints (F026_04,
  threshold: >=85%)
- Secondary: C1'-C1' paired fraction (threshold: >=90%)
- Tertiary: WC ref-relative at fully unrestrained 20 ps (F026_07, threshold: >=85%)
- Quaternary: energetic consistency — ENM bond energy at each stage (should not
  increase when positional restraints are removed; if it does, ENM is absorbing
  structural strain)

## Expected Outcome If Correct

The ENM+positional overlap allows a smooth handoff: at k=0.05 the positional
contribution is negligible relative to ENM, and removing positional restraints
has minimal structural impact. ENM-only production (F026_04) passes the WC gate.
Gradual ENM reduction may also succeed (F026_05–07).

This would establish an ENM-assisted production protocol directly analogous to
the published Aksimentiev approach, with the specific adaptation for B_tube's
higher initial strain.

## Expected Outcome If Wrong

Adding ENM at k=1 stage causes the same failure seen in F015 (sparse ENM from
k=0.5) or the dense-ENM direct-start failure (F016): the system fails within the
first saved frame of the ENM-only stage. This would indicate that the force field
applied by the dense ENM at the F020_11 coordinate set still introduces too much
strain, and the issue is not the transition timing but the ENM force field itself
or the coordinates it is anchoring to.

## Priority

Medium-High. This is a low-cost test (branches from an existing F020 checkpoint,
uses existing ENM infrastructure) that directly implements the smoothest version
of the ENM handoff that the literature motivates. Its key advantage over F022 is
that the ENM is introduced gradually alongside decreasing positional k, rather than
as an abrupt replacement.

Lower priority than F021 (simplest change) and F023 (tests the leading collapse
mechanism hypothesis) but higher priority than F024 (expensive system rebuild) and
F025 (redundant high-k equilibration test).
