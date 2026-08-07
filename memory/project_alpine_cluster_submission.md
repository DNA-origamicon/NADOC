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

## Alpine GPU fleet (2026-08-06) + the availability popup

Source: [CURC alpine-hardware docs](https://curc.readthedocs.io/en/latest/clusters/alpine/alpine-hardware.html),
**reconciled against the live cluster 2026-08-06** via `scontrol show node` + `sbatch --test-only`.

**Live partition list (ground truth, 2026-08-06):** `aa100, acompile, acpu, ah200, al40, amem,
ami100, artxpro6000, atesting, dtn, gh200`.

| Partition | GPU | nodes | GPUs/node | cores | RAM/core | GRES token | QoS | billing/core |
|---|---|---|---|---|---|---|---|---|
| `aa100` | NVIDIA A100 | 12 | 3 | 64 | 3.8 GB | `a100-40gb`, `a100_80gb` | gpu-normal/long/**testing** | 6.13 |
| `ami100` | AMD MI100 | 8 | 3 | 64 | 3.8 GB | `mi100` | gpu-normal/long/**testing** | 6.13 |
| `al40` | NVIDIA L40 | 3 (Anschutz) | 3 | 64 | 3.8 GB | `l40` | gpu-normal/long | 6.13 |
| **`ah200`** | NVIDIA H200 | 8 (CUB) | 4 | 128 | 12 GB | `h200` (+MIG `h200_3g.71gb`, `h200_2g.35gb`) | gpu-normal/long | **12.63** |
| **`artxpro6000`** | NVIDIA RTX Pro 6000 | 8 (CUB) | 4 | 128 | 12 GB | `rtx_pro_6000` (+MIG `_2g.48gb`, `_1g.24gb`) | gpu-normal/long | **9.13** |
| `gh200` | Grace-Hopper | 2 | 1 | 72 | 6.65 GB | `gh200` | `gh200` (7 d, 1 job) | ~2× A100 |

**Traps this encodes** (all now covered by tests):
- **`ah200`/`artxpro6000` have NO `gpu-testing` QoS.** Offering it produces a rejected sbatch.
  That's why `allowed_qos` is per-partition, not per-kind.
- **They are NOT billed at the A100 rate.** `ClusterProfile.su_per_gpu_hour` (108.2, A100) is
  now overridable per partition (`Partition.su_per_gpu_hour`); ah200 ≈ 334, artxpro6000 ≈ 242,
  scaled from the published billing weights. Without this the review card under-quoted an H200
  job ~4×. Confirm against `sacctmgr`/`sreport` when next connected.
- **Throughput is A100-anchored, and walltime is derived from throughput.** `_GPU_SPEED_FACTOR`
  in `cluster_resources.py` scales the guess per partition. This is not cosmetic: an H200 job
  that requests 2.5× the walltime it needs gets *worse* queue priority for nothing.
  `cluster_throughput.py` is keyed `cluster:partition:bucket`, so a real measured ns/day
  supersedes the guess automatically after one run.
- **`gh200` is request-only** — surfaced in the popup as greyed/"request access", never as a
  submission target.

### `workspace/clusters.json` shadows the embedded profile — edit BOTH

`cluster_config.load_profiles()` **overwrites the whole `alpine` entry** with the JSON on disk.
A partition added only to `alpine_profile()` in Python is invisible to the running app. There is
now a drift guard: `test_cluster_config.py::test_workspace_clusters_json_has_not_drifted_from_the_embedded_profile`
fails if the GPU targets go missing or a shared partition's kind/gres/QoS diverges.

### `GET /api/cluster/availability` — the popup's data

`backend/core/cluster_queue.py` (pure parsers + one async probe) → `routes_cluster.py`.
Read-only: `scontrol -o show node`, `squeue -t PD`, `sacct`, and `sbatch --test-only`
(validates + predicts a start time **without submitting**). Probe cached 60 s in-process;
each command capped at 20 s; commands run sequentially because `ClusterConnection` serializes
on one lock and asyncssh ops must stay on the uvicorn loop the connection is bound to.

**Three wait signals, kept separate so the UI can show provenance** — the estimate is a range
with a stated basis, never one confident number:
1. `free now` — idle GPUs from `scontrol`. Only claims "starts now" when *nothing is pending*;
   free GPUs behind a backlog are already spoken for. Drained/down nodes' GPUs are excluded.
2. `SLURM backfill estimate` — `sbatch --test-only` for the real job shape. **`None` means
   UNKNOWN, never zero** — SLURM only answers when backfill could place the job.
3. `median of N recent jobs` — `sacct` (Start − Submit). Falls back from `-a` (cluster-wide) to
   own-jobs-only where the site restricts it, and the popup labels which one it got.

Rows sort by **time-to-result** (wait + runtime at that partition's throughput), not by wait —
a faster GPU that starts later often finishes first. Both axes are shown (SU cost and ns/day)
per [[feedback-gpu-value-is-two-axes]].

Frontend: `ui/cluster_availability.js` (factory) + `ui/cluster_availability_rows.js` (pure,
tested), button + mount `#md-jobs-alpine-availability` in the Clusters card, wired from
`md_jobs_panel.js` — **`main.js` LOC Δ = 0**. Polls only while the popup is open AND the tab is
visible, 60 s, with an in-flight guard.

### `amilan` → `acpu`: CONFIRMED RENAMED (2026-08-06)

`scontrol show node` reports **no `amilan` and no `amilan128c`**. They became **`acpu`**, and the
QoS were renamed with them: `normal`/`long` → **`cpu-normal`/`cpu-long`**, `mem` →
**`mem-normal`/`mem-long`**. Every CPU submission — including the **ensemble replica path, which
hardcoded `amilan` in three places** (`routes_md.py` Field defaults, `md_submit_review.js`,
`md_jobs_panel.js`) — was therefore being rejected at sbatch. All renamed.

`ClusterProfile.qos_for()` now tries `<kind>-<tier>` for **both** kinds (was gpu-only), so CPU
resolves to `cpu-normal`. The bare `normal`/`long`/`mem` tiers were deleted from the profile —
they no longer exist on Alpine. `GET /cluster/availability` warns whenever a profile partition is
absent from the live cluster, so the next rename surfaces immediately instead of at sbatch time.

### Live-measured queue reality (2026-08-06, 63k-atom / 200 ns job)

`sbatch --test-only` predicted starts — this is why the default moved:

| partition | predicted start | whole GPUs free | pending |
|---|---|---|---|
| **ah200** | **immediately** | 6/16 (+25/40 MIG) | 2 jobs |
| ami100 | immediately | 6/12 | 0 |
| artxpro6000 | ~1 d 13 h | 0/12 (+39/48 MIG) | 33 jobs |
| al40 | ~5 d 5 h | 0/9 | 4 jobs |
| **aa100** | **~13 d 16 h** | 0/30 | **630 jobs / 644 GPUs** |

**`default_partition` moved `aa100` → `ah200`.** aa100 is saturated (630 queued jobs); ah200 costs
~3× per GPU-hour but runs ~2.5× faster and starts now, so SU-per-ns is comparable while wall-clock
is not close. Note ah200 has **no `gpu-testing`** — a 1-hour smoke test must still use aa100/ami100.

### Live GRES tokens (confirmed)

`aa100`: `a100-40gb`, `a100_80gb`, `a100_3g.20gb`(MIG) · `ami100`: `mi100` · `al40`: `l40` ·
`ah200`: `h200`, `h200_2g.35gb`(MIG), `h200_3g.71gb`(MIG) · `artxpro6000`: `rtx_pro_6000`,
`rtx_pro_6000_1g.24gb`(MIG), `rtx_pro_6000_2g.48gb`(MIG). All profile `gres_type` values correct.

**MIG is the trap.** `CfgTRES gres/gpu` sums MIG slices with whole cards, so ah200's 8 nodes first
read as **56 GPUs**. NADOC requests `--gres=gpu:h200:1` — a whole card — so free slices are
unusable capacity. `cluster_queue.is_mig_type()` (matches `\d+g\.\d+gb`) splits them; the popup
shows slices on a separate sub-line, never added to the whole-GPU count.

### Owed — needs the user present for Duo

1. **Confirm the GPU NAMD module on ah200.** `gpu_module_loads` is still `namd/3.0.1_gpu`;
   Hopper (sm_90) may need a newer CUDA build, and this is now the DEFAULT partition. `GET
   /api/cluster/namd-modules` lists what's there. **Highest-value remaining check.**
2. **One real ah200 submission** end-to-end — nothing has actually run on the new default.
3. **In-app exercise of the popup** — the button/modal has never been clicked in a browser
   (`just smoke` was blocked by a running NAMD production job).
4. **CPU QoS names are docs-derived**, not live-tested by sbatch. The GPU half of the same docs
   table was live-confirmed, which is good corroboration, but `cpu-normal` has not been submitted.

---

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

