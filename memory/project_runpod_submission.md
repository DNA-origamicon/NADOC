---
name: runpod-submission
description: Run a saved NAMD segment chain on a rented RunPod GPU — NADOC provisions the pod, runs the ladder, fetches results, terminates the pod. Third execution_target after local/alpine.
metadata:
  node_type: memory
  type: project
---

# project runpod submission — topic guide

## Managed SNUPI environment (2026-11-18)

`solver_runpod_environment.py` provisions the default SNUPI interpreter on the
network volume before preflight. Python 3.12, uv and CPU-worker dependency versions
are pinned; a volume lock serializes setup and a successful-import marker avoids
reinstalling on each pod. Custom paths and mrDNA/ARBD remain user-managed.
Setup runs after the exact-pod watchdog starts and consumes the accepted budget.
This repairs the missing `/workspace/nadoc-solver-env/bin/python` failure from
BigO-poly coarse job `b6b1359b377e` (ISSUE-227). Remote tar extraction retains
remote ownership, and bundles include core scaffold sequence/runtime data.
Live retry `b958e97feeae` completed coarse + RMSF in 1129.96 s, returned 424,144
finite positions, downloaded successfully and served display/RMSF HTTP 200.
All retry pods were independently confirmed absent; combined compute cost $1.025.
Original assembly and snapshot hashes were unchanged. Evidence:
`.development-artifacts/snupi-runpod-environment-20261118/checks.json`.

## SNUPI dynamics telemetry (2026-11-18)

`solver_progress.py` transports bounded worker receipts without mutating job
metadata. Dynamics progress uses actual integration counters (60,000 planned),
not weighted setup fractions or the static load-step setting. Named setup phases
are indeterminate; stale transport is labelled and suppresses ETA. Rate excludes
setup and resets on retries. Live replacement job `bebad41f65e7` confirms receipt
transport from RunPod. Original `4c9ec02f01e5` was stopped to deploy this change;
its pod is gone. Combined old spend and new cap remain under $5. Completion of
this Langevin job remains unconfirmed; inspect current status before retrying.
Validation also exposed ISSUE-231: imported route workspace aliases let a test
process falsely mark a live job's controller interrupted. Test startup now
redirects those aliases; the running job was restored only after exact owner
identity, remote process and fresh receipt checks. No new pod was created.

## Solver allocation availability (2026-11-18)

SNUPI/mrDNA use `solver_runpod_stock.py` to query GraphQL `gpuTypes.lowestPrice`
with the selected network-volume datacenter, requested RAM (GiB converted to
decimal GB), CPUs, Secure Cloud, public IP, CUDA and disk requirements. Global
GPU availability is insufficient: failed SNUPI job `3869962f92e9` selected an
A100 PCIe visible globally but unavailable at EU-RO-1 for 75 GiB/8 CPUs. No pod ID
or spend was recorded. The REST volume parser accepts both `dataCenterId` and
the current `dataCenter` field. Review and rental recheck capacity; supply races
fail clearly with no automatic retry or GPU substitution.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Third **`MdJob.execution_target`** after `local` and `alpine`: **`runpod`**. NADOC rents a
GPU pod on demand, runs the whole segment ladder on it, fetches results back, and
**destroys the pod**. Unlike Alpine there is no scheduler and no 2FA — which means resume
can be fully automatic, and interruptible (spot) pods become viable.

Related: [[alpine-cluster-submission]] (the remote seam this extends — read its Resume
model block), [[md-job-system]] (the local job system), [[project_water_shell_carve]].

November 16, 2026: migrated the provider boundary to REST v2
(`https://api.runpod.io/v2`). Pod reads/deletion, paginated pod/volume lists,
non-expiring creation, and Secure Cloud GPU stock use v2. The internal launch
specification and UI response fields remain stable; the adapter translates GPU,
CUDA, mount, cost, status and direct-SSH fields. `ERROR` is terminal but still
requires deletion. GPU candidate lists are attempted client-side in priority order.
Balance and `terminateAfter` creation deliberately retain GraphQL because the
current v2 schema lacks those capabilities; both use Bearer headers. Spot pods
are retired by RunPod and explicitly rejected before creation (the main executor
already disabled them). Independent watchdogs remain required; the provider
expiry hint is not a verified billing guarantee. Standalone deadman deletion URLs
also use v2. Read-only account checks succeeded for pods, volumes, catalog and
balance; no paid provisioning/simulation validation was performed.
Validation: `just test-smart` selected FAST (20,945 passed, 90 skipped);
FULL remains deferred without a test session. `just test-frontend`: 10,643 passed,
1 skipped. The 50 focused route tests were skipped by the active-oxDNA resource
guard; no browser/paid launch verification was performed.
Sources: https://docs.runpod.io/api-reference-v2/migrate-from-v1 and
https://api.runpod.io/v2/openapi.json.

November 12, 2026: the shared RunPod status card refreshes pods and balance every
15 seconds while mounted and connected, independently of job selection/polling.
Previously stopping then deleting the final job could freeze a stale billing
warning after successful provider termination. The card exposes `dispose()` to
clear its timer and coalesces overlapping billing refreshes.

