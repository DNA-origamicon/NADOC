# Chudoba PEG port and benchmark reproduction

**Active, incomplete goal.** The bulk Hamiltonian is implemented in an isolated
oxDNA CPU/CUDA engine. The current reconstruction uses `--cutoff zero_tail`,
supported by the published potential-curve audit. Benchmark reproduction and
verification against the final journal main text remain outstanding.
See [STATUS.md](STATUS.md) for concise coverage and validation evidence.
The existing PEG surface demo uses a different mapping and remains experimental.

This file includes the investigation history. Earlier raw/shifted results remain
controls; their initial interpretation as the published Hamiltonian is superseded
by the zero-tail reconstruction documented below. Published chain-size comparisons
use sqrt(mean(Rg²)), rather than mean instantaneous Rg.

## Sources and model

Model: Chudoba, Heyda and Dzubiella, JCTC 13 (2017), 6317–6327,
[DOI 10.1021/acs.jctc.7b00560](https://pubs.acs.org/doi/10.1021/acs.jctc.7b00560).
Checked against the [open manuscript](https://arxiv.org/abs/1710.09191) and final
publisher SI (`reference/ct7b00560_si_002.pdf`). PDF hashes and provenance are in
`reference/sources.json`. The complete final main text has not been accessed;
publisher metadata alone does not establish identical methods.

* One bead per symmetric CH2–O–CH2 repeat; methyl-capped chain mapping.
* Harmonic bond: 0.33 nm, 17000 kJ/mol/nm², factor 1/2.
* Cosine-harmonic internal angle: 130°, 85 kJ/mol, factor 1/2.
* Torsion amplitudes (1.96, 0.18, 0.33, 0.12) kJ/mol; phases (π,0,0,0), trans π.
* Normalized Mie plus Gaussian, nominal cutoff 0.9 nm; the current convention
  zeroes the negative outer tail after the barrier. Only directly bonded pairs are
  excluded; 1–3 and 1–4 interactions remain. Corrected epsilon 1.372 kJ/mol.
* Continuous temperature formulas over 294–381 K; section 4.3 specifies the
  discrete SI fit at 396 K. Discrete 270/422/450 K fits are also implemented.
  Other extrapolated temperatures are not validated.
* oxDNA orientation vectors are bookkeeping for these isotropic PEG beads;
  the PEG potential depends on bead positions, not those vectors. Native kinetic
  output includes auxiliary rigid-body rotation and is not PEG translational
  kinetic energy alone. The HMC acceptance calculation uses translational
  kinetic energy explicitly.
* Units: 0.8518 nm, 24.943387854 kJ/mol. PEG-only dynamics uses mass 44 g/mol
  and time unit 1.131322 ps. Concentrations use chemical mass 44.05 g/mol.

This neutral implicit-water bulk model does not validate surface, DNA, ion or
field interactions. MC sweeps are sampling attempts, not physical time.

Build with `bash scripts/build-oxdna-chudoba.sh`. Upstream revision is pinned to
`8028cf33b3cba12992b771156085fa54879f50cd`; isolated installation is under
`~/.local/share/nadoc/engines/oxdna-chudoba/build/`. It does not replace the
existing `oxdna-peg` engine. Manifests hash the executable AND shared library.
NADOC UI selection of this chemical model is pending.

Inputs use `interaction_type = DNA2PEG`, `peg_chudoba = true`, plus legacy PEG
parser settings. `peg_chudoba_pure = true` requires all particles to be PEG and
shortens neighbor lists without changing the interactions. Shared analytical
CPU/CUDA math, patch scripts and the independent oracle are in `tools/oxdna_peg/`.

## Unresolved cutoff convention

The literal potential is nonzero just inside 0.9 nm: −0.0137708 kJ/mol at 294 K
and −0.0891505 at 396 K. Raw truncation has an energy jump. Smooth-force MD
without a boundary impulse samples the potential-shifted Hamiltonian, while
raw-energy Metropolis samples a different Hamiltonian. The authors' original
input tables have not been located.

Both are exposed: `peg_chudoba_shift = false` (literal raw default) and `true`
(subtract U(rc) inside cutoff). Cutoff-crossing tests demonstrate the raw jump
and shifted conservation on CPU/CUDA. At N=36, 294 K, three-seed mean Rg is
1.32094 nm raw versus 1.34623 nm shifted. Do not hide this difference by refitting.

The smooth molecular-virial estimator lacks the boundary impulse for raw MC.
Raw MC EOS comparisons therefore use NPT mean volume, not that estimator.

## Current evidence

`verification.txt`: **72 tests passed** locally, including independent forces,
CPU and both CUDA neighbor modes at 294/347/371/396 K, interacting periodic
chains, energies/virials, MC snapshots, cutoff crossings, ideal-gas NPT volume
statistics and interacting NPT snapshot energies with cell and Verlet lists.

`chain_comparison_294.json` and `.png`: three independent raw-MC seeds per
length. Completed N=9,18,27,36,76,135 mean Rg deviations from digitized published
markers are approximately 0.02%, −0.12%, 1.22%, 0.47%, 0.64%, 0.59%.
These are preliminary results; cutoff, convergence and finite-seed limits remain.

`campaign_comparison.json` and `.png` report all completed three-seed states
and explicitly list missing coverage. Shifted N=76 results at 361/381 K are
approximately 16%/25% larger than the published markers. Further shifted
allocations have therefore been stopped; their current child runs may finish.
Raw high-temperature campaigns now take priority. This is evidence for testing
the literal cutoff, not proof of the authors' original implementation.

The 10 fs MD pilot showed rare large bond excursions. Current MD checks use
2 fs; independent CPU/CUDA sampling and timestep convergence remain required.
The 108×135-bead solution MD pilots lasted only 0.2 ns and are unequilibrated.
CPU observables dominated their timing; do not extrapolate as GPU force speed.

## Benchmarks and operation

`reference/published_targets.json` contains 47 chain-size and 15 EOS markers,
with explicit digitization bounds from vector markers in the open manuscript.

* Chains: Figure 6a short-chain 294 K points; Figure 7b N=36,76,135,275,455,795
  at T=294,320,347,361,371,381,396 K. Current campaigns allocate 100000 pivot-MC
  sweeps and three seeds per state; this is not a convergence guarantee.
* EOS: 108 chains. N=135, 294 K at P=1,10,20,50,100,200,1000 kPa;
  N=455, 294/371 K at P=1,10,100,1000 kPa.
* Published allocations: 300–5000 ns for chains, 1000 ns for EOS. Equilibrium
  MC may reproduce observables without matching physical time, provided mixing,
  independent seeds and initialization sensitivity are established.

Launchers: `run_chain.py`, `run_chain_campaign.py`, `run_solution.py`.
Analyzers: `analyze_chain.py`, `compare_chain.py`, `analyze_solution.py`,
`analyze_npt.py`. Completed-run status does not imply equilibrium. Runs retain
inputs, topology, coordinates, trajectories, logs and manifests. New large runs
live in `workspace/peg_chudoba/runs`, with experiment-tree symlinks.

NPT uses translations, pivots and symmetric log-volume proposals. Molecular
centers and box scale together; internal coordinates stay fixed. The acceptance
Jacobian is (N_molecules+1) log(V'/V). Cell lists are now the NPT default: the
14580-bead, 20-sweep test took 6.21 s. The older Verlet pilot was stopped cleanly
after 153 sweeps / 504.56 s, marked interrupted, and replaced by a cell-list run.
These are RTX 3080 Ti workstation observations, not RTX 6000 estimates.

The 2000-sweep cell-list run finished in 467.85 s. Its retained NPT estimate is
19.33 g/L versus digitized 17.21 g/L, but only ~2.94 effective volume samples
remain and the retained half means drift. It is explicitly unequilibrated.
Two 20000-sweep allocations now use seeds 301/302 and starting concentrations
20/14 g/L to test equilibration. Seed 301 repeats its original initial state;
the 2000-sweep pilot is not an additional independent replica.

Current allocations (reinspect processes and `run.json` before resuming):

| Directory under `runs/` | Allocation |
| --- | --- |
| `equilibrium_294` | Raw 294 K chain series |
| `cutoff_shifted_294` | Further allocation stopped; current N=135 child may finish |
| `equilibrium_shifted_320_347` | Further allocation stopped; current N=135 child may finish |
| `equilibrium_shifted_361_371` | Further allocation stopped; current N=135 child may finish |
| `equilibrium_shifted_381_396` | Further allocation stopped; current N=135 child may finish |
| `equilibrium_raw_320_347` | Raw 320/347 K, shorter chains first |
| `equilibrium_raw_361_371` | Raw 361/371 K, shorter chains first |
| `equilibrium_raw_381_396` | Raw 381/396 K, shorter chains first |
| `npt_cells_n135_m108_p10_raw_s301` | Completed 2000-sweep pilot, insufficient sampling |
| `npt_n135_m108_p10_raw_s301_20k` | 20000 sweeps, starts at 20 g/L |
| `npt_n135_m108_p10_raw_s302_20k` | 20000 sweeps, starts at 14 g/L |
| `dynamics_n36_t294_dt2_shifted_s105` | CUDA N=36, 294 K, 20 ns at 2 fs |

PEG jobs use nice 19; existing QM jobs remain untouched. Cloud spend: $0 / $3.
Next: solution mixing and all EOS states with independent seeds; long-chain and
high-temperature convergence/initialization checks; cutoff/source audit; then
NADOC chemical-model selection. Historical findings are in `progress_history.md`.

## GPU Metropolis correction (HMC)

`sim_type = PEG_HMC` uses CUDA mixed-precision Verlet trajectories as proposals,
with independently refreshed translational Maxwell momenta and a Metropolis
accept/reject step using the full CPU endpoint energy plus translational kinetic
energy. Momentum reversal supplies the reversible proposal; rejected positions
are restored. This is an equilibrium sampler, not a physical-time trajectory.
The method follows the reversible, volume-preserving proposal construction in
[Neal, MCMC Using Hamiltonian Dynamics](https://arxiv.org/abs/1206.1901).
The method reference and hash are saved in `reference/neal_hmc_2011.*`.

This corrects the endpoint energy errors, including the raw cutoff jump, rather
than claiming ordinary smooth-force MD samples that discontinuous Hamiltonian.
Finite-precision and convergence checks remain necessary. HMC currently requires
pure chemical PEG, CUDA mixed precision, and no external forces, sorting or MD
barostat. Optional molecular log-volume MC moves provide NPT sampling. Existing
CPU MC and ordinary CPU/CUDA MD implementations remain available.

Sources: `tools/oxdna_peg/PEGHMCBackend.h`, `peg_hmc_backend.inc`, and
`patch_chudoba_hmc.py`. The build script includes them. Chain and solution
launchers accept `--sampling hmc --hmc-steps N`. Solution HMC also accepts
`--hmc-volume-attempts N` and `--initial-run PATH`; the latter checks the source
model and dimensions and records configuration/manifest hashes. HMC manifests
have no physical duration, and new HMC energy outputs count macro proposals.
Earlier pilot energy files inherited MD-style fractional labels; their saved
trajectory headers and manifests identify actual proposal counts.

Checks now cover HMC rejection rollback, independent endpoint energies,
interacting periodic solution snapshots, the ideal-gas NPT volume distribution,
and the analytic two-bead radial distribution proportional to
r² exp[-k(r-b)²/(2RT)]. Full current engine suite: 72 passing tests; hashes in
`verification_manifest.json`.

Completed first GPU raw-cutoff chain allocation:
`runs/hmc_n36_t381_raw_s902`, N=36, 381 K, 20000 proposals × 500 Verlet steps,
2 fs proposal timestep, 297.09 s wall time. Mean Rg=1.13267 nm, estimated
SEM=0.06737 nm, ESS≈12.7, retained half means 1.22459/1.04076 nm. Acceptance
was 86.04%. This is consistent with raw CPU MC and the published marker but is
not converged; it needs extension and an equilibrated/compact initial state.

Twenty-proposal 108×135-bead solution diagnostics at 294 K, 1 ps proposal length:

| Initial state | Cutoff | Timestep | HMC accepted |
| --- | --- | --- | --- |
| Packed initial geometry | Raw | 2 fs | 0/20 |
| CPU MC 2000-sweep endpoint | Raw | 2 fs | 1/20 |
| CPU MC endpoint | Raw | 1 fs | 0/20 |
| CPU MC endpoint | Raw | 0.5 fs | 7/20 |
| CPU MC endpoint | Shifted | 2 fs | 1/20 |

These small pilots are not throughput or convergence claims. The shifted
control also rejects heavily, demonstrating an integration-error contribution,
not only a cutoff mismatch. Do not use the 2 fs large-solution HMC configuration
as production evidence. CPU NPT allocations continue independently.

## Sampling performance changes

Temperature-only pair coefficients are cached per CPU thread and invalidated
on temperature changes. Identical pair checksums and all independent force tests
are retained. Informal timing source/results are in `performance/`; this does
not change the potential and is not a whole-simulation speed claim. Existing
processes keep their previously loaded library; subsequent manifests record the
new library hash.

New single-chain pivot runs use proposal weight `min(0.1, 3/N)` against local
translation weight 1, keeping approximately three pivots per sweep for long
chains. Earlier runs used 0.1 regardless of N. Both preserve the same equilibrium
distribution; sampling efficiency/convergence must be compared from outputs.
The resolved weight is recorded in the run manifest and input, and can be set
explicitly with `--pivot-prob`. This avoids spending an increasing fraction of
long-chain work on dozens of global rotations per sweep.

A longer GPU HMC comparison is now running in
`runs/hmc_n36_t381_raw_warm_s903`: 100000 proposals, 500 steps per proposal,
2 fs, seed 903. It starts from the completed raw CPU MC N=36, 381 K, seed 203
endpoint; initial coordinates were checked for exact preservation. This is an
independent sampler seed, not an additional independent CPU-chain replicate.
`run_chain.py --initial-run PATH` now records the source configuration and
manifest hashes as well as the new sampler settings. Assess the long HMC run
against both the short extended-start HMC run and independent CPU seeds.

## Full first-pass EOS campaign

`run_eos_campaign.py` now records and executes a restartable, sequential plan.
`runs/eos_full_plan/plan.json` contains all 15 published states × 3 seeds = 45
initial allocations. Three disjoint queues are running, one simulation per queue:

| Queue | Allocations | Local log |
| --- | --- | --- |
| `runs/eos_pilot_n135_t294` | 7 pressures × 3 seeds | `/tmp/nadoc-peg-eos-n135-294.log` |
| `runs/eos_pilot_n455_t294` | 4 pressures × 3 seeds | `/tmp/nadoc-peg-eos-n455-294.log` |
| `runs/eos_pilot_n455_t371` | 4 pressures × 3 seeds | `/tmp/nadoc-peg-eos-n455-371.log` |

Each initial allocation is 2000 MC sweeps, 108 chains, raw cutoff, cell lists.
Seeds 401/402/403 start at 1.15/0.85/1.00 times the digitized concentration,
respectively. These values only choose initial states: the pressure ensemble,
Hamiltonian and resulting concentration are not fitted or constrained to them.
Convergence requires independent-start agreement, adequate effective samples,
structural stationarity and appropriate extensions. A result staying near its
initial target is not sufficient evidence.

The molecular log-volume proposal width is explicitly recorded in each plan:
0.04 below 30 g/L, 0.015 below 150 g/L, 0.003 for denser 294 K states, and
0.001 for the dense 371 K branch. Pivot weight is min(0.01,1.5/N) against
translation weight 1, avoiding excessive global rotations in long chains.
Existing 20000-sweep, 10 kPa N=135 runs continue independently.

Local 50-sweep cost/acceptance probes (not equilibrated EOS data):

| System | Time | Translation / pivot / volume acceptance |
| --- | --- | --- |
| 108×135, 294 K, initial 75 g/L | 23.30 s | .328 / .136 / .088 |
| 108×455, 294 K, initial 6 g/L | 84.39 s | .327 / .320 / .204 |
| 108×455, 371 K, initial 420 g/L | 186.87 s | .362 / .006 / .424 |

Removing the redundant accepted-PEG-pivot list rebuild preserved the checked
energies, but the repeated dilute 455-bead timing was 82.43 s: no substantial
speedup is established by these timings. Six focused MC/NPT regression checks
pass after that change. Earlier full-suite results remain in `verification.txt`.
The first-pass dense queue alone is roughly a day of local CPU work by simple
extrapolation; concentrations, contention and convergence extensions can change
that estimate. This is not an RTX 6000 performance estimate.

`analyze_npt.py` now records terminal move acceptance, chain-size traces and
maximum bond length in addition to concentration and volume correlations.
`compare_eos.py` produces `eos_comparison.json/.png`, reports missing three-seed
states, and avoids double-counting a pilot and its longer same-seed repeat.
All estimates remain explicitly unvalidated until convergence is assessed.

## Cross-replica convergence assessment

`sampling_diagnostics.py` implements rank-normalized and folded split R-hat
using [Vehtari et al. (2021)](https://doi.org/10.1214/20-BA1221); the method PDF
and hash are retained in `reference/vehtari_rhat_2021.*`. Four focused diagnostic
tests pass, including separated means, unequal variances, frozen traces and an
AR(1) autocorrelation reference. The autocorrelation estimator now pairs lags
(0,1), (2,3), etc. with the initial-monotone truncation. ESS remains capped at
the saved draw count. New analyses carry `diagnostics_version = 2`.

The comparison scripts recompute current correlation diagnostics from saved
traces rather than trusting older cached ESS estimates. R-hat >= 1.01 or fewer
than 100 effective samples per replica recommends extension; these are triage
criteria, not proof of equilibrium. Constant volume traces are explicitly
excluded from uncertainty-based EOS comparisons. Chain-size reports also
exclude solution records, so future EOS summaries cannot be mistaken for
single-chain replicas.

`runs/chain_extensions_round1/plan.json` queues 18 continuations (three replica
origins per state) from completed CPU endpoints:

| State | New sweeps per replica |
| --- | --- |
| N=76, 371 K | 600000 |
| N=76, 381 K | 300000 |
| N=76, 396 K | 300000 |
| N=135, 361 K | 300000 |
| N=135, 371 K | 500000 |
| N=135, 381 K | 600000 |

The launcher is `run_chain_extensions.py`, log
`/tmp/nadoc-peg-chain-extensions1.log`. This plan is a snapshot of completed
flagged states; newly completed states still require assessment. Continued runs
record `replica_id` and `sampling_generation`. Comparisons never count a source
trajectory and its continuation as independent replicas, and only promote a
new chain generation once its complete three-replica set is available.

The longer GPU HMC run `hmc_n36_t381_raw_warm_s903` has completed: mean Rg
1.14024 nm, autocorrelation SEM 0.01558 nm, block SEM 0.01647 nm, ESS about 244,
acceptance 85.75%, maximum bond 0.38891 nm, elapsed 1215.19 s. The published
marker is 1.13883 nm and the three-seed CPU mean is about 1.11187 nm; these are
consistent within combined sampling/digitization uncertainty. Retained HMC half
means are 1.16860 and 1.11187 nm, so independent GPU replicas are still needed.
`run_hmc_replicas.py` now runs warm seeds 904 and 905 sequentially, from the
independent CPU seed-201/202 endpoints, logging to
`/tmp/nadoc-peg-hmc381-replicas.log`. HMC proposal counts have no physical-time
interpretation.

## Correction: published chain-size observable

`audit_rg_definition.py` integrates the seven vector probability-density curves
in preprint Figure 7(a), then compares their moments with the independently
extracted 795-mer markers in Figure 7(b). Every marker agrees with
**sqrt(mean(Rg²))**, within 0.003 nm. The mean instantaneous Rg differs by as
much as 0.164 nm. The plotted density areas are 0.9997–1.0003; integration uses
exact piecewise-linear moments. Evidence is retained in
`reference/rg_definition_audit.json`, including the source hash. Finite plot
range and vector rounding remain limitations. This establishes a strong
internal consistency check for Figure 7; using the same convention for Figure
6 is an explicitly inferred consistency assumption.

Earlier README/progress comparisons using mean instantaneous Rg are superseded.
Both comparison scripts now use sqrt(mean(Rg²)), with autocorrelation and
18-block uncertainties on Rg², propagated through the square root by the delta
method. Between-replica uncertainty is also computed on Rg². Diagnostics use
squared-radius traces. The original mean-Rg measurements remain valid as a
different observable; no trajectories or interaction parameters were changed.
Six focused statistics tests pass (`verification_rg_statistics.txt`).

The corrected comparison is not a universal pass: raw N=36 at 381 K is now
1.1373 nm versus the 1.1388 nm marker, while N=275 at 320 K is 4.3282 nm,
about 9.6% above the marker despite acceptable current mixing diagnostics.
N=135 at 396 K remains about 8.7% below its marker with sampling flagged.
These discrepancies require investigation; neither extra sampling nor an
observable correction should be assumed to eliminate them. Existing saved-endpoint
extension allocations continue unchanged, and all EOS estimates remain preliminary.

## Solution structural mixing diagnostics

EOS comparisons now require chain-shape mixing as well as volume mixing before
clearing their extension recommendation. The first complete three-seed N=135,
294 K, 1 kPa pilot gives 2.2841 g/L versus the published 2.3026 g/L, but volume
R-hat is 1.382 and chain-shape R-hat is 1.269, with only about four effective
samples for each. Agreement of the averages does not establish reproduction.

New solution allocations write `shape.dat` at the thermodynamic sampling
cadence (roughly 1000 records per allocation), without increasing the size of
full trajectory files. `PEGChainShape.h` reconstructs each ordered linear
molecule through minimum-image bond displacements and reports mean Rg in nm
and mean Rg² in nm² over molecules. It does not mutate the configuration.
The observable requires CPU coordinates, including synchronization for CUDA.
`analyze_npt.py` prefers this trace when present; existing runs fall back to
saved configurations and are flagged when structural sampling is insufficient.
An acceptable shape diagnostic alone does not prove all aggregation modes mixed.

Five focused checks pass, including agreement with independent configuration
analysis for CPU NPT, CUDA MD and CUDA HMC. Build/source hashes are retained in
`verification_shape_manifest.json`; output is in `verification_shape.txt`.
Already running engines and inputs retain their previous observable set; new
children in the existing queues receive the additional output. No interaction
parameters or Monte Carlo acceptance rules changed.

## CUDA cell-capacity correction

The third warm GPU replica, seed 905, stopped at saved proposal 800 (error
configuration step 804) with a cell-overflow error. The upstream cell-fill
kernel checked the shared count after insertion with `count >= capacity`,
incorrectly rejecting a cell containing exactly its allocated number of beads.
It also wrote before checking capacity. A compact chain can trigger this case
without an unstable trajectory.

`patch_chudoba_cells.py` now uses the slot returned by atomicAdd, writes only
when `slot < capacity`, and flags larger slots as overflow. Two exact-capacity
force/energy regressions (edge and non-edge CUDA) fail on the old code and pass
on the correction. A separate actual-overflow case still fails safely. Together
with CPU/CUDA, HMC and shape regressions, 36 tests pass; results and hashes are
in `verification_cells.txt` and `verification_cells_manifest.json`. The failing
regression output is preserved in `verification_full_cell_before.txt`.

The failed run is retained unchanged. `hmc_n36_t381_raw_warm_s905_retry1` restarts
the full allocation from the same independent CPU endpoint and seed, using the
corrected library. The failed prefix will not be pooled with the retry.
`hmc_s905_recovery.json` records the relationship; log:
`/tmp/nadoc-peg-hmc381-s905-retry1.log`. Warm seed 904 completed 100000 proposals
with RMS Rg 1.15868 nm; the independent GPU cohort is still incomplete.

The first three-replica chain extension (N=76, 371 K, 600000 additional sweeps
per origin) completed. Its corrected RMS Rg is 1.60657 ± 0.01879 nm SEM versus
the 1.65694 nm marker. Minimum squared-radius ESS is about 180, but R-hat
1.01078 still exceeds the current triage threshold, and the largest retained
half difference is 0.11076 nm. This is not a completed convergence claim.

## New evidence: zero outer attractive tail in the plotted Hamiltonian

`audit_potential_curves.py` digitizes the adjusted green and red vector lines
in preprint Figure 4(b), excluding legend segments. It compares analytic curves
without fitting any parameter. With the SI's discrete parameters, retaining
only the positive portion beyond the Gaussian center reproduces the plotted
294 K and 371 K curves with RMS errors 0.000503 and 0.000466 kJ/mol and maximum
errors below 0.00161 kJ/mol. Both plots remain exactly zero after their outer
zero crossing, before the nominal 0.9 nm cutoff. Raw truncation retains a small
negative tail there; subtracting U(0.9) shifts the entire interior curve and
also disagrees. Full vector coordinates, comparison variants and source hash
are in `reference/potential_curve_audit.json`.

This strongly supports **zeroing the outer attractive tail**, consistent with
the text's removal of the second minimum, rather than the previously inferred
raw or globally shifted truncation conventions. The final journal main text and
original GROMACS tables remain unavailable, so this is a reconstruction from
the preprint's explicit plotted Hamiltonian. Figure 4 uses discrete fitted
parameters; Figure 7's text specifies continuous functions at 294–381 K and
Table S1 at 396 K. Those distinctions must remain intact.

Further allocations of the raw Hamiltonian were paused by terminating only
the sequential queue drivers, leaving their current child simulations to
finish. `raw_queue_pause.json` records the PIDs, commands and reason. The raw
results remain useful controls but must not be called a reproduction of the
plotted Hamiltonian. Completed orphaned children may need their analyses and
cohort summaries refreshed. The independent GPU raw-HMC check continues.

Before this curve finding, a three-origin 20000-sweep EOS continuation plan was
created at `runs/eos_extensions_n135_t294_p1_round1/plan.json`; its first child
is running and its driver is included in the pause. That plan and all endpoint
provenance remain available. The next implementation step is an explicit
`zero_tail` convention with CPU/CUDA force checks and separate benchmark
allocations; do not overwrite or silently reinterpret earlier raw runs.

## Explicit zero-tail implementation and new benchmark cohorts

The engine option `peg_chudoba_zero_tail = true` removes the negative outer
tail when r > mu(T), while retaining the inner attractive well. It is mutually
exclusive with the globally shifted convention. CPU and CUDA use the same
energy/derivative rule; the nominal neighbor cutoff remains 0.9 nm. The outer
zero crossings and full temperature parameters are recorded in
`reference/zero_tail_parameters.json`. At these benchmark temperatures the
energy is continuous at the crossing and the derivative changes finitely;
there is no raw-truncation energy jump or associated delta-function impulse.

Scientific launchers accept `--cutoff zero_tail`. New chain and EOS campaign
drivers default to this reconstructed convention; standalone run launchers
retain their older default for compatibility, so specify the option explicitly.
All manifests record the choice. Comparisons separate all three conventions;
EOS figures and missing-state coverage now refer to zero-tail runs, with raw
controls retained in the JSON report.

New three-seed chain allocations cover the complete 45-state matrix across
`equilibrium_zero_tail_294`, `equilibrium_zero_tail_320_347`,
`equilibrium_zero_tail_361_371`, and `equilibrium_zero_tail_381_396` under `runs`.
Each starts with 100000 sweeps per seed; allocation is not convergence proof.
Three EOS queues (`eos_zero_tail_n135_t294`, `eos_zero_tail_n455_t294`, and
`eos_zero_tail_n455_t371`) cover all 15 published pressure states with three
initial 2000-sweep allocations each. Each queue runs one worker at a time with
nice 19; local compute only. Logs use `/tmp/nadoc-peg-zero-tail*.log` and
`/tmp/nadoc-peg-eos-zero*.log`. Earlier raw children continue to finish without
additional raw allocations being scheduled.

Zero-tail validation: 91 distinct tests passed across the initial batch (87),
three MC/pivot/HMC sampled-energy checks, and one rerun of the existing analytic
harmonic-bond distribution test. The initial distribution test timed out at
60 s under concurrent GPU load; the rerun allowed 180 s and passed in 58.9 s.
The workload, analytic reference and tolerances were unchanged. Full results,
the timeout, retry and engine/source hashes are preserved in
`verification_zero_tail_manifest.json` and its referenced outputs. New checks
cover energy continuity and finite-difference derivatives at all seven benchmark
temperatures, plus CPU/CUDA pair forces inside the well, at the barrier and in
the removed tail. The original raw convention remains covered by regression tests.

## Published intervals and queued GPU dynamics comparison

`extract_chain_intervals.py` now extracts all 42 Figure 7(b) error-bar intervals
from vector endpoints. `reference/published_chain_intervals.json` retains their
source hash and numerical endpoints. The accessed preprint does not specify
whether these bars represent SEM, standard deviations, or another quantity;
they are therefore reported as **plotted intervals**, not assigned a confidence
level. The comparison JSON adds descriptive point-in-interval and interval-overlap
checks; the original stricter marker-only comparison remains available. The
plots show the published bars separately from our ±2 SEM estimates. For
example, the 275-mer at 320 K spans 3.6618–4.2347 nm, whereas the 795-mer spans
7.3780–9.0212 nm. Digitization bounds remain separate.

`run_zero_tail_gpu_check.py` queues three 20 ns CUDA Langevin trajectories for
N=36 at 381 K, dt=2 fs, from the three independent zero-tail CPU endpoints.
The plan is `runs/zero_tail_gpu_n36_t381/plan.json`, log
`/tmp/nadoc-peg-zero-tail-gpu.log`. Its driver checks the live process belonging
to the existing raw-HMC seed-905 retry and waits until that control has completed
before using the GPU. Each source/output retains replica ancestry. This is an
independent sampler comparison, not a claim that 20 ns per replica is sufficient.

Continuation helpers now accept an explicit cutoff convention and default to
`zero_tail`. Existing plans without a convention are treated as legacy raw
plans and require `--cutoff raw`; they cannot silently become zero-tail runs.
Both chain and EOS helpers refuse convention mismatches, preserve their frozen
plans, and expose `--plan-only`. Four regression checks pass in
`verification_continuation_convention.txt`. The previously paused raw plans
remain unchanged; this update does not resume any allocation.

The raw-HMC control now has three completed independent origins (203, 201, 202).
`compare_samplers.py` reports RMS Rg 1.15527 ± 0.01044 nm SEM, versus CPU pivot
1.13733 ± 0.00875 nm. Their 0.01794 nm difference is within two combined SEM;
GPU R-hat is 1.00488 and minimum squared-radius ESS is about 232. This supports
consistency of the GPU endpoint-corrected sampler for the raw control; it does
not validate that convention against the published model. The initial-state
dependence caveat and per-cohort diagnostics are retained in
`sampler_comparison.json`.

The queued zero-tail CUDA dynamics comparison has started its first 20 ns
replica (`runs/zero_tail_gpu_n36_t381/s701`). The queue verified the control's
completion before starting it. Future invocations of `compare_samplers.py` will
also assess that cohort once all three trajectories have finished.

Additional zero-tail solution verification: eight focused checks pass for the
independent molecular-volume energy derivative and interacting periodic NPT
snapshots, using CPU cell lists, CPU Verlet lists and GPU HMC. Both raw and
zero-tail conventions are checked. The independent solution oracle now accepts
`zero_tail=True` for energies and the smooth molecular virial. Its documentation
explicitly excludes interpreting the raw smooth-force virial as a complete
thermodynamic pressure without the cutoff impulse. Results and source/build
hashes are retained in `verification_zero_tail_npt.txt` and its manifest.

The first zero-tail extension plan is now running at
`runs/zero_tail_chain_extensions_round1`: N=76, 320 K, 500000 additional sweeps
per independent origin (201/202/203). Its initial three-replica cohort had
minimum squared-radius ESS 45.1 and R-hat 1.01247. The new generation starts
from each saved endpoint, preserves the zero-tail convention and ancestry, and
will replace the comparison cohort only after all three continuations finish.
Log: `/tmp/nadoc-peg-zero-tail-extensions1.log`. This frozen three-allocation plan
does not automatically include later flagged states.

A second zero-tail chain extension plan now covers N=76 at 361 K: three
700000-sweep continuations from independent endpoints. The initial cohort had
minimum squared-radius ESS 32.3 and R-hat 1.04995. Plan:
`runs/zero_tail_chain_extensions_round2/plan.json`; log:
`/tmp/nadoc-peg-zero-tail-extensions2.log`.

The chain extension planner now reserves generations already present in frozen
plans, with cutoff conventions kept separate. Round 2 explicitly skipped the
320 K generation already allocated in round 1. A reservation does not assert
process liveness: a stopped plan requires explicit recovery, not a duplicate
allocation. Five continuation-convention checks pass.

Zero-tail chain extension round 3 covers N=76 at 381 K with three 200000-sweep
continuations. Its initial cohort has squared-radius ESS at least 130 but
R-hat 1.02006, so between-replica agreement still needs assessment. The planner
skipped the already reserved 320 K and 361 K generations. Plan:
`runs/zero_tail_chain_extensions_round3/plan.json`; log:
`/tmp/nadoc-peg-zero-tail-extensions3.log`. Each extension queue runs one CPU
worker at nice 19; existing QM jobs are not modified.

The first zero-tail CUDA Langevin replica (N=36, 381 K, seed 701) completed
20 ns at dt=2 fs in 668.31 s on the local GPU. RMS Rg is 1.16803 nm, compared
with the current CPU zero-tail cohort's 1.1749 nm. Maximum saved bond length
is 0.38759 nm; the mean-Rg trace has approximately 111 effective samples and
retained half means 1.15187/1.13557 nm. These are single-replica diagnostics,
not the final three-replica sampler comparison. The queue proceeds to seeds
702 and 703; all inputs, trajectories and analysis remain in
`runs/zero_tail_gpu_n36_t381`.

The first complete zero-tail EOS pilot cohort (N=135, 294 K, 1 kPa) yields
2.46755 ± 0.10512 g/L conservative SEM, but volume R-hat is 1.42889 and
chain-shape R-hat is 1.15751. Minimum effective sample counts are only 12.3
(volume) and 4.9 (shape). This is not a converged reproduction result.
`runs/eos_zero_tail_extensions_n135_t294_p1_round1/plan.json` now allocates
20000 additional sweeps for each independent origin, starting from saved
endpoints with the same Hamiltonian. These are bounded continuations, not a
promise of convergence. The queue runs one worker at nice 19; log:
`/tmp/nadoc-peg-eos-zero-tail-extensions-p1.log`.

A source audit of oxDNA's native GPU MD barostat found unresolved proposal-measure
and mixed-precision molecular-rescaling issues. It remains unused by these
benchmarks. See [native_gpu_barostat_audit.md](native_gpu_barostat_audit.md) for
the derivation, affected paths and source hashes. CPU NPT and GPU HMC use the
separately tested log-volume move; the ongoing GPU dynamics check is NVT.

N=76, 381 K zero-tail generation 1 completed with RMS Rg
1.61593 ± 0.01498 nm conservative SEM, minimum squared-radius ESS 209 and
R-hat 1.01153. Since the R-hat threshold is still exceeded, round 4 allocates
three 400000-sweep generation-2 continuations from those latest endpoints.
Plan: `runs/zero_tail_chain_extensions_round4/plan.json`; log:
`/tmp/nadoc-peg-zero-tail-extensions4.log`. Older generations are not pooled as
independent replicas.

The second zero-tail GPU dynamics replica (seed 702) completed 20 ns in
742.06 s with RMS Rg 1.19562 nm and maximum saved bond 0.38784 nm. Its mean-Rg
trace has about 111 effective samples and half means 1.13418/1.20204 nm.
The third planned replica has started; full cross-replica convergence remains
pending. These single-run measurements do not replace the cohort assessment.

A bounded zero-tail GPU HMC solution pilot is queued after the third GPU chain
replica. It uses N=135, 108 chains, 294 K, 1 kPa from a completed zero-tail
endpoint, with 100 proposals each at dt=2, 1 and 0.5 fs (500, 1000 and 2000
integration steps per proposal). The plan and eventual timing/acceptance results
are under `runs/zero_tail_hmc_solution_pilot`; launcher:
`run_zero_tail_hmc_pilot.py`; log:
`/tmp/nadoc-peg-zero-tail-hmc-pilot.log`. The driver verifies the predecessor's
live process and successful completion before starting. These short probes test
whether the existing HMC path merits larger allocations; acceptance rate alone
will not establish mixing or calibrated dynamics.

The zero-tail N=76, 320 K generation-1 cohort now passes the current triage
criteria: RMS Rg 2.02070 ± 0.00833 nm conservative SEM, R-hat 1.00049,
minimum squared-radius ESS 791. Its estimate lies within the published plotted
interval, including digitization bounds. Passing these diagnostics is evidence
for this state, not proof of full model validation.

The new N=135, 381 K initial cohort is poorly mixed (R-hat 1.38314, minimum
ESS 21.6). Extension round 5 allocates three 1000000-sweep continuations from
its saved endpoints. Plan: `runs/zero_tail_chain_extensions_round5/plan.json`;
log: `/tmp/nadoc-peg-zero-tail-extensions5.log`. Other reserved generations
were excluded from the new plan.
