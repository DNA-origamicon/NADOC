---
name: alpine-cluster-submission
description: Multiphase plan — one-click submit of NADOC MD jobs to CURC Alpine (SSH+SLURM); auto-resource decision tree with review; per-phase handoff
metadata: 
  node_type: memory
  type: project
  originSessionId: 909b50d7-8696-47a9-979c-fb67ba2f41ec
  modified: 2026-08-20T04:18:38.929Z
---

# Alpine cluster submission

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Before changing restart behavior, read the Resume model detail below. User-visible progress is carried forward from evidence, never fabricated. Cluster profiles, deployment instructions and measured fleet/queue observations retain their original dates; verify live availability before use.

- [Overview — continued detail](details/project_alpine_cluster_submission/01-overview.md)

**2026-09-29 command channel cleanup:** Repeated stalled Slurm queries left SSH
channels open after timeout, followed by `open failed` and session expiry around
80–103 seconds after login. Commands now own their process before the exec
acknowledgment and close their channel on completion, timeout, or cancellation.
A channel-open refusal preserves an open transport and logs its exception type/code.
Local real-SSH regression covers twelve consecutive timeouts and startup cancellation;
Fresh Duo login confirmed working SFTP and a sustained session; scheduler fallback
above resolved the remaining progress-poll blocker. Passive incident capture
is running as user service `nadoc-alpine-diagnostics` for 24 hours.

**2026-09-28 scheduler timeout isolation:** A command timeout preserves an open SSH
transport, so slow availability/history queries do not interrupt result downloads.
Closed transports still expire. Timeout logs include transport/session state;
concurrent identical history queries share one request across job shapes. Restart
an idle detached worker to load the change, then reconnect through Duo.

**2026-09-21 fixed-pose image clearance:** The submission review and submit/resume/ensemble
routes now require a separate acknowledgment for low or unverified solute-to-image
envelope gaps. Production uses its actual equilibrated coordinates/cell. The recommendation
is max(2.4 nm, twice the configured cutoff); the existing rotational override does not
bypass this check. Remote-resume poses remain unverified until their actual remote
checkpoint can be inspected. See [submission clearance](../docs/namd_submission_clearance.md).

Related: [[md-job-system]] (the local job system this extends), [[md-prep-relaxation-exp29]]
(prep ladder that produces the package we ship), [[namd-solvate]], [[btube-benchmark]].

---

## HANDOFF — how to use this file

Each phase is a self-contained fresh-session chunk. To run one: open this file,
find the **first unchecked phase** in the Status tracker, read that phase's
section + the Appendix, implement, verify per its Done criteria, then **tick the
box and append a one-line "shipped:" note under that phase** before ending the
session. The user starts each with *"proceed to next phase of the alpine cluster md"*.

**Standing rules for every phase** (from `CLAUDE.md`):
- Backend change → run `just test-smart`, cite its decision + pass count. Flag any test-count drop. (Full `just test` = pre-push gate.)
- Frontend change → exercise in the running app, or lead with `NOT VERIFIED IN APP`.
- **Module-first law.** New cohesive logic lands in the **new modules named per
  phase**, NOT in `main.js` or as a fat block in an existing file. `main.js` gets
  only import + factory init + thin wiring; cite its LOC Δ (flat/lower).
- New pure functions get ≥1 vitest/pytest test (input→output).

**External dependency:** Phases 1, 3, 4 need **real Alpine credentials + the user
present for Duo 2FA** to validate end-to-end. Auth cannot be fully headless
(see Appendix "Auth reality"). Schedule those validations when the user is available.

---

