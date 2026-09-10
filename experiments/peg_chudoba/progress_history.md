# Historical development notes

These chronological notes include superseded findings. See README.md for current status.

# Chudoba PEG port and benchmark reproduction

Active work, started 2026-09-09. No benchmark reproduction is claimed yet.
Goal: complete CPU/CUDA Hamiltonian port plus published chain-dimension and
osmotic-pressure benchmarks, with saved inputs/results and uncertainty analysis.

## Source audit

Local `reference/sources.json` records PDF provenance and SHA256 hashes.
The final publisher supporting information was retrieved through the ACS
Figshare API, article 5573527. The main open manuscript is arXiv:1710.09191v1.
Publisher metadata confirms JCTC 13, 6317–6327 and DOI 10.1021/acs.jctc.7b00560.
Direct access to the publisher main text returned HTTP 403; comparison of the
complete final main text remains outstanding. This does not prevent developing
and checking the publicly specified Hamiltonian.

Important distinctions for implementation:

* SI Table S1 supplies individual temperature fits; main Table 2 supplies
  continuous formulas. Do not silently substitute one for the other.
* Final SI confirms epsilon 1.372 kJ/mol. The earlier 1.193 value is intermediate.
* Main text specifies final cutoff 0.9 nm and zero beyond cutoff, without an
  explicit force/potential shifting rule. Reference code implements that literal
  convention; resolve any final-text qualification before claiming reproduction.
* Chemical angular convention: 130-degree internal angle, trans dihedral pi.
  Only immediate bonded neighbors are excluded from pair interactions.

## Required benchmark coverage

Source: manuscript section 2.2.2, Figures 6–8, final SI Figure S10.

| Observable | Published systems and conditions |
| --- | --- |
| Chain dimensions | N = 9, 18, 27, 36, 76, 135, 275, 455, 795; T = 294, 320, 347, 361, 371, 381, 396 K |
| Sampling reference | 300–5000 ns depending on chain; 20 blocks, first two discarded |
| Osmotic EOS | 108 chains of N = 135 or 455; 1, 10, 100, 1000 kPa; 294 and 371 K |
| EOS sampling reference | 1000 ns, initial 100 ns discarded; 10 fs timestep |

These are coverage targets, not completed simulations or guarantees that the
same elapsed time converges in oxDNA. Record autocorrelation, effective sample
size, between-seed agreement, and equilibration/finite-size sensitivity. Extract
plot targets with documented digitization uncertainty where raw data is absent.
Keep equilibrium comparison separate from a physical dynamical time mapping.

## Current evidence and next work

`tools/oxdna_peg/chudoba_reference.py` implements a separate physical-unit
energy/finite-difference-force oracle. Eight tests pass, checking the literal
Mie expression, its n=m limit, derivatives, rigid-motion invariance and zero
net force/torque. These validate the oracle; they do not validate an oxDNA port.

The shared C++/CUDA-compatible math is now implemented in
`tools/oxdna_peg/chudoba_math.h`. Its analytical many-body forces agree with the
independent oracle on 24 randomized chain/temperature cases. The CPU engine
integration is implemented in `patch_chudoba.py` and builds successfully in
`~/.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA`.
Three real one-step CPU simulations at 294, 347 and 371 K agree with the
reference forces after physical-unit conversion. Combined result: **35 tests
passed** (`tests/test_chudoba_{reference,math,engine}.py`). The patch assigns
many-body terms to their first bond, extends MC affected-pair bookkeeping and
accumulates virials. Energy/MC/pressure bookkeeping still needs direct tests.

Build reproducibly with `bash scripts/build-oxdna-chudoba.sh`. Select
`interaction_type = DNA2PEG` and `peg_chudoba = true`; legacy PEG settings
are still required by the existing parser. The published spring overrides the
legacy spring settings.
GPU integration has been added by `patch_chudoba_cuda.py`: both neighbor
list modes use the shared pair potential and gather angle/torsion forces in a
separate kernel. Existing DNA2PEG remains intact.

Latest verification: **41 tests pass**, including real CPU/CUDA force,
potential-energy and initial virial checks at three temperatures. The energy
test exposed duplicate neighbor candidates from expanded affected-pair lists;
the patch now deduplicates PEG candidates. CPU pressure sampling beyond the
initial step still needs investigation: the upstream timestamp check can
reject a final-step sample. Initial virials are verified without bypassing
the custom stress calculation (`stop_at = 0` in the test output).

