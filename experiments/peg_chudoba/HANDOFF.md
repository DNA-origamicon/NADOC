# PEG handoff — 2026-09-10

## Latest status — September 11

N36 passes the bounded CPU/GPU and timestep-equivalence checks. The N135/1 fs
recovery completed successfully; its cohort remains inconclusive (RMS Rg
2.9751 nm, conservative SEM 0.0758 nm, minimum effective samples 16.8). The
recovery lease restored the historical scheduler. N135/2 fs long extensions
have not started. All 27 EOS proposal diagnostics completed without resolving
dense-state convergence. See [RESULTS_20260911.md](RESULTS_20260911.md).

The next dense-solution convergence round and coupled brush–tile pilot have
not launched. The proposed two-engine pilot targets reversible osmotic packing
pressure over approximately 3 nm, including tile stability and chain-level
bimodality; it is not yet an implemented gold-electrode voltage model. The
self-contained [proposal briefing](../../docs/research/PEG_ACTUATOR_PILOT_PROPOSAL_BRIEF.md)
records methods, limitations, sources and the approximately $7,500 compute budget.
That budget differs in scope from the earlier generic PEG/NAMD development budget;
reconcile overlapping allocations rather than adding them automatically.

**Help → PEG testing** now displays 60 completed 294 K trajectories with length
and run/replica selectors, play/pause, scrubbing and playback speed. See
[viewer documentation](../../docs/peg_testing.md). The 125 MB display exports
are regenerated locally with `python -m experiments.peg_chudoba.export_viewer`;
they are gitignored. Validation verdicts remain separate from run completion.
Frontend verification: 6,247 unit tests and the real-browser viewer check passed;
export periodic-unwrapping test passed. Full smoke was blocked by the existing
active-simulation guard; lint reports two existing unrelated issues.

All running-status entries below describe historical launches. Current process
state must be checked from runtime records and live processes, not inferred from
these notes. Runtime scheduler PID snapshots should not be staged as source changes.

## Revised diagnostics launched

User authorized the revised next steps. `run_diagnostics.py` is running as PID
3684311; inspect `workspace/peg_chudoba/scheduling_294_20260910/diagnostics_revision/driver.json`
and `driver.log` for current state. The lease is parked with this driver as owner;
historical N455 work is suspended and will restore on completion/failure.
N36/1 fs round 1 is active, with 12 CPU EOS workers in parallel. See
[DIAGNOSTIC_REVISION.md](DIAGNOSTIC_REVISION.md) for the frozen diagnostic allocation.
The corrected classifier calls the existing N36/2 fs result inconclusive, not
resolved disagreement. Its raw results are preserved and the pre-revision
validation report is archived. Fourteen focused scheduling tests passed.
N36 gets only its remaining original caps; N135 GPU requires N36 equivalence.
EOS uses a separate 27 × 2,000-sweep proposal diagnostic; exhausted production
caps remain exhausted. No automatic sampler promotion or force-field refit.
Execution source snapshots are saved alongside the diagnostic driver record.


## Latest status: bounded driver stopped; diagnostics needed

At the 20:51 MDT check, the bounded campaign had stopped at 19:27 MDT on its first
GPU comparison. See [STATUS_REASSESSMENT_20260910.md](STATUS_REASSESSMENT_20260910.md).
All nine CPU chain lengths pass; all seven N135 EOS states exhausted caps without
sampling convergence. N36/2 fs completed 3 × 20 ns: mean Rg differs from CPU by
3.47%, but the uncertainty-inclusive bound is 6.10%, so 5% equivalence is unresolved.
The driver's "disagreement" stop conflates inconclusive equivalence with demonstrated
out-of-band bias. N36/1 fs and N135 GPU cohorts have not run. The lease restored the
older serial controller, now running historical N455 EOS work. This assessment did
not alter any processes or code; prior "running bounded validation" notes below
are historical. Prioritize verdict classification, small N36 diagnostics and EOS
mixing over expanding surface simulations or spending the H200 pilot allocation.

## Parallel atomistic PEG infrastructure

User authorized setting up NAMD PEG-brush infrastructure while bounded oxDNA
validation continues. See [../peg_namd/README.md](../peg_namd/README.md) and
[../peg_namd/GAPS.md](../peg_namd/GAPS.md). The planner produced 27 cases in
`workspace/peg_namd/brush_plan_v1`: N36/N45/N76, three densities, three replicas.
The isolated builder consumes parameterized chain/slab assets and writes VMD
solvation plus staged NAMD inputs. Physical PEG/gold assets are still missing;
no physical NAMD brush or force-field fit has been launched. The first protocol
is neutral gold with harmonic graft proxies, not Au-S chemistry or actuation.
Seventeen focused tests and a 6,560-atom synthetic VMD file-pipeline check passed;
these are software checks, not model validation. Existing oxDNA runs/leases and
force fields were not modified by this work.

