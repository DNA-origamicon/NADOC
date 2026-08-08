---
name: runpod-submission
description: Run a saved NAMD segment chain on a rented RunPod GPU — NADOC provisions the pod, runs the ladder, fetches results, terminates the pod. Third execution_target after local/alpine.
metadata:
  node_type: memory
  type: project
---

Third **`MdJob.execution_target`** after `local` and `alpine`: **`runpod`**. NADOC rents a
GPU pod on demand, runs the whole segment ladder on it, fetches results back, and
**destroys the pod**. Unlike Alpine there is no scheduler and no 2FA — which means resume
can be fully automatic, and interruptible (spot) pods become viable.

Related: [[alpine-cluster-submission]] (the remote seam this extends — read its Resume
model block), [[md-job-system]] (the local job system), [[project_water_shell_carve]].

---

## Architecture (decided 2026-07-13)

1. **Reuse the `conn` duck-type, don't rewrite the executor.** Every function in
   `md_executor.py` takes an explicit `conn` satisfying an informal contract
   (`run`, `sftp_put`, `sftp_get`, `mkdir_p`, `mirror`, `user`, `is_connected` —
   documented at `md_executor.py:13-16`). **A pod is an SSH box, so it satisfies it.**
   `stage_plan`, `fetch_outputs`, `poll_remote_progress` / `parse_progress_listing` /
   `apply_remote_progress` all work UNCHANGED. Only submit/poll/cancel are new, because
   those are the SLURM-shaped parts (`sbatch`/`squeue`/`sacct` are string-formatted
   inline in `md_executor.py:355,403,409,511,593`; `ClusterProfile.scheduler` is stored
   and **never branched on** — it is not a dispatch mechanism, don't be fooled).

2. **One script for the whole ladder** (same call as Alpine's single-sbatch): re-queuing
   per segment stacks latency. NADOC tracks a PID + sentinel files, not a queue.

3. **NADOC owns the pod lifecycle** (user decision): create → run → fetch → **terminate**,
   with terminate in a `finally` and a hard `max_lifetime_s` kill-switch. That IS the cost
   model. An orphaned pod bills at $0.34–2.39/hr until someone notices.

   **The kill-switch is a BUDGET, not a duration** (user decision, 2026-07-14: $15 for
   this test). `runpod_script.lifetime_for_budget(budget_usd, cost_per_hr)` derives the
   wall-clock from the rate of the pod we ACTUALLY got — the same $15 buys 44 h at
   $0.34/hr and 6 h at $2.39/hr, so a hardcoded duration is wrong on every card but one.
   `DEFAULT_BUDGET_USD = 15.0`. Unknown rate → assume `DEFAULT_MAX_USD_PER_HOUR` (guess
   HIGH → shorter life → safe direction). Floor `MIN_LIFETIME_S = 900`.

   ⚠️ **The guard is per-POD, not per-JOB.** It stops a runaway ladder; it does NOT cap
   cumulative spend. Every spot reclaim relaunches with a FRESH budget, so N resumes can
   cost N × $15. Cumulative accounting is not built — see Open items.

   ⚠️ **The guard cannot stop the billing.** It runs ON the pod (`sleep N; pkill -9`) and
   has no API key, so it can only kill NAMD. Pod DESTRUCTION lives in the backend's
   `client.pod()` `finally`. If the backend dies, the guard fires, NAMD stops, and the
   pod keeps billing with an idle GPU. The reaper-on-connect is the backstop for that.

4. **API key in backend memory only** (user decision), mirroring the Alpine credential
   rule. No Duo, so re-entry after a server restart is cheap.

5. **Interruptible/spot pods** (user decision): a reclaim is a NORMAL event, not a failure.
   The chain script is idempotent (skip any step whose `output/<name>.coor` exists), so
   resume = relaunch the same script. This is the Alpine mid-segment-checkpoint machinery
   paying off in a place it fits better.

## Status tracker

- [x] **Phase 1 — pure core.** `backend/core/runpod_script.py`: chain-script generator,
      GPU sizing from a measured VRAM model, status/heartbeat/resume parsing.
      `tests/test_runpod_script.py` (39, incl. tests that EXECUTE the generated bash
      against a fake namd). Lint clean.
- [x] **Phase 2a — REST client.** `backend/core/runpod_api.py`: `build_create_payload`,
      `parse_pod`, `ssh_endpoint`, `pod_is_ready`, `RunpodClient` (create/get/list/
      terminate/`wait_for_ssh`) and **`client.pod(payload)` — an async context manager
      that terminates in a `finally`. Create pods NO OTHER WAY.** `tests/test_runpod_api.py`
      (21, httpx MockTransport, no network); the load-bearing ones prove the pod dies on
      the happy path, when the body raises, AND on wait-for-SSH timeout.
- [x] **Phase 2b — the `conn` duck-type.** `backend/core/runpod_conn.py`:
      `RunpodConnection` (run/mkdir_p/sftp_put/sftp_get/mirror + `launch_detached`,
      `pid_alive`, `read_file`). **PROVEN by execution**: `tests/test_runpod_conn.py`
      drives the REAL `md_executor.poll_remote_progress` over a `RunpodConnection` and it
      advances segment state correctly — so `stage_plan` / `fetch_outputs` /
      `poll_remote_progress` are reused, not reimplemented. 12 tests.
- [x] **Phase 2c — executor + seam.** `backend/core/runpod_executor.py`: `submit_job`
      (stages via the REUSED `md_executor.stage_plan`, renders the chain script, launches
      detached), `poll_job`, `cancel_job` (kills the process GROUP — killing just the bash
      pid orphans NAMD, which keeps the GPU busy and the pod BILLING while the UI reads
      "stopped"), `fetch_results` (REUSED `md_executor.fetch_outputs`), and
      **`run_job_on_pod`** = provision → stage → run → fetch → **destroy**.
      `tests/test_runpod_executor.py` (15) proves the pod dies on ALL FOUR paths: success,
      NAMD failure, mid-run exception, spot reclaim.
      Seam turned out to be TINY — the three `namd_runner.py` guards are already
      `!= "local"` (they route any non-local target away, no change needed), and
      `md_executor.py:741`'s `!= "alpine"` filter is CORRECT as-is (that is the Alpine
      poller; RunPod needs its own). Only two files changed:
      * `md_job.py`: `runpod_pod_id`, `runpod_pid`, `runpod_heartbeat` + load-setdefaults.
      * `md_pipeline.py:40`: `_VALID_RUN_TARGETS` now `("local", "alpine", "runpod")`.
- [x] **Phase 3a — routes.** `backend/api/routes_runpod.py` (registered in `main.py`):
      connect / status / disconnect / **`GET /runpod/pods` (the LEAK CHECK — anything it
      returns is billing right now)** / terminate / `POST /runpod/estimate` (GPU + cost
      from the measured VRAM model, creates no pod) / gpu-types.
      `tests/test_routes_runpod.py` (12). API key in memory only.
- [x] **Phase 3b — run-target radio.** "RunPod" option beside Local/Alpine.
      **Found and fixed a real trap:** ~28 sites in `md_jobs_panel.js` assumed a BINARY
      world and used `!== 'alpine'` as a synonym for "local". With a third target, four of
      them misclassify a RunPod job as LOCAL — including the two `isLocalRun` sites that
      gate autostart, so a RunPod job would have been launched on the user's desktop GPU.
      New pure `mdIsLocalTarget(target)` / `mdIsRemoteJob(job)`, vitest-pinned.

- [x] **Phase 3c — dispatch.** `routes_md.start_md_job` branches on
      `execution_target == "runpod"` **BEFORE** `find_namd()` (a RunPod job runs NAMD on the
      POD; requiring a local NAMD would refuse a valid job on a machine with no GPU).
      `routes_md.stop_md_job` branches **BEFORE** its `!= "local"` Alpine `scancel` path —
      a RunPod job falling in there finds no cluster session, reports "stopped", and
      **LEAVES THE POD BILLING**. New `backend/core/runpod_supervisor.py` owns the task
      registry, the pod id (so a cancel can kill a pod mid-provision), `n_atoms_for` /
      `min_name_for`, and `reap_orphan_pods`. `tests/test_runpod_supervisor.py` (12).

- [x] **Phase 5 — THE JOB WIZARD.** (2026-08-07) RunPod stopped being a Clusters-card-only
      feature. Its wizard card was inert (`UNWIRED_TARGETS.runpod`) and blocked Next; now it is
      full parity with Alpine's step 1. The Clusters card keeps its own mounts unchanged —
      shared modules, both live.
      * **`runpod_select.plan_options()`** generalises `gpu_options`, which hardcoded a 19.2 ns
        ladder at 4 fs and so could not react to anything. Relaxation and production are costed
        **separately, at their own timesteps** (the ladder's soft chunk is 1-2 fs and is the
        most expensive chunk per ns). `gpu_options` is now a relax-only projection of it — one
        rate path, pinned by `test_plan_options_relax_only_matches_gpu_options`.
      * **`backend/core/runpod_storage.py`** — output bytes (reuses `disk_guard.
        namd_run_output_bytes`), volume fit, and the billable staging upload. ⚠️ RunPod's API
        reports a volume's SIZE but **not its usage**; measuring free space needs a live pod, so
        `used_known: False` is returned rather than assuming an empty volume.
      * **`POST /runpod/job-preview`** — the `/cluster/slurm-preview` analogue. Cards + storage +
        balance + live pods + pre-flight in ONE round trip. Soft-fails to `{sized: false}`; a
        missing design is not a 404 (the wizard polls it on every debounced plan refresh).
      * **`POST /runpod/volume`** — sets the session volume **without the API key**. The setup
        modal could re-POST `/connect` because it still holds the key; the wizard cannot and
        must not, so its volume picker had no way to record a choice at all.
      * **`MdJob.runpod_gpu_key` / `runpod_budget_usd` / `runpod_volume_id`** + `CreateJobRequest`.
        This fixed a LIVE BUG: `runpod_gpu_key` had been sent by the frontend since Phase 3b and
        **silently dropped by pydantic**. The budget was a module constant the user never saw;
        it now threads `job → start_job → run_job_on_pod(budget_usd=…)`.
      * **The picker and the renter used DIFFERENT selection logic.** `pod_payloads_for` ranks
        with `plan_execution` (VRAM fit against pinned prices, cheapest first — no live stock, no
        arch-vs-build gate, no $/ns), while the UI ranks with `runpod_select`. The wizard showed
        one card and rented another. The chosen key now heads `gpuTypeIds`; it stays a LIST.
      * Frontend: `md_job_wizard_runpod_model.js` (pure, 41 tests) + `md_job_wizard_runpod.js`
        (24 tests) + `jobOptionView`/`renderJobOptionRows` in `runpod_gpu_options.js`. The
        estimate follows the later tabs through the EXISTING `loadPlan() → refreshSizing()` hook.
        Cache key = steps/timesteps/dcd_freq; **budget and card selection are deliberately NOT in
        it**, so typing a cap or picking a card re-gates with zero network traffic.
      * Frontend never re-sorts the rows — `select_cards(prefer="balanced")` already applied the
        two-axis rule, and a client-side "cheapest first" would resurrect the A6000 trap.

- [x] **Phase 5b — the RUN button.** (2026-08-07) The wizard could set a RunPod job up but
      nothing could start one: `mdRunControl` had an Alpine-only branch, so a RunPod job
      **read "■ Stop Run" through its whole local package build** (offering to stop a run that
      had not begun) and, once prepared, sat **disabled** telling the user to "submit it from
      the review card" — a card the wizard had replaced. The click handler had no RunPod
      branch either, so pressing Run did literally nothing.
      * New pure `mdRunpodPhase(job)` names the three unattended waits from signals the job
        already carries: `preparing` (local packaging, nothing rented) → `renting` (status
        running, no `runpod_pod_id`) → `uploading` (`runpod_pod_id` set, `runpod_pid` not).
        **`runpod_pid` is the boundary** — it is written when the chain script launches, so
        "pod but no pid" is exactly the staging window where the GPU bills and computes nothing.
      * New pure `mdRunpodStartable(job)`; the click dispatches it to `_startSelected` →
        `POST /md/jobs/{id}/start` → `_start_runpod_job`. Kept SEPARATE from `mdJobIsStartable`
        because `mdQueueable` leans on that one to keep remote jobs out of the LOCAL run queue.
      * `▶ Rent & Run` is gated on the RunPod pre-flight, which now also refreshes when a
        RunPod job is **selected** (it previously only ran when the run-target radio moved).
        No pre-flight yet → not blocked; the backend runs the same check and 400s with the
        same reason.
      * **Two painters were fighting over the same button.** `_paintRunpodGate` set
        `disabled`/`opacity`/`title` keyed on the RADIO (where the NEXT job runs) while
        `_paintRunControl` keyed on the SELECTED job. It now only shows/hides the Clusters-card
        boxes; the gate moved into the pure, tested `mdRunControl`.
      * **`hasActiveRemoteJob` was Alpine-only**, so the 20 s remote poll never armed for a
        rented run — the label would have frozen on "Renting a GPU…" through the entire
        upload. Same for `mdWatchdogDecision`, which chased a local status WebSocket that a
        pod-side run does not have.
      * The local-concurrency confirm is skipped for a rented run (it asks about this
        machine's GPU), and the toast says the pod is destroyed when the run finishes.
      * ⚠️ **Deliberate trade-off:** the button is disabled through `renting`/`uploading`, per
        the user's request for Alpine-like behaviour. The pod IS billing then, so the escape
        hatch is the Clusters card's pod list (`GET /runpod/pods` + terminate) — the tooltip
        says so.

- [x] **Phase 4 — END-TO-END ON A LIVE POD. PASSES.** (2026-07-13)
      `experiments/exp43_runpod_bench/e2e_runpod_job.py`: real 6hb package, real pod.
      ```
      sizing : RTX 4090 $0.34/hr — fits GPU-resident
      status : completed        wall: 5.2 min (~$0.03)
      fetched: 6hb_sim_v2_00_min_enm_k0p5.coor + ..._01_300K_NPT_ENM_k0p5_p10.coor
      live pods after teardown: 0  ✓ nothing billing
      ```
      NADOC provisioned the GPU, staged 76 MB, ran minimise → segment, fetched results,
      and destroyed the pod, unattended.

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
is backend-memory-only, so *every* dev-server reload silently disconnects the session. The
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

## Operational facts

- Network volume **`77pnhye88p`** (`yappiest_yellow_hyena_volume`), datacenter **`EU-RO-1`**,
  **200 GB** (was 50; grown since). It PINS the pod's datacenter — which is why a single named
  GPU is often unavailable (`500 "There are no instances currently available"`) and why
  `gpuTypeIds` must be a priority LIST.

  **Housekeeping (2026-08-07): 176 GB → 89.6 GB (88% → 45%).** Removed `blade_capture`
  (68.8 GB — three parallel 21.5 GB coord/vel/force DCDs from the shelved BLADE capture),
  `bench` + `nadoc_bench` (8.9 GB of per-GPU benchmark packages), 10 job dirs with no local
  job record (7.8 GB), and the one job that was fully downloaded (1.2 GB).

  ⚠️ **"Archived locally" does NOT mean "downloaded".** Checking every volume file against
  `/media/jojo/Archive` by name+size found that **only 1 of 28 job dirs was complete** — the
  fetch is selective by design (checkpoints come down, production DCDs stay), so a job that
  looks archived can still be the only copy of its trajectory. Compare sizes before deleting
  anything. `df` on the pod is useless here: it reports the whole MooseFS cluster (1.4 P), not
  the volume quota — use `du -sb /workspace`.

  ⚠️ **An interrupted fetch leaves a silently truncated file.** `2xT_full.dcd` was 3.22 GB
  locally against 22.85 GB on the volume, with no error anywhere — the fetch log just stops
  mid-line. `rsync --append-verify --partial --inplace` resumes it correctly.
- Image: **`runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`**. A plausible-but-wrong tag
  500s at pod-create and there is no API to discover valid tags.
- Patched NAMD (sm_89) + all three packages + all three minimisation checkpoints live on
  the volume. Pods are disposable; the toolchain is not.

## The 3x6x400 production run (2026-07-14) — what it proved, and what it cost

**1.94M atoms, full ladder + 5.5 ns production, ~$13 of a $15 cap.**

| | |
|---|---|
| relaxation | **4/4 stages bridged at p10** — 4.32M of 4.8M steps SKIPPED (a **10x** acceleration; exp36's 4.9x was pessimistic) |
| | 4.6 h, **$3.99**. Un-accelerated: ~35 h, ~$26 |
| measured 4 fs GPU-resident | **26.4 ms/step** = 13.1 ns/day on an RTX PRO 4500 Blackwell |
| ⚠️ | the 4090 per-Matom fit predicted **20.9** — it does **NOT transfer across architectures** |
| bugs found | **11 — and NINE produced no error of any kind** |

The 6hb e2e (225k atoms, 5 min, $0.03) was green and documented as "PROVEN on a live pod".
**It reached none of the eleven.** Scale, duration and money each expose a disjoint class of
failure.

> **READ BEFORE RENTING ANYTHING:**
> * **[REFERENCE_RUNPOD_RUNBOOK](REFERENCE_RUNPOD_RUNBOOK.md)** — the hardened protocol:
>   pre-flight gates, the measured cost model, monitoring, teardown, the failure catalogue.
> * **`python experiments/exp43_runpod_bench/preflight.py <job_id>`** — the MECHANICAL gate.
>   It refuses a package that would silently cost 4x, run on the wrong disk, or rent a card
>   the binary cannot execute. Verified: it rejects the exact broken package this run
>   started from, and passes the one that worked.
> * **[LESSONS](LESSONS.md) category L (L1–L6)** — indexed by symptom.

**The two lessons worth carrying to any rented-compute work:**

1. **"Fails safe" can mean "fails expensive."** The early-stop evaluator's fail-safe is HOLD
   (run everything) — right for the science, ruinous for the wallet. Always ask: *safe for
   whom?*
2. **A safety net can have the same hole as the thing it protects.** The spend ledger existed
   *because* the kill-switch had no memory — and then it under-reported, freezing at $0.95
   while a real GPU billed to $1.35. **A ledger that under-reports is worse than no ledger,
   because it is trusted.**

**Scripts** (`experiments/exp43_runpod_bench/`): `prep_3x6x400.py` (free, ends in the
degeneracy gate) · `preflight.py` (refuses a bad run) · `launch_relax.py` ·
`launch_production.py` (self-sizing from the parent's logs) · `supervise.py` (re-attach to an
orphaned pod) · `watch.py --oneline` · `reap.py --kill` (**the panic button**) ·
`spend_ledger.py` (cumulative across ALL pods — the $15 is a SESSION cap).

## Open items

- **Cumulative spend is not tracked *in the app*.** The kill-switch caps ONE pod's life and
  has no memory, so a relaxation pod and a production child each get the full budget — a
  "$15 cap" silently authorises $15 × N. `experiments/exp43_runpod_bench/spend_ledger.py`
  is the stopgap (sums every pod in a session; budget decisions read it), but the real fix
  is an `MdJob.spent_usd` that accumulates across pods and SHRINKS the next pod's budget.
  **The wizard's per-job cap does NOT close this** (user deferred it, 2026-08-07) — the UI
  says so in as many words rather than implying a guarantee the system does not make.
- **The learned rate registry has never been written.** `runpod_select.DEFAULT_RATES_PATH`
  (`/media/jojo/Archive/nadoc_bench_campaign/gpu_rates.json`) does not exist, so every estimate
  comes from the conservative static priors. It degrades correctly (`load_rate_registry()` → `{}`)
  and the priors are close — the wizard predicts 17.6 ns/day for a 4090 at 1.31M atoms against
  17.3 measured — but seeding it from the 11-card sweep in
  `experiments/exp43_runpod_bench/logs/bench_*.log` would make them measured rather than assumed.
- **The atom estimate ignores the wizard's solvent settings.** `/runpod/job-preview` accepts
  `padding_nm` but the frontend does not send it yet, so changing padding / water shell / ion
  concentration does not move the atom count. Alpine's `/cluster/slurm-preview` has the same gap.
  Related: `md_vram._profile_cache_key` includes `padding_nm` but **omits `nacl_mM`/`mgcl2_mM`**,
  so a changed ion concentration returns a stale ion census from the memo.
- **Never exercised on a live pod through the wizard.** The whole Phase-5 path is verified with
  mocked stock and a loaded design; that a job created in the wizard actually rents the chosen
  card and honours the chosen cap needs `frontend/e2e/runpod_submit.spec.js`
  (`NADOC_E2E_RUNPOD=1`, ~$0.50, a real pod) in a deliberate budgeted session.
- **Staging is billable.** The 1.9M-atom package is 1.21 GB and uploads over SFTP at
  domestic upstream speed — ~15 min of pod time (~$0.20) before NAMD runs a single step.
  It lands on the NETWORK VOLUME (`REMOTE_ROOT=/workspace/nadoc_jobs`, `volumeMountPath=
  /workspace`), so **staged inputs AND outputs survive the pod dying** — a second pod for
  the same job_id re-uses them and the chain script skips completed steps. Worth exploiting:
  a pre-staging step on a cheap pod, or simply not re-staging for the production child.
- **The prep pipeline can emit a degenerate package and nobody notices.** Job `f702f4a3282f`
  shipped a VoltronCore package with **279 coincident atoms (0.000 Å)** and 634k real
  clashes; NAMD died with an uninterpretable NaN. A rebuild from the SAME design is clean
  (0 coincident, min 0.408 Å) — the design was never at fault. **`dry_audit` should reject a
  package whose minimum heavy-atom distance is degenerate**, so this fails loudly at prep
  time instead of hours later inside NAMD. Not yet implemented.
- The design-layer clash detector (`clash.py::clash_report`) is **structurally blind** to a
  fold that drives a cluster into an *immediately adjacent* helix: its straight-vs-posed
  margin rule pre-excludes lattice neighbours as "designed proximity". It correctly returned
  0 for VoltronCore, but it could not have caught the case even if one existed.
- NAMD binary: the patched `3.0.2p1` must be built **per GPU architecture** (4090 = `sm_89`,
  3080 Ti = `sm_86`, 2080S = `sm_75`). `cuobjdump --list-elf` shows the union of NAMD's own
  kernels AND the bundled NVIDIA libs (cuFFT etc.) — do not read the union as NAMD's coverage.
  Build once onto the network volume; pods are disposable, the toolchain is not.
