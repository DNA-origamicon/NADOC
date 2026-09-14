# Fundamental audit of NADOC's oxDNA workflow

**Recommendation:** retain a repaired, validated Bussi option for geometry
relaxation; develop an explicitly configured Andersen-like (`john`/`brownian`)
path for production sampling and implicit-solvent dynamics. Do not switch the
current hybrid workflow by changing only the thermostat name. The installed
Bussi implementation fails an algorithmic limit, Brownian has an additional
protein bookkeeping defect, and the DNANM backends use different protein–DNA
repulsion strengths.

This audit adds native executable tests, an independent mathematical contact
oracle, an isolated CPU thermostat experiment, literature review, upstream
history, and inspection of NADOC's protocol/export code. It does not install an
engine fix or change application defaults. Fixed-gold GPU execution remains
guarded. All new calculations ran sequentially on the local CPU/RTX 2080 SUPER;
there was no additional paid computation. This is an audit of the principal
workflow and identified failure mechanisms, not certification of every oxDNA
potential, model, backend, or historical trajectory.

**Bussi is useful and current; three different scientific goals must be separated.**

| Goal | Thermostat assessment |
| --- | --- |
| Remove clashes and relax a strained design | Correct Bussi rescaling can remove released energy efficiently. MC and capped MD are deliberately preparatory calculations. |
| Sample equilibrium positions and fluctuations | Correct Bussi and Andersen-like dynamics can both preserve the canonical distribution. Adequate mixing, timestep control and the intended potential are still required. |
| Represent motion through implicit solvent | Local random kicks and momentum relaxation are needed. Global rescaling alone does not supply solvent drag or Brownian reorientation. |

