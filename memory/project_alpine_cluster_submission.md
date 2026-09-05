---
name: alpine-cluster-submission
description: Multiphase plan — one-click submit of NADOC MD jobs to CURC Alpine (SSH+SLURM); auto-resource decision tree with review; per-phase handoff
metadata: 
  node_type: memory
  type: project
  originSessionId: 909b50d7-8696-47a9-979c-fb67ba2f41ec
  modified: 2026-08-20T04:18:38.929Z
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
- **They are NOT billed at the A100 rate.** `ClusterProfile.su_per_gpu_hour` (108.6, A100) is
  now overridable per partition (`Partition.su_per_gpu_hour`); ah200 = 370.4, artxpro6000 = 260.4,
  scaled from the published billing weights. Without this the review card under-quoted an H200
  job ~4×. Confirm against `sacctmgr`/`sreport` when next connected.
- **Throughput is A100-anchored, and walltime is derived from throughput.** `_GPU_SPEED_FACTOR`
  in `cluster_resources.py` scales the guess per partition. This is not cosmetic: an H200 job
  that requests 2.5× the walltime it needs gets *worse* queue priority for nothing.
  `cluster_throughput.py` is keyed by cluster, partition, exact GRES, and size bucket, so a real measured ns/day
  supersedes the guess automatically after one run.
- **`gh200` is request-only** — surfaced in the popup as greyed/"request access", never as a
  submission target.

### MEASURED benchmark matrix (2026-08-07) — supersedes the guessed speed factors

Head-to-head, our own GPU-resident NAMD 3 build, identical inputs/settings per system, 4 fs HMR:

| System | ah200 (H200) | artxpro6000 (Blackwell) | al40 (Ada) | al40/ah200 |
|---|---|---|---|---|
| 2hb (~63k atoms) | 644.4 ns/day | **650.0** | 481.6 | 0.75 |
| 24hb | 38.2 ns/day | **41.9** | 23.0 | 0.60 |
| VoltronCore | 1.1 (0.0753 s/step) | 1.1 (0.0761) | 0.6 (0.1371) | 0.55 |

Four findings that changed the code:

1. **artxpro6000 ≥ ah200 on every system size, and bills 260.4 vs 370.4 SU/GPU-h.** Blackwell is the
   SU-efficient choice on *both* axes — not a trade-off. `_GPU_SPEED_FACTOR` holds both at 2.5.
   (Their ratio wanders 0.99–1.10 across the three sizes with no trend — they are equal.)
2. **al40 was underrated ~2×.** The old 0.75 reasoned from fp64, which is irrelevant to NAMD3
   GPU-resident (single precision throughout). Now `1.4`, anchored on the VoltronCore ratio.
   Mirrored in the wizard's `_LOCAL_GPU_FACTORS` (`'l40'`). This matters because al40 is *much*
   easier to get into than ah200 — underrating it pushed users onto contended partitions.
3. **A single scalar speed factor is LOSSY for al40** — see the ratio column: it degrades
   monotonically with system size (0.75 → 0.60 → 0.55). That is a memory-bandwidth story, L40
   GDDR6 ~0.9 TB/s vs H200 HBM3e ~4.8 TB/s: small systems are latency-bound and hide the gap,
   large ones are bandwidth-bound and expose it. The factor is anchored at the production end,
   so it *over-promises on small systems*. If that starts to matter, make the factor
   size-dependent rather than re-tuning the scalar. ah200/artxpro6000 show no such trend.
4. **The sm_90 binary JITs onto Ada sm_89.** al40 ran with no separate build. PTX forward-JIT
   covers the fleet; do not add per-partition builds without re-checking this.

**Single-GPU VoltronCore is not viable for production lengths**: at 1.1 ns/day a 200 ns run is
~6 months of wall-clock on the best card in the fleet. Anything at that scale needs multi-GPU,
a shorter target, or CG. The benchmark says the *hardware ranking* is right, not that the run
is affordable.

**aa100 is NOT in this table on purpose** — it is effectively unschedulable (rank ~608/621,
`squeue --start` returns N/A), so those jobs were killed rather than waited out. The 1.0 anchor
therefore rests on the earlier production measurement, not on this matrix.