<a id="status-tracker"></a>
- [Status tracker](details/project_alpine_cluster_submission/02-status-tracker.md#status-tracker)

<a id="key-architecture-decisions-read-before-phase-1"></a>
- [Key architecture decisions (read before Phase 1)](details/project_alpine_cluster_submission/02-status-tracker.md#key-architecture-decisions-read-before-phase-1)

### Resume model (2026-07-03 pivot — supersedes the auto-resubmit chain)

User directive after the first live TIMEOUT (job `2719c1c8700f`, SLURM 29566908→auto-resubmit→
29572963, then stopped): **do NOT auto-resubmit in the supervisor.** Rationale + the correct model:
- **Long walltimes get lower scheduler priority (esp. GPU).** A series of SHORT jobs finishes sooner
  than one long job. So the intended usage is: submit with a short walltime that WILL time out, then
  resume-from-checkpoint as a fresh submission — repeatedly — rather than request one 50 h block.
- **Duo 2FA blocks automation.** A resubmit needs a live SSH session, which needs the user present
  for Duo. So NADOC must NOT loop/auto-resubmit. Instead: a timed-out job enters a **resumable**
  state; the user logs in (Duo) and clicks **Resume** (one click) → NADOC resubmits from the latest
  checkpoint as a new SLURM job.
- **NADOC's job = prepare a job to be resumable, then one-click resume.** Because Resume is
  user-triggered with the **backend present**, NADOC can be smart at resume time (unlike a bare
  node): inspect scratch, find the interrupted segment + its restart step, generate the resume conf
  (reuse the local runner's `_write_resume_conf` logic), upload a resume sbatch, resubmit.

**CRITICAL correctness point:** short walltimes time out **MID-SEGMENT** (a single relax segment
can exceed the walltime — e.g. 2hb: ~2.8 h/segment vs a 1 h block → NO segment ever completes). So
**segment-granularity skip is NOT enough** — resume MUST continue the interrupted segment from its
NAMD `*.restart.{coor,vel,xsc}` checkpoint, or a short-walltime job makes zero progress and loops
forever. The idempotent-skip sbatch (increment 9) handles *completed* segments; the interrupted one
needs true mid-segment restart.

**Revised Phase-5 resume TODO (increment 10 — NOT built):**
1. Remove the supervisor auto-resubmit (`poll_remote_jobs`/`reconcile_remote_job` must NOT resubmit).
2. On SLURM TIMEOUT/DEADLINE: fetch outputs (incl. restart files) back, mark the job **resumable**
   (a distinct state, not `failed` — proposal: `status=paused` or a `resumable=True` flag + a clear
   "Timed out at segment N/M — reconnect and Resume" message), keep `resubmit_count` for display.
3. `POST /md/jobs/{id}/resume-remote` (needs connection): find the interrupted segment, read its
   restart step (fetch the small `.restart.xsc`), generate a remote resume conf (port
   `_write_resume_conf`: firsttimestep + remaining steps + restart file refs, output naming so the
   next segment finds `output/<seg>.coor`), upload it + a resume sbatch (skip done → run resume conf
   → remaining segs fresh), resubmit; new SLURM id, `resubmit_count++`, back to running/queued.
4. Frontend: one-click **Resume** button on a resumable remote job (enabled only when connected).
5. Decide: same NADOC job (resubmit_count++) — proposed — vs a new child job row.

**Already shipped but now MIS-MODELED:** increment 9's `resubmit_from_scratch` + the auto-resubmit
call in `reconcile_remote_job` + `is_timeout_state` gating + `_MAX_AUTO_RESUBMITS`. Repurpose
`resubmit_from_scratch` into the user-driven resume; DELETE the supervisor auto-call. The idempotent
sbatch (skip-if-`.coor`) STAYS — it's the completed-segment half of resume.

---

<a id="alpine-gpu-fleet-2026-08-06--the-availability-popup"></a>
- [Alpine GPU fleet (2026-08-06) + the availability popup](details/project_alpine_cluster_submission/03-alpine-gpu-fleet-2026-08-06--the-availability-popup.md#alpine-gpu-fleet-2026-08-06--the-availability-popup)

<a id="measured-benchmark-matrix-2026-08-07--supersedes-the-guessed-speed-factors"></a>
- [MEASURED benchmark matrix (2026-08-07) — supersedes the guessed speed factors](details/project_alpine_cluster_submission/03-alpine-gpu-fleet-2026-08-06--the-availability-popup.md#measured-benchmark-matrix-2026-08-07--supersedes-the-guessed-speed-factors)

<a id="seeing-a-running-cluster-job-in-the-viewport--the-one-frame-fetch-2026-08-07"></a>
- [Seeing a RUNNING cluster job in the viewport — the one-frame fetch (2026-08-07)](details/project_alpine_cluster_submission/03-alpine-gpu-fleet-2026-08-06--the-availability-popup.md#seeing-a-running-cluster-job-in-the-viewport--the-one-frame-fetch-2026-08-07)

<a id="the-progress-bar-between-sign-ins--carried-forward-never-invented-2026-08-07"></a>
- [The progress bar between sign-ins — carried forward, never invented (2026-08-07)](details/project_alpine_cluster_submission/03-alpine-gpu-fleet-2026-08-06--the-availability-popup.md#the-progress-bar-between-sign-ins--carried-forward-never-invented-2026-08-07)

<a id="workspaceclustersjson-shadows-the-embedded-profile--edit-both"></a>
- [`workspace/clusters.json` shadows the embedded profile — edit BOTH](details/project_alpine_cluster_submission/03-alpine-gpu-fleet-2026-08-06--the-availability-popup.md#workspaceclustersjson-shadows-the-embedded-profile--edit-both)

<a id="get-apiclusteravailability--the-popups-data"></a>
- [`GET /api/cluster/availability` — the popup's data](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#get-apiclusteravailability--the-popups-data)

<a id="amilan--acpu-confirmed-renamed-2026-08-06"></a>
- [`amilan` → `acpu`: CONFIRMED RENAMED (2026-08-06)](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#amilan--acpu-confirmed-renamed-2026-08-06)

<a id="live-measured-queue-reality-2026-08-06-63k-atom--200-ns-job"></a>
- [Live-measured queue reality (2026-08-06, 63k-atom / 200 ns job)](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#live-measured-queue-reality-2026-08-06-63k-atom--200-ns-job)

<a id="live-gres-tokens-confirmed"></a>
- [Live GRES tokens (confirmed)](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#live-gres-tokens-confirmed)

<a id="live-rtx-pro-6000-mig-production-benchmark-2026-08-27"></a>
- [Live RTX Pro 6000 MIG production benchmark (2026-08-27)](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#live-rtx-pro-6000-mig-production-benchmark-2026-08-27)

<a id="re-verified-live-2026-08-06-second-session-after-the-fixes"></a>
- [Re-verified live 2026-08-06 (second session, after the fixes)](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#re-verified-live-2026-08-06-second-session-after-the-fixes)

<a id="known-gap--a-clamped-walltime-reads-as-a-completion-time"></a>
- [Known gap — a clamped walltime reads as a completion time](details/project_alpine_cluster_submission/04-get-apiclusteravailability--the-popups-data.md#known-gap--a-clamped-walltime-reads-as-a-completion-time)

<a id="gpu-resident-namd-on-alpine-there-is-no-module-you-must-build-it-2026-08-07"></a>
- [GPU-resident NAMD on Alpine: there is no module, you must build it (2026-08-07)](details/project_alpine_cluster_submission/05-gpu-resident-namd-on-alpine-there-is-no-module-you-must-build-it.md#gpu-resident-namd-on-alpine-there-is-no-module-you-must-build-it-2026-08-07)

### Owed — needs the user present for Duo

**Items 1–3 are DISCHARGED (2026-08-07).** ~~Confirm the GPU NAMD module on ah200~~ — moot: no
CUDA NAMD module exists on Alpine at all, so we build our own and point `gpu_namd_bin` at it.
~~One real ah200 submission~~ — done many times over: the whole benchmark matrix plus the 24hb
production run (SLURM 30958617). ~~In-app exercise of the popup and the wizard's new first step~~
— **user-confirmed in app 2026-08-07, all features pass** (see below).

1. **CPU QoS names are docs-derived**, not live-tested by sbatch. The GPU half of the same docs
   table was live-confirmed, which is good corroboration, but `cpu-normal` has not been submitted.
   Untouched by the 2026-08-07 validation — that exercised the GPU/display path only.

<a id="user-validated-in-app--2026-08-07"></a>
- [User-validated in app — 2026-08-07](details/project_alpine_cluster_submission/06-user-validated-in-app--2026-08-07.md#user-validated-in-app--2026-08-07)

<a id="result-download-is-a-separate-verified-lifecycle-2026-08-09"></a>
- [Result download is a separate, verified lifecycle (2026-08-09)](details/project_alpine_cluster_submission/06-user-validated-in-app--2026-08-07.md#result-download-is-a-separate-verified-lifecycle-2026-08-09)

<a id="flexibility-map--replica-package-invariant-from-upstream-2026-07-09"></a>
- [Flexibility-map / replica-package invariant (from upstream 2026-07-09)](details/project_alpine_cluster_submission/06-user-validated-in-app--2026-08-07.md#flexibility-map--replica-package-invariant-from-upstream-2026-07-09)

<a id="patch-grid-recovery-and-physical-restraint-inheritance-2026-09-04"></a>
- [Patch-grid recovery and physical restraint inheritance (2026-09-04)](details/project_alpine_cluster_submission/06-user-validated-in-app--2026-08-07.md#patch-grid-recovery-and-physical-restraint-inheritance-2026-09-04)

<a id="r1-graphene-force-field-correction-2026-09-04"></a>
- [R1 graphene force-field correction (2026-09-04)](details/project_alpine_cluster_submission/06-user-validated-in-app--2026-08-07.md#r1-graphene-force-field-correction-2026-09-04)

<a id="small_plate-restrained-wall-barostat-audit--2026-09-05"></a>
- [small_plate restrained-wall barostat audit — 2026-09-05](details/project_alpine_cluster_submission/06-user-validated-in-app--2026-08-07.md#small_plate-restrained-wall-barostat-audit--2026-09-05)

**2026-10-20 download queue:** Completion discovery and recovery no longer await
multi-GB transfers; queued result jobs show “Finished on Alpine — waiting to download.”
API and worker admission serialize bulk downloads, deduplicate submission-scoped
requests, and preserve queued intent across reloads. Local indexing is scheduled
separately. Existing authenticated workers are preserved; their own admission
enforcement loads on the next ordinary restart. See the queue policy in
[restart recovery](../docs/alpine_restart_recovery.md).
