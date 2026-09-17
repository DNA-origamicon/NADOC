# Mobile gold–streptavidin–biotin–DNA approximation

The `DNA2GOLD` CUDA engine supports a rigid streptavidin coating on a translating
and rotating gold core. Newly generated biotin-DNA sets use mobile cores. Older
documents explicitly marked `oxdna_fixed_core` retain their old fixed-core model;
remove and regenerate their biotin-DNA set to select the new default.

| Connection | Approximation |
| --- | --- |
| Gold to streptavidin | Rigid attachment at the authored coating pose, for both adsorption and biotin-tether placement modes |
| Streptavidin to biotin | Permanent occupancy of the authored tetramer/chain pocket |
| Biotin to DNA | Harmonic tether from the pocket C11 anchor to the native 5′ backbone site; authored linker reach is its rest length |

The tether transfers equal and opposite forces, including DNA and core torques.
No fictitious DNA bases or independent biotin particles are introduced. The
streptavidin and biotin coordinates follow the mobile core in trajectory display.
Four radius-1.1 nm monomer spheres per tetramer provide coarse steric exclusion
against DNA and other composite particles. Contacts transfer torque to the owner
core. These spheres are a deliberately approximate envelope, not atomistic shape.

Pocket geometry comes from the existing PDB-aligned model. The primary
[1STP structure and associated study](https://www.rcsb.org/structure/1STP) support
the pocket geometry and high-affinity binding architecture. They do not calibrate
our coarse spring or adsorption mechanics. The provisional spring stiffness is
1.424 oxDNA energy/length², inherited from the older coarse tether; the authored
1–10 nm linker reach is preserved rather than fitted to the starting conformation.

Use Conjugate Manager to apply streptavidin and generate biotinylated DNA, then
prepare an oxDNA job normally. Every simulation stage uses CUDA MD; there is no
CPU simulation fallback. The updated engine is selected through the existing
mobile-gold engine path. `COATING_V1` in `mobile_gold.dat` records body-local
monomer centers. Older mobile-gold binaries reject that extension instead of
silently dropping the coating. See [mobile gold build instructions](oxdna_mobile_gold.md).

The approximation supports at most 64 gold cores and 64 total tetramers. It
rejects missing strands/tetramers, duplicate terminal grafts, duplicate pocket
occupancy and chain A occupancy when that pocket is reserved for the gold tether.
Unrelated protein models, quantum-dot cores and electrode/surface combinations
remain unsupported. Standalone DNA-only topology export still rejects coatings.

This model does **not** simulate adsorption/desorption, protein sliding or
reorientation relative to gold, biotin unbinding, protein deformation, or explicit
TEG conformations. Coating mass and hydrodynamic drag are omitted: the integrator
uses the bare gold sphere mass/inertia and diffusion approximation. Absolute
kinetics and binding energetics are unqualified. Numerical attachment checks do
not establish origami pairing stability or equilibrated structural ensembles.

Native verification scripts and retained evidence live under
`experiments/mobile_gold/`, with generated outputs isolated in its ignored `ws/`
directory. See [validation results](validation/oxdna_mobile_strep_2026-09-16.md).