**VoltronCore cost 4 crashed attempts first** (velocity-limit ×2 → missing `.enm.extra`, a CUDA
exclusion-count error → missing `.vel`), all seeding/restart-file problems, not GPU problems.

### Seeing a RUNNING cluster job in the viewport — the one-frame fetch (2026-08-07)

The 3D display was local-only: every link reads a local DCD, so a running Alpine job sat on
"Waiting for trajectory output" for its whole duration with no guard and no explanation. It could
not simply be made to stream — measured on job 3e9e2df26012 (24hb, 1.32M atoms):

| source on the node | size | grows? |
|---|---|---|
| `output/<seg>.dcd` | **2.88 GB** after ~90 min | yes, without bound |
| `output/<seg>.restart.coor` | **31.7 MB** | no — rewritten every `restartfreq` (5 000) steps |

So `backend/core/remote_live_frame.py` pulls the *restart checkpoint*, not the trajectory, and
writes it as a **one-frame DCD** at `output/<seg>.dcd` — the exact path the real trajectory will
later occupy. That path choice is the design: `_latest_display_segment`, `resolve_md_config`,
`ws.py` and `md_panel.js` are **completely unchanged**; the only missing local artefact for
`ready:true` was that one file (PSF/PDB/manifest are always local, because prep + solvation run
here before upload).

**Cadence is on-login, not on a timer, and that is forced by Duo** — NADOC can only talk to Alpine
while the user is signed in, so there is no background session to stream into. Triggers are the
`nadoc:cluster-state-change` **connect edge** (the chip re-broadcasts every 15 s, so it must be
edge-detected) and job selection. `POST /md/jobs/{id}/fetch-live-frame`.

**Three traps, all guarded, all with tests:**
1. **A one-frame DCD is ~16 MB and sails past `_segment_has_trajectory`'s 4096-byte floor**, so
   health/RMSF would have run on it — and RMSF over one frame is identically 0.0, which reads as a
   *good* measurement. Every write is recorded in `job.live_frame`; that gate now takes `job` and
   refuses a marked segment. `fetch_outputs` clears the marker when real results land, and the
   module refuses to overwrite a real trajectory with a snapshot.
2. **`mda.Writer` infers format from the file extension** — the atomic `.dcd.part` temp made it
   fail with `No trajectory or frame writer for format 'PART'`. Pass `format="DCD"` explicitly.
3. **The package ships more than one PSF** (`X.psf` *and* `X_hmr.psf`, identical atom counts). The
   frame must be written against the one the *viewer* will open, so `resolve_topology` was split
   out of `resolve_md_config` and both call it. Do not re-inline that rule.

Solute is contiguous at the head of the atom ordering (24hb: atoms 1–213 445 of 1 320 174, 16.2%,
independently confirmed by an MDAnalysis `nucleic` selection), and NAMD's binary `.coor` puts atom
*i* at byte `4 + 24i` — so a **byte-prefix fetch would give a solute-only frame for 5.1 MB instead
of 31.7 MB**. Not taken: it needs a solute-only PSF to pair with and the package only ships
solvated ones. Available if a once-per-login 31.7 MB ever feels slow.

### The progress bar between sign-ins — carried forward, never invented (2026-08-07)

`_namd_live_progress` derived the running step from `live_segment_step`, which reads the **local**
log/xsc. A cluster job writes those on the node, so the step was `None` for the entire run and the
master bar sat at **0 %** until a segment flipped to done. Fixed in two layers:

1. **Use the node's last reported step.** `_remote_projected_step` reads `job.live_metrics["step"]`
   and takes whichever of (local read, node reading) is further along — a stale local file must
   never drag the bar backwards. On the live 50M-step job this alone moved 0 % → 1.16 %.
2. **Carry it forward at the last measured rate** (`namd_metrics.projected_step`, pure) using
   elapsed wall time, because Duo means the job is unobservable while signed out.

**Anchor on NADOC's clock, not the node's.** The blob's `collected_at` is the compute node's
`time.time()`; extrapolating against our clock would turn any host/node skew into fake progress.
`apply_live_metrics` now stamps `retrieved_at` — and *only when the blob actually changed*: an
identical blob means the collector has not rewritten it, so the run HAS advanced since we first saw
that step, and re-anchoring would silently discard that progress.