First dynamics pilot: `runs/pilot_n36_t294_s101`, 36 beads, 294 K, 10 ns,
10 fs timestep, CUDA. Completed in 62.64 s (13,793 ns/day for this tiny system).
Mean Rg = 1.338 nm; autocorrelation SEM = 0.033 nm; two retained halves average
1.285 and 1.391 nm. This is not converged benchmark evidence. A rare bond
excursion to 0.534 nm at step 303500 coincides with an energy spike; independent
trajectory energy matches the engine. A 2 fs pilot was launched to investigate
integration stability before any production campaign. Do not promote the 10 fs
pilot to a calibration result.

Next: timestep-convergence and stability investigation, MC bookkeeping and
finite-density pressure checks;
full benchmark matrix, analysis and convergence extensions. Preserve the
existing experimental surface recipe until its chemical mapping is explicitly
migrated. The published bulk model does not validate the graft, DNA contacts
or field response.

Local GPU inspected: RTX 3080 Ti, no QM compute process on the GPU at inspection.
Force tests and short pilots have run; no production benchmark or cloud
resources have been started for this port. Cloud spend
remains $0 against the existing $3 authorization.

## Subsequent progress

The 2 fs / 2 ns GPU pilot (`pilot_n36_t294_dt2_s102`) completed: maximum sampled
bond 0.383 nm, mean Rg 1.368 nm, approximately nine effective samples. This is
too short to establish convergence. A 10 ns run at 2 fs with seed 101 is active
in `runs/stability_n36_t294_dt2_s101` (exec session 48158 at launch).

`patch_chudoba_observables.py` fixes CPU pressure sampling by recomputing the
custom many-body virial at the sampled state while preserving integrator forces.
It also corrects legacy MC's initial total energy for terms that involve more
than two particles. CPU/CUDA pressure checks now include the final timestep.
Snapshot energies and legacy MC's per-step cached-energy check pass. Combined
verification is **43 passing tests**, saved in `verification.txt`.

For efficient equilibrium sampling, the existing oxDNA MC2 pivot move is reused
with a PEG-specific full-energy Metropolis difference; its old per-particle sum
would weight changed many-body terms incorrectly. Local translation moves remain
in the mixture to sample bond lengths. The 10,000-sweep, 36-bead pilot completed
in 3.25 s with mean Rg 1.324 nm and about 61 effective samples, agreeing within
sampling error with the GPU pilots. MC sweeps are not assigned physical time.

`run_chain_campaign.py` is running the 294 K chain-size series, N = 9, 18, 27,
36, 76, 135, 275, 455, 795, three seeds each, initially 100,000 MC2 sweeps per
seed. Results accumulate in `runs/equilibrium_294/summary.json`; exec session
5797 and `/tmp/nadoc-peg-equilibrium294.log` identify the launcher. It uses one
CPU process at reduced priority. These allocations will be extended where
autocorrelation or between-seed discrepancies require it. This is the first
temperature in the full matrix, not a reduced definition of the benchmark goal.

New run manifests record the shared-library hash as well as the executable
hash, because the interaction implementation lives in `liboxdna_common.so`.
Earlier pilot manifests recorded only the executable and are preliminary timing
and stability evidence, not a fully versioned benchmark archive.

## Curve extraction and solution setup

`extract_targets.py` uses PyMuPDF 1.28.2 to extract vector marker centers from
the open PDF. Plot axes were visually checked against rendered pages 8–9.
`reference/published_targets.json` contains 47 chain-size and 15 EOS points,
with explicit conservative digitization bounds. These are plotted data, not
values computed from our own model or fitted to its output.

Three completed seeds at each of N = 9, 18, 27, 36, 76 give mean Rg values
0.5716, 0.8675, 1.1190, 1.3209, 2.0832 nm at 294 K. The largest difference
from the extracted Figure 6(a) centers is 1.22%. See
`chain_comparison_294.json` and `chain_comparison_294.png`. Larger chains are
still running in session 5797. This agreement is preliminary for the reasons
below; it does not complete the full benchmark matrix.

The 10 ns, 2 fs GPU run finished in 291 s: mean Rg 1.425 ± 0.027 nm (SEM),
maximum sampled bond 0.380 nm. A separate CPU dynamics run (seed 104) finished
in 156 s: mean Rg 1.314 ± 0.026 nm, maximum bond 0.379 nm. Longer independent
GPU replicas are needed to distinguish sampling variation from residual bias.

