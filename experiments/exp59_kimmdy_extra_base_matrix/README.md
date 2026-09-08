# exp59 — extra-base KIMMDY simulation matrix

This experiment inventories every local and Archive-media NAMD DCD, identifies managed
NADOC jobs whose crossover inserts are thymine, and applies the design-aware KIMMDY CPD
geometry only to reciprocal crossover inserts.  Ordinary duplex thymines are never included
in the primary analysis.

The scientific comparison uses unrestrained production DCDs.  Restrained equilibration,
minimization, vacuum/probe, SMD/umbrella, incomplete one-frame files, jobs without an exact
design mapping, and zero-partner asymmetric controls remain in the inventory but do not enter
the propensity comparison.

The standard run samples at most 500 frames spread across each production trajectory.  This
keeps every stored run represented while avoiding duration-weighting and multi-terabyte I/O.
Both the upstream and periodic-angle KIMMDY scores are saved; the corrected periodic score and
the joint reactive-corner criterion (`d_mid < 0.45 nm` and circular angular error `< 45 deg`)
are used for comparisons.

```bash
uv run python experiments/exp59_kimmdy_extra_base_matrix/run.py inventory
uv run python experiments/exp59_kimmdy_extra_base_matrix/run.py analyse
uv run python experiments/exp59_kimmdy_extra_base_matrix/run.py quality
uv run python experiments/exp59_kimmdy_extra_base_matrix/run.py summarize
uv run python experiments/exp59_kimmdy_extra_base_matrix/run.py summarize-ungated
```

`REPORT_UNGATED.md`, `crossover_summary_ungated.csv`, and
`lineage_summary_ungated.csv` are the primary scientific outputs. They include every finite
sampled frame without treating expected single-stranded conformations or terminal fraying as
structural failures. `REPORT.md` and the CSVs without the `_ungated` suffix retain the original
canonical-geometry-gated analysis as a sensitivity check. `inventory.json` is the complete
audit, and per-job KIMMDY summaries and rank-aligned time series are under `results/jobs/`.
