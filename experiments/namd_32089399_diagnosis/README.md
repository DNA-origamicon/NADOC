# Slurm 32089399 exclusion failure: isolated replays

Source: `workspace/md_jobs/7aa73d7afe93/package/small_plate_namd_solvated`.
All inputs refer to the original package by absolute path; every output goes into
this experiment. Original checkpoints, configurations, and job state are untouched.

The local patched NAMD 3.0.2 build differs from Alpine Git-2025-12-04.
Local GPU: RTX 2080 class, 8 GB. Original: RTX Pro 6000 on Alpine.
A local success alone cannot establish an Alpine fix.

After the user opens `just test-session`, run from the repository root:

```bash
bash experiments/namd_32089399_diagnosis/run_replay.sh baseline
```

Each trial is capped at 5,000 steps, with energies every 10 steps and checkpoint,
trajectory, and cell output every 100. Each variant starts from the same k=0.1
checkpoint and seed. These output frequencies differ from the original and may
change GPU synchronization, so reproduction must account for that as well.

Variants: baseline; margin4; margin6; offload; relax2fs (relaxation only);
enm_control (retain k=0.1). Run sequentially and select follow-ups based on evidence.
If baseline reproduces, first determine the failure step and affected geometry.
A candidate passing 5,000 steps still needs a full 120,000-step segment and Alpine
validation before being described as a confirmed fix.

`keep_connection.py` sends a read-only OS probe through the existing backend SSH
connection once per minute for at most four hours, stopping on HTTP/transport
exceptions. It stores no credentials and cannot override a server-enforced session
expiry. Its output is `keep_connection.log`. Avoid restarting the backend while
this authenticated session is needed.

The user opened the test session and the controls have run. See
`results.json` and `../../docs/namd_graphene_barostat_failure_audit.md`.
The original baseline, margin4, offload and enm_control all diverged. A per-step
`trace` ties the divergence to the graphene restraint energy. `piston10ps` changes
only period/decay to 10000/5000 fs and completed 5000 steps at 4 fs.
`recovery_package` is the isolated corrected continuation; `run_full_segment.sh`
uses the original 120000 steps and original output cadence. Do not run the failed
trace's checkpoints. Do not run `launch.sh` in the recovery package: it would
repeat earlier stages; the continuation runner selects the intended stage.

Final verification: 75 focused tests plus 21 production-cell tests passed. Ruff
and diff whitespace checks passed. `test-smart` selected FULL and was interrupted
at 99% after 27m53s with 8009 passed, 11 failed, 83 skipped, 1 xfailed and 1 error;
see the audit for failure classification. The full 120000-step continuation has
been prepared but not launched. The 5000-step corrected replay completed cleanly.
