# Experimental hybrid melting sampler

**Status: shelved research prototype, not a production feature.** The pilot and
longer-training trials did not validate equilibrium Tm precision. Experiment raw
data and isolated native builds were removed on 2026-11-21; rebuild and rerun
native validation before any new campaign. This local, uncommitted source is a
research starting point, not a supported application workflow. See
[retained notes, metrics and handoff](../../docs/oxdna_equilibrium_tm_research.md).

Research CLI for the existing 8-bp DNA2 duplex export. This is not a wizard or
managed-job mode, and does not change the application's selected engine. CPD
inputs and other duplex sizes are rejected rather than silently approximated.
It consumes existing topology/configuration exports; all subsequent coordinates
are native simulation output. It does not author NADOC structures.

## Protocol

1. Four persistent oxpy workers, two starting bound and two separated, learn one
   shared well-tempered metadynamics table. The controller deposits Gaussian hills
   at synchronized endpoints. Total hill height per epoch is independent of the
   walker count. Grid values are energies in oxDNA units, not beta times energy.
2. Freeze and hash the table. Discard every training frame from equilibrium
   estimation. Start fresh production workers from the original opposing initial
   states, with independent seeds, and discard a fixed equilibration interval.
3. Run a fixed production budget with that table unchanged. Save energy, native
   pairing count, continuous coordinate, trajectories, checkpoints, runtime
   identity, source snapshots and ordered execution events.
4. Remove the fixed bias using weights proportional to exp(+V/kBT). The COM
   restraint's two native force-energy reports represent ONE potential, not two.
   Refuse inconsistent observed bias energies. Estimate autocorrelation on both
   coordinates and the weighted population influence. Trapped trajectories never
   get zero-width confidence intervals.
5. Reevaluate saved frames with DNAnalysis at each target temperature. This uses
   the full temperature-dependent DNA2 Hamiltonian, including stacking and salt
   screening; do not just multiply the source-temperature energy by beta.
   Convert single-box binding odds to the bulk heterodimer bound fraction at the
   box-implied total strand concentration. Report unbracketed Tm values explicitly.

Defaults for the benchmark are **experimental choices, not literature-certified
melting settings**: 70 C, 0.3 M salt, inherited 12 mM total strand concentration,
dt .005, Brownian thermostat every 100 steps, diffusion coefficient 2.5; 2M
training steps per walker, hills every 10k steps, total initial height .5 kBT,
bias factor 10; 200k fixed equilibration and 5M production steps per replica.
Hill width is .25 for pairing coordinates and .2 for COM separation. Mixed
coordination uses 70% orientation-sensitive HB proxy and 30% base-site distance
switching. The HB proxy is a sampling coordinate, not the physical energy.

## Native prerequisites

Use an **isolated** source/build directory on configured development storage.
Start from the pinned engine source with the existing GPU periodic-COM fix
(`../oxdna_umbrella/gpu-com-periodic.patch`). Apply in order:

* `gpu-coordination.patch`: GPU distance derivatives must use base-site separation;
  retain floating-point grid boundaries.
* `coordination-continuity.patch`: restore the smoothed radial tails in the HB
  proxy on CPU and GPU, avoiding discontinuous bias energy at cutoffs.
* `coordination-base-pbc.patch`: apply the periodic minimum image to base-site
  separation consistently with the CPU switching coordinate.
* `coordination-cache.patch`: recompute the CPU coordinate when forces query it;
  a timestep label alone cannot identify positions during Verlet integration.

These change bias machinery, not the physical DNA2 interaction. Build oxDNA and
DNAnalysis with CUDA in the isolated tree, with the repository validation wrapper
and one build worker. Existing compatible oxpy bindings can load the isolated
library via LD_LIBRARY_PATH. The worker verifies the actually loaded shared
library via /proc/self/maps; no application engine symlink is changed.

`build.py` copies an explicitly supplied source tree, applies these patches (or
verifies they are already present), and writes a source/build/library receipt.
Run it under `just validate-safe`; it uses one native build worker. The CPU
cache removal favors correctness; biased CPU-MD speed has not been measured.

Compile `gradient_probe.cpp` against that source and library (include `src` and
`src/extern`, link `oxdna_common` and `tinyexpr`). Then run:

```bash
python -m tools.oxdna_hybrid.validate \
  --inputs EXISTING_EXPORT --binary BUILD/bin/oxDNA \
  --probe GRADIENT_PROBE --output FORCE_RECEIPT.json
```

The validation uses unchanged existing `conf.dat`, `boundary.dat`, and
`unbound.dat` frames; numerical perturbations exist only in probe memory.
It checks translational and rotational derivatives, radial cutoff continuity,
and CPU/CUDA short-step parity. Campaigns require a passing receipt matching the
library hash. Keep the source, patches, build flags, receipt and library together.

## Run and benchmark

Set `NADOC_TEST_SCRATCH_ROOT` to an existing development scratch directory. Where
required, also set `NADOC_TEST_SCRATCH_MOUNT`; an unavailable configured mount is
fatal. Outputs must go under `.development-artifacts/`, never the user workspace.

```bash
python -m tools.oxdna_hybrid.campaign \
  --inputs EXISTING_EXPORT --output NEW_CAMPAIGN \
  --library BUILD/src/liboxdna_common.so --oxpy OXPY_PACKAGE_PARENT \
  --force-validation FORCE_RECEIPT.json
python -m tools.oxdna_hybrid.analysis NEW_CAMPAIGN
python -m tools.oxdna_hybrid.temperature NEW_CAMPAIGN \
  --binary BUILD/bin/DNAnalysis --temperatures 60 62 64 66 68 70 72 74 76 78 80
```

`benchmark` accepts the same options and runs `unbiased`, `com`, `hb_cutoff` and
`mixed` cases sequentially. The unbiased control reallocates the training budget
to production and disables external forces, giving the same total steps. Compare
actual elapsed time separately: biases have different per-step costs. GPU
concurrency can use `python -m tools.oxdna_umbrella.mps -- ...`. Its temporary
Unix-socket directory must have a short path; keep large simulation outputs and
child scratch on the configured development filesystem.

Each campaign has a hard deadline, owns its worker processes, and cleans them
up on failure/interruption. It never stops a managed user job. The controller
emits stage/checkpoint/completion/failure events; it does not poll job completion.
Existing campaign outputs are never overwritten. A failed campaign is evidence,
not a resumable or certified production job.

`refine.py` compares `--radii .5 1.5` with the same engine, seeds and budgets.
`training.py` independently replays the ordered hill history and measures late
bias-shape changes. `pairing_audit.py` checks all interstrand HB pairs using the
exact sampling settings. `report.py` exports CSV/PNG/PDF comparisons and traces.
Distance rounding is explicitly bounded; weights use recorded native bias
energies, not four-decimal reconstructed distances. See the completed
[benchmark report](../../docs/oxdna_hybrid_benchmark.md).

## Interpretation and limits

Compare initial-state disagreement, q=0 crossings, passages between q=0 and q>=6,
weighted effective samples, autocorrelation and total compute cost. Rapid q=0/1
flickering does not prove independent binding cycles. Error bars conditional on
a frozen bias do not validate the learned coordinate or rule out hidden states.
The temperature report labels replicate intervals provisional and does not
automatically certify +/-1 C. Independent campaign replication, temperature
overlap, drift checks, and model/CPD validation remain necessary before making
that claim. No repeated-look stopping rule is implemented.
