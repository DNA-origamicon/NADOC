# VR presenter figure — 2026-09-28

Implementation and research are described in [VR presenter model](../vr_presenter_model.md).
The prior Share tab and this new avatar work are local working-tree changes; the
previous pushed VR authoring/view-menu commit remains `d9f9f252`.

Evidence:

- `.development-artifacts/vr-avatar/initial`: initial steady_fast real-host/guest
  proof passed (headset/controller figure, scale and toggle).
- `.development-artifacts/vr-avatar/final`: stricter guest checks exposed a real
  lifecycle bug: prepared scene replacement clears the runtime scene and detached
  the transient avatar. Preserved failed trace and screenshots. Fixed by reattaching
  the figure after model replacement, with a regression assertion. No thresholds
  were relaxed.
- `.development-artifacts/vr-avatar/final2`: profile campaign with projected-bone
  pixel checks and native-to-guest coordinate comparisons. Each action captures
  native eyes/mirror and guest pixels. Offscreen point checks and the actual Off
  screenshot are negative controls. Guest camera is positioned once to include the
  model and figure; it remains unchanged for the scale, gesture and toggle checks.
- Arm targets use profile-driven physical controller poses; scaling uses real
  two-hand grip movement. No direct native transform or action injection.
- Local host management authority, guest cookie authentication, SSE and prepared
  guest rendering are real. A test-only HTTP proxy serves development viewer assets
  and forwards real meeting traffic, enabling read-only scene inspection. No public
  server or internet invitation is created.

Focused validation:

- 33 frontend tests passed: IK finite/singular cases, inverse avatar scale, scene
  reattachment, stale/disabled poses, protocol validation, publisher coalescing,
  document/room transitions, guest meeting and desktop sharing regressions.
- Four backend tests passed: control envelope, local document-bound writes,
  pose-feed TTL/off/tracking loss, and inversion of combined export rotation,
  model rotation/translation/scale and normalization.
- Native build and two sidebar layout/grip tests passed.
- Existing host/room/proxy tests passed (19); two dedicated avatar host/state tests
  passed, including auth rejection, malformed/stale-revision rejection and expiry.
  The first dedicated HTTP test omitted its temporary assets directory; corrected
  only the test fixture, then reran successfully.

Limitations: shoulders/elbows are estimated, not motion-captured. Validation proves
local guest delivery and rendered stereo/menu output, not through-lens comfort,
real-person body fit, or internet latency. Multi-overlay compositing shares only
the final representation layer's depth with the transient figure.

Final results:

- All four profiles passed in `final2/result.json`. Six projected bones per visible
  capture had 100% pixel coverage: 16 positive guest captures in total. All four
  Off captures had zero avatar-colored pixels. Offscreen projection controls failed
  as expected. Native menu states and stereo text checks passed for both toggles.
- Guest scale ratios after the approximate 2× physical grip enlargement were
  0.500753 (steady_fast), 0.498941 (steady_deliberate), 0.509462 (variable_fast), and
  0.486513 (variable_deliberate). The variation follows the measured controller
  motion. Exact synthetic transform tests prove reciprocal scaling independently.
  `avatar-validation.json` records these results and acquisition attempts (at most
  two, within the unchanged existing three-attempt policy).
- `just test-frontend`: **7,156 passed, one skipped**, 553 test files passed.
- `just test-smart`: **decision FAST**, **9,355 passed, 93 skipped, one failed**.
  The failure is the previously reproduced, unrelated geometry assertion
  `test_the_scalar_and_loop_skip_fast_paths_agree`. No geometry source was changed.
  `DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.`
  Runtime budget passed: `test time: 27s / 60s ok`.
- 25 focused Debug tour catalog/launcher tests passed, including Share and Avatar
  demo/validation entry points. Final frontend production build passed, with the
  existing large-chunk advisory. Native build passed before physical campaigns.
- Cleanup verified: no temporary tour workspaces, avatar-host fixtures, owned native
  viewer, or `__e2e__*Avatar*` design remains. Random-port test control files were
  removed; existing 5173/5174 host control/status files were preserved.

The demo additionally brings the guest forward for a short review hold after each
measured stage; validation mode has no review holds. Logs are retained in
`.development-artifacts/vr-avatar/logs/`.
