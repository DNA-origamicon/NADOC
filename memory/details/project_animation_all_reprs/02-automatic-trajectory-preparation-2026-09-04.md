# Automatic trajectory preparation (2026-09-04) — supporting detail

[Topic head](../../project_animation_all_reprs.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Automatic trajectory preparation (2026-09-04)

The animation sidebar now prefetches trajectory coordinates when rendering/selecting
trajectory keyframes and changing their job/scope/stride. It uses the same display
controller through `trajectory_keyframes.prefetch`; `trajectory_downloads.js` stores
single-flight downloads keyed by job, alignment, scope and stride. Prefetch does not
activate the controller, move the scene, or change topology. Off-screen sessions now
prepare heavy display frames too (`trajectory_preparation_cache.js`), keyed by job,
resolution, representation and surface settings. Rows report frame counts, readiness
and cancellation. Play joins the same work using inline progress rather than a modal
and refuses missing/failed frames. Preview remains optional
for authoring scrubs. Downloads are retained only for the active animation; explicit
refresh bypasses them and cancellation aborts pending requests.

Bottom Play's dirty signature now includes trajectory identity, engine, scope, stride
and start/end. Paused playback cannot silently reuse a pre-edit trajectory schedule.
Prepare tracks frame counts per job **and resolution**, including later jobs sharing
one controller. Job/stride swaps settle the requested frame before playback advances;
the animation clock pauses for asynchronous preparation. Both video exporters already
await `player.settleFrame`, so they share that guarantee. Heavy geometry remains bounded
by the existing memory plan; completed per-job caches are adopted when switching jobs.
Representation changes warm a new cache. Cancel releases the UI immediately and stops
subsequent background work; an in-flight server request may finish without adoption.

Browser verification uses an isolated in-memory API fixture and actual sidebar/player/
display modules: cold background load does not move the model; bottom Play waits, plays
frames in order without Preview, downloads once, and honors range edits on replay.
No workspace files, jobs or exported videos are created by that check.

Non-modal follow-up verification: real VoltronCoreScad's saved 51/151-frame jobs reached
ready; VDW Play exposed inline progress, allowed Help-menu interaction and cancelled
cleanly (browser test passed, no console errors). The final UX check hides software
WebGL drawing to isolate preparation; it is not a full-model FPS benchmark. Private
job/design copies and Playwright artifacts are cleaned even on failure. See the audit
for full-suite/smoke failures and the scope of the large-model check.

Sequence readiness follow-up: download + frame preparation now share an authored-order
queue across engines (`trajectory_preparation_queue.js`). The bottom scrubber exposes
per-keyframe, duration-weighted prepared coverage (`animation_readiness.js` and
`animation_readiness_bar.js`), with download work distinguished from usable cache cells.
Later job metadata allows Play to begin the ready prefix while remaining jobs warm.
Visible job lists bypass the idle timing gate; default background waits expire after
2 seconds without cancelling the timed operation. Metadata/preparation no longer wait
for job dropdown population. See the audit for focused and browser verification.

2026-09-05 correction: segment labels now show live parser/transfer stage percentages
with blue loading fill; green remains actual prepared coverage. The initial version
hid those intermediate work percentages in tooltips and therefore appeared binary
for coarse-grained trajectories. Parser polling stops once transfer begins.