**Two honesty rules, both tested:**
- **A projection never crosses 99 %** (`_MAX_PROJECTED_FRACTION`). Reaching 100 % asserts a
  completion nobody observed — the run may have crashed or hit its walltime a second after the
  last report. Verified: 7 days signed out on a 5.3-day job reads 99.00 %, not 100 %.
- **No rate → no extrapolation.** Missing/zero `s_per_step`, or a clock that went backwards,
  returns the last step unchanged. A frozen bar is honest; a fabricated one is not. A reading with
  no anchor yet is returned as a real (if stale) observation with `estimated=False`, so it is not
  hedged — only genuine projections carry the `~` and "estimated from last cluster sync".

`progress_estimated` rides on both channels (`GET /md/jobs` and `/ws/md-jobs/{id}`) from the one
shared helper, so the two can never disagree about whether a number was measured.

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

**Maintenance truth fix (2026-08-29).** The availability probe now reads
`scontrol -o show reservation` and returns active/upcoming reservations carrying SLURM's
explicit `MAINT` flag. The wizard and Cluster card show the downtime window immediately
after Alpine connects, plus the selected resource's `sbatch --test-only` next start when
available. A future SLURM start now outranks raw idle-GPU counts: before this fix, 14 idle
MIG slices were painted "free now" even though seven-day jobs `31786854` and `31796572`
both reported `Reason=ReqNodeNotAvail,_Reserved_for_maintenance` and
`StartTime=2026-09-03T06:30:00`. Physical vacancy is no longer presented as scheduler
eligibility.

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

**MIG is a counting trap, but is now a supported target.** `CfgTRES gres/gpu` sums MIG slices
with whole cards, so ah200's 8 nodes first read as **56 GPUs**. NADOC splits typed resources with
`cluster_queue.is_mig_type()` (matches `\d+g\.\d+gb`); the popup never adds slices to the
whole-GPU count and can submit an explicitly selected slice with its exact typed `--gres` token.

### Live RTX Pro 6000 MIG production benchmark (2026-08-27)

`2hb_2xT` job `da4af0483372` / Slurm `31729706` was confirmed by `scontrol` on
`c3gpu-e7-u9` with `AllocTRES ... gres/gpu:rtx_pro_6000_2g.48gb=1`, 8 CPUs and 7 GB RAM.
At step 9,955,000 (39.82 ns; 2 h 46 min scheduler runtime), the 32,868-atom, 4 fs HMR
GPU-resident production run sustained **316.521 ns/day** (1.09187 ms/step) across repeated
live samples. The matched whole RTX Pro 6000 reference, job `029a76c6a59f` / Slurm
`30964837`, measured **498.802 ns/day** (0.69286 ms/step). Thus the 2g.48gb slice retained
**63.46%** of whole-card throughput and ran **1.85x faster** than NADOC's conservative
171.139 ns/day estimate. A 500 ns trajectory projects to 37.91 h on the slice versus 24.06 h
on the whole card. Treat this as provisional until completion; full provenance is in
`experiments/exp56_namd_mig_benchmark/results/2hb_2xT_rtx_pro_6000_2g48_2026-08-27.json`.

### Re-verified live 2026-08-06 (second session, after the fixes)

- **Zero drift warnings** — the profile now matches the live partition list exactly, so the
  `acpu` rename is correct end to end.
- **Per-partition ns/day is real**: ah200 115.7 / artxpro6000 74.0 / aa100 46.3 / al40 34.7 /
  ami100 23.1 for a 63k-atom job — exactly the base guess × each `_GPU_SPEED_FACTOR`. Before
  the fix every row read an identical 221.6. `job_ns_per_day_measured: false` everywhere,
  correctly: no learned Alpine throughput exists for this size bucket yet.
  **Those five numbers are now stale** — they predate both the `_GPU_NSDAY_ATOM_CONSTANT`
  recalibration (2.9e6 → 4.5e6) and the measured artxpro6000/al40 factors above. The *point*
  they were recorded to make (per-partition scaling reaches the popup at all) still stands;
  the magnitudes do not. Re-read them from the live popup, not from here.