Main-paper section 4.3 explicitly uses continuous parameters within 294–381 K,
but SI Table S1 directly at 396 K. The reference and shared engine math now
follow that convention (396 K: m=5.94, sigma=0.4238 nm, mu=0.7154 nm). The
other tabulated temperatures outside that interval are also recognized. Engine
force/energy/pressure checks include 396 K, with oxDNA's explicit temperature
override enabled for these PEG-only reference runs. Values at other temperatures
outside the interpolation interval remain extrapolations, not validated states.

`solution.py` builds nonoverlapping periodic chains and implements an independent
molecular-virial pressure estimator. Its volume derivative is checked by finite
differences. `run_solution.py` prepares a 108-chain, 135-bead-per-chain, 20 g/L,
294 K GPU startup pilot (14,580 particles) in
`runs/solution_pilot_n135_m108_c20`, session 80492. The first packing attempt
stalled before any simulation; adding bounded chain backtracking resolved that
initialization limitation. This is a throughput/stability pilot, not an
equilibrated pressure measurement.

### Open cutoff consistency issue

The literal analytical potential is not exactly zero at 0.9 nm: U(rc) is
-0.01377 kJ/mol at 294 K, -0.06450 at 371 K, and -0.08915 at 396 K. Truncating
that energy creates a jump. Ordinary MD uses the truncated derivative without
an impulse at the jump, whereas Metropolis MC uses energy differences. Their
effective equilibrium models can therefore differ by a per-contact energy
shift. Existing force tests do not resolve this boundary issue.

Before calling either the port or pressure reproduction complete, implement and
compare an explicitly potential-shifted convention, check cutoff-crossing energy
conservation, and establish which convention reproduces the authors' dynamics.
Do not tune epsilon to hide the difference. The molecular-virial estimator is
appropriate for the continuous, force-consistent potential; an unshifted
discontinuous MC potential additionally needs a cutoff contribution. No current
MC pressure result should be interpreted without resolving this.

[GROMACS 5.1 documentation](https://manual.gromacs.org/documentation/5.1/user-guide/mdp-options.html)
distinguishes potential shifts and cutoff schemes; its defaults alone do not
identify the authors' tabulated-potential settings. Final-paper full-text/SI
comparison and exact table/cutoff conventions remain open source-audit items.

## Explicit cutoff comparison and current handles

`peg_chudoba_shift = true` now subtracts U(0.9 nm) inside the cutoff on CPU and
CUDA, changing energies but not smooth forces. The default remains the raw
literal truncation for compatibility with existing runs. Six real cutoff-crossing
tests show the expected raw energy jump and energy conservation with the shift,
on CPU and both CUDA neighbor modes. Total verification: **62 passing tests**.
This verifies implementation behavior; it does not resolve the authors' settings.

At N=36 and 294 K, three shifted-MC seeds give mean Rg 1.3462 nm versus 1.3209
for raw MC and a digitized paper center 1.3148 nm. The shift therefore changes
the mean by about 1.9%; the distinction cannot be silently ignored or fitted
away. Raw and shifted cohorts remain separately named and recorded.

Explicit `peg_chudoba_pure = true` now restricts neighbor lists to the PEG
0.9 nm cutoff and rejects any non-PEG particle. It leaves the Hamiltonian
unchanged and is enabled in the benchmark launchers. The larger DNA neighbor
radius had added unnecessary work. The 14,580-particle pilot took 325 s with
the original list radius and 120 s with the PEG-only list radius, each for
0.2 ns. The original timing log attributes 96% of runtime to observables,
largely frequent CPU energy reconstruction, rather than GPU force evaluation.
Reduce energy-output frequency before extrapolating production runtime.

The first solution pilot's molecular pressure is -0.46 ± 5.06 kPa (SEM from
only 20 retained frames), versus atomic pressure 1.93 kPa. Neither is a
converged EOS result. A sampled bond reaches 0.590 nm even at 2 fs in the large
system. This rare integration excursion, finite-density equilibration and
statistical uncertainty must be addressed before MD production is validated.
Use exact Metropolis sampling as an independent thermodynamic reference.

Active chain campaigns (all at reduced CPU priority, three seeds per state):

| Exec session | Output / log |
| --- | --- |
| 5797 | Raw 294 K series; `runs/equilibrium_294`, `/tmp/nadoc-peg-equilibrium294.log` |
| 41795 | Shifted 294 K full series; `runs/cutoff_shifted_294`, `/tmp/nadoc-peg-shifted294-full.log` |
| 39175 | Shifted 320/347 K; `runs/equilibrium_shifted_320_347`, `/tmp/nadoc-peg-shifted320347.log` |
| 61127 | Shifted 361/371 K; `runs/equilibrium_shifted_361_371`, `/tmp/nadoc-peg-shifted361371.log` |
| 36797 | Shifted 381/396 K; `runs/equilibrium_shifted_381_396`, `/tmp/nadoc-peg-shifted381396.log` |

