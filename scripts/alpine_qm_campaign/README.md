# Alpine all-form TT-CPD response campaign

This campaign runs the 24 remaining policy-2.1 fixed-geometry response cases as a
64-core Slurm array. Each array element owns one product/conformer and runs its 211
independent MP2/6-31G(d) analytic-gradient tasks as 32 two-thread workers.

The source plans and transfer bundle live on the local Archive drive. Alpine's node-local
`$SLURM_SCRATCH` is used only for active Psi4 scratch; completed task pairs are copied to
the campaign's durable Alpine scratch directory even when an array element exits early.
Nothing generated here releases a force field or makes a product simulation-ready.

Build and submit from the repository root:

```bash
bash scripts/alpine_qm_campaign/build_bundle.sh
bash scripts/alpine_qm_campaign/submit_from_local.sh
```

The submitter requires the existing reusable SSH connection at
`/tmp/nadoc-alpine-$(id -u)/control.sock`. It refuses to overwrite a local or remote
campaign. After completion, results must be fetched to the matching policy-2.1 Archive
plan tree, verified against the case completion receipts, and assembled locally.

The submitted campaign can be collected unattended while the reusable SSH master is
alive:

```bash
bash scripts/alpine_qm_campaign/watch_and_collect.sh SLURM_JOB_ID
```

The watcher waits for all 24 Slurm array elements to become terminal. It then downloads
to the Archive drive, validates every case receipt and task hash, checkpoints only
complete pairs into byte-identical local plans, and runs normal local Hessian assembly
and fixed-response auditing. If a task tree is complete but the case-level post-processing
receipt is absent, `repair_case_completions.py` may reconstruct only that receipt after
checking every original QCSchema result/run-record pair. Missing or invalid task evidence
still fails closed.