- **Time-to-result ordering does its job**: ami100 is *free right now* yet ranks 3rd (168 h)
  because it is slow, behind ah200 (62 h) and artxpro6000 (136 h). Starts-first ≠ finishes-first.
- **Cost is closer than the rate suggests**: ah200 21,286 SU vs aa100 18,081 SU — ~18% more in
  total, not 3×, because the faster card holds the allocation for far less time.

### Known gap — a clamped walltime reads as a completion time

ami100's "done in 168 h" is the `gpu-long` ceiling, not a real finish: `recommend()` clamped
the walltime and recorded a note saying the run will need resume-from-checkpoint. The
availability row does not surface that note, so a clamped row looks like a slower-but-viable
option instead of one that cannot finish in a single submission. Same family as the four wait
bugs fixed above; not yet fixed.

### GPU-resident NAMD on Alpine: there is no module, you must build it (2026-08-07)

**The failure.** SLURM 30948986 (24hb_0xT) died instantly: `Lmod ... The following
module(s) are unknown: "namd/3.0.1_gpu"`. That string was never real — the profile comment
said outright it was a guess from the `_cpu`→`_gpu` convention. July's jobs worked because
they were CPU; this was the first GPU submission, so the guess was exercised for the first
time. Cost: an 814 MB upload and a queue wait to learn about a typo.

**Live cluster facts (probed 2026-08-07 — do not re-derive):**

| | |
|---|---|
| NAMD modules | `namd/2.14`, `namd/3.0.1_cpu` — **no CUDA build exists** |
| OS / glibc | RHEL 8.10, **glibc 2.28** |
| CUDA modules | 11.2, 11.3, 11.4, 11.8, **12.1.1** (newest) |
| GCC modules | 10.3.0, 11.2.0, 13.2.0, 14.2.0 |
| FFTW | 3.3.8 / 3.3.9 / 3.3.10 |

**Three consequences, each load-bearing:**
1. **A desktop binary cannot be uploaded.** The local Dec-2025 build needs GLIBC_2.38 vs
   Alpine's 2.28. Not a near miss — building on the cluster is mandatory.
2. **CUDA 12.1.1 caps the targets.** sm_80 (aa100) ✓, sm_89 (al40) ✓, **sm_90 (ah200) ✓**,
   but **sm_120 (artxpro6000, Blackwell) needs CUDA ≥ 12.8 → cannot be targeted at all**.
   ah200 is therefore the GPU target, which is also the fastest and least contended.
3. **nvcc 12.1 rejects GCC > 12.2**, so the profile's `gcc/14.2.0` cannot build CUDA. Use
   **`gcc/11.2.0` + `cuda/12.1.1`** — and per CURC's own rule the sbatch must load the same
   set, so `gpu_module_loads` must match the build exactly.

**CURC endorses building** ("begin a compile job by using the `acompile` command"); nothing
discourages user-built software. `acompile` has no GPUs (4 cores/12 h) — fine, `nvcc`
cross-compiles — so NADOC submits the build as a normal `acpu` batch job instead, which
survives disconnection and logs.

**What was built for this** (all tested, `main.js` untouched):
- `ClusterProfile.namd_bin` / `gpu_namd_bin` + `namd_command(gpu)` — a private build is
  addressed by absolute path since it is on no module's PATH. Reaches both the real sbatch
  and the wizard preview; the "CPU-looking module" warning self-suppresses for private paths.
- **Submit pre-flight** (`md_executor.submit_job`): `module load … && command -v <namd>` on
  the LOGIN node before staging. Catches both a bad module and a module set that loads fine
  while leaving no `namd3` — Alpine's normal state for GPU. Fails in ~2 s with nothing uploaded.
- `list_namd_modules` now loads a compiler first and falls back to `module spider`: Alpine's
  Lmod is **hierarchical**, so the old bare `module avail namd` returned EMPTY precisely when
  it was needed.
- `GET /cluster/probe` — read-only, a **named registry** (`os`, `modules`, `cuda-compilers`,
  `gpu`, `squeue-mine`, `job`, `sinfo`), not an allowlist over free text; `arg` validated to
  `[A-Za-z0-9_.+/-]{1,64}`. A test asserts every probe is non-mutating.