The pure-list solution pilot has completed; its analysis was launched as exec
session 25567. Revalidate that handle before polling. The authoritative analysis path is
`runs/solution_pilot_pure_n135_m108_c20/analysis.json`.

### 2026-09-09 23:10 UTC — completed GPU dynamics cohort

All three zero-tail N36, 381 K GPU MD replicas completed 20 ns at 2 fs. Pooled RMS radius is 1.180928 ± 0.013438 nm (conservative SEM), versus CPU pivot 1.174929 ± 0.007834 nm. Difference 0.005998 nm is within two combined SEMs; GPU minimum squared-radius ESS 112.1 and rank/folded split R-hat 1.00475 pass current screening. This is one-state sampler consistency, not full published benchmark reproduction. See sampler_comparison.json for provenance and shared-initialization caveat.

The refreshed primary campaign covers 22/45 chain states, with 19 passing current sampling screening and no screened state outside the comparison intervals after simulation SEM, published plotted intervals and digitization allowances. Positive marker offsets remain a possible systematic discrepancy. Pressure coverage remains 1/15 three-replica states and unconverged. Status process discovery now uses the executable path, fixing omission of live NPT workers whose manifests store the library hash but not its path. No force code changed; no cloud spend.

### 2026-09-09 — completed solution GPU timing probes

Three 100-proposal HMC probes on 14,580 beads finished at 4%, 11%, and 29% acceptance for 2, 1, and 0.5 fs respectively. A separate ordinary GPU NVT probe completed 0.2 ns in 46.90 s wall time; engine observables dominate this short allocation. CPU NPT reproduction queues remain active. See gpu_solution_pilot.md for the full measurements and limitations. No cloud spend.

### 2026-09-09 — new convergence result and precision audit

N76 at 361 K completed three 700,000-sweep continuations: RMS 1.784536 ± 0.010476 nm, minimum squared-radius ESS 762.0, rank/folded split R-hat 1.00073. N135 at 371 K was newly flagged (minimum ESS 24.31, R-hat 1.03338); round6 now runs three 900,000-sweep endpoint continuations at nice19, without duplicating reserved generations. Coverage reached 24/45 chain states, 21 passing screening.

A direct Figure 5 vector audit found modest coefficient differences from rounded Table 2. Reconstructed curves increase pair B2 by 0.7–9.1% across 294–381 K, which does not straightforwardly explain the larger simulated radii. No running model parameters changed. See parameter_precision_audit.md and reference/parameter_curve_audit.json.

### 2026-09-09 — longer-chain GPU sampler check started

The GPU was verified free of simulation compute processes before allocating N135 at 396 K, three sequential 20 ns GPU MD replicas at 2 fs (seeds 721–723), each initialized from a different completed CPU origin 201–203. This tests sampling agreement in a longer collapsed chain, including the discrete 396 K SI parameters; it is not assumed equilibrated after 20 ns. CPU continuation round7 remains the independent sampler comparison. Plan: runs/zero_tail_gpu_n135_t396/plan.json.

The bounded GPU driver now accepts chain length, 381/396 K temperature and seed base. The comparator includes the new pending cohort; recalculation preserved both prior N36 cohort RMS values to 1e-12 nm, and the new cohort remains pending until all three finish. No force code changed. No cloud spend.

### 2026-09-09 — raw dense pressure control finalized

The orphaned raw-cutoff N455 × 108, 371 K, 1 kPa control completed 2,000 sweeps in 7,111.06 s; its stopped campaign driver was not resumed. Saved endpoint and trajectory analysis were refreshed and included in the raw control summary. Mean concentration 483.193 g/L, volume ESS 4.32, translation/pivot/volume acceptance 0.368/0.008/0.500. This single poorly mixed raw control is not evidence of published-model reproduction. Zero-tail primary pressure workers remain active.

### 2026-09-09 — first N135/396 K GPU replica completed

Seed721 completed 20 ns at 2 fs in 720.24 s. Maximum saved bond length was 0.39310 nm, RMS radius 2.17255 nm. Mean-radius ESS was only 8.81 after 10% discard, showing this longer collapsed-chain trajectory is not adequately sampled at 20 ns. The remaining two independent origins continue under the existing bounded plan; no three-replica agreement claim is made. Analysis: runs/zero_tail_gpu_n135_t396/s721/analysis.json.
