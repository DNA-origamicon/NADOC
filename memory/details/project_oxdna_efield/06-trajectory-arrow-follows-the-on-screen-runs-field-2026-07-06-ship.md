# Trajectory arrow follows the on-screen run's field (2026-07-06, SHIPPED) — supporting detail

[Topic head](../../project_oxdna_efield.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Trajectory arrow follows the on-screen run's field (2026-07-06, SHIPPED)
Viewing the composite trajectory of a field lineage (relax → field1 → field2 → …, a
chain of child runs each with its own `dir`/`field_pN`) now re-aims the E-field arrow
per frame to whichever run is on screen — so a chain with DIFFERENT field directions
shows the direction used at each point in the scrub, and the arrow HIDES during the
relaxation stages (no field).
- **Backend.** `routes_oxdna._job_field(job)` → `{dir, field_pN}|None` (run_config.field
  first, else the older `efield {force_pN, dir}`). `_composite_inputs` tags each stage
  tuple with a 5th element = the owning job's field; `oxdna_health._aligned_downsampled_frames`
  + `composite_trajectory_meta` read `item[4]` and surface it as `stages[].field` in BOTH
  the full `/trajectory` payload and the lightweight `/trajectory-meta`. Backward-compatible:
  3/4-tuples still work (field defaults None).
- **Frontend.** Pure `stageAtFrame(stages, i)` / `fieldAtFrame(stages, i)` in
  `oxdna_trajectory_player.js` map a composite frame → its contiguous stage → field. The
  panel stores `r.stages` as `_trajStages`; the player's `onSeek` calls `_applyTrajField(i)`
  which fires a new `onTrajectoryField(field)` dep ONLY at stage boundaries (memoized by
  `_lastTrajField` object identity, so no per-frame DOM churn). main.js wires
  `onTrajectoryField → efieldSetup.applyConfig(field)` (reuses the same arrow path the
  run-config echo uses; `applyConfig` does NOT fire onChange, so no live re-aim side-effect).
  Toggling trajectory OFF restores the SELECTED job's own field via `runConfigForJob`.
- Tests: backend `test_job_field_prefers_run_config_falls_back_to_efield` +
  `test_composite_trajectory_carries_per_stage_field` (field flows through full + meta);
  frontend `stageAtFrame`/`fieldAtFrame` pure specs in `oxdna_trajectory_player.test.js`.
  Backend 4067 / frontend 2207 green; vite build clean. **NOT app-exercised** — needs a real
  chained-field-run lineage with a completed trajectory (GPU runs) to eyeball the arrow
  flipping direction mid-scrub → owes an MV row.