The [original Bussi algorithm](https://doi.org/10.1063/1.2408420) evolves the
**current** kinetic energy after Hamiltonian integration and resizes the
velocities accordingly. It provides canonical sampling when implemented and
sampled correctly. It is not simple deterministic rescaling or Berendsen
coupling. [Braun, Moosavi and Smit's tests](https://arxiv.org/abs/1805.02295)
specifically distinguish correct canonical stochastic rescaling from the
equipartition artifacts of those older schemes. Modern
[HOOMD-blue documentation](https://hoomd-blue.readthedocs.io/en/v5.2.0/hoomd/md/methods/thermostats/bussi.html)
still supports Bussi, including separate translation and rotation baths.

The [official oxDNA relaxation recipe](https://lorenzo-rovigatti.github.io/oxDNA/relaxation.html)
uses Bussi with `bussi_tau=1000`, `newtonian_steps=53`, and capped MD at `dt=.002`.
NADOC inherited that recipe. The
[model authors' primer](https://doi.org/10.3389/fmolb.2021.693710) describes the
standalone Andersen-like default and LAMMPS's rigid-body Langevin implementation.
It also cautions that oxDNA kinetics are not quantitatively calibrated physical
time: commonly used diffusion coefficients accelerate sampling, and these
thermostats do not include cooperative hydrodynamics. Brownian coupling is
therefore a better solvent-motion model, not an automatic route to accurate
experimental rates. For the user's equilibrium DNA-positioning objective,
ensemble sampling and attachment mechanics take priority over physical timing.

**The installed Bussi algorithm has a reproducible defect, but that does not make
every use of it useless.**

CPU and CUDA calculate `K_now_t` and `K_now_r`, then evolve cached `_K_t` and
`_K_r` without replacing them with those current energies. The caches start at
the target temperature. The source history contains this behavior before
NADOC's patches. The 2020 upstream “Fix the Bussi thermostat” commit adjusts COM
treatment but leaves the cached-energy handoff intact.

With 64 noninteracting DNA2 nucleotides initially at twice the translational
target energy, zero COM velocity, `newtonian_steps=1`, and `bussi_tau=10^9`:

| CPU/CUDA implementation | One-step change in translational kinetic energy |
| --- | ---: |
| Installed CPU | −50.000094% |
| Installed CUDA | −50.000094% |
| Unchanged CPU source compiled as an isolated symbol override | −50.000094% |
| Same CPU experiment, supplying current K to the update | −0.000133% |

The last two builds use the same compiler options. They isolate the kinetic
energy handoff from compilation effects. Only selected child processes load
these diagnostic libraries; the installed engine is untouched. This restores
the expected weak-coupling limit in this test, **not full thermostat validation**.

The bad handoff is less consequential in the strong-coupling limit: with
`c=exp(-newtonian_steps/bussi_tau)` approaching zero, the update discards its
incoming kinetic energy and draws a new canonical radial energy. Rescaling can
also successfully dissipate strain during nonphysical preparation. Thus useful
relaxation is possible despite the defect. That is not a reason to preserve a
known algorithm error when a correct implementation can serve the same purpose,
or to count such relaxation frames as validated equilibrium samples.

[Upstream issue #124](https://github.com/lorenzo-rovigatti/oxDNA/issues/124)
reports low-temperature melting with GPU Bussi and was closed in March 2025
without a public explanatory comment or closure commit. It does not establish
that our shared CPU/CUDA defect is that same issue. A separate
[relaxation-version issue #63](https://github.com/lorenzo-rovigatti/oxDNA/issues/63)
remains unresolved; it likewise is not proof of our mechanism.

**Mixing and COM motion are separate from the cached-energy defect.**

A native force-free DNANM control started 32 protein points cold and 32 DNA
nucleotides hot, with an eightfold ratio of translational energies. Global
rescaling preserves that ratio in a disconnected system. After 20,000 steps:

| Thermostat/backend | Protein translational T / target | DNA translational T / target |
| --- | ---: | ---: |
| Bussi CPU | 0.22145 | 1.77161 |
| Bussi CUDA | 0.22145 | 1.77161 |
| John CPU | 0.99382 | 0.99793 |
| John CUDA | 1.00506 | 0.99691 |

These are averages of the final 1,000 sampled frames, not independent replica
tests. John used `pt=1` every ten steps. The disconnected example demonstrates
an ergodicity limitation of global scaling even if its implementation is fixed;
it does not prove that correct Bussi violates the canonical distribution in an
interacting system. It explains why correct total temperature can coexist with
slow or absent thermalization between subsets. This is an alternative mechanism
to investigate in the previously observed mixed-system DNA overheating.

In a separate pure-DNA force-free control, every particle started with COM
velocity 1 and received a uniform force 0.02 for reduced time 10. Bussi gave
final COM velocity 1.200000 on CPU and 1.200014 on CUDA: the undamped Newtonian
prediction. John with `diff_coeff=.1` dissipated the initial drift; its final
single-realization x velocities were 0.03247 and 0.05708. Those noisy values
are not precision mobility estimates. This distinction matters for NADOC's
field-driven jobs and would persist after fixing Bussi's cached K. A tethered
structure can transfer momentum to its anchors, but those restraints do not
substitute for a specified solvent friction model.

An additional harmonic control used 64 DNA2 particles in separate traps of
stiffness 1 or 16, four independent simulation seeds, 200,000 steps per seed and
method, and the second halves for analysis. Average configurational temperature
ratios were:

| Method | Soft group, mean [95% interval] | Stiff group, mean [95% interval] |
| --- | --- | --- |
| Installed Bussi | 1.097 [0.980, 1.214] | 0.916 [0.828, 1.003] |
| Current-K CPU experiment | 1.069 [0.947, 1.192] | 0.924 [0.830, 1.017] |
| John | 0.994 [0.957, 1.031] | 0.991 [0.981, 1.001] |

Intervals use independent seed means, not frames. None of twelve configurational
and kinetic mean checks rejects after Holm correction. These short, partly
degenerate harmonic systems do not establish equivalence or prove that the
current-K change cures the mixed strep/DNA overheating. That causal claim still
requires corrected-engine interacting-system runs. The directional limit test
above is decisive even though this distribution test is inconclusive.

**Brownian is not yet a one-setting replacement in NADOC.**

Two concrete issues were verified:

- Selecting `john` through `OxdnaStageSpec` does not render either `pt` or
  `diff_coeff`. A real executable run of the rendered production input exits
  with `pt or diff_coeff must be specified for the John thermostat`.
- Both Brownian implementations generate angular momenta for non-rigid protein
  points. The hot/cold control started their angular momentum at zero and ended
  with nonzero values on both backends. Mean fictitious rotational energy was
  4.764 and 4.740 reduced units, close to the 4.736 expected for 32 extra rigid
  rotors. These are not physical protein degrees of freedom. John does not use
  those values in a global rescaling factor, so this is **not evidence of the
  same DNA-heating mechanism** as the earlier Bussi DOF error. The ordinary
  kinetic-energy observable already excludes non-rigid rotations. A rigid-body
  mask is nevertheless needed for clean hybrid integration and checkpoint state.

The current standalone `langevin` alternative is also not a blanket answer.
Its explicit Euler velocity update has the free-particle stationary variance
`T/(1-gamma*dt/2)` rather than exactly T (derived from its AR(1) update).
CPU skips non-rigid angular updates while CUDA does not. These are source-level
observations, not a new Langevin validation campaign. Do not confuse this
implementation with the distinct rigid-body Langevin integrators used by LAMMPS.

**The protein–DNA force/torque claim survives independent scrutiny, with an
important qualification about which potential is intended.**

The new test executes the native CLI binary directly; it does not use the
previous oxpy measurement worker. Synthetic cases contain two particles, no
gold, no springs, no external forces, and no thermostat. They cover:

- Protein–backbone and protein–base contacts separately.
- The Lennard-Jones and quartic smoothing branches, plus outside-cutoff controls.
- Identity and rotated geometries, correctly transforming DNA torque to its
  body frame.
- Two integration impulse timesteps, `10^-5` and `10^-6`.
- Protein–protein contacts as controls against generic edge double counting.

There are 15 geometries and 60 native runs. An independently written analytic
potential/force/torque evaluator uses the CPU's numerical parameters. Its own
central finite differences agree within 2.64e-7 for force and 4.22e-8 for torque
under the normalized metrics in the JSON report.

| Active protein–DNA quantity | Native result / analytic CPU-parameter reference |
| --- | ---: |
| CPU force | 0.99999927–1.00000000 |
| CPU torque | 0.99999927–1.00000000 |
| CUDA force | 1.99954135–2.00009107 |
| CUDA torque | 1.99954141–2.00009099 |

Outside-contact cases have zero response; protein–protein cases agree near one.
The small residual variation is largest in the very narrow smoothing region in
mixed precision. It is insignificant relative to the factor of two.

CPU `DNANMInteraction.cpp` sets protein–DNA stiffness to 1. CUDA's
`excluded_volume_quart` uses `EXCL_EPS=2` for the same terms. These interaction
files have **no local modifications** relative to the pinned upstream revision.
The discrepancy is also visible in the
[original ANM repository](https://github.com/sulcgroup/anm-oxdna): CPU's
`DNANMInteraction.cpp` uses 1 while CUDA's `CUDA_ANM.cuh` uses `EXCL_EPS`.
The [upstream ANM merge](https://github.com/lorenzo-rovigatti/oxDNA/pull/192)
therefore did not introduce a NADOC-specific interaction change.

This establishes different parameterizations, not that CPU is automatically the
scientifically intended one. The
[published ANM paper](https://doi.org/10.1039/D0SM01639J) describes one epsilon
for its excluded-volume form and prints a dimensional value of 82 pN nm^-1,
although epsilon in that potential would have energy dimensions. Together with
the inconsistent released code, this is insufficient to silently select a
definitive intended amplitude. Reconcile publication, parameter-generation
assets and author intent before standardizing that value. The paper explicitly
uses equal residue and nucleotide masses; unit mass in this port is consequently
a documented coarse-graining assumption, not an explanation for this force ratio.

There is also a useful conservation check. A four-run isolated collision test
evaluates CPU trajectories with `K+U` and CUDA trajectories with `K+2U`, where U
is the CPU protein–DNA contact potential. At dt=5e-5 their relative energy ranges
are 1.88e-5 and 3.46e-5 respectively. The same CUDA trajectory evaluated with
`K+U` changes by about 1.711 energy units. Thus CUDA approximately conserves
its **own twice-strength Hamiltonian** in this example. The earlier apparent
energy failure against CPU's potential is consistent with this mismatch; it
does not establish a generally nonconservative GPU integrator. Torque doubling
is the corresponding lever-arm response to the same doubled force.

This is a serious backend-consistency defect in DNANM protein–DNA contacts. It
does not establish a factor-of-two error in ordinary DNA–DNA forces, nor invalidate
all published oxDNA work. No upstream bug report has been posted from this audit.

**Other workflow and model findings.**

| Finding | Physical implication and needed treatment |
| --- | --- |
| Shared Bussi defaults reach production and electric-field builders | Separate preparation, equilibrium sampling and dynamical settings; the frontend also explicitly seeds Bussi settings. |
| Bussi tau is an integer number of integration steps | The same tau=1000 represents reduced coupling times 2 at dt=.002, 5 at dt=.005, and 0.1 at fixed-gold dt=.0001. Changing dt changes coupling time. Persist and label units explicitly. |
| `3_equil` retains a backbone-force cap of 50 | This is only equivalent to the uncapped potential while the cap is inactive. It must not be called unconditionally unbiased equilibration. Add an explicit uncapped settling period before collecting production statistics. |
| `refresh_vel=true` is rendered for every MD stage | New stages randomize momenta. This can be legitimate preparation or ensemble sampling, but is not a continuous dynamical restart; do not stitch time correlations across these boundaries. |
| Standard DNA2 inherits `use_average_seq=true` | Assigned bases retain complementarity, but default interaction strengths are sequence averaged. Sequence-specific thermodynamic predictions need an explicit supported parameter-file path and metadata. |
| Gold and anchors correctly retain absolute coordinates and fixed-gold dt <= .0001 | Keep this safeguard. Turning on coordinate recentering in an absolute field changes the physical arrangement. Numerical stability at this dt is not itself convergence evidence. |
| Gold is a prescribed exclusion field; three traps prescribe strep orientation | Results are conditional on imposed placement and restraint stiffness, not predictions of adsorption orientation or occupancy. |
| Strep uses a 1.5 nm ANM cutoff and uniform spring constant 50 | The present near-rigid model is not a strep-specific fit to thermal fluctuations. Protein flexibility needs calibration/sensitivity checks. |
| The DNA linker uses stiffness 1.424 from a different conjugation example, and rest length from initial geometry | It is not a validated biotin–streptavidin linker model. Linker reach/flexibility and the chosen tether point can directly change predicted DNA-position uncertainty. |
| Core radius is offset by 0.8 nm and shares one repulsive shell for DNA/protein centers | The effective steric surface needs sensitivity checks. The core field is a coarse geometric barrier, not an atomistic gold potential. |
| Native CUDA potential-energy accounting is defective in edge paths | Retain the earlier diagnostic finding, distinct from forces. The normal host-evaluated potential is not an independent device-energy check. |

**Order of corrective work.**

1. Resolve the intended protein–DNA amplitude and make both backends share it;
   retain contact-branch, rotation and energy-gradient regression checks.
2. Repair current-K Bussi handling and audit rigid/point handling across CPU and
   CUDA thermostats. Implement Brownian parameter rendering and explicit stage
   selection. Use repaired Bussi for relaxation if it performs well; prefer the
   validated local bath for production of these weakly coupled hybrid systems.
3. Validate both against analytical limits, physical DOFs, force/energy/torque
   consistency, true uncapped NVE convergence, and independently sampled
   configurational/equipartition observables. Expand the ordinary DNA2 interaction
   test matrix; the present contact controls do not cover every DNA term.
4. Rerun interacting strep/DNA replicas before interpreting positional uncertainty.
   Vary orientation priors, anchor stiffness, ANM flexibility and linker mechanics;
   these model uncertainties remain even after numerical agreement is achieved.

The previous multi-replica overheating remains an observed failure with an
unresolved quantitative cause. This audit supplies stronger mechanisms and
reproducers, not a claim that any single correction has already fixed it.

**Artifacts.** Native inputs, logs and raw/derived reports are under
`workspace/validation/fundamental_audit_20260913/`. Portable script entry points
and instructions are in `scripts/validation/oxdna_physics_audit/README.md`.
The consolidated [JSON report](oxdna_fundamental_audit_2026-09-13.json) records
results and source provenance. The earlier
[physical-check report](strep_physical_checks_2026-09-13.md) retains the original
mixed-system results and diagnostic failures.
