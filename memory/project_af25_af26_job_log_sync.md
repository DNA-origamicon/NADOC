---
name: af25-af26-job-log-sync
description: AF-25/AF-26 status — feature-log seek + job-staleness roll/return; the overhang-membership seek bug fix
metadata: 
  node_type: memory
  type: project
  originSessionId: 43bf8123-51d7-4d70-8d4e-e9085375de09
---

Tier-7 "job/feature-log sync" loop (design_automation_backlog.md). As of 2026-06-24:

**AF-25 — DONE.** `headless_build.seek_features(position, sub_position=None)` + `automation_harness.assert_feature_seek`
(5 scrub invariants). The oracle went RED first run and caught a real backend bug: `crud._topology_substitute` restored
every topology field from the seek snapshot **except `overhangs`** (the downstream seek loop only re-applies overhang
*rotations*, never membership), so seeking before an overhang-extrude left a dangling overhang → wrong
`design_build_fingerprint`. **Fix: one line — `overhangs=snap_design.overhangs` in `_topology_substitute`.** Coverage 37→38.

**AF-26 — DONE (backend + real e2e leg). TIER 7 / "job-feature-log sync" COMPLETE.** Backend: wrappers
`headless_oxdna_build.roll_job_to_run_state(job_id, workspace)` + `headless_build.return_to_latest(loadout_id)` +
`automation_harness.assert_roll_return_lifecycle` (full simulate→edit→roll→return + 409 guard). Pin:
`test_oxdna_staleness.py::test_af26_roll_return_lifecycle_overhang_edit`. Coverage 38→39 + oxDNA 4→5.
E2E leg: `frontend/e2e/job_log_sync.spec.js` drives the real oxDNA panel + overhang edit + feature-log seek, asserts
the rendered ⚠ clears + model rolls; seeded GPU-free by `tests/e2e_seed_af26.py` (self-cleaning). Panel got 2 hooks:
`row.dataset.jobId` + `.oxdna-job-stale-warn`. CAN-GO-RED proven in-browser (revert the `_topology_substitute` line →
spec fails at post-seek). smoke + panel vitest green.

**Key diagnosis.** The AF-26 backend oracle stays GREEN even with the AF-25 fix reverted — `roll_active_to_job_state`'s
snapshot-overlay *fallback* clears the flag backend-side, so the "Roll & run" button path always worked. The reported
live bug ("⚠ doesn't clear after a manual feature-log rail-seek; cursor/model don't roll") traces to the SEEK path,
whose fingerprint was wrong (the overhang bug). The frontend wiring was already correct: `client.seekFeatures` →
`_syncFromDesignResponse` updates the store (scene rebuilds) AND fires `nadoc:design-changed` → both job panels
(`oxdna_jobs_panel.js`, `md_jobs_panel.js`) `_fetchJobs()` re-evaluate `out_of_date`. So the AF-25 one-line backend
fix is very likely the actual root-cause fix for the manual-seek bug. **Must still be PROVEN by the AF-26 Playwright
e2e leg** (the backlog requires it; reasoning alone is not trusted per CLAUDE.md). The e2e leg must drive the real
oxDNA/MD panel + Feature Log rail and be shown can-go-red (revert the `_topology_substitute` line → e2e red).

Full backend suite green: 3123 passed / 64 skipped. Nothing committed (user did not ask). See
[[project_md_panel_status]] (live-mode/stale issues) and design_automation_log.md AF-25/AF-26 rows.