- `backend/core/cluster_build.py` + `POST|GET /cluster/build/namd` — packs the source
  (dropping the local build tree and `.git`: 618 MB → 89 MB), uploads, and submits a
  generated build script. Also not a shell: every module/gencode/name is validated and
  writes are confined to `<project_base>/nadoc_builds/<name>`.

**When the build lands**, it is a two-line `workspace/clusters.json` edit:
`"gpu_namd_bin": "<build_dir>/<src>/Linux-x86_64-g++/namd3"` and
`"gpu_module_loads": ["gcc/11.2.0", "cuda/12.1.1"]`.

### Owed — needs the user present for Duo

**Items 1–3 are DISCHARGED (2026-08-07).** ~~Confirm the GPU NAMD module on ah200~~ — moot: no
CUDA NAMD module exists on Alpine at all, so we build our own and point `gpu_namd_bin` at it.
~~One real ah200 submission~~ — done many times over: the whole benchmark matrix plus the 24hb
production run (SLURM 30958617). ~~In-app exercise of the popup and the wizard's new first step~~
— **user-confirmed in app 2026-08-07, all features pass** (see below).

1. **CPU QoS names are docs-derived**, not live-tested by sbatch. The GPU half of the same docs
   table was live-confirmed, which is good corroboration, but `cpu-normal` has not been submitted.
   Untouched by the 2026-08-07 validation — that exercised the GPU/display path only.

### User-validated in app — 2026-08-07

Every feature of this arc was hand-exercised by the user and **all pass**:

- GPU-availability popup; wizard step 1 "Where it runs" (local probe, Alpine partition table with
  wait/speed/SU, node selection) and the step-3 SLURM inspection block.
- Submit review: close-on-submit + double-submit guard; upload/prepare progress and stages.
- Cluster-chip ⇄ wizard state sync; the availability button's disabled reason when signed out.
- Live metrics on a running job, **including ns/day** (the `days/ns`-only regex fix).
- Health card populating on reconnect.
- One-frame display fetch for a running Alpine job, and its "Snapshot at step N" label.
- Progress bar carried forward while signed out, re-anchoring on sign-in.

So this feature set is **no longer manual-validation debt**; see `manual_validation_debt.md`
(`MV-ALPINE-GPU`). What that validation does *not* cover: the CPU-partition path above, and
`just smoke` (the console-error gate) still never ran — it stayed blocked by a running NAMD
production job throughout.

**Editing `backend/**` drops the SSH session** — uvicorn `--reload` watches `backend` and
`scripts` only, and the asyncssh connection lives in that process. `memory/**` and
`workspace/**` are excluded, so profile-JSON and memory edits are safe mid-session. Batch
backend edits, then reconnect once.

---

### Result download is a separate, verified lifecycle (2026-08-09)

SLURM completion and local result availability are deliberately independent. `MdJob.download_status`
persists the exact remote `relative path -> byte size` inventory, verified/transferred byte counts and
file counts. The unified Jobs card says **Download complete** only after every local file matches that
inventory; a browser reload or expired Duo session cannot invent success. For older jobs that predate
the per-file inventory, exact aggregate bytes plus exact file count are the conservative offline proof.

Every entry point (automatic completion reconciliation, Stop, Fetch remote, End run and download) goes
through one per-job async lock plus an advisory filesystem lock. This covers concurrent routes, dev-server
reload overlap and multiple backend processes. Downloads use `.part`, resume by exact byte offset and
atomically rename only after fsync + size verification. The offline verifier never touches a job whose
transfer state is `downloading`; after interruption it may promote an exact-size `.part` without Alpine.
Filesystem/permission errors fail the file operation but do **not** expire a healthy SSH/Duo session.

Byte verification is followed by a separately persisted `processing` phase while NADOC reads the fetched
trajectory to compute final health and metrics. This pass can take minutes for a multi-GB DCD. The unified
Jobs card keeps a striped 100% bar visible, says **Download verified — processing trajectory health and
metrics…**, and disables the action as **Processing…** until bookkeeping finishes. Browser refreshes and
offline verification preserve this state; successful finalization returns it to `verified` and marks the
job/segment complete.

