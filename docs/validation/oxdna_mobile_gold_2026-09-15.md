# Mobile gold validation — 2026-09-15

The CUDA implementation passes numerical mechanics checks and moves attached
nanoparticles. **Physical linker parameters and origami equilibration remain
unqualified.** The longer origami test failed its structural health gate.

All simulations used the local NVIDIA RTX 2080 SUPER. No RunPod jobs were
attempted; cumulative spend is $0 against the authorized $5 cap. Remote staging
is covered by tests, not by a completed cloud run.

## Model and numerical checks

Mobile rigid spherical cores have mass and rotational inertia, body-fixed graft
sites, reciprocal linker forces and torques, and DNA/core and core/core exclusion.
The linker represents a persistent attachment, not reactive Au–S chemistry.
Both generated 5′ and 3′ terminal handles were exercised for 30,000 CUDA steps.
All six handles remained grafted; endpoint distances were 0.486–0.853 nm and the
two cores translated 0.164–0.167 nm.

Analytical force and torque checks pass with edge and non-edge neighbor lists in
float and mixed precision. Maximum force error was 1.71e-6 engine units and
force reciprocity error 4.25e-7. Exclusion and split/continuous restart checks pass.

Nine 10,000-step NVE cases tested linker stiffnesses 3, 10 and 30 and timesteps
0.001, 0.002 and 0.004. The selected timestep cap is 0.002; relative full-energy
span was 7.25e-5 at the provisional stiffness 10. Full energy includes exclusion
and mass/inertia-weighted kinetic energy. Stock host energy omits the custom
kernel and is suppressed in generated inputs.

For 32 free cores sampled over 100,000 steps, translational and rotational
temperature ratios were 0.9395 and 0.9883. These are finite-sample thermostat
checks, not calibration of physical diffusion or hydrodynamic coupling.

## Throughput and structural qualification

The matched 6,012-nucleotide, 20,000-step timing pilot measured:

| System | Wall time | Steps/s |
| --- | ---: | ---: |
| DNA only | 6.583 s | 3,038 |
| DNA plus one 10 nm mobile core | 6.984 s | 2,864 |

This is approximately 6.1% runtime overhead in this single pilot, not a scaling
claim for many cores. The core translated 0.0917 nm, rotated 0.0327 radians,
and finished with a graft extension of 0.816 nm.

The managed short review job `7c83e7c70d3c` used a deliberately disabled retention
gate for an integration smoke test. After 10,000 relaxation and 20,000
equilibration steps, designed-pair retention was approximately 86% then 47%.
The matched DNA-only protocol gave 85% then 48%. Thus this short protocol is
not a qualified origami equilibration protocol, with or without gold.

The longer job `b9ea567b8dd7` used 200,000 relaxation and 50,000 equilibration
steps and an 80% retention gate. Retention was 59.5% then 54.4%; the job correctly
**failed**. Throughput remained approximately 3,005 and 2,901 steps/s. A matched
long DNA-only control has not been run; the cause of structural loss is unresolved.
Increasing run length did not establish qualification. Do not interpret the
short smoke job's completion as structural validation.

`experiments/mobile_gold/ws/Mobile_gold_review.nadoc` is the review artifact. The manifest explicitly
records `parameters_qualified: false`. Literature motivates the rigid-core graft
architecture; it does not establish the provisional effective spring constant.
See [model and literature notes](../oxdna_mobile_gold.md) for assumptions and
unsupported combinations. Numerical stability alone does not determine physical
linker compliance; that requires a defensible experimental or atomistic target.

## Evidence and reproduction

Raw evidence was moved out of the user workspace into `experiments/mobile_gold/ws/`.
Its cleanup manifest lists retained files and deleted duplicate/preliminary runs.
Original job inputs and logs retain historical absolute paths as provenance;
regenerate a job in the isolated workspace rather than directly restarting them.

Compact measurements are retained in [the JSON record](oxdna_mobile_gold_2026-09-15.json).
Native scripts are in `experiments/mobile_gold/`; mechanics, sweep and timing
commands are documented in the model notes. The retained `generated_handles`,
`dna_control` and `long_origami` modules reproduce the original campaign setup
and use its workspace paths. Choose fresh output paths before repeating runs.
The initial unsequenced-fixture timing attempt failed before simulation; the
reported timing uses the sequenced `workspace/3x6Sq_oxDNA.nadoc` fixture.
