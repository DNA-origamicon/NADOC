# F025: Extended Equilibration at k=20 Before Starting the k-Ramp

## Hypothesis

The F020 protocol starts the k-ramp from a system that has undergone only 2000 steps
of minimization at k=20 plus 10 ps NVT at 50K. This is insufficient time for the
2.3M atom explicit-solvent system to equilibrate the ion distribution, water shell,
and inter-helix packing at full restraint strength. Extending the high-k equilibration
to 1–2 ns at 310K before beginning the k-ramp will reduce the accumulated non-
equilibrium stress that propagates through the ramp and drives collapse at F020_16.

The claim: after 1 ns at k=20 310K NPT, the subsequent k-ramp reaches F020_16
unrestrained with >=85% WC ref-relative, where the current 10–50 ps high-k stages
do not.

## Motivation

The Aksimentiev practical guide (Yoo et al. 2018) uses a 3–10 ns equilibration phase
at the initial high-restraint state before beginning any restraint reduction. The
reasoning is that Mg2+ hexahydrates must diffuse into the origami structure and
occupy their stable sites near phosphate groups — a process that requires nanoseconds,
not picoseconds. If Mg2+ are poorly positioned at the start of the k-ramp, the
electric potential environment driving DNA structure is incorrect throughout the ramp,
and no amount of slow k-reduction will compensate.

The F020 MGH extrabonds file holds each Mg2+ to its six water oxygens at 500
kcal/mol/Å² (much stronger than the Aksimentiev 1 kcal/mol/Å² during equilibration),
which means the MGH clusters cannot exchange water ligands or reposition to their
equilibrium binding sites during the run. This is intentional for preventing
irreversible Mg2+-DNA binding during initial equilibration (as documented in the
Aksimentiev counterion study), but the clusters still need to translate as rigid
units to their optimal positions, which requires time.

Additional motivation: the F018 run (k=5 ramp, slower) and F020 run (k=20 ramp)
use the same time budget per level. Both are expected to fail at F020_16 unrestrained.
The difference between them is only the peak restraint strength, not the equilibration
time. If the failure mode is Mg2+ mispositioning or water-shell non-equilibrium,
longer high-k equilibration — not slower k-reduction — is the fix.

F020 health data: at 100K with k=20, the system reports 99.8% C1' / 99.9% WC ref-
relative, consistent with a well-constrained but potentially non-equilibrated structure
(the restraints are hiding any non-equilibrium stress).

## Starting Point

This experiment requires a new run from the F020 starting point (minimization),
not a branch from mid-F020 stages. The intent is to replace F020_00 (2000 steps
min) + F020_01/02/03/04 (10–20 ps at cold temperatures) with a longer high-k phase.

Recommended branch point: immediately after the F020 minimization checkpoint
`output/F020_00_min_k20` (the minimized structure).

Alternative: branch from F020_05 (310K NPT k=20 50ps) end state, which is the
first 310K NPT stage at maximum restraint — extend this specific stage to 1 ns
instead of 50 ps.

## Protocol

**Option A — extend F020_05 (310K NPT k=20) from 50 ps to 1 ns:**

Generate `F025_00_310K_NPT_k20_1ns.conf` by copying F020_05_p100 conf and changing:
```
binCoordinates     output/F020_05_310K_NPT_k20_50ps_p100.coor
binVelocities      output/F020_05_310K_NPT_k20_50ps_p100.vel
extendedSystem     output/F020_05_310K_NPT_k20_50ps_p100.xsc
constraintScaling  20
run                950000     # additional 950 ps to reach 1 ns total at 310K k=20
dcdFreq            10000      # every 10 ps
outputEnergies     5000
```

After F025_00, run the full k-ramp (k=10 → k=0.05) as in F020 stages 06–15 but
starting from the 1 ns k=20 checkpoint.

**Option B — full cold-start rebuild:**

Less practical — would require re-running the full F020 cold ramp (50K → 310K) with
extended timescales, which costs more compute and provides less clean information.
Option A is preferred.

**Monitoring:**
- Monitor Mg2+ radial distribution function (Mg-P distances) during the 1 ns
  extension to verify approach to equilibrium. Use VMD `measure gofr` or a simple
  Python script on the DCD. Convergence of the Mg-P RDF is an indicator of
  sufficient equilibration.
- Run C1' + WC monitors every 100 ps during the extension.

**Wall time estimate:** 1 ns extension at 0.4 ns/day → ~2.5 days. Then remaining
k-ramp stages at F020 timing → additional ~3 days. Total ~5.5 days for the full
F025 trajectory to F020_16 equivalent.

## Measurable Metrics

- Primary: WC ref-relative fraction at 20+ ps unrestrained (threshold: >=85%)
- Secondary: C1'-C1' paired fraction (threshold: >=90%)
- Tertiary: Mg2+-phosphorus RDF convergence during the 1 ns k=20 extension —
  compare at t=0, 250 ps, 500 ps, 750 ps, 1 ns to see if the distribution is
  stabilizing
- Quaternary: difference in structural metrics at k=0.05 (last stage before
  unrestrained) between this run and the original F020 — if identical, extended
  equilibration at k=20 had no effect on the accessible conformation space

## Expected Outcome If Correct

Mg2+ RDF converges by ~500 ps of 310K k=20 NPT. The subsequent k-ramp produces
a system with lower WC drift rate at each stage. F020_16 equivalent (unrestrained)
reaches >=85% WC ref-relative. The successful outcome would confirm that the current
F020 failure is driven by insufficient Mg2+ equilibration at the high-k stage, not
by any fundamental incompatibility between unrestrained production and the current
force field/geometry.

## Expected Outcome If Wrong

Even after 1 ns at k=20, the unrestrained stage fails at an equivalent rate to F020.
Mg2+-P RDF does not significantly change between 50 ps and 1 ns (already converged
at 50 ps). This would indicate the collapse is not caused by ion mispositioning and
is instead dominated by structural/force-field or timescale effects at the low-k end
of the ramp (favoring F021 or F024).

## Priority

Medium. This experiment is partially redundant with F021 (which tests extended
low-k equilibration) but tests the complementary hypothesis that it is the high-k
equilibration that is insufficient. It is lower priority than F021 because:

1. The F020 data at 50 ps/stage already shows the system is well-constrained at k=20
   (99.9% WC ref-relative), suggesting the high-k equilibration is not the bottleneck.
2. The Aksimentiev protocol specifically describes the 10 ns pre-ramp equilibration
   as needed for Mg2+ positioning, but the MGH-extrabonds approach (strong harmonic
   bonds) means the MGH units may equilibrate faster than free Mg2+.
3. F021 tests the low-k end, which is where the breakdown occurs, and is therefore
   a more direct test.

Promote to High if: F021 fails (ns at low-k doesn't help) and Mg2+-P RDF analysis
shows the distribution has not converged in the existing F020 k=20 stages.
