# Physical validation of CPU/CUDA DNANM, 2026-09-13

**Overall result: failed. The GPU default remains disabled.** These checks found
implementation defects beyond the earlier DNA-end sampling uncertainty. The CPU
also fails a thermostat test; CPU/GPU agreement alone is insufficient.

Follow-up: the [fundamental audit](oxdna_fundamental_audit_2026-09-13.md)
independently reproduces the contact-force ratio and qualifies its interpretation:
CPU/CUDA use different protein–DNA amplitudes, and the isolated GPU collision
approximately conserves its own twice-strength Hamiltonian. Which amplitude the
published model intended requires reconciliation. The original CPU-reference
energy failures below do not by themselves establish a nonconservative GPU
integrator. The follow-up also distinguishes correct Bussi theory, its current
implementation, global-bath mixing limits, and gaps in a Brownian replacement.

No engine code was changed during this audit. New computations used the installed
`8028cf33b3cba12992b771156085fa54879f50cd-adaptive-memory-bussi-v2` engine through
oxpy on the local CPU and RTX 2080 SUPER in mixed precision. This incurred no
additional RunPod spending. Previously completed 27 CPU/27 RTX 4090 trajectories
and existing force-free controls supplied kinetic-energy samples.

## Failed checks

### 1. GPU protein–DNA repulsion is twice the CPU interaction

The original six relaxed/stressed same-state probes pass aggregate force/torque
and directional energy-derivative tolerances. However, an energy excursion during
the biotin-tethered GPU NVE test exposed a configuration with an active protein–DNA
contact. At that configuration, GPU/CPU relative force error is 28.54% over the
whole system, 101.31% over DNA, and 97.33% for DNA torque. CPU forces agree with
finite differences of the physical potential; GPU DNA force and torque
projections disagree by approximately 50% and 49%, respectively.

A minimal reproducer containing **one protein bead and one nucleotide**, with no
gold, springs, or external forces, confirms:

| Quantity | GPU / CPU norm |
| --- | ---: |
| Force | 2.00000067 |
| Torque | 2.00000109 |

Source diagnosis: `DNANMInteraction.cpp` sets protein–backbone and protein–base
stiffness to 1.0. CUDA's `excluded_volume_quart` in `CUDA_DNANM.cuh` uses the generic
`EXCL_EPS`, which is 2.0 in `model.h`, for those same interactions. Protein–protein
repulsion also uses this helper but legitimately uses EXCL_EPS on CPU; a fix must
therefore distinguish the interaction types.

The additional contact snapshot was selected diagnostically after observing an
NVE energy excursion at reduced time 0.684. It is not an independently selected
statistical replica. Its direct force discrepancy and minimal reproducer do not
rely on equilibrium sampling. Earlier snapshot passes did not sufficiently
exercise active protein–DNA excluded-volume contacts.

### 2. Both Bussi implementations fail the weak-coupling limit

For 64 force-free protein points, initialize zero center-of-mass velocity and
kinetic energy at twice the target. Set `bussi_tau=1000000000` and
`newtonian_steps=1`. Such weak coupling should approach unthermostatted dynamics.
The predeclared test allowed a generous 0.1% energy change in one step.

| Backend | Initial K | K after one step | Change |
| --- | ---: | ---: | ---: |
| CPU | 18.6480000 | 9.32398251 | −50.000094% |
| CUDA | 18.6480002 | 9.32398241 | −50.000095% |

Both `BussiThermostat.cpp` and `CUDABussiThermostat.cu` compute current kinetic
energy but evolve cached `_K_t`/`_K_r` values initialized at the target. Those
cached values are not first replaced by the kinetic energies after the
Hamiltonian step. This differs from steps 2–4 of Bussi et al.'s algorithm and
fails its explicitly stated tau-to-infinity limit. This defect is present in the
pinned upstream source as well; it was not introduced by the preceding rigid-DOF
or CUDA RNG patches. Those earlier patches did not fix it.

### 3. Interacting-model DNA translational equipartition fails on both backends

Using the second halves of the existing nine independent replicas per geometry:

