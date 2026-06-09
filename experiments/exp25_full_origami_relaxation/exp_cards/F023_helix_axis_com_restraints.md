# F023: Helix-Axis Center-of-Mass Positional Restraints After Restraint Removal

## Hypothesis

The primary structural collapse mode is not base-pair melting but helix-helix XY
separation: when positional restraints are removed, individual helices drift away
from each other in the plane perpendicular to the tube axis, disrupting crossover
topology and triggering secondary base-pair loss. Restraining the center-of-mass
(COM) position of each helix segment (not individual atoms) will prevent global
helix-helix drift while allowing local DNA breathing, base-pair thermal fluctuation,
and backbone relaxation.

Falsifiable claim: COM helix-axis restraints allow unrestrained (no per-atom
positional) MD to reach >=85% WC ref-relative at >=20 ps, where per-atom
restraint removal at F020_16 fails.

## Motivation

The periodic-cell experiments (H013–H018 in exp23) established that the B_tube
collapse begins within the first 10 ps frame and is already at ~52% C1' by 10 ps.
The energy and temperature remain stable while structure is lost. This profile is
inconsistent with base-pair breathing from thermal noise (which accumulates over
hundreds of ps) and is consistent with a coordinated helix-helix XY translation:
helices are held in their honeycomb-packing arrangement by crossovers, but when
per-atom restraints are removed, the entire honeycomb can deform as a rigid body
in XY, pulling crossovers into strained geometries that drive rapid base-pair
disruption at the junction sites.

The Aksimentiev Counterion paper (Shi et al. 2019 ACS Nano 13:12443) specifically
identifies crossovers and nicks as the primary hotspots for hydrogen bond disruption
during production MD, consistent with crossover-strain being the initial trigger.

DNA origami tubes are known to exhibit an isotropic lateral compliance much softer
than their axial bending stiffness. In the absence of restraints, the honeycomb
packing is held by crossovers alone, and a tube with ~50 helices may have collective
soft modes in the 0–10 cm⁻¹ range that couple to large XY displacements on ps-ns
timescales before any individual base pair melts.

Helix-COM restraints directly suppress these soft translational modes without
suppressing local DNA thermal motion, base-pair breathing, or backbone
conformational sampling.

## Starting Point

`output/F020_15_310K_NPT_k0p05_50ps_p100.coor` (last F020 stage before unrestrained,
assuming it passes health check).

## Protocol

**Step 1: Identify per-helix atom groups**

Write a script `scripts/build_helix_com_restraints.py` that:
1. Reads B_tube.psf and B_tube.pdb from the F020 run directory
2. Groups DNA heavy atoms by helix ID (segment-based, using the NADOC PSF segment
   naming convention)
3. For each helix, writes a NAMD collective-variables (`colvar`) block restraining
   the XY components of the helix COM:

```tcl
colvar {
  name helix_00_com_xy
  width 0.1
  lowerboundary -999
  upperboundary 999
  com {
    atomnumbers { <comma-separated heavy-atom indices for helix 00> }
  }
}

harmonic {
  colvars helix_00_com_xy
  forceConstant 0.5         # kcal/mol/Å² per helix COM displacement
  centers 0.0 0.0           # XY COM at reference position
  outputEnergy yes
}
```

Only restrain XY (perpendicular to tube axis Z); leave Z unconstrained.
Target reference COM positions: take from the last F020_15 checkpoint coordinates
(average XY per helix) rather than the original template, to avoid re-introducing
template strain.

**Step 2: F023_00 — COM restraints only, no per-atom positional, 50 ps**

Modify a copy of the F020_16 conf:
```
constraints        off
colvarsConfig      helix_com_restraints.colvars
extraBonds         on
extraBondsFile     mgh_extrabonds.txt    # retain MGH
run                50000                 # 50 ps
dcdFreq            1000
```

Use forceConstant = 0.5 kcal/mol/Å² per helix initially (soft enough not to impede
breathing, strong enough to prevent drift >2–3 Å over 50 ps).

**Step 3: Gate results at 50 ps then 200 ps**

If F023_00 passes WC >=85% gate at 50 ps:
- Run F023_01: extend to 200 ps, same COM restraints
- Run F023_02: halve COM force constant to 0.25, run 200 ps
- Run F023_03: remove COM restraints, fully unrestrained 20 ps

If F023_00 fails:
- Diagnostic: measure per-helix XY displacement from reference in the DCD — if
  helices are NOT drifting (disp <2 Å) but WC is still failing, the collapse is
  local (crossover or base-pair breathing) and F022 (ENM+WC) is the right approach
- If helices ARE drifting despite COM restraints, increase forceConstant to 2.0
  and retry

**Step 4: Implementation note on NAMD collective variables**

NAMD 3.x collective variables module supports per-group COM restraints via the
`harmonic` bias with `com` colvar. Verify that the colvar module is compiled into
the NAMD 3.0.2 CUDA build before running (it should be). A short 1000-step test
with `colvarsConfig` but `run 0` can verify the module loads correctly.

## Measurable Metrics

- Primary: WC ref-relative fraction at 20+ ps without per-atom positional
  restraints (threshold: >=85%)
- Secondary: C1'-C1' paired fraction (threshold: >=90%)
- Tertiary: per-helix XY COM displacement from reference over the run — expected
  to stay <2 Å under 0.5 kcal/mol/Å² COM restraints
- Quaternary: global tube RMSD (measure whether the chickenwire relaxation is
  occurring in Z/rotational degrees of freedom while XY is held)

## Expected Outcome If Correct

With COM XY restraints, the B_tube remains WC-stable over 50–200 ps without any
per-atom positional support. After gradually releasing COM restraints, unrestrained
production achieves >=85% WC ref-relative. This would confirm the helix-helix XY
drift hypothesis and establish a physically meaningful restraint regime for
production: helix COM restraints mimic the experimental origami scaffold topology
constraint without suppressing internal DNA dynamics.

## Expected Outcome If Wrong

WC metric drops below 85% even with COM restraints holding helices in place. This
falsifies the "XY drift as primary mechanism" hypothesis and points toward local
base-pair instability (likely crossover junction strain or force-field problems)
as the dominant failure mode. In that case, F022 (ENM+WC) and F024 (CHARMM36
force field) should be prioritized.

## Priority

High. The XY drift mechanism is the leading mechanistic hypothesis from the H013–H018
periodic data and is consistent with the rapid, thermally-stable collapse profile.
Helix COM restraints are the most direct test of this mechanism and require no
structural rebuild — only a colvar config file. If correct, this provides a
biophysically interpretable production protocol (suppressing soft tube modes while
sampling helix-internal and crossover dynamics).

Implementation complexity is moderate: requires writing the colvar config generator
script (~100 lines Python) before running.
