# The dev-server reload killed live runs (fixed 2026-08-07) — supporting detail

[Topic head](../../project_runpod_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## The dev-server reload killed live runs (fixed 2026-08-07)

Editing any file under `backend/` destroyed a running rented job. `just dev` runs uvicorn
with `--reload --reload-dir backend`, and a live 200 ns production died at 0.4% twice this
way before the cause was understood.

**There are TWO teardown paths, and the obvious one is not the load-bearing one.**

1. `main._terminate_runpod_pods` — the explicit shutdown hook. Now skipped when
   `dev_reload.under_reloader()` finds a `uvicorn --reload` supervisor in the process's
   `/proc` ancestry (uvicorn sets no marker and the signal is an ordinary SIGTERM, so
   ancestry is the only signal). Verified True against the real server child.
2. ⚠️ **`client.pod()`'s `finally` — structural, and the one that actually killed the run.**
   At process exit every in-flight task is cancelled; the `CancelledError` unwinds through
   the context manager and the pod dies. **Skipping the hook does nothing about this.**
   Suppressing it needs `runpod_api.set_handoff(True)`, which the hook now sets.

Diagnostic that identifies path 2: the job record is stuck at `running` with a pod id and
no error. `_supervise_run` only leaves the loop by writing `completed`/`failed`/`paused`,
so `running` + a dead pod means the task was CANCELLED, not that the run ended.

`under_reloader()` and `set_handoff()` both fail toward **destroying** pods: a leaked pod
bills forever, a killed dev run costs minutes and resumes from the volume.

**A pod a running job claims is not an orphan.** `reap_orphan_pods` used to kill any
`nadoc-*` pod absent from the in-memory registry — which is empty in a fresh process, so
the first reconnect destroyed exactly the run the reload was meant to preserve. It now
returns `(killed, adoptable)` and `/runpod/connect` re-attaches the adoptable ones via
`runpod_supervisor.reattach_job` → `runpod_executor.reattach_job_on_pod`, which adopts the
pod (same terminate-in-finally guarantee via `client.adopt`) and **never relaunches a live
chain** — two NAMDs on one GPU would corrupt each other's restart files.

## Shared RunPod accounts: installation ownership (fixed 2026-08-12)

An API key identifies a RunPod **account**, not a NADOC controller. Two computers using
the same account previously treated every `nadoc-*` pod as local. Depending on which job
records existed on the second computer, it could attempt to adopt the first computer's run
or, worse, terminate it as an unclaimed orphan.

Each installation now creates a random, non-secret id in
`~/.config/nadoc/instance_id` (override with `NADOC_INSTANCE_ID`). New pod names use
`nadoc-i-<installation-id>-<design>-<job>` and the job persists `runpod_owner_id`.
Reconnect/adoption/reaping only manages pods carrying the local id. Foreign signed pods
remain visible in the account but are ignored. Unsigned legacy `nadoc-*` pods are also
left alone when no active local job explicitly claims them; their provider-owned
`terminateAfter` is the safety net.

Pulling this code onto another computer protects all **new signed pods** as soon as both
backends restart. It cannot retroactively sign an already-running legacy pod. Do not ask
the second computer to adopt that pod; let its creating computer supervise it, or terminate
it manually in RunPod if ownership is uncertain.

## Package transfer progress and pre-staging (fixed 2026-08-12)

Before `runpod_pid` exists, idle CPU/GPU telemetry means NADOC is staging the package, not
running NAMD. The SFTP writer now reports transferred bytes; `remote_submit_progress`
persists byte/file totals and overrides synthetic NAMD steps in the unified progress bar.
It clears when the chain launches or staging aborts. Files already complete on the
persistent network volume count toward progress and are skipped on retry.

RunPod's S3-compatible network-volume API can transfer without renting compute, including
multipart transfer for large files. The RunPod setup wizard collects and validates its
separate `user_…` access key + one-time `rps_…` secret against the selected volume, then
stores them owner-only at `~/.config/nadoc/runpod_s3.json` (environment alternative:
`RUNPOD_S3_ACCESS_KEY` + `RUNPOD_S3_SECRET_KEY`). Finished runs terminate the GPU and close
its billing session before downloading results through S3. Uploading the prepared input
package still uses SFTP after GPU creation; moving that direction into preparation is the
remaining cold-start improvement.

## Progress on a rented run (fixed 2026-08-07)

`live_metrics` was never populated for RunPod — zero references in any `runpod_*.py`.
Progress advanced only when a whole segment landed its `.coor`, so a single-segment 200 ns
production read **0.0% for its entire multi-day life** while NAMD was demonstrably at step
370k. The frontend was polling fine at 1.5 s; there was nothing to read.

`poll_job` already delegates to `md_executor.poll_remote_progress`, which already `cat`s
`output/live_metrics.json` — the endpoint existed with nothing writing to it. The fix
stages Alpine's own `remote_live_metrics.py` onto the pod and launches it from the chain
script, so the poll costs nothing extra.

**`LIVE_METRICS_INTERVAL_S = 60`, deliberately not the UI's 1.5 s.** NADOC anchors each
reading and extrapolates (`_remote_projected_step`), so a slow collector still drives a
smooth bar. Sampling faster only contends with NAMD's own writes to the same MooseFS
volume, on a machine billing by the second.

⚠️ **Extrapolation makes a DEAD run look alive.** The bar kept advancing (0.0077 → 0.0083)
for minutes after the pod had been destroyed, because the projection runs off the last
anchor and its rate. `progress_estimated: true` is the only honest signal. When diagnosing
"is this run alive", read `live_metrics.step` and `runpod_heartbeat` — never the bar.

⚠️ **The bar can also go BACKWARDS.** A re-anchor replaces the projection with the truth, so
an over-extrapolated reading snaps back (observed 0.0151 → 0.0074 on a resume). Honest, but
confusing; `_namd_live_progress` only takes `max()` between the LOCAL and REMOTE sources,
not between successive remote readings. Not fixed.

Verified live (2026-08-07): pod-side resume wrote a `.resume.conf` with
`firsttimestep 370000` off the previous pod's checkpoint; the collector ran as
`python3 nadoc_live_metrics.py . 60`; NADOC re-synced `progress_fraction 0.0076`, a 47.2 h
ETA, and full health (101 ns/day, 296.3 K, 12.7 bar, 4 fs). **The reload-survival and
re-attach paths are unit-tested but NOT yet proven on a live pod.**

## "I cannot resume the stopped run" (fixed 2026-08-07)

**Root cause: Resume was never gated on the RunPod pre-flight, only Run was.** The API key
was backend-memory-only *at the time*, so every dev-server reload silently disconnected the
session (fixed at the source 2026-08-08 — see Decision 4 — but the gate is still right: a
revoked key or a RunPod outage disconnects too). The
Resume button stayed lit and fired a start that could only ever return
`400 RunPod pre-flight failed: RunPod API key — not connected`.

Two aggravating factors, both fixed:
* The RunPod status box was tied to the run-target RADIO, so a user looking at a stopped
  RunPod *job* saw no hint that the session was down. It now shows whenever the SELECTED
  job is a RunPod run, and `_selectJob` refreshes the pre-flight at that moment.
* A dead pod leaves the job at `running` until `reconcile_job_status` marks it
  `failed` ("Remote pod is gone (orphaned launcher)"). Until then the only offered action
  is Stop.

**Full button mapping, confirmed in the running app** (`mdRunControl`):

| job state | connected | disconnected |
|---|---|---|
| `queued` (prepared) | ▶ Rent & Run | disabled — "Cannot run on RunPod yet" |
| `preparing` | Preparing… (disabled) | same |
| `running`, no pod | Renting a GPU… (disabled) | same |
| `running`, pod, no pid | Uploading… (disabled) | same |
| `running` + pid | ■ Stop Run | ■ Stop Run (**always enabled** — a stop must never be blocked) |
| `stopped` / `failed` | ↻ Resume Run | disabled — "Cannot resume on RunPod yet" |
| `completed` | disabled | disabled |

Stop stays enabled while disconnected on purpose: `stop_md_job` marks the job stopped
locally and returns a `warning` that the pod could not be confirmed dead, which is more
useful than refusing.
