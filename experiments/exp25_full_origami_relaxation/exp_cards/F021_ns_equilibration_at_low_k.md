# F021: Extended ns-Timescale Equilibration at Low k Before Restraint Removal

## Hypothesis

Each k-step in F020 uses 50 ps of equilibration. Extending the final low-k stages
(k=0.5 down to k=0.05) to 500 ps–1 ns each will allow the solvent, ions, and backbone
to genuinely re-equilibrate after each increment, reducing the accumulated non-equilibrium
strain that drives structural collapse when restraints are finally removed at F020_16.

The claim is falsifiable: if WC ref-relative retention at F020_16 (unrestrained) is
>=85% after ns-timescale low-k stages but <85% after 50 ps stages (as expected from
F020), extended equilibration is sufficient.

## Motivation

The canonical Aksimentiev protocol (Yoo & Aksimentiev 2013 PNAS 110:20099;
Yoo et al. 2018 Methods Mol Biol) uses 10 ns of restrained equilibration at k=1
before switching to ENM restraints, then ~15 ns under ENM, then unrestrained
production at 200+ ns. The total pre-production equilibration time is on the order of
tens of nanoseconds — roughly 100-200x longer per restraint level than the current
F020 protocol (50 ps/level).

The F014 and F015–F017 series demonstrated that going directly from k=5 to any weak
chemistry-aware restraint fails within the first saved frame. This strongly implies
the system has not reached a self-supporting near-equilibrium conformation at any
k-step; each stage exits with residual non-equilibrium stress that the next k-step
cannot relax in 50 ps.

Prior data: F020 through 100K shows 99.8% C1' / 99.9% WC ref-relative at k=20 —
the system is well-constrained but likely not equilibrated in the degrees of freedom
that matter once the constraints soften. The F014_20 run (20 ps at k=5, 0.4 ns/day
throughput) achieved 99.48% C1' / 96.12% WC — indicating that even at k=5, the
system is still evolving within 20 ps.

## Starting Point

Branch from the last healthy F020 checkpoint before the unrestrained stage fails.
Nominally: `output/F020_15_310K_NPT_k0p05_50ps_p100.coor` (if F020_15 passes health
check) or the last passing checkpoint before failure.

The most useful branch points are the stages where k drops below 1.0, because that
is where the structure is most likely under-equilibrated relative to the final force
field energy landscape:

- `F020_12_310K_NPT_k0p5_50ps_p100` — extend to 1 ns at k=0.5
- `F020_13_310K_NPT_k0p2_50ps_p100` — extend to 1 ns at k=0.2
- `F020_14_310K_NPT_k0p1_50ps_p100` — extend to 1 ns at k=0.1
- `F020_15_310K_NPT_k0p05_50ps_p100` — extend to 1 ns at k=0.05

## Protocol

1. After F020 completes or fails at F020_16, identify the last passing stage.
2. From that checkpoint, generate extension confs using the F020 conf template with:
   - Same k value as the branching stage
   - `run 500000` (500 ps at 1 fs timestep) per extension segment — total ~1 ns
   - Monitor every 50,000 steps (50 ps) with C1' + WC monitors
   - Retain all other F020 settings: timestep 1 fs, fullElectFrequency 1,
     isotropic NPT, langevinDamping 1, MGH extrabonds
3. After each 1 ns extension, drop to the next k level and run another 1 ns.
4. Final stage: attempt unrestrained 20 ps (F020_16 equivalent) from the final
   k=0.05 1-ns checkpoint.

Concrete NAMD changes per extension segment (relative to existing F020 confs):
```
run                500000      # 500 ps at 1 fs
outputEnergies     5000        # every 5 ps
dcdFreq            10000       # every 10 ps for trajectory
restartfreq        50000
```

Estimated wall time: 1 ns/day throughput → ~4 ns total = ~4 days on RTX 2080 SUPER.
Consider running only the k=0.5 and k=0.1 levels at 1 ns first (2 days) as a
feasibility gate before the full ladder.

## Measurable Metrics

- Primary: WC ref-relative fraction at >=20 ps unrestrained (threshold: >=85%)
- Secondary: C1'-C1' paired fraction (threshold: >=90%)
- Tertiary: per-stage WC ref-relative drift rate over the 1 ns extension — if the
  structure is still drifting at the end of 1 ns, equilibration is insufficient
  and longer runs or a different approach is needed
- Quaternary: temperature 309 ± 5 K, pressure 0 ± 30 bar (no barostat runaway)

## Expected Outcome If Correct

WC ref-relative retention reaches >=85% at the first unrestrained frame and holds
over 20+ ps. The structure would still be physically restrained-equilibrated (not a
free-energy minimum), but would represent a much less stressed starting point for
restraint removal.

## Expected Outcome If Wrong

Even after 1 ns at k=0.05, unrestrained production still fails within the first 10 ps.
This would indicate that the collapse is not a kinetic artifact of insufficient
relaxation time but rather a structural/force-field problem: the atomistic B_tube
model has no stable CHARMM36 potential energy minimum accessible from the current
coordinates without continuous positional support.

## Priority

High. This is the cheapest experiment to execute from the existing F020 infrastructure
(no new setup, just extend existing confs), tests the most physically intuitive
hypothesis (insufficient equilibration time), and has a clear binary outcome. The
Aksimentiev protocol's 10+ ns per stage is the most directly supported literature
precedent for the current NAMD/CHARMM36 setup.

The main risk is compute time (~4 days), but because stages can be gated on health
checks, failure is caught early.
