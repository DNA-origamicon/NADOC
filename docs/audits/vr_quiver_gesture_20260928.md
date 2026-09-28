# Scissors quiver gesture — 2026-09-28

Either controller toggles Nick by reaching from in front of the headset to behind
the head/shoulder, with buttons released, and dwelling 0.35 seconds. Both scissors
equip/stow together. Selecting Nick again on the wheel remains an alternative.
The gesture uses ordinary tracked controller/head poses and the existing Nick
activation path; it does not mutate the design.

The detector uses horizontal headset facing. Its inner region is within 55 cm
laterally, 25 cm below to 35 cm above eye height, and 12–55 cm behind the head.
An outer hysteresis region avoids boundary chatter. A 0.15-second front dwell
rearms; at least 18 cm of actual controller travel is required. Remaining behind
does not repeat, and turning the head past a stationary controller does not count.
Menus, button presses, active manipulation, pending edits and invalid tracking
reset/suppress detection. Equip/stow pulse amplitudes are 0.55/0.25 respectively.

## Validation

- Native viewer rebuilt successfully. Three focused native tests passed, including
  both hands, dwell, held-behind non-repetition, disabled/tracking-loss reset,
  yaw-relative placement and head-turn-only rejection.
- The existing **Nick with scissors, Undo and Redo** tour now includes two quiver
  reaches before the nick. All four profiles passed: `steady_fast`,
  `steady_deliberate`, `variable_fast`, `variable_deliberate`.
- Each profile verified stow and re-equip, no repeated toggle during a further
  0.7-second behind-head hold, and no design revision change. The subsequent
  analog scissors, glowing bond, cut, Undo and Redo checks also passed.
- Eight projected sphere/scissors checks passed in both submitted eyes and the
  actual mirror buffer. Offscreen negative controls failed as expected. The
  steady-fast stowed/equipped mirror frames were visually inspected.
- Motion presets and existing hit radii were unchanged. Reach traces and any
  acquisition retries remain in the evidence; explicit dwell belongs to the new
  gesture and is separate from measured reaching. Ordinary grip framing positions
  the design for the existing nick test before the gestures.

Evidence: `.development-artifacts/vr-nick/a4fdd8b73e/result.json`, with
`end/<profile>/.../nick/quiver-stowed/` and `quiver-equipped/` captures and pixel
reports. Temporary documents and viewers were removed on exit. Reproduce through
Debug → VR Tours & Tests → Tools · Authoring → **Nick with scissors, Undo and Redo**,
or `uv run python -m tools.vr_workflows.nick_tour --validate`.

This is physical-runtime evidence with synthetic right-controller motion. Both
hands and head-turn rejection have native software coverage. Human reach comfort,
behind-head tracking occlusion and through-lens visibility remain unverified.
