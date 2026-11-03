# Status tracker — supporting detail

[Topic head](../../project_alpine_cluster_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Status tracker

- [x] **Phase 1** — Cluster config + SSH transport + connect UI (de-risk Duo auth)
- [x] **Phase 2** — SLURM script generation + auto-resource decision tree (pure logic)
- [x] **Phase 3** — Remote executor: submit / poll / fetch / cancel (wire it together)
- [x] **Phase 4** — Frontend: run-target selector + auto-with-review card + remote monitoring.
  **Superseded in part (2026-08-07): the review card no longer auto-opens.** Its resources
  (cores / wall time / memory / GPUs / QoS) now live in the Job Wizard's step 1, beside the
  partition table and autopopulated from the design's estimated size; the card survives only
  for the manual **Submit to Alpine**, Resume and Ensemble. See "The SLURM resources moved
  INTO step 1" in [[md-job-system]] for the full shape (sparse `slurm_resources` →
  `MdJob.requested_resources` → `_merge_requested`).
- [x] **Phase 5** — Hardening: learned ns/day ✓, session-expiry UX ✓, live progress ✓ (increment 9);
  auto-resubmit → **user-driven one-click Resume from mid-segment checkpoint** ✓ (increment 10). See
  the "Resume model (2026-07-03 pivot)" block below before touching resume logic. Live-validation of
  the actual Resume round-trip still needs a real short-walltime timeout + Duo.
- [x] **Ensemble production replicas** (2026-07-07) — see "Ensemble production" block below.
- [x] **In-sbatch relaxation early-stop** (2026-07-07, detail archived) — **retired the Tier A/B split
  entirely (2026-08-21)**, see [[project_declash_reaudit]]'s early-stop section. No more restraint-scale
  eligibility gate and no energy-only mode: every non-final relaxation chunk on Alpine/RunPod now gets
  the real on-node WC health step + the same `should_early_stop_stage` (energy AND WC) test the local
  runner uses — byte-for-byte parity, not an approximation. Also fixed in the same pass: the staged
  `md_health.py` copy's `identify_unpaired_residues`/sidecar helpers were moved INTO `md_health.py` from
  `md_protocols` (a cross-module import that silently failed standalone on the node, returning an empty
  ss-exclusion set every time — caught by `_unpaired_exclusion_set`'s own `except Exception: return set()`,
  so it never crashed, just silently used the wrong candidate pool). `MdJob.load()` now drops any
  dataclass field the current schema no longer declares (`tests/test_md_job_schema_evolution.py`) — the
  first-ever MdJob field REMOVAL, needed so `early_stop_tier` still on old job.json files (including the
  real archived `bb8654eef459` / 24hb_2xT) doesn't crash loading.

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
   - **Amended 2026-08-06: the default is now `ah200` (H200), not `aa100`.** aa100 is
     saturated — a live `sbatch --test-only` put its start 13 d 16 h out against an
     immediate ah200 start (table below). CPU fallback is `acpu`, not `amilan`.
     Partition choice is otherwise informed by the **GPU availability popup** (live
     free GPUs, queue depth, time-to-result). Auto-selecting the best partition at
     submit time was deliberately NOT built — the popup informs, the user picks.

4. **Credentials live in backend memory only, never on disk.** Password + Duo held
   for the session; on expiry the UI shows "Reconnect". No key files (CURC
   disables SSH keys — see Appendix).

---
