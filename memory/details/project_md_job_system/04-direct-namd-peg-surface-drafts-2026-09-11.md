# Direct NAMD PEG surface drafts (2026-09-11) — supporting detail

[Topic head](../../project_md_job_system.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

- Remote campaign update: initial RunPod PRO 4500 pod terminated after tar ownership
  failure ($0.035398); fixed `--no-same-owner` and reused verified archive. Current
  pod `smsmj10f1fr4p4` is RTX 4090 at $0.74/hour, force/energy/restart probes pass,
  40 ns running (~750 ns/day). User $5 total cap includes prior attempt; provider
  expiry 2026-09-14T22:02:58Z + independent watchdog. Alpine remains running ~850
  ns/day. Both hardware duplicates' input/config equality audited against local run.
  Proof logs fetched onto Archive. Campaign README has current platform/budget details.
- Electrode cleanup (2026-09-14): 24 previous jobs / 3.53 GB moved to
  `/media/jojo/Archive/NADOC_electrode_history/2026-09-14/jobs`. All data preserved.
  Eight ancestors remain in the archive index; 16 other trial entries retired from
  the catalogue (restore script/catalogue manifest in that archive). Three current
  40 ns jobs remain under workspace/md_jobs and running. 199 probe/benchmark
  symlinks and 16 analysis job lists repointed; gpu_screening.py source resolution
  is now archive-aware. Historical raw snapshots/log paths remain provenance; use
  archive move_manifest.json for translation. See docs/namd_electrode_archive.md.

- 2026-09-14 remote 40 ns result processing: both Alpine and RunPod native runs
  completed normally at 10M steps. User configured podless S3; RunPod 9.32 GB/36
  files retrieved, 20k DCD frames verified, job outputs marked verified. Compute
  total $1.074943 including cancelled transfer pod. Screening fit 0.551 nm vs
  central-salt classical 0.539 nm (ε=78.3); local reference 0.553 nm. Window/block
  sensitivity and limitations in electrode_remote_40ns_20260914/RESULTS.md.
  Alpine trajectory retrieval + cached analysis + job/report publication continue
  via process_results.py, resume_cached_analysis.py, publish_alpine_results.py.
  Missing local campaign status fixed; corrupted Alpine job.json trailing brace
  backed up/repaired and old overlapping monitor stopped. No broad save-lock fix.

- Alpine result processing subsequently completed: 47 files/9.344 GB SHA256 verified,
  20k frames analyzed, job download state verified. Full fit 0.575 nm versus
  classical 0.541; last 20 ns 0.547 nm, with a decreasing 10 ns-window trend.
  docs/namd_debye_assessment.md summarizes campaigns, literature and remaining
  timestep/dielectric/metal-response validation. No new dynamics in this assessment.
