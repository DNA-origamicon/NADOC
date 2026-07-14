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

## Operational facts

- Network volume **`77pnhye88p`**, datacenter **`EU-RO-1`**, 50 GB. It PINS the pod's
  datacenter — which is why a single named GPU is often unavailable
  (`500 "There are no instances currently available"`) and why `gpuTypeIds` must be a
  priority LIST.
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
