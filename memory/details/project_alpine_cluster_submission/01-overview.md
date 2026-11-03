# Overview — supporting detail

[Topic head](../../project_alpine_cluster_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.


Add a remote execution backend so a prepared NADOC MD (NAMD) job can be submitted
to the **CU Research Computing "Alpine" cluster** (SLURM scheduler) with a
connect-once / submit flow, instead of only running as a local subprocess.
Design synthesized from the **NAMDRunner** reference project
(github.com/travisformayor/NAMDRunner — a Rust/Tauri app that already solved the
CURC/Alpine SSH→SLURM pipeline for the *same* DNA-origami CPD use case).

**Nothing lifts as code** (NAMDRunner is Rust; NADOC is Python/FastAPI + vanilla
JS). What transfers is the lifecycle design, the CURC/Alpine specifics, and two
pieces of portable *data* — all captured in the Appendix below so the reference
clone is not needed.

**2026-09-13 restart recovery:** Slurm requeues are now detected and journaled on the
compute node. Interrupted dynamics resume from a validated checkpoint without NADOC
connected; outputs and input checkpoints are preserved per attempt. Legacy resets
produce linked preserved-job entries and revisioned acknowledgment notices. The live
24hb_0xT allocation was protected through an atomic Tcl config wrapper, without
cancel/requeue. See [restart recovery](../../../docs/alpine_restart_recovery.md) for behavior,
limitations, and the recovered 120.64 ns attempt. This supersedes historical text below
that treats an interrupted segment rerun as acceptable or requires the backend for
all mid-segment recovery; user-triggered new Slurm submissions remain unchanged.

**2026-09-14 independent downloads:** The default Alpine manager is now a Unix-socket
client of `backend.core.alpine_worker`, which owns authentication and full result
transfers outside uvicorn. Server reloads retain SSH/downloads; transfer progress
lives in `alpine_transfer.json` and overrides stale job records. Explicit Disconnect
stops transfers; worker/workstation/transport loss requires reconnecting, with partial
file validation/resume preserved. See the restart-recovery document above.

**2026-09-30 finish/download cancellation:** Job `983f5c8e66bc` (SLURM
`33128431`) remained active while scheduler cancellation timed out from both
login and compute nodes. Verified node-local SIGTERM stopped its batch shell,
NAMD and metrics process group at checkpoint 28.18 ns; repeated process inspection
confirmed no survivors. Slurm accounting remained RUNNING, so allocation release
was not confirmed. The detached transfer completed: all 18 output files (24.05 GB) match remote sizes;
1,409 DCD frames passed sampled structural checks. NADOC reports completed/verified.
`alpine_cancel.py` now falls back from bounded `scancel --ctld --quiet` to a
single-node SSH stop using `alpine_node_stop.py`. It verifies UID, numeric job ID,
batch-shell command, cgroup, scratch directory, one process group, and PID start
identity before SIGTERM, then verifies exit. The observer SSH group in the allocation
extern step is excluded; other job process groups are refused. Ambiguous/mismatched/unconfirmed
stops still return HTTP 503 and never download/archive. Host keys are pinned with
accept-new in a job-scoped file; changed keys are rejected. Direct-stop evidence
records allocation-release uncertainty in `slurm_diagnostics`. Helper is Python
3.6-compatible for Alpine nodes. Regression: 24 cancellation/finish tests and 97 executor tests pass; FAST suite
9,480 passed with six existing unrelated geometry/surface/VR failures.
Top-level log inventory now uses `stat --printf`, because `stat -c` emitted a
literal backslash-t which the tab-delimited parser dropped. This run's four logs
were fetched and verified separately while the existing worker finished its DCD.
Evidence: `.development-artifacts/alpine-finish-20260930/`.

**2026-09-30 scheduler fallback:** Live shell/SFTP and per-user `sacct` worked
while `squeue`/`scontrol` stalled. Job polling now falls back to accounting after a
10-second queue timeout or nonzero exit; failed queries plus missing accounting
cannot imply completion. Restart inspection bounds `scontrol` remotely to 8 seconds
so the attempt journal remains readable. Live job 33128431 resumed persisted metrics
updates through the fallback; the authenticated worker stayed connected.