| Geometry | CPU equivalent translational temperature | CUDA equivalent translational temperature |
| --- | ---: | ---: |
| 5 nm adsorption | 372.24 K | 387.35 K |
| 10 nm adsorption | 388.02 K | 378.25 K |
| 10 nm biotin tether | 373.03 K | 383.98 K |

The target is 296 K. All six DNA translational mean tests reject the expected
value after Holm correction across 54 mean, second-moment and stationarity tests
(adjusted p = 0.000129–0.025393). The CPU biotin translational second moment about
the expected mean is also flagged. Total kinetic energy and DNA rotational
moments are not flagged. No first/second-half shift survives correction; this
alone does not establish equilibration or ergodicity.

Each statistical replicate is a complete independent seed, not a saved frame.
Means and second moments are calculated within each replica, with Student-t
uncertainty across nine replicas. The second moment about the expected mean
reflects both bias and dispersion; its temperature-equivalent RMS is not an
independent estimate of distribution width when the mean is biased.

The Bussi defect is a plausible contributor to this failure, but a corrected-
engine rerun is needed to establish causality and exclude additional sampling or
model issues. These results do not establish reliable equilibrium DNA positioning.

### 4. Native GPU internal-energy diagnostic fails

`CUDA_print_energy` reports approximately 49% of the independently evaluated CPU
internal potential on the three relaxed configurations:

| Geometry | CPU internal energy | CUDA diagnostic |
| --- | ---: | ---: |
| 5 nm adsorption | 66.549152 | 32.731000 |
| 10 nm adsorption | 70.886658 | 34.800000 |
| Biotin tether | 68.097029 | 33.356079 |

All seven tested snapshots fail the 1e-4 normalized error check. CUDA output has
only six decimal places per particle, but this cannot explain the discrepancy.

Source inspection finds that the edge nonbonded kernel uses `LR_atomicAddXYZ`,
which discards its energy component. The protein spring kernel already allocates
half the pair energy to each endpoint, while the backend divides the aggregate
by two again. Both contribute to incorrect native energy reporting. This is a
diagnostic/accounting defect separate from the protein–DNA force mismatch.
The ordinary potential-energy observable uses a CPU evaluator even during CUDA
runs; its apparent CPU/GPU agreement is not an independent CUDA energy check.

## Conservation and timestep scaling

Eighteen NVE runs cover three geometries, both backends, and dt = 1e-4, 5e-5,
2.5e-5. Every run covers the same reduced duration 1, with 10,000, 20,000 or
40,000 steps and 1,001 equally spaced measurements. All start from the same
CPU-relaxed checkpoint for their geometry, preserving velocities. No thermostat
or diffusion correction is active.

The conserved energy was evaluated as internal potential + kinetic energy +
static gold repulsion + three anchor potentials + **one** physical energy per
reciprocal tether spring. Standard oxDNA total energy omits external potentials;
blindly summing both tether force records would double-count the spring.

All runs remain finite and within the provisional peak-to-peak bound of
1e-3 kBT per physical degree of freedom over this duration. This was an engineering
bound, not a universal literature tolerance. Passing it does not override the
confirmed force discrepancy.

| Geometry/backend | Largest excursion, kBT/DOF | dt-halving fluctuation exponents |
| --- | ---: | --- |
| 5 nm CPU | 1.67e-7 | 2.16, 1.97 |
| 10 nm CPU | 2.40e-7 | 1.84, 1.80 |
| Biotin CPU | 4.73e-7 | 2.19, 0.07 |
| 5 nm CUDA | 1.57e-5 | −1.13, −0.04 |
| 10 nm CUDA | 2.08e-5 | 0.52, −1.07 |
| Biotin CUDA | 8.96e-4 | −0.002, 0.001 |

An exponent of two is expected in the second-order truncation-error regime;
the predeclared diagnostic range was 1.5–2.5. The two adsorption CPU cases pass.
The biotin CPU and all CUDA cases fail that scaling criterion. Mixed-precision
round-off plausibly dominates the small adsorption GPU fluctuations. The much
larger biotin GPU excursions expose the confirmed contact-force discrepancy.
The remaining small CPU biotin floor is not fully diagnosed. These failures are
not all equivalent in magnitude or cause.

## Passing controls and methods

