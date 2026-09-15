# Proposed change for review — graphene solvent-density equilibration

**Status: proposal only; not implemented.** A matched 200 ps comparison demonstrates that fixed-area pressure equilibration removes depletion-induced voids with the existing wall model while they grow at fixed volume. The fixed-volume continuation also completed its longer 344 ps persistence check with the cavities still present. Short whole-system interventions establish stability and their limitations. Existing jobs and application code remain unchanged.

## Problem to address

The periodic graphene safeguard currently disables every pressure-control stage, including stages named NPT. The as-solvated solvent volume is therefore frozen while the origami hydrates and relaxes. The actual cube_pore parent records averaged group pressure −462 bar; its pore goes from wet after minimization to dry during relaxation. Identical bulk-electrolyte controls retain about −631 bar at that initial fixed volume but reach near-atmospheric pressure after approximately 3.7% volume contraction under NPT.

An intervention on a depleted open-pore checkpoint removes 80.512 nm³ of detected void volume and restores aperture water occupancy from 550 to 806 without adding water or changing wall interactions. At equal elapsed time, a fixed-volume continuation from the same coordinates, velocities and cell has 114.304 nm³ of void and only 504 aperture waters. Both use the same physical parameters and patch margin; integration execution mode differs after a GPU-resident failure in the source segment. This is sufficient evidence to require compatible density equilibration before interpreting transport. It is not proof that an already dry full-system checkpoint will rapidly recover, nor a measurement of the correct reservoir size for converged conductance.

## Concrete behavioral change proposed

For a **new, fully solvated periodic graphene package**, provide a membrane-compatible equilibration stage that fixes the lateral lattice and equilibrates pressure normal to the membrane. Center the pressure-scaling origin on the restrained membrane plane. After the solvent volume and hydration have stabilized, start fixed-volume production from that equilibrated checkpoint and cell.

Do not silently change an existing package, enable an isotropic piston on Cartesian wall restraints, or classify a zero-current dry run as origami blockage. Preserve the existing wall force field, voltage conversion, ion detection, and original trajectory as evidence.

For the axis-aligned +z case tested here, replace the existing pressure-control settings with the following experimental configuration; do not append conflicting duplicate settings:

```tcl
# The two tangential cell vectors remain exactly the original values.
# The same membrane-centered origin must be present in the starting XSC.
cellOrigin 133.746 134.1195 12.0
useGroupPressure yes
useFlexibleCell yes
useConstantArea yes
langevinPiston on
langevinPistonTarget 1.01325
langevinPistonTemp 300
langevinPistonPeriod 1000
langevinPistonDecay 500
margin 4
```

These are the **tested experimental settings**, not yet a universal default. The origin describes the same starting periodic lattice; atom coordinates and Cartesian restraint references are not rescaled when constructing the starting checkpoint. Arbitrarily oriented graphene needs the equivalent operation in its established membrane-aligned cell frame, with dedicated validation. A tilted membrane must not be treated as if its normal were laboratory z.

Implementation would need to coordinate `namd_graphene.graphene_pressure_conf`, package pressure eligibility/manifest metadata, initial and resumed stage writers, the guards in `backend/api/routes_md.py`, production-child generation in `backend/core/md_ensemble.py`, and production inheritance of the equilibrated XSC. The existing `graphene_nanopore.cell_policy = fixed_volume` descriptor is also consumed by those guards; a new equilibration mode must survive regeneration while production remains explicitly NVT. Stage labels must report the ensemble actually executed. An explicit pressure mode should distinguish fixed volume, ordinary NPT, and fixed-area membrane equilibration; merely flipping `npt_allowed` would be insufficient.

## Relaxation and reservoir decisions

- Begin from a newly wet, minimized system; do not assume the current dry parent is a suitable production seed. Release origami restraints while continuing compatible pressure equilibration. The 8 ps force comparison shows that the initial elastic network adds substantial tensile stress; its release and solvent equilibration should be assessed together rather than assuming a named ladder stage has equilibrated. The original 1.68 ns ladder did not establish equilibrium solvent density.
- Judge completion from stable volume, temperature, pressure averages, and sustained pore hydration across successive windows, rather than a nominal stage name or a single pressure sample. Literature provides precedent for multi-nanosecond constant-area equilibration; the short controls here do not establish a universal duration.
- Transfer the **equilibrated** cell into NVT production. If using a 4 fs production integrator, verify stability and density after that transition; the bulk controls show a small density difference from 2 fs, not the large deficit needed to explain this cavity.
- More reservoir is a separate convergence choice. The original far-side DNA-to-next-membrane-plane clearance is about 2.4 nm. A follow-up comparison should add normal reservoir thickness while preserving the lateral graphene lattice, equilibrate each box, and compare bulk-like water/ion plateaus and transport. Increasing box size at unequilibrated density alone is not an evidenced cure. No exact new padding value is justified by the present controls.

## Acceptance evidence required before a production rollout

1. Fresh cube_pore remains hydrated through the proposed equilibration and a subsequent NVT segment; local water coordinates must show a connected solvent path through the aperture, not just visible beads or a nonzero water count near an edge.
2. Lateral cell vectors, membrane seam, pore radius, and wall position remain stable; normal scaling does not stretch the Cartesian restraints or create force/pressure instability.
3. Volume and averaged group/normal pressure stop drifting; pressure uncertainty is reported over time blocks. Individual instantaneous pressure samples are not an equilibrium test.
4. The saved and resumed cell equals the equilibrated cell, including its origin, and configured voltage is unchanged. A wet open-pore positive control allows ion crossings.
5. Existing fixed-volume jobs retain their recorded ensemble; tilted membranes and non-graphene packages receive separate compatibility tests.

This proposal is reviewable without applying an application patch. The [full-system NAMD configuration](full_npzat/run.conf) and [depleted-pore pressure configuration](open_pore/fill_92_npzat/run.conf) record the exact tested interventions; the [fixed-volume comparison](open_pore/fill_92_nvt_offload/run.conf) records its execution-mode difference.
