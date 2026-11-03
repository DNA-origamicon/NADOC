# `GET /api/cluster/availability` — the popup's data — supporting detail

[Topic head](../../project_alpine_cluster_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