Size authority follows the lifecycle: live remote heartbeat bytes while the job is active; actual local
directory size after download; verified inventory totals in the transfer UI. Directory-size caches are
invalidated after a transfer. This prevents a terminal card from retaining the last-running remote size.

Remote minimisation also participates in progress: node metrics carry the real minimisation step, successive
samples derive seconds/step when NAMD emits no TIMING record, and the card shows step/total, percent and ETA.
For a deliberately ended production, downloaded XST/restart markers supply actual completed steps and the
conf supplies the real timestep. The stage row reports actual ns (SLURM 30958617: **65.97 ns**) and renders
the green completion check because the job is marked complete, rather than claiming its requested 200 ns ran.

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

### Patch-grid recovery and physical restraint inheritance (2026-09-04)

`small_plate` job `d882c98ac759` / Slurm `32086330` completed minimization but failed
in the first NPT settle stage with `Periodic cell has become too small for original
patch grid!`, before its first 5,000-step checkpoint. Alpine now stages
`remote_cell_recovery.py` and `remote_resume_conf.py` on both Submit and Resume.
The generated sbatch retries this exact failure within the allocation, rebuilding
from a validated checkpoint and remaining steps; one gentler pre-checkpoint retry is
allowed. Retries are bounded and reject stalled checkpoints or >15% cumulative volume
loss. Physical restraints and integrator choices persist. No scheduler auto-resubmission.

The same audit fixed harmonic anchors becoming hard fixed atoms in appended production,
inherited harmonic settings for production children, and graphene-only controls acquiring
an NPT barostat after their NVT relaxation. Details and verification limits are in
[the audit](../docs/namd_alpine_failure_audit.md). The failed job has not been resubmitted.

## R1 graphene force-field correction (2026-09-04)

R1 `0a2aaa5638ff` / Slurm `32088967` failed at k=0.1 step 14: unbonded
graphene CA sites experienced enormous mutual LJ repulsion at 1.42 Å. New
packages use dedicated NGRC sites with CA cross LJ and zero NGRC–NGRC NBFIX
in `par_np_thiol.prm`. Geometry, anchor stiffness and 4 fs timestep are unchanged.
`namd_graphene.validate_graphene_wall_package` blocks legacy wall packages before
Alpine submit/resume, local execution and RunPod provisioning. Copy + Run must
rebuild and minimize; old graphene checkpoints are not reusable. Copy remains an
editable draft and does not prepare or submit. See `docs/namd_graphene_wall_failure_audit.md`.

## small_plate restrained-wall barostat audit — 2026-09-05

Slurm `32089399` (`7aa73d7afe93`) failed after a successful k=0.1 recovery:
recovery had slowed the piston to 10000/5000 fs, but k=0.01 reset it to
1000/500 fs. Local 4 fs replays reproduce alternating, amplifying cell/pressure
oscillations within 12 steps, driving graphene restraint energy from 34.8k to
752M kcal/mol before the exclusion fatal. Margin 4, GPU offload, and retaining
k=0.1 all fail. Changing only the piston to 10000/5000 fs passes 5000 steps.
This is independent of the earlier corrected graphene self-LJ defect.

Restrained graphene NPT config composition now keeps at least 10000/5000 fs
across relaxation, appended production and replica production; NVT stays NVT.
See [audit](../docs/namd_graphene_barostat_failure_audit.md). The failing job's
intact pre-failure checkpoint can be used with the corrected piston; unlike the
self-LJ fix, this does not require rebuilding or reminimization. An isolated
continuation is under `experiments/namd_32089399_diagnosis/recovery_package`.
The backend was preserved during diagnosis, then restarted by the user before the
new copy was prepared. On September 5 at 21:11 UTC, copy `e75ffd56c6f8` was verified
as SLURM `32108809`, RUNNING on `c3gpu-g7-u5`. All 75 package inputs transferred
successfully and all 22 active NPT configs retain 10000/5000 fs. Full-ladder stability
is still unverified. See [upload audit](../experiments/namd_e75ffd56c6f8_upload_audit/README.md).