The existing force-free DNA-only, protein/DNA, and protein-only controls pass ten
kinetic-energy distribution checks on CPU/CUDA after Holm correction. Translation
is measured relative to each frame's center-of-mass velocity with 3(N−1) degrees
of freedom; rigid-DNA rotation uses 3N_DNA. Bussi preserves the force-free COM
motion, so including that constant energy in a gamma distribution would be an
incorrect test. Samples are 100 steps apart with thermostat tau=10; the final
100 samples from each of two seeds are used. These equilibrium-marginal tests
alone miss the weak-coupling defect above. Protein point rotational energy stays
zero throughout all checks.

Same-state forces/torques were measured through native one-step impulses at
 dt=1e-7 from negligible initial momenta. CPU and CUDA therefore execute their own
force kernels. Directional central differences use h=1e-4 and 5e-5, covering
all positions, DNA positions, anchor positions and DNA rotations. For the
conservation audit, high-precision CPU energy evaluation is intentionally applied
to configurations generated by either backend. The independent native CUDA
energy check is reported separately. Near-zero individual forces make per-
particle relative errors ill-conditioned; those values are retained in JSON but
not interpreted as large absolute force errors.

## Artifacts and references

- [Machine-readable results](strep_physical_checks_2026-09-13.json).
- Scripts, logs, checkpoints and minimal reproducers:
  `workspace/validation/strep_physical_20260913/` (`run_checks.py`, `worker.py`,
  `nve.py`, `snapshots.py`, `thermometry.py`, `gas_distributions.py`,
  `weak_coupling.py`, `contact_pair.py`). Existing completed-campaign inputs are
  dependencies; the three relaxed checkpoints were copied individually from
  Alpine for these tests, without bulk trajectory downloads.
- [Merz & Shirts, physical validation](https://doi.org/10.1371/journal.pone.0202764).
- [OpenMM validation procedures](https://docs.openmm.org/latest/userguide/library/07_testing_validation.html).
- [Bussi, Donadio & Parrinello, canonical velocity rescaling](https://doi.org/10.1063/1.2408420),
  [accessible manuscript, Section II.2](https://arxiv.org/html/0803.4060).

## Scope follow-up: ordinary DNA2 simulations

Direct tests with `interaction_type=DNA2`, no protein particles, no ANM springs,
and no gold or attachment forces were run after the user asked about ordinary
DNA simulations. Results are in
`workspace/validation/dna2_scope_20260913/report.json`; `check.py` reproduces them.

- The Bussi weak-coupling failure also occurs in ordinary DNA2: CPU K changes
  9.1760000 → 4.58800366 and CUDA 9.17599993 → 4.58800359 in one step at tau=1e9.
  It is a shared thermostat defect, not intrinsically a CPU/GPU force discrepancy.
- An isolated DNA–DNA nonbonded contact has CPU/CUDA relative force error
  3.67354e-5 (0.003674%). The protein–DNA stiffness factor-of-two defect does not
  apply to this interaction. This single contact test is not full DNA2 validation.
- The optional `CUDA_print_energy` native edge-kernel diagnostic reports zero
  for the isolated nonbonded contact, versus CPU potential 30.7027221. The
  host-evaluated CUDA configuration energy is 30.7039667. The standard DNA CUDA
  edge kernel also omits nonbonded energy accumulation through
  `LR_atomicAddXYZ`; this diagnostic issue is therefore not restricted to DNANM.
  It does not imply that the ordinary host-evaluated energy-file potential is zero.
- NADOC's current `OxdnaStageSpec` defaults to Bussi; ordinary MD uses DNA2 unless
  overridden. Both non-validation saved local live-session input files found
  (one CPU, one CUDA) specify DNA2/Bussi. This small inventory is not a complete
  history of all local/remote jobs or their engine builds.

These defects predate the nanoparticle validation changes in the pinned engine
source. The degree of bias in each historical simulation is not established.
MC stages and MD runs using other thermostats do not exercise the Bussi defect.
The earlier protein rotational-degree bookkeeping bug also does not apply to
pure DNA, where every particle is a rigid nucleotide. The DNA translational
372–388 K result above belongs to the mixed protein/DNA campaign and must not be
assigned to ordinary DNA-only jobs without testing those systems.
