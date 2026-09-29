# Early VR startup and menu depth — 2026-09-29

Implemented the ordinary `/vr/launch` loading room and depth-aware frosted menus.
See [behavior and reusable checks](../vr_startup.md).

## Physical-runtime evidence

The actual SteamVR/OpenXR viewer was used, with the existing X11/NVIDIA runtime.
No source part or desktop document was edited. The startup tour uses a private
in-memory copy of `workspace/24hb_0xT.nadoc`; scene placement in the tracked view
is an explicit observation adjustment for verifying the final model.

- Final cold export: first observed loading frame **2.43 seconds**, first observed
  ready part **88.38 seconds**. Export wrote 11,819,095 records / 258,163,667 gzip
  bytes in 65.85 seconds. Both eyes contained the loading panel and final design.
  Observed frame counters advanced from 73 to 7,499. The panel is anchored at
  tracked head height and initial horizontal facing direction, with a larger
  1.15 presentation scale after inspecting the first capture.
- `.development-artifacts/vr-startup/cold-final/` retains loading/part-ready eye
  PNGs, desktop backbuffers, progress samples and viewer logs. The initial run
  `cold-01` observed loading at 2.53 seconds and the part at 88.98 seconds; it
  predates the larger panel and frame submissions between GPU style uploads.
- `.development-artifacts/vr-depth/matrix-01/` passes **all four motion presets**.
  Both eyes retain 935–1,027 foreground controller pixels inside the menu region,
  including 165–207 sharp orange core pixels. Rear controller pixels inside the
  panel are zero; removing the panel reveals 468–493 pixels there, ruling out an
  offscreen/absent-controller false pass. Actual desktop window checks pass.
- The older room-UI test's blur/color/text assertions pass (mean blur errors
  3.37 / 3.15 RGB levels). Its floor-boundary assertion fails because the calibrated
  boundary is outside the present headset FOV (zero projected samples). This is
  retained in `vr-depth/room-01`; no floor thresholds or head tracking changed.

These timings exclude a reboot of the operating system or SteamVR. SteamVR was
already running. A compiled native binary was available; native rebuilds remain
a prerequisite. Captures show application-submitted eyes, not compositor scanout,
through-lens readability or physical headset comfort. GPU upload stages are
synchronous individually; loading frames are submitted between styles.

## Software checks and development retries

- Five startup tests pass: atomic/private progress, scene-before-ready publication,
  export failure, stopped-viewer cleanup, launch-before-export scheduling.
- Six native tests pass: sidebar grips, sidebar layout, interaction, menu layout,
  explicit empty authoring and rejected unmarked empty scene.
- Ruff and whitespace checks pass. Native Release build passes with the established
  sanitized system-tool environment. An initial unsanitized shell build linked
  through Conda and failed; no system/runtime configuration was changed.
- Depth-check development attempts are preserved: `depth-01` used a nonexistent
  orientation telemetry field; `depth-02` exposed a Python list/array mismatch;
  `depth-03` found a checker coordinate bug (native stencil bytes are bottom-up,
  PNGs top-down). Corrected the oracle's row convention rather than changing its
  thresholds. `depth-04` passes the initial steady-fast case; `matrix-01` adds the
  uncovered rear-controller negative control and all four profiles.
- The startup tour now joins its owned cleanup thread. Earlier runs exited before
  daemon cleanup finished; their exact owned exports/feeds were removed and
  verified, without touching user designs. No owned viewer remains running.
- `just test-smart`: **FAST**, **9,429 passed, 93 skipped, 1 failed**. The failure is
  the previously recorded unchanged
  `test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree` exact-array
  comparison. Total test time was 26 seconds, within the 60-second backstop.

Selector notice:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```
