# Waiting-screen animation and shared-worktree commit audit

The guest invitation screen uses the existing NADOC DNA GIF, with a dark overlay
and responsive cover sizing. The original 1920×1080 asset has 451 frames and an
infinite loop extension. The host now serves GIF assets as image/gif. Existing
lobby disposal removes the image on Start. Host-unreachable recovery retains the
waiting screen; this does not make invitations available while the host is off.

Validation: build passed; 580 frontend test files / 7,308 tests passed, one skipped;
23 smoke tests passed; persistent invitation and QR export browser checks each
passed. The invitation check verified the image decoded at 1920 pixels, its MIME
type, and Start/Stop/restart/reset transitions. Desktop and mobile screenshots
were captured; the mobile screenshot was visually inspected. Prior guest-entry
checks are retained under .development-artifacts/guest-entry-20260930/.
13 Node tests, 11 QR Python tests, two native renderer/sidebar tests, and nine CPD
numerical/protocol tests passed. Lint and diff checks passed. Physical QR cube
alignment remains the earlier session's on-site validation limitation.

main.js LOC delta: 0.

Other-session work was preserved in separate QR/VR, CPD, and NAMD/evidence commits.
No new scientific campaign or parameter promotion was performed. The only lint
repair removed an unused import from the existing CPD protocol test.

## Backend regression debt

Initial FAST run: 9,483 passed, seven failed, 93 skipped. One CUDA worker broken-pipe
failure did not recur. Final selection: decision: FAST (fast suite only).
Final run: 9,482 passed, six failed, 93 skipped; 29 seconds guard wall time.
The six remaining failures also appeared before this change:

```
FAILED tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree
FAILED tests/test_surface_bin_transfer.py::test_simulated_figure_surface_honors_probe
FAILED tests/test_vr_representation_tour.py::test_fixed_color_preview_controls_are_disabled_and_unselected
FAILED tests/test_surface_field.py::test_simulation_field_selects_continuous_extraction[chimerax]
FAILED tests/test_surface_field.py::test_simulation_field_selects_continuous_extraction[continuous]
FAILED tests/test_surface_field.py::test_simulation_field_selects_continuous_extraction[remeshed]
```

```
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

## Required timing triage

Applied .claude/skills/triage-slow-tests/SKILL.md. Initial timings and isolated
rechecks (seconds, including setup where relevant):

| Test | Initial | Isolated | Finding |
| --- | ---: | ---: | --- |
| Desktop VR representation round trip | 10.46 | 9.34 | Real complete representation export/native validation; registered slow, md fallback area |
| Biotin cache invalidation | 8.21 | 0.91 | Numeric fit/cache test; contention, retained fast |
| ChimeraX trajectory surface | 6.97 | 5.90 | Real surface extraction; only this parameter registered slow, oxdna area |
| Mock headless oxDNA recovery | 6.90 | 0.78 | Mock executable and recovery, retained fast |
| Project lease takeover | 5.49 | 0.99 | Local store I/O, retained fast |
| Mock melted-run gate | 5.08 | 1.19 | Mock runner, retained fast |

Both reclassified cases passed in focused runs and remain in slow collection.
Source/test paths with no narrower leaf rule conservatively select FULL; no
selection rule or budget was weakened. Final FAST timing guard passed without
per-test violations. No additional broad sweep is needed for timing.

## Artifact accounting

Test workspace parts, project histories, isolated :5174 control/status files,
and browser output directories were cleaned by their failure-safe teardown.
Post-run scans found no __e2e__ workspace entries or browser output directories.
The unrelated :15174 viewer control was preserved.
Two inactive root diagnostic files (opt_log.out, 187 bytes; psi.840251.clean,
19 bytes) were moved, not deleted, into the ignored evidence directory with
SHA-256 relocation records. No active process held either file and no source
reader referenced them. Raw validation logs and screenshots remain under
.development-artifacts/waiting-dna-20260930/.
