# Retained equilibrium Tm research evidence

See [the report](../../oxdna_equilibrium_tm_benchmark_20261121.md) for conclusions.
**No method met the calibrated sub-hour ±1°C target.** These are research metrics,
not production validation or a CPD model.

- `comparison.json/csv`, figures and `traces/`: measured method comparison.
- `campaigns/*/manifest.json`: original inputs, seeds, model and native hashes.
- `campaigns/*/driver_source.py`: actual driver snapshot for that campaign.
- `campaigns/*/stages.json`: ordered logical stages, exact native inputs/weights,
  execution receipts and output hashes. Parallel walkers share a training round.
- `campaigns/*/full_analysis.json`: full temperature-dependent energy analysis.
- `campaigns/*/sufficient_statistics.npz`: time-resolved inverse-bias temperature
  weights partitioned by native binding, preserving statistical replay.
- `campaigns/*/pairing_audit/`: independent all-pair classifications and summaries.
- `campaigns/distance_confirmation/binding_definition.json`: uncertainty and true
  unbound round trips with any interstrand bond defining association.
- `distance_audit.json` and `distance_samples.npz` in distance campaigns:
  independently recomputed base-site distances and recorded-bin checks.
- `calibration.json`, `validation.json`, `retained_replay.json`: limited synthetic
  coverage, software/native checks and independent statistical replay.
- `inputs/`: unchanged baseline native exports and their source provenance.
- `dependencies/`, `native_build.json`, `checkout_revision.txt`: exact supporting
  source snapshots and native build identity. They are research dependencies,
  not instructions to replace a production engine.
- `raw_inventory.json.gz`, `cleanup.json`: hashes and pruning receipt. Original
  absolute raw paths in archived manifests are historical, not live dependencies.

Recompute statistical results without trajectories or a native engine:

```sh
uv run python -m tools.oxdna_tm_research.replay \
  docs/benchmarks/equilibrium_tm_20261121/campaigns
uv run python -m tools.oxdna_tm_research.binding_definition \
  docs/benchmarks/equilibrium_tm_20261121/campaigns/distance_confirmation
```

To rerun the independently trained confirmation with the matching native engine:

```sh
uv run python -m tools.oxdna_tm_research.proposals \
  --job-dir docs/benchmarks/equilibrium_tm_20261121/inputs --salt .3 \
  --unbound-conf docs/benchmarks/equilibrium_tm_20261121/inputs/unbound.dat \
  --binary /path/to/matching/oxDNA --output /path/to/new-owned-campaign \
  --minutes 27 --block-steps 1000000 --blocks 8 --seed 811100 \
  --target-halfwidth 1 --translation .5 --rotation 1 --maxclust 12 \
  --training-walkers 4 --cadence 1000 --distance-split 1
```

Use an isolated checkout at `checkout_revision.txt`, the new research tools/tests,
and the dependency snapshots at their corresponding relative paths. Check the
native binary/library hashes and periodic patch/header against `native_build.json`.
The two small orchestration scripts contain historical local paths; the parameterized
CLI above uses retained inputs instead. Native replay is hardware/build sensitive;
reported wall times are measured on the recorded workstation, not promised elsewhere.
Raw molecular trajectories/checkpoints were removed after summaries, hashes,
audits and statistical replay were verified. New coordinate/Hamiltonian analyses
require rerunning the native campaign; sufficient statistics cannot replace raw
configurations for those purposes. No saved NADOC structure was authored or changed.
