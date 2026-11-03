---
type: project
status: active
authority: canonical
review_after: 2026-09-21
---

# ScryWrite VR troubleshooting — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

<a id="scrywrite-vr-troubleshooting"></a>
- [ScryWrite VR troubleshooting](details/project_scrywrite/01-scrywrite-vr-troubleshooting.md#scrywrite-vr-troubleshooting)

## Start here: live visual inspector status (audited 2026-09-22)

[Inspector capability index and entry points](../docs/scrywrite_inspector.md).
Implemented: unified native VR inspector at `http://127.0.0.1:8766` (when running),
`tools/scrywrite_inspector/` and `frontend/scrywrite/inspector/`. It combines stereo
pixel identity picking, frame-bound hit geometry/rays, production input ownership,
normal/hidden scene rendering and the existing Extrude human-profile workflow.
`tools/vr_motion/session.py` shares the transport/session/capture/release safeguards.
Use steady_fast first; final validation all four in the same viewer session.
Hide the chiral fixture after tests requiring its scene/object identity complete;
restore it only for scene-dependent checks and hide again afterward. Rendering-only
hiding preserves sizing/normalization; scene picking remains active outside UI.
Session launch/socket/PIDs: `.development-artifacts/vr-human-motion-live/launch.json`.
Remaining: synchronized scrubbable native/browser timeline, general actionability
locators and per-control occlusion assertions. The desktop Three.js inspector remains
`frontend/src/scene/scene_inspector.js`; it serves a different renderer.

Human-motion testing (2026-09-22): [dataset location and modeller](project_vr_human_motion.md),
with [CLI/runbook](../docs/vr_human_motion.md). Seeded synthetic traces and imported
Vive recordings feed existing Witness/live interfaces; human-profile calibration and
physical validation of the new modeller remain open.

For Vive recovery or a requested dummy left-eye window, first read
[VR recovery guardrails](feedback_vr_restore_proven_path.md). The existing physical
mirror and view-relative framing were user-confirmed working on 2026-09-08; do not
substitute a scripted actor view or new display method.

<a id="mission"></a>
- [Mission](details/project_scrywrite/02-mission.md#mission)

## Binding decisions

1. Reuse Playwright Test as the outer runner and artifact/reporting system. Add a
   `scrywrite` fixture; do not build a second scheduler.
2. Production remains OpenXR-driven. Deterministic test input enters only through an
   explicit test adapter/entry point and must be impossible to enable accidentally.
3. Locate by stable v12 semantic primitive/owner/tool-scope identities and roles, not
   draw indices or pixels.
4. The browser/backend remain authoritative for mutations. Native scripted feedback
   is a state-machine test, never evidence of a persisted design edit.
5. Use explicit virtual frame steps and observable-state waits, never timing sleeps.
6. Keep all control/trace formats bounded, versioned, private where live, and strict
   about malformed, non-finite, stale, or future input.
7. Separate fast logic, deterministic render, OpenXR-runtime, and physical-headset
   gates. Never claim haptics, comfort, reach, or legibility from simulation.
8. Preserve the current numeric scene oracle (`1e-6 nm`, `1e-5°`) and add visual
   evidence as a separate gate rather than loosening geometry tolerances.

<a id="poc-acceptance"></a>
- [POC acceptance](details/project_scrywrite/03-poc-acceptance.md#poc-acceptance)

<a id="historical-next-after-poc-plan-superseded-by-later-implementation"></a>
- [Historical next-after-POC plan (superseded by later implementation)](details/project_scrywrite/03-poc-acceptance.md#historical-next-after-poc-plan-superseded-by-later-implementation)

<a id="poc-implementation-2026-08-21"></a>
- [POC implementation (2026-08-21)](details/project_scrywrite/03-poc-acceptance.md#poc-implementation-2026-08-21)

<a id="witness-mode-implementation-2026-08-21"></a>
- [Witness Mode implementation (2026-08-21)](details/project_scrywrite/03-poc-acceptance.md#witness-mode-implementation-2026-08-21)

<a id="headset-free-evidence-export-2026-08-21"></a>
- [Headset-free evidence export (2026-08-21)](details/project_scrywrite/03-poc-acceptance.md#headset-free-evidence-export-2026-08-21)

<a id="adversarial-audit-tranche-2026-08-21"></a>
- [Adversarial audit tranche (2026-08-21)](details/project_scrywrite/03-poc-acceptance.md#adversarial-audit-tranche-2026-08-21)

<a id="physical-hmd-desktop-mirror-poc-2026-08-21"></a>
- [Physical-HMD desktop mirror POC (2026-08-21)](details/project_scrywrite/03-poc-acceptance.md#physical-hmd-desktop-mirror-poc-2026-08-21)

<a id="live-menu-positioning-validation-2026-08-21"></a>
- [Live menu positioning validation (2026-08-21)](details/project_scrywrite/04-live-menu-positioning-validation-2026-08-21.md#live-menu-positioning-validation-2026-08-21)

<a id="layered-menu-debugging-and-fault-oracles-2026-08-21"></a>
- [Layered menu debugging and fault oracles (2026-08-21)](details/project_scrywrite/04-live-menu-positioning-validation-2026-08-21.md#layered-menu-debugging-and-fault-oracles-2026-08-21)

<a id="full-origami-atomistic-md-validation-2026-08-24"></a>
- [Full-origami atomistic MD validation (2026-08-24)](details/project_scrywrite/04-live-menu-positioning-validation-2026-08-21.md#full-origami-atomistic-md-validation-2026-08-24)

<a id="live-agent-interface-2026-09-16"></a>
- [Live agent interface (2026-09-16)](details/project_scrywrite/04-live-menu-positioning-validation-2026-08-21.md#live-agent-interface-2026-09-16)

## Cautious execution after VSCode crash (2026-09-22)

User reported an unexpected VSCode crash and requested caution. Continue the VR goal with one test/build/runtime workload at a time; use bounded workers (browser1, unit tests/builds at most2) and focused checks before broad mandatory verification. Do not overlap full frontend/backend suites or native builds with physical VR tests. Inspect process handles before relaunching; preserve crash evidence and user editor sessions. No automatic VSCode/SteamVR restarts for diagnostics.

Initial read-only check: about21GiB available RAM, swap unused, no pytest/Vitest/Playwright workload remaining. Current-boot journal search found no OOM/segfault/NVIDIA Xid match; this does not establish the cause of the earlier crash. Older Code log shows an unresponsive extension host around17:39, without a confirmed causal link. Keep goal active; caution is not a user-requested goal pause.

Caution command detail: use `PYTEST_XDIST_AUTO_NUM_WORKERS=2 just test-smart`; the recipe passes `-n auto`, so omitting this environment variable uses all detected cores. The continuation-guard checkpoint accidentally omitted it; subsequent backend checks must set it explicitly. Frontend uses `VITEST_MAX_WORKERS=2`, Playwright `--workers=1`.

2026-09-23 recovery checkpoint: no active test/build workload; about19GiB RAM
available. Recent2h kernel journal has no OOM/segfault/NVIDIA Xid entry; cause of
reported editor crash remains unknown. Preserve serial/worker limits above.
Review visibility helper now has passing combined and variable_deliberate VR-first
pilots, with both-eye bounds/cluster/RGB checks and actual X11 mirror matching.
Temporary workspaces verified absent; no new runtime workload during reconciliation.
See docs/vr_authoring_workflows.md and review-view-validation.md in the workflow
artifact directory. Goal remains active, zero final acceptance cohort credit.

Freeform placement follow-up2026-09-23: optional NADOC_VR_PROFILE_PLACEMENT=1
uses shared explicit-pose noisy reach, preserves wrist roll and records applied
capture pose.40focused checks and steady_fast combined physical pilot pass. See
docs/vr_authoring_workflows.md and placement-validation.json. End gestures still
ideal; independent tracking-to-saved-placement oracle needs presentation-transform
telemetry; trace delivery/fixed cohorts still open. Zero cohort credit.

Blunt-end profile follow-up2026-09-23: shared menu_navigation preserves exact selected
end identity while fresh paint resets Inspect. NADOC_VR_PROFILE_END=1 profiles
terminal reach, menus, length clicks and Confirm. Steady_fast combined pilot passes
3.6m;34focused checks pass. Review parts republished from verified end-profile and
VR-first-review-desktop runs (end-profile-publication.json). High-variability end
pilots, applied-pose geometry oracle, setup/clear policy, trace delivery and final
cohorts remain open; zero acceptance credit. See docs/vr_authoring_workflows.md.

User-requested stopping point2026-09-23: visible terminal command is
`uv run python -m tools.vr_workflows.demo`; guide docs/vr_workflow_demo.md. Both
headed workflows passed under demo-kzp60tl9, with profiled end/freeform and real
pose→saved-placement oracle.69focused checks and36native checks passed. Review
parts republished, temporary workspace absent, idle focused viewer restored.
Three unrelated lint findings remain. User asked to stop, summarize, package demo,
commit and push; pause the persistent goal at this checkpoint, not complete it.
Fixed80trial90%acceptance, full authoring traces and headset comfort remain open.
