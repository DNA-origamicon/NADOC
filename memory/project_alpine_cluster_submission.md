---
name: alpine-cluster-submission
description: Multiphase plan — one-click submit of NADOC MD jobs to CURC Alpine (SSH+SLURM); auto-resource decision tree with review; per-phase handoff
metadata: 
  node_type: memory
  type: project
  originSessionId: 909b50d7-8696-47a9-979c-fb67ba2f41ec
---

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

## Status tracker

- [x] **Phase 1** — Cluster config + SSH transport + connect UI (de-risk Duo auth)
- [x] **Phase 2** — SLURM script generation + auto-resource decision tree (pure logic)
- [x] **Phase 3** — Remote executor: submit / poll / fetch / cancel (wire it together)
- [x] **Phase 4** — Frontend: run-target selector + auto-with-review card + remote monitoring
- [x] **Phase 5** — Hardening: learned ns/day ✓, session-expiry UX ✓, live progress ✓ (increment 9);
  auto-resubmit → **user-driven one-click Resume from mid-segment checkpoint** ✓ (increment 10). See
  the "Resume model (2026-07-03 pivot)" block below before touching resume logic. Live-validation of
  the actual Resume round-trip still needs a real short-walltime timeout + Duo.
- [x] **Ensemble production replicas** (2026-07-07) — see "Ensemble production" block below.
- [x] **In-sbatch relaxation early-stop (Tier B + Tier A)** (2026-07-07) — see "In-sbatch early-stop" block below.

## Key architecture decisions (read before Phase 1)

1. **Whole-ladder single sbatch, NOT per-segment submission.** The remote job is
   ONE `sbatch` script that runs the entire segment chain (minimize → all
   ENM-release segments → optional production) on the compute node, exactly like
   NAMDRunner. NADOC polls `squeue`/`sacct` for status and fetches outputs.
   - *Why not per-segment?* NADOC's local runner orchestrates one segment at a
     time (health check between). Re-queuing each segment on a scheduler stacks
     hours of queue latency per segment — unacceptable. A single job avoids that.
   - *What we lose:* between-segment control flow. **Nothing, in practice** — the
     health gate is already **advisory-only** (removed as control flow 2026-06-25,
     see [[md-job-system]]). Health is display metadata, computed *after* fetching
     `health.jsonl`/restart coords back to the login node / locally. So a single
     remote job loses no behavior we still rely on.

2. **Local execution path stays byte-for-byte unchanged.** We do NOT rewrite
   `run_job`/`_run_namd_async`. The seam is a **branch at `start_job` / `stop_job`
   / `reconcile_job_status` on a new `MdJob.execution_target` field** (`"local"`
   default vs `"alpine"`). All remote logic lives in new modules. This is the
   low-risk seam the repo philosophy wants ("modify existing > new module > never
   a fat block"), not a deep executor rewrite.

3. **GPU by default.** NADOC's local pipeline is CUDA and NAMD3 GPU-resident is
   far faster; target Alpine's `aa100` (A100) partition + a GPU NAMD module by
   default, CPU (`amilan`) only as fallback. (NAMDRunner used the CPU build — we
   diverge here deliberately.)

4. **Credentials live in backend memory only, never on disk.** Password + Duo held
   for the session; on expiry the UI shows "Reconnect". No key files (CURC
   disables SSH keys — see Appendix).

---

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


> **History.** Phase 1–5 build detail, in-sbatch early-stop, ensemble production, run logs + the appendix live in [project_alpine_cluster_submission_archive.md](project_alpine_cluster_submission_archive.md). Read on demand only.

### Flexibility-map / replica-package invariant (from upstream 2026-07-09)

- **Flexibility-map fix (2026-07-09)**: a replica production package must ALSO carry
  `charge_audit.json` (the segid→NADOC-chain map). `build_replica_package` originally
  hardlinked only PSF/PDB/forcefield/hmr, so `load_segid_chain_map` fell back to the
  reference-PDB P-order — which can't build the 21 phosphate-less 5'-termini specs → those
  bases rendered un-positioned/un-coloured in the Flexibility map (RMSF returned 1307/1328
  keys). Fix = two layers: (A) `build_replica_package` now `_link_or_copy`s
  `charge_audit.json`; (B) `load_segid_chain_map` falls back to `manifest.json`'s embedded
  `charge_audit` field when the standalone file is absent (fixes replicas already on disk —
  the child manifest already carries the map). Verified on prod job `6d7c2e38e455`: RMSF
  route now returns 1328/1328. See LESSONS A10.

