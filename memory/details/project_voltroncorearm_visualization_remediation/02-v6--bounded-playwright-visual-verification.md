# V6 — Bounded Playwright visual verification — supporting detail

[Topic head](../../project_voltroncorearm_visualization_remediation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### V6 — Bounded Playwright visual verification

Status: **implemented and Playwright-verified**

Problem: a SwiftShader screenshot of the live WebGL canvas can take over five minutes and
may ignore the useful test timeout while Chromium is blocked in readback.

Implementation:

- Keep state/timing tests screenshot-free and event-driven.
- Capture lightweight cloned-DOM screenshots for transient UI states.
- Run sparse scene pixel checks in a separate GPU-backed project when available.
- Put each scene capture behind an external watchdog so a wedged compositor cannot hold
  the suite indefinitely; retain trace/state evidence on timeout.
- Geometry invariants remain the headless correctness oracle for the large scene.

Acceptance:

- The timing diagnostic finishes within 90 seconds when using a retained local frame.
- A headless visual job exits predictably on readback failure.
- Equilibrium and MD-applied geometry are both verified without requiring continuous
  SwiftShader rendering.
