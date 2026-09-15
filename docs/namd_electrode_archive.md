# Historical electrode jobs archived — 2026-09-14

Moved **24 prior NAMD electrode jobs, 3.53 GB**, from `workspace/md_jobs` into:

[/media/jojo/Archive/NADOC_electrode_history/2026-09-14/jobs](/media/jojo/Archive/NADOC_electrode_history/2026-09-14/jobs)

The [archive inventory and restore instructions](/media/jojo/Archive/NADOC_electrode_history/2026-09-14/README.md)
list each experiment, creation time, outcome and folder. All 17 completed runs,
five failures and two stopped attempts were preserved, including full available
trajectories, checkpoints, configurations and logs. No scientific data was discarded.
The workspace was already backed by the Archive disk; this organizes historical
files outside the active workspace rather than reclaiming system-disk capacity.

Eight checkpoint ancestors remain indexed as archived jobs so the active runs'
parent chains still resolve. The other 16 historical entries were retired from the
active catalogue but remain fully restorable without copying their data back.
The three current 40 ns jobs (local, Alpine and RunPod) remain in place and running.
Only those three electrode job directories remain directly in `workspace/md_jobs`.

Analysis campaign `jobs.json` files now point to the archived packages, and 199
benchmark/probe symlinks were repaired. Archived package location metadata was
updated; original records are backed up under the archive's `reference_backups`.
Historical logs and API snapshots retain their old paths as provenance; consult
`move_manifest.json` to translate them. The screening preparation helper now
resolves its source through `MdJob.package_dir()` so archived seeds remain usable.

[Integrity verification](/media/jojo/Archive/NADOC_electrode_history/2026-09-14/verification.json)
records file checksums, metadata updates, catalogue checks, readable archived DCDs,
and the status of the three protected live jobs.