<a id="adaptive-large-assembly-oxdna-phase-2026-08-26"></a>
- [Adaptive large-assembly oxDNA phase (2026-08-26)](details/project_runpod_submission/01-adaptive-large-assembly-oxdna-phase-2026-08-26.md#adaptive-large-assembly-oxdna-phase-2026-08-26)

November 12, 2026: capacity fallback also recognizes GraphQL
`SUPPLY_CONSTRAINT` and “no longer any instances available.” The old matcher
only recognized “no instances” and stopped before trying other eligible cards.
Non-capacity failures still stop immediately; mocked API tests cover both paths.

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
   cost N × $15. The per-pod billing ledger and final-cost snapshot make that cumulative
   spend visible in the Clusters tab, but a deliberate resume remains a new authorization.

   ⚠️ **The guard cannot stop the billing.** It runs ON the pod (`sleep N; pkill -9`) and
   has no API key, so it can only kill NAMD. Pod DESTRUCTION lives in the backend's
   `client.pod()` `finally`. If the backend dies, the guard fires, NAMD stops, and the
   pod keeps billing with an idle GPU. The reaper-on-connect is the backstop for that.

4. **API key resolved from disk at startup** (user decision, REVERSED 2026-08-08 — it was
   "backend memory only, mirroring the Alpine rule"). `runpod_api.resolve_api_key()` reads
   `$RUNPOD_API_KEY` then `~/.runpod_key` — the same order every `exp43_runpod_bench` script
   already used, so app + launchers + watchdogs share ONE credential. `main.lifespan` calls
   `routes_runpod.autoconnect()` in the background; a pasted key still overrides it, and
   `/runpod/status` reports `key_source: env|file|manual|none`.

   The Alpine rule never applied: that credential is a human password + a Duo push, which
   cannot be stored. A RunPod key is a machine credential meant to be stored, and holding it
   in memory only had a real cost — **after any restart NADOC could not terminate a pod it
   was still being billed for**, so the reaper waited on a human noticing. It now runs on
   boot. Opt out with `NADOC_RUNPOD_AUTOCONNECT=0` (the test suite sets this).
   `~/.runpod_key_kill` stays separate: it ships INTO a pod for the deadman switch.

5. **Interruptible/spot pods** (user decision): a reclaim is a NORMAL event, not a failure.
   The chain script is idempotent (skip any step whose `output/<name>.coor` exists), so
   resume = relaunch the same script. This is the Alpine mid-segment-checkpoint machinery
   paying off in a place it fits better.

<a id="status-tracker"></a>
- [Status tracker](details/project_runpod_submission/02-status-tracker.md#status-tracker)

- [Status tracker — continued detail](details/project_runpod_submission/02-status-tracker.md)

<a id="the-dev-server-reload-killed-live-runs-fixed-2026-08-07"></a>
- [The dev-server reload killed live runs (fixed 2026-08-07)](details/project_runpod_submission/03-the-dev-server-reload-killed-live-runs-fixed-2026-08-07.md#the-dev-server-reload-killed-live-runs-fixed-2026-08-07)

<a id="shared-runpod-accounts-installation-ownership-fixed-2026-08-12"></a>
- [Shared RunPod accounts: installation ownership (fixed 2026-08-12)](details/project_runpod_submission/03-the-dev-server-reload-killed-live-runs-fixed-2026-08-07.md#shared-runpod-accounts-installation-ownership-fixed-2026-08-12)

<a id="package-transfer-progress-and-pre-staging-fixed-2026-08-12"></a>
- [Package transfer progress and pre-staging (fixed 2026-08-12)](details/project_runpod_submission/03-the-dev-server-reload-killed-live-runs-fixed-2026-08-07.md#package-transfer-progress-and-pre-staging-fixed-2026-08-12)

<a id="progress-on-a-rented-run-fixed-2026-08-07"></a>
- [Progress on a rented run (fixed 2026-08-07)](details/project_runpod_submission/03-the-dev-server-reload-killed-live-runs-fixed-2026-08-07.md#progress-on-a-rented-run-fixed-2026-08-07)

<a id="i-cannot-resume-the-stopped-run-fixed-2026-08-07"></a>
- ["I cannot resume the stopped run" (fixed 2026-08-07)](details/project_runpod_submission/03-the-dev-server-reload-killed-live-runs-fixed-2026-08-07.md#i-cannot-resume-the-stopped-run-fixed-2026-08-07)

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

<a id="the-3x6x400-production-run-2026-07-14--what-it-proved-and-what-it-cost"></a>
- [The 3x6x400 production run (2026-07-14) — what it proved, and what it cost](details/project_runpod_submission/04-the-3x6x400-production-run-2026-07-14--what-it-proved-and-what-it.md#the-3x6x400-production-run-2026-07-14--what-it-proved-and-what-it-cost)

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
- **Staging no longer rents a pod when S3 is configured (2026-08-12).** The observed
  VoltronCoreArm package was 1.91 GiB and sequential 256 KiB SFTP writes from Colorado to
  EU-RO-1 managed ~0.9 MB/s: a projected 37–40 minutes on an idle $0.74/hr pod. NADOC now
  inventories the persistent volume first, gzip-compresses only missing/changed inputs,
  uploads one archive through the podless S3 endpoint using 10-way multipart transfer
  (16 MiB parts), and rents only after that completes. The pod expands the archive on the
  mounted volume and removes it before the existing size-based stager verifies/reuses the
  files. No S3 credentials/datacenter → the old SFTP path remains the compatibility fallback.
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
