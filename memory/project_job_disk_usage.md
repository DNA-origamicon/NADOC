---
name: job-disk-usage
description: "Welcome-screen \"Data on disk\" column + Help ▸ About-this-file panel + per-job sizes"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1f766f1d-28a3-4726-8d47-59748bd2677c
---

On-disk size accounting for designs and their simulation data (added 2026-06-24).

- `backend/core/design_disk_usage.py` — read-only accounting: `dir_size_bytes`
  (stat-only walk, ~ms even for 27 GB), `sim_bytes_by_source_path` (groups
  MD+oxDNA job bytes by the job's `design_source_path`, reusing the [[job-archive]]
  / job_cleanup linkage), `jobs_for_source_path`, `assemblies_referencing`.
- `GET /api/library/files` now adds `sim_bytes` + `disk_bytes` per part → welcome
  screen `library_panel.js` shows a "Size" column (sortable; sim-carrying designs
  highlighted amber, tooltip splits file vs sim).
- `GET /api/design/about?path=…` (in routes_assembly_workspace.py) aggregates total
  bases, strands/helices, loadouts + features-per-loadout, MD+oxDNA jobs with sizes,
  and assemblies using the part. Topology from the live active design, else loaded
  from `path` on disk, else `{empty:true}`. Help menu "About this file…" →
  `ui/about_file_modal.js`.
- Shared byte formatter: `frontend/src/ui/format_bytes.js` (B→TB; unit-tested).
- Per-job `size_bytes` is added in the `/api/{md,oxdna}/jobs` list routes and shown
  in each job row (see [[job-archive]]).

Real workspace at creation time: 18hb carried 42.7 GB of sim data, 6hb_84bp 10.5 GB
— the column's whole point (spotting designs hogging disk before archiving them).

## Pre-run forecasting names its volume (2026-07-30)

Accounting above is *after the fact*; the **forecast** side lives in
`backend/core/disk_guard.py` and now reports which disk it measured:
`forecast()` returns `target_dir` + `volume` (`volume_root()` → real mount point).
An **archived** job's `package_dir` resolves onto its external drive, so "12 GB free"
was ambiguous between the system disk and the archive drive; `diskWarningMessage`
prints the volume when present. The relax route `estimate-disk` also measures
`run_dir` instead of always the workspace.

Separately, `bigRunSummary` / `confirmBigRunOk` (`ui/job_activity.js`) confirm any run
over `BIG_RUN_BYTES` (10 GB) **or** `BIG_RUN_HOURS` (24 h) — this fires on a roomy
drive where the low-space warning never would. See [[md-job-system]] for the
production-cap context and the worked 1 µs example.
