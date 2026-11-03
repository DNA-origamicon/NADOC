# Alpine GPU fleet (2026-08-06) + the availability popup — supporting detail

[Topic head](../../project_alpine_cluster_submission.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
