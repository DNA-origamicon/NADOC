# Welcome library performance

The welcome screen deliberately paints its file tree in stages so a large
workspace does not delay the first useful UI.

## Loading sequence

1. `ui/library_panel.js` reads `nadoc:library-files:v1` from `localStorage` and
   renders the last successful listing immediately.
2. `GET /api/library/files` returns current `.nadoc` / `.nass` metadata and
   folders. This walk prunes engine-owned simulation trees.
3. `GET /api/library/disk-usage` returns simulation bytes keyed by normalized
   design path. The frontend merges these values into the visible rows without
   blanking or rebuilding the loading state first.

Network failure leaves a cached or already-rendered tree visible. A generation
counter prevents an older refresh from overwriting a newer one.

## Identity migration

Legacy duplicate design identities still receive the same whole-workspace
reconciliation, but it is not part of the listing response. The first library
request schedules one deduplicated background audit per workspace/backend
process. Opening a `.nadoc` continues to reconcile that file authoritatively.

Any migration write uses a temporary sibling plus `os.replace`, so a concurrent
open can see either the old complete JSON or the new complete JSON, never a
partially-written file.

## Simulation directories

The metadata walk returns an engine-owned root folder so the existing “show sim
folders” option remains meaningful, but it does not descend into job/run
contents. These trees can contain thousands of trajectory and checkpoint files
that are irrelevant to the design-file tree.

The pruned root names must stay aligned with `frontend/src/ui/sim_folders.js`.
Names ending in `_jobs` are also pruned by convention.

## Validation results (2026-11-02)

The metadata walker uses `os.scandir` and checks root exclusions once instead of
repeatedly constructing and relativizing paths for every nested entry. Under the
top-level `validation` directory it discovers `.nadoc` / `.nass` files at any
depth, but only stats and returns folders that are ancestors of those documents.
Result-only folders are omitted; ordinary empty user folders remain visible.
No files are moved, rewritten, or deleted, and every refresh discovers additions
and removals without a stale listing cache.

On the current workspace this reduced the response from 3,624 entries to 222,
preserving all 204 parts/assemblies (including the three validation parts).
Standalone listing time fell from 0.69–0.70 s to 0.10–0.11 s. Live request timing
remained variable; this does not establish the cause or resolution of the
reported 20-second quick-open/close stall. Regression coverage is in
`tests/test_workspace_listing.py`.

## Running simulation location

While the welcome screen is visible, `ui/library_panel.js` polls
`GET /api/jobs/active` every four seconds. A design with an active simulation
shows a spinner and an execution-location tag immediately after its part name:

- `Local` for work running on the NADOC host;
- `Alpine(GPU type)` for a remote SLURM job, with the GPU inferred from its
  selected Alpine partition; or
- `RunPod(GPU type)` for a rented pod, using the GPU selected for that job.

The active-job response carries the display-only `accelerator_name`; simulation
ownership and concurrency decisions continue to use `execution_target` and
`resource_class`. Missing hardware metadata degrades to `Alpine` or `RunPod`
rather than hiding the active simulation.

## Performance reference

Measured 2026-08-09 against the development workspace (75 GB, 8,459 files, 193
`.nadoc` files):

| Operation | Before | After |
|---|---:|---:|
| Welcome listing response path | ~4.22 s | ~22 ms |
| Disk-usage enrichment | included above | ~66 ms cold / ~12 ms warm |
| Browser reload first paint | waited for network | immediate from cache |

The former response synchronously parsed about 89 MB of design JSON for the
identity audit and recursively traversed the complete simulation tree.

## Regression coverage

- `tests/test_design_identity_api.py` covers asynchronous legacy-identity repair.
- `tests/test_design_disk_usage.py` covers split disk enrichment and simulation
  tree pruning.
- `frontend/src/ui/library_panel.test.js` covers cache persistence and disk-usage
  merging.
- `frontend/src/ui/job_activity.test.js` covers execution-location tag formatting.
- `tests/test_jobs_active_execution_target.py` covers remote GPU-name enrichment.
