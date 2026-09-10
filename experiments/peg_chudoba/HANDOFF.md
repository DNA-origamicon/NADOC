# PEG handoff — 2026-09-10

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