## Project deliverable: actuator feasibility map

The user identified a PEG-supported DNA platform above gold as the motivating
device and agreed that the deliverable is a parameter-space map of experimentally
feasible actuation regimes. See [ACTUATOR_FEASIBILITY_MAP.md](ACTUATOR_FEASIBILITY_MAP.md)
for inputs, outputs, evidence levels and staged modeling/experimental criteria.
The approximately 50 × 50 platform's units remain provisional. No actuator sweep
has yet been performed; this planning update does not alter bounded bulk runs.

## Published limitations and prior art

See [LITERATURE_GAP_ASSESSMENT.md](LITERATURE_GAP_ASSESSMENT.md) for the targeted
literature check: relevant crowder-oxDNA and coarse-grained PEG–gold work exists;
no retrieved paper establishes a fundamental incompatibility of this port.
Cross interactions and interfacial solvation remain the key validation gaps.
This assessment did not alter the running bounded simulations.

## Twelve-worker benchmark and scheduler handoff

The user subsequently authorized benchmarking twelve CPU workers first and
adopting that count if scaling remains roughly linear. See
[CPU12_SCHEDULING.md](CPU12_SCHEDULING.md). `scale_cpu.py` now owns the lease;
it preserved running native replicas and retired the previous bounded driver.
The eight matched timing batches precede automatic adoption of twelve or four
workers according to the predeclared 2.4x threshold. Check `cpu12/selection.json`
and `active_selection.json` for the result: all four comparisons passed,
2.710x geometric-mean throughput versus four workers. Twelve NPT workers are
now standard; ten reserved replicas resumed/started immediately. Progress is in `cpu12_driver.log`, not the older log.
The updated validator adopts orphaned run wrappers and overlaps independent
pressure cohorts without exceeding the selected worker count. Nine focused
scheduling/recovery tests passed. Scientific limits and criteria are unchanged.

## Bounded production revision

User authorized completing bounded bulk validation after the gold-surface
assessment. [BOUNDED_VALIDATION.md](BOUNDED_VALIDATION.md) supersedes production
scope only; the original timing document stays frozen. GPU equilibrium now uses
N36/N135, 20 ns then at most 80 ns per origin/timestep, not N795 multi-microsecond
MD. EOS retains seven pressures with two additional 20k-sweep rounds maximum,
after finishing the 12 reserved 20k replicas. Acceptance criteria are unchanged.
N795 numerical energy checks passed at eight serial GPU timing endpoints;
all seven prior implementation-manifest hashes match. Seven scheduling unit
tests pass. These numerical checks do not establish GPU N795 equilibrium.

`python -m experiments.peg_chudoba.run_bounded` waits for the existing benchmark
owner to exit and its lease to restore, requires all 26 timing batches and the
selected configuration, then runs production under a fresh lease. Inspect
`bounded_driver.json`, `bounded_driver.log`, `validation.json`, and `REPORT.md`
in the scheduling runtime directory. Do not start a duplicate driver. Completion
of bounded allocations can result in an explicitly incomplete validation verdict.

## New authorized work: matched scheduling and first 294 K claim

The user subsequently requested serial-versus-parallel benchmarks, followed by
validation using the best measured configuration. This supersedes the earlier
serial-only preference for this experiment. See [NARROW_VALIDATION.md](NARROW_VALIDATION.md).
The user also clarified that `just test-session` is a regression-test gate, not
a gate for these explicitly requested experiments. No guard or marker was changed.

Runner: `python -m experiments.peg_chudoba.benchmark_scheduling --execute`.
Preparation is `--prepare`; `--benchmark-only` stops after matched timing.
Runtime evidence and the frozen plan are under
`workspace/peg_chudoba/scheduling_294_20260910`; `REPORT.md` is the readable report.
This work is incomplete until `validation.json` records all required verdicts.
Timing runs are deliberately outside the legacy `runs` discovery path.

While `lease.json` there says `parked`, the historical serial controller and
its trees are intentionally suspended. A PID/start-checked watchdog restores
the old schedule if the owner dies, freezing any surviving new task trees.
Do not resume the historical controller manually while the lease owner is live.
Read-only inspect `lease.json` and `/proc`. For recovery after owner exit, use
`/usr/bin/python3 -m experiments.peg_chudoba.scheduling_lease restore --state
workspace/peg_chudoba/scheduling_294_20260910/lease.json` only after inspecting
the surviving task trees. Suspended processes are not durable checkpoints.

The remainder is the earlier checkpoint, preserved as history.

