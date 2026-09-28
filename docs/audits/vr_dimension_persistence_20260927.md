# Shared desktop/VR measurements — 2026-09-27

Placed controller measurements now belong to the launching document. Stable IDs,
names, endpoints in desktop nanometres and visibility are serialized in `.nadoc`
and `.nass` documents. Desktop Dimensions restores their lines, labels and icon
controls. Polling discovers native changes and triggers the existing desktop
workspace autosave; an unsaved document still needs its normal first Save.
Saved records import at VR launch. Desktop changes made during an already-running
VR session are not streamed back into that viewer.

The native writer uses an atomic acknowledged journal bound to the launch document
and UUID. It reverses normalization and the actual viewer origin; the backend
reverses launch rotation. Only placed/frozen endpoints are saved. Model grip
transforms leave document coordinates unchanged. Per-ID mutations preserve
unrelated records, reject invalid points and do not invalidate geometry caches.
A failed journal is retained; desktop failed writes remain queued for retry.

Validation:

- Native build and CTest: 40/40, including nonzero center/scale/origin conversion,
  saved-record import, acknowledgements, visibility and deletion.
- Focused backend persistence: 5 passed, covering file round trips for parts and
  assemblies, document binding, rotation, replay, invalid coordinates and cache identity.
- Frontend suite: 545 files, 7,083 passed, one skipped.
- Chromium persistence scenario passes: real metadata route, rendered line and
  5.000 nm label, save file, reopen through normal workspace boot action, hide/delete.
  Test workspace files and project histories are cleaned by global teardown.
- `just test-smart`: 9,281 passed, 92 skipped, one failure in
  `tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`.
  An additional existing desktop pointer-selection scenario failed to pick
  bases during this run; the new file-persistence browser scenario passes.
- Native live persistence launch was blocked by SteamVR: compositor watchdog
  aborted in `DoSwapchainPresent`, while server/dashboard remained running.
  The production launcher correctly rejected this runtime. No runtime settings
  were changed to bypass it. Consequently the new native launch/save/relaunch
  check and its four-profile run remain unverified, as does physical comfort.

Evidence logs: `.development-artifacts/dimensions-*-latest.log`,
`.development-artifacts/dimensions-browser-final.log`,
`.development-artifacts/dimensions-native-persistence.log`. Earlier failed browser
attempts exposed test reopening errors (API import alone does not dismiss the
welcome screen); the final scenario uses the actual workspace boot action.

After SteamVR is healthy, run:

```bash
uv run python -m tools.vr_workflows.dimensions_persistence_check \
  --output .development-artifacts/vr-dimensions/persistence-live
uv run python -m tools.vr_workflows.dimensions_persistence_check --validate \
  --output .development-artifacts/vr-dimensions/persistence-four-profiles
```

The check refuses to replace another active native viewer, uses an isolated demo
backend document, writes only its supplied artifact directory, cleans its owned
viewer/journal, and compares endpoint positions as well as lengths after reload.

DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
