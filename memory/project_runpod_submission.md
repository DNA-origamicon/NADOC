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

## FOUR bugs the live run found — each cost a real, billing pod

1. **`gpuTypeIds` must be arch-filtered.** `build_patched_namd.sh` compiles for ONE
   `sm_XX` ("single arch: ~4x faster nvcc pass") and the volume's build is **sm_89**. When
   no 4090 was free, the fallback rented an **A100 (sm_80)** — which booted fine and then
   died at step 0 with `cudaMemcpyToSymbol ... bindExclusions ... no kernel image is
   available`, the SAME failure as the local sm_75 binary on the 4090. `GPU_TYPES` now
   carries an `sm` field and `NAMD_BUILD_ARCHS = ("sm_89",)` filters it. **To use A100/
   A6000/H100, rebuild NAMD multi-arch and widen that tuple.**
2. **A price ceiling is mandatory.** Unbounded "fall back to whatever is available" rented
   a **$1.39/hr A100** to relax a 225k-atom duplex whose cheapest viable card is $0.34.
   `DEFAULT_MAX_USD_PER_HOUR = 1.00`.
3. **`+p` needs a CAP, not just a halving.** The A100 host had 128 vCPUs → `vcpus//2` asked
   for **`+p64`**, far off the end of NAMD's single-GPU scaling curve. `MAX_NAMD_THREADS = 16`.
4. **Never set `dockerStartCmd`.** It REPLACES RunPod's own start script — which is what
   launches **sshd**. A pod created with `sleep infinity` boots, reports RUNNING, exposes
   port 22, and refuses every SSH connection.

Plus two that cost only time:
- **`cd D && CMD &` re-subshells the launch** and that subshell's stdout is still the SSH
  channel, so the channel never closes and `conn.run` times out. Use `;`, so `&` binds to
  the redirected `setsid` alone.
- **`!NATOM` is NOT in the first 4 KB of a PSF.** psfgen writes one `REMARKS` line per
  patch: 6hb has 604 title lines (`!NATOM` at byte 18,729), flat_1x50 has **7,342** and it
  lands past 64 KB. Stream lines; never head-read.

## Operational facts

- Network volume **`77pnhye88p`**, datacenter **`EU-RO-1`**, 50 GB. It PINS the pod's
  datacenter — which is why a single named GPU is often unavailable
  (`500 "There are no instances currently available"`) and why `gpuTypeIds` must be a
  priority LIST.
- Image: **`runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`**. A plausible-but-wrong tag
  500s at pod-create and there is no API to discover valid tags.
- Patched NAMD (sm_89) + all three packages + all three minimisation checkpoints live on
  the volume. Pods are disposable; the toolchain is not.

## OLD — superseded (kept for the reasoning)

Everything above is built and tested, but **the Run button does not yet dispatch to
RunPod**. To close the loop:

1. `routes_md.start_md_job` (and the create/autostart path) must branch on
   `execution_target == "runpod"` → `runpod_executor.run_job_on_pod(...)`, taking the
   API key + `network_volume_id` from `routes_runpod._SESSION`.
2. A supervisor poll loop for runpod jobs (mirror `md_executor.poll_remote_jobs`, which
   filters `!= "alpine"` and therefore skips them).
3. `n_atoms` for sizing: read `!NATOM` from the package PSF (`routes_md` already does this
   for the production disk estimate).
4. `min_name`: from `manifest.json["minimization"]["name"]`.
5. **NOT YET EXERCISED IN THE APP** — the radio is served and the pure logic is unit-tested,
   but no click-through and no live pod round-trip. Phase 4 = end-to-end on a real pod.

- [ ] **Phase 4 — end-to-end on a live pod**, auto-resume on reclaim, cost readout in the
      panel, pod-leak reaper on startup.

## MEASURED on a rented RTX 4090 (2026-07-13) — the numbers the code is calibrated to

32 vCPU / **16 physical cores** / 131 GB RAM / 24,564 MB VRAM, NAMD 3.0.2p1 (patched),
$0.34/hr community cloud.

