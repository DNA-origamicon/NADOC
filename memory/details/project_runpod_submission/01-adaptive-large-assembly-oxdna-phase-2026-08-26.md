# Adaptive large-assembly oxDNA phase (2026-08-26) — supporting detail

[Topic head](../../project_runpod_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Adaptive large-assembly oxDNA phase (2026-08-26)

`backend/core/runpod_oxdna.py` and `scripts/submit_runpod_oxdna.py` provide the first
headless oxDNA submission path. It pins upstream revision `8028cf33`, applies NADOC's
adaptive-neighbor/compact-cell/wide-index patch, and builds persistent `sm_90` (H200) or
`sm_120` (RTX PRO 6000) engines. Prepared jobs are compressed, staged, run through a
restartable status/heartbeat chain, fetched into their standard job directory, and the
pod is destroyed structurally. A durable campaign ledger caps cumulative attempts rather
than resetting the dollar authorization per pod.

Live validation: 32-copy BigO, 451,584 nt, H200 compute capability 9.0 / 143,771 MiB;
100 CUDA MD steps completed at 2.56054 ms/step. Adaptive neighbor capacity grew 64→181
for 160 observed maximum neighbors; the edge list held 28,119,421 observed edges in a
33,743,305-entry allocation. Fetched `last_conf.dat` contains exactly 451,584 particle
lines. All pods were destroyed. Total campaign ledger spend including failed preflight
attempts was about $1.25, below the user-authorized $5 cap. Evidence lives under
`workspace/runpod_oxdna_validation/validation_report.json` and `validation_audit.json`.

---
