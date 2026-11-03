# Status tracker — supporting detail

[Topic head](../../project_runpod_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
      `tests/test_routes_runpod.py`. API key from `resolve_api_key` (Decision 4).
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