| system | atoms | conservative 2 fs | fast HMR+4 fs | **fast + GPU-resident** | offload VRAM | resident VRAM |
|---|---|---|---|---|---|---|
| 6hb_sim_v2 | 225,504 | 20.73 | 41.38 | **137.49** ns/day | 854 MB | 1,114 MB |
| flat_1x50 | 1,442,735 | 2.59 | 5.15 | **21.29** ns/day | 3,496 MB | 5,016 MB |
| VoltronCore | 5,656,632 | cell_shrink | cell_shrink | **4.48** ns/day | 12,334 MB | **17,678 MB** |

- **GPU-resident is worth 3.3–4.1×** and scales BETTER with system size. NADOC's shipped
  `equilibrium_aware` confs do NOT enable it (only the `fast` path does) — that is the
  single biggest free win, locally and remotely.
- **A 5.66M-atom system fits GPU-resident in 24 GB** (17.7 GB). VRAM model:
  `offload ≈ 2100 MB/Matom + 400`, `resident ≈ 3212 MB/Matom + 400` — predicted 18,571 MB
  for VoltronCore vs 17,678 measured (5% conservative, the safe direction).
- **`+p` must equal PHYSICAL cores.** `+p32` on 16 real cores ran 18.85 ns/day vs `+p16`'s
  41.38 — oversubscribing SMT **halved** throughput. RunPod advertises vCPUs → `vcpus // 2`.
- The extreme flat box (1146 × 44 × 294 Å, 26:1) is a **non-issue** — minimised clean, no
  patch-grid trouble. Box anisotropy was not the problem it was assumed to be.

## Traps that cost hours — encoded as code + tests, do not re-derive

- **NAMD renames its process to `NAMD masterPe`.** `pgrep -x namd3` matches NOTHING and
  reports a live job as dead. A CPU-only control run therefore survived `pkill`, ate 32
  threads for an hour, and silently contaminated an entire benchmark (every ns/day ~6× low,
  GPU at 4%, and it produced the FALSE conclusion "GPU-resident gives no speedup"). **Track
  the PID you spawned; match `argv[0]`, never the process name.** Both the chain script and
  the bench harness now refuse to run on a contended machine.
- **A NaN-stalled minimisation never exits.** Its line minimiser sits on NaN forever. Needs
  the stall watchdog (no log output for N minutes → kill), or a wedged job bills until the
  account is empty.
- **The watchdog subshell must have its stdio detached** (`) >/dev/null 2>&1 &`). Otherwise
  its orphaned `sleep` holds the script's stdout pipe open after NAMD exits and every reader
  blocks a full poll interval per step — the job looks hung. Load-bearing, not tidiness.
- **`cell_shrink` is a RESTART, not a failure.** An NPT box relaxing ~3% to equilibrium
  density crosses NAMD's fixed patch grid → "Periodic cell has become too small". It killed
  BOTH offload VoltronCore cells. Self-healing on restart; bounded retry in the chain script.
  **Never "fix" it with a `margin` keyword** — that crashes the GPU tile-list kernel on a
  carved box.
- **NAMD reports throughput in DIFFERENT UNITS by mode**: offload prints `days/ns`,
  GPU-resident prints `ns/day`. Parsing one silently drops every cell of the other.
- **`GPUresident` must precede `run`** in a conf. After `run` it is a runtime change to an
  already-finished simulation: NAMD dies with "Can't modify CUDASOAintegrate when that mode
  was never enabled" — *after* silently running the whole segment in offload mode.

## Open items

- **Cumulative spend is not tracked.** The `$15` kill-switch caps ONE pod's life. A spot
  reclaim relaunches with a fresh budget, so a job that gets reclaimed 3× can bill 3×$15
  and no code notices. To fix properly, `MdJob` needs a `spent_usd` that accumulates
  across pods and shrinks the next pod's budget. Until then, **$15 is a per-pod cap, and
  the real exposure on a heavily-reclaimed job is a multiple of it.**
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