Read this first in a fresh session. The user requested a summary and commit, not a claim that validation is finished. The persistent goal remains incomplete. This checkpoint does not stop the existing simulation queue.

## What exists

1. **Help → PEG testing**: a preliminary visualization playground with approximate chain models and browser GPU support. See `docs/peg_testing.md`, `frontend/src/ui/peg_testing.js`, and `frontend/src/scene/peg_gpu.js`. It is not a calibrated field-responsive PEG model.
2. **Persistent surface milestone**: `workspace/PEG_surface_review.nadoc`, recreated by `scripts/create_peg_surface_review.py`. The initial DNA2PEG CPU/CUDA bead–spring/WCA extension, backend job integration, saved PEG metadata and bead visualization are implemented. See `docs/oxdna_peg.md`. This surface example is the original statistical approximation, not the chemical Chudoba model. Workspace files are outside Git; the generator is committed.
3. **Chemical bulk model port**: isolated oxDNA CPU/CUDA implementation of Chudoba, Heyda & Dzubiella (2017), DOI 10.1021/acs.jctc.7b00560. Build and patch sources are in `scripts/build-oxdna-chudoba.sh` and `tools/oxdna_peg/`. This model is available through the benchmark CLI; chemical-model integration into the playground remains unfinished.
4. **Research, validation and reproducible analysis**: prior-work review, NAMD calibration estimates, physical-unit reference implementation, force checks, CPU/CUDA checks, equilibrium samplers, replica continuation drivers, source audits, digitized targets, uncertainty and convergence analysis. See `docs/peg_prior_work.md`, `docs/peg_validation_plan.md`, this directory's `README.md`, and `verification_zero_tail_manifest.json`.

## Model and source fidelity

- One neutral bead per chemical EO repeat. Preserve chemical mapping; do not infer a bead count correction from a discrepant radius.
- Harmonic bond: 0.33 nm, 17000 kJ/mol/nm² with factor 1/2. Cosine-harmonic angle: 130°, 85 kJ/mol with factor 1/2. Four torsion terms: 1.96, 0.18, 0.33, 0.12 kJ/mol, phases π, 0, 0, 0. Directly bonded pairs excluded; 1–3 and 1–4 pairs retained.
- Temperature-dependent Mie-plus-Gaussian nonbonded interaction, corrected epsilon 1.372 kJ/mol. Full coefficients and units are in `tools/oxdna_peg/chudoba_reference.py` and `reference/zero_tail_parameters.json`.
- Primary convention is `zero_tail`: remove only the outer negative tail beyond its zero crossing. Preprint Figure 4(b) vector curves support this reconstruction; raw and globally shifted results are controls. Do not silently switch to a launcher's raw default.
- Radius comparison uses sqrt(mean(Rg²)), supported by the Figure 7 density audit. Published plotted error-bar meaning is unspecified. Passing the broad interval comparison does not establish exact marker reproduction.
- Preprint and final supporting information are saved with provenance. **Final journal main text and original simulation tables remain unavailable/unverified.** The final PDF was previously requested from the user. Do not claim full source fidelity.
- Surface, PEG–DNA and electric-field interactions remain separate, unvalidated assumptions. Neutral PEG is not assigned DNA backbone charge.

## Results at this checkpoint

Authoritative refreshed snapshot: `status.json`, generated 2026-09-10 07:03 UTC.

| Benchmark | Three-replica states | Current assessment |
|---|---:|---|
| Chain dimensions | 39 / 45 | 27 pass sampling checks; 12 flagged for extension |
| Osmotic pressure | 5 / 15 | Completed cohorts do not establish converged EOS reproduction |

The N275/320 K extension passes sampling checks but remains about 9.87% above the published marker: RMS Rg 4.33802 ± 0.02418 nm SEM. It fails the predefined broad comparison. Discard-sensitivity analysis shows the interval failure is not robust to every discard choice; retain the predefined 10% discard, not a selectively passing subset. Energy, mapping, periodicity and offline pivot-accounting audits did not explain the discrepancy. Offline accounting is not a native trial-cell-list/acceptance audit.

Newer completed cohorts are in `campaign_comparison.json`:

| N / T | RMS Rg ± conservative SEM (nm) | Sampling assessment |
|---|---|---|
| 795 / 320 K | 8.08070 ± 0.06152 | Pass; marker comparison passes |
| 795 / 347 K | 6.89159 ± 0.11952 | Flagged; minimum ESS 47.3 |
| 455 / 361 K | 4.49468 ± 0.06809 | Flagged; minimum ESS 65.0; outside comparison interval |
| 455 / 371 K | 3.61837 ± 0.12293 | Flagged; minimum ESS 26.3, R-hat 1.044 |

N455 and N795 at 320 K do not continue the earlier increasing radius discrepancy through N275. Do not claim a general monotonic chain-length bias.

Prior GPU N36/381 K three-replica results agree with CPU sampling. GPU N135/396 K at 20 ns per replica is unconverged; three 400 ns continuations are already allocated, with the first suspended in the queue.

## CPU versus GPU: explicit user clarification

The paper used molecular dynamics. **CPU Monte Carlo was our implementation choice, not a literature requirement.** Current main validation campaigns use CPU pivot MC for chain dimensions and CPU NPT MC for the EOS. A GPU pressure-control correctness issue excluded that native route; see `native_gpu_barostat_audit.md`. CUDA MD and experimental HMC paths exist, but their existence does not validate GPU NPT or dynamics.

Converged MC can validate equilibrium chain sizes and the EOS for the same model/ensemble. It does not provide physical time, diffusion, relaxation, field-response kinetics, or full GPU MD validation. Scheduled-run completion alone is not convergence.

User strongly prefers serial benchmarks and originally requested GPU support. We previously ran 16 PEG engines concurrently; this was acknowledged as a scheduling mistake. Do not repeat it. See `performance/RUN_HISTORY_ESTIMATE.md`: recent N795/320 CPU runs averaged 28.1 minutes per 100k sweeps versus 26.8 minutes process CPU time. This is only a scheduling-delay reference, not a clean QM-off benchmark. Historical N135 GPU MD throughput suggests about 4 hours per 400 ns replica, excluding suspension. CPU MC and MD rates are not interchangeable.

## Live queue and safe continuation

- At snapshot: **one unsuspended CPU engine, 12 suspended engines**. Active PID 2081428: `equilibrium_zero_tail_361_371/n795_t361_s201`. Always inspect `/proc` again; PID snapshots go stale.
- `serialize_existing.py` controls existing campaign trees using SIGSTOP/SIGCONT, preserving state in RAM. `serial_schedule.json` contains PID/start identities, queue and events; it is a historical snapshot in Git and a mutable local runtime file. Never restore an older committed state over a live queue. The lock file is ignored.
- Use `/usr/bin/python3` for the controller: pidfd support is required. Read `SERIAL_SCHEDULING.md` before recovery. Do not start another controller while the existing one is live, manually resume another tree, duplicate delayed allocations, or infer death from a stale run manifest.
- Suspension retains RAM and GPU VRAM; it is not a durable checkpoint. Reboot/restart requires separate assessment of saved configurations. Elapsed run time includes pauses for affected jobs.
- No new simulation allocations since the user's earlier stopping-point request. Existing allocations continue. No QM processes were modified. Local hardware: Ryzen 9 9950X, RTX 3080 Ti 12 GB. Cloud spend remains $0 / $3.

Live inspection (read-only):

```python
from experiments.peg_chudoba.serialize_existing import table, STATE, alive
import json
s = json.loads(STATE.read_text())
print('controller alive:', alive(s['controller']))
for p in table().values():
    if p['name'] == 'oxDNA' and 'peg_chudoba/runs/' in p['cwd']:
        print(p['pid'], p['state'], p['cwd'])
```

Refresh completed-result analysis without starting simulations:

```sh
python -m experiments.peg_chudoba.compare_campaigns
python -m experiments.peg_chudoba.compare_eos
python -m experiments.peg_chudoba.write_status
```

## Storage, verification and remaining work

Run inputs, trajectories and per-run manifests persist under `workspace/peg_chudoba/runs`, physically on `/media/jojo/Archive/NADOC_archive/runtime/workspace`. `experiments/peg_chudoba/runs` points there and is ignored by Git. **The commit is not a trajectory backup.** Recreate run storage through `storage.py`; do not move active working directories.

Chemical engine: `~/.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA`; runtime shared library `build/src/liboxdna_common.so`. Recorded library SHA256: `374d2dbbe0990256cfabc3049adf4ef9be9e6d8849a282a9212c14dff3f4ee5d`. Current library matches the saved 91-check validation manifest. Do not rebuild the live shared engine casually. The original surface engine lives separately in `oxdna-peg/current`.

At handoff, lightweight checks passed: 15 Python reference/statistics/continuation-convention tests and 8 frontend PEG-model tests. No new native simulations were launched for this checkpoint. Historical native force/CUDA/sampling validation is preserved in the verification files; a fresh full suite was not run while the queue was active.

Next substantive work: finish and assess allocated cohorts; resolve remaining sampling failures and the N275 discrepancy; verify final publication fidelity; validate the GPU route needed for published MD reproduction and then integrate the chemical model into the playground. Preserve the original full goal. Do not mark it complete on equilibrium MC results alone. Unrelated QM campaign changes were deliberately left outside the PEG commit.
