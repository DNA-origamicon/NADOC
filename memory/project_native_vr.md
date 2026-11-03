---
type: project
status: active
authority: canonical
review_after: 2026-12-01
---

# Native VR expansion

## Current menu-hover timing follow-up (2026-10-13)

The user reports substantially reduced doubling after normal deployment, with
remaining lag/frame drops as menus enter view or the other controller aims,
hovers or vibrates while moving the model. ISSUE-77 is open; MV-44 is improved
but remains open. This follow-up adds diagnostic coverage, not a rendering or
haptic behavior fix. The earlier normal-launch evidence below is historical.

User recording 962531370889719 saved all 179 final presentations, zero accounting
drops. The completed stereo decode joins all 358 eye images to exact CRC/session/
eye/frame records: 144 distinct submitted images, 35 two-presentation runs per
eye, matching left/right IDs, no unknowns/gaps/regressions. Reuse accounts for
19.55% of final presentations. The journal has 143 predicted-in-window rows;
boundary membership differs from the 144 decoded image IDs. The original fixed-ROI
result (313 joins, 45 unknowns, 22 proven pairs per eye) is preserved. Opt-in
following used a fixed 80-pixel allowance and 20-pixel adaptive margin, changed
no acceptance thresholds, and was evaluated retrospectively on this recording.

The 242-row journal reports head and hand tracking flags 15 throughout: no flagged
dropout, not proof that tracking jitter is absent. Both menus are logically open
while their visible coverage changes. Application prediction intervals mix 11/22 ms.
Input/actions reaches 1.61 ms; xrEndFrame reaches 20.88 ms. This locates the long
host wait, without attributing it to GPU work, hover, haptics or a tracking fault.
The exact-ID groups correlate with that wait: reused-image application frames have
median host duration 22.242 ms and xrEndFrame 20.259 ms, versus 11.104/2.347 ms for
single-presentation frames. This association is not a menu/haptic causal test.
The old recording has no per-frame hover/haptic diagnostics. Native inspection
found event-triggered haptic dispatch and possible hover-driven texture refresh;
visible menu shading/backdrop work is another candidate. None is proven causal.

Current normal physical-inspect viewer: PID 545874, session
545874-963676394554697, native SHA256
65bcd41e1de02d1d6271c19a1aa7d04683087358eb0dd78a17d4eb282cb8a4d3,
frozen at menu-hover-followup-20261013/native-build/nadoc-vr-viewer.
Existing SteamVR compositor 2783034 was retained. Scientific export is unchanged;
the restored normalization matrix differs by at most 1.0547e-7. The actual browser
reattached: feed 480591238→480591239 and coordinate sequence 2, unchanged placement,
Help → Exit VR available. Menu open state and former sidebar positions were not
restored; both menus are closed after reload. Reopen/place them before another
physical reproduction. Verify live process identity again before future actions.

New capture-only capture_ui_diagnostics version 1 records requested/dispatched
haptics with result and host duration, bounded hover IDs/changes, sidebar texture
updates/cache hits, and eye menu/backdrop host spans. Idle collection uses zero
diagnostic clocks. Fixed storage adds 1,240 bytes per frame, 10,158,080 bytes across
8,192 journal slots. The module adds no GPU queries, pixel readbacks or active
file writes. Event overflow, string truncation and clock errors remain explicit.
Host call time is not GPU busy time; a draw is not visible coverage; API dispatch
does not independently observe physical vibration. Nested spans overlap.

Use python -m tools.vr_tracking summarize-interactions --journal JOURNAL
--identities IDENTITIES --output NEW_DIRECTORY after capture. Identities are
optional and, when supplied, must match the exact journal/session/request. Older
journals report missing telemetry as unavailable. Optional marker ROI following
is a manifest setting; the ordinary identify-frames command is unchanged.

Deployment check 963838453284914 saved 179 final frames with zero accounting drops
and 288 journal rows. Both menus were closed; all UI activity/clock counters were
zero, with zero overflow/clock errors. Physical hands were invalid in this check;
it does not exercise worn-controller hover or vibration. The first verification
incorrectly required positive UI clocks; its failure is retained, and the corrected
zero-demand check passed without recapture or native edits. Actual GL hover/cache
and haptic API dispatch/result tests passed separately. Six native checks,
45 interaction-reader tests and 69 marker-decoder tests passed. No broad/full-suite
rerun was performed; the previously documented psfgen/CPD and timing-guard debt
remains open, and no clean-worktree claim is made.

Evidence: [native audit](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-audit.json),
[complete stereo identity proof](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json),
[native freeze](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-freeze.json),
[closed-menu live check](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/verification.json),
[interaction findings](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/interaction-timing-findings.json),
[final deployment verification](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/final-verification.json),
[retained initial verification failure](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/initial-verification-failure.json),
[browser attachment](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/browser-connected.png),
and [reusable tool documentation](../docs/vr_origami_tracking.md#menu-hover-and-haptic-timing).

## Memory routing and evidence availability (October 17 maintenance)

No VR implementation, runtime or headset requalification occurred during this edit.
The October 13 process/session identities above are historical and must be rechecked.
The [full prior head](project_native_vr_archive.md#active-head-snapshot-preserved-october-17-2026)
retains every feature checkpoint, measured result, question and old handoff verbatim.
Read only the relevant archived section when working on that feature. The older
phase table/questions below retain unresolved requirements; later dated feature
checkpoints supersede their historical implementation status. They are not a queue
that overrides the current user task or feature-history session handoff.

The two former worktree runbook links are unavailable here. Use the maintained
[capture runbook](../docs/scrywrite_inspector.md#final-steamvr-output-capture-2026-10-12)
and [tracking runbook](../docs/vr_origami_tracking.md). Historical captures and frozen
worktree paths in the archive are provenance, not evidence of present availability.
Do not fabricate missing artifacts or silently redirect frozen evidence to new bytes.

## Recent feature state and remaining qualification

- Join's October 13 follow-up includes 0.3–10 nm Reach, scope locking, stale-pose
  refusal and duplicate-preview/reselection correction (ISSUE-78). Recorded four-profile
  Cancel/Apply/Undo and final-output results are in the archive's Join section.
  Do not generalize the measured fixture's near-90 FPS results to arbitrary scenes.
  Raw Join captures were pruned by user instruction; preserve compact summaries,
  configured builds and live runtimes. Future captures require failure-safe cleanup.
- The October 12 Full simulation panel uses real jobs, explicit Load, bounded
  trajectory pages and shared visualization options. Atomistic parity and physical
  checks remain outside that iteration; see [simulation audit](../docs/audits/vr_simulations_20261012.md).
- Every new workflow needs a discoverable Debug → VR Tours & Tests entry, through
  `tools/vr_workflows/tour_catalog.py`; see [sidebar guide](../docs/vr_sidebar_menus.md).
- ISSUE-77 and MV-44 remain open. No current PID, physical tracking state, deployment,
  causal hover/haptic diagnosis, broad regression pass or headset comfort is inferred.
- Before workstation recovery, read [VR recovery guardrails](feedback_vr_restore_proven_path.md)
  and [proven workstation fixes](project_steamvr_drm_lease_fix.md). This memory edit
  does not request headset access, start services or change runtime settings.

## Binding invariants

1. Desktop geometry, topology, job data, and visualization state remain authoritative. VR is a projection and intent source, never a competing model.
2. VR selection emits normalized intents through the canonical selection controller; it does not become a second state writer. Assembly selection remains an explicit boundary.
3. DNA polarity and topology follow `REFERENCE_DNA_TOPOLOGY.md`. Ask before encoding an ambiguous handedness, strand order, loop/skip, crossover, or spatial relation.
4. Keep the composition root thin. Cohesive VR logic belongs in testable modules, not `main.js` or route handlers.
5. Never mutate a shared live server merely to verify behavior. Use pure/unit tests, isolated fixtures, or read-only inspection.
6. A visual change needs both a numeric/snapshot oracle and an actual rendered-image or headset check. A status label is not visual verification.
7. Each phase ends in a narrow, reversible checkpoint commit. Stage only phase-owned files in the shared worktree; never stash, reset, restore, or sweep up unrelated edits.
8. Preserve user scale and spatial context across representation changes. Display element sizes must be derived from model-space geometry and one world transform, never camera distance or FOV visibility.

Repository/user Git authorization takes precedence over older checkpoint language:
commit and push only when explicitly requested. Preserve unrelated worktree changes.

## Phase ledger

| Phase | Scope | Exit checkpoint | State |
|---|---|---|---|
| 0 | Durable plan, source inventory, validation metrics, fixture strategy | Memory lint; inventory and first acceptance matrix recorded | Complete |
| 1 | Exact static visual fidelity: overhangs, crossovers, forced ligations, extra bases, extensions, same-helix domain gaps, ends/markers/arcs | Primitive/topology parity tests plus headset visual check | Manual gate |
| 2 | Scene-projection contract and representative VR regression fixtures | Stable-ID scene snapshots, tolerance tests, failure diagnostics | Complete |
| 3 | Expanded Quick View controller shortcut | Superseded: right trackpad now owns radial Tools; no quick-expand binding | Superseded |
| 4 | VR picking and selection intents from cluster through smallest supported element | Canonical selection matrix passes in desktop and VR | Manual gate |
| 5A | Complete Move/Rotate UI/UX: exact previews, Confirm/Cancel, transaction-bound one-step Undo, recovery | Cluster/Base/End/Domain/Strand workflows pass transaction and headset gates | Automated gate complete — physical gate required |
| 5B | Complete exact-End Extrude UI/UX: settings, preview, revalidation, Confirm/Cancel, one-step Undo | One-cell continuation workflow passes safety, fidelity, and headset gates | Queued behind 5A |
| 5C | Twist/Bend editing transactions | Safe preview/commit/undo with plane-pair fidelity | Deferred by user redirect |
| 6 | Unified job-list shell and simulation-result navigation in VR | Job identity/status/action parity with desktop | Active (read-only live-status foundation) |
| 7 | Every simulation engine's visualization options and time/result controls | Engine-by-option parity matrix and playback checks pass | Queued |
| 8 | UX polish, accessibility, comfort, performance, resilience | Sustained task tests and headset regression checklist pass | Queued |

## Provisional validation contract

Ratify thresholds during Phase 0 research; do not silently turn provisional numbers into science gates.

- Geometry fidelity: primitive count/type/visibility by stable design identity; topology-edge parity; position RMS and maximum error in nm; orientation angular error; dimension/scale error; negative-space checks for intentional gaps.
- Styling fidelity: representation/color parity and, where screenshots are deterministic, perceptual image difference. Lighting may differ stereoscopically but must not obscure topology.
- Interaction: selection hit/miss and false-positive rates; task completion time; accidental activation, re-grab, cancel, and undo counts; menu acquisition time; controller travel/reach.
- Comfort/performance: target the active headset refresh rate (original Vive normally 90 Hz); record application CPU/GPU frame-time p50/p95/p99, missed frames/reprojection, long-frame bursts, and scale/pose stability. The 90 Hz frame interval is 11.11 ms, but application budgets must leave compositor margin.
- Manual comfort: short symptom rating before/after demanding tasks, with explicit stop criteria for eyestrain, nausea, disorientation, or loss of balance. Never optimize comfort by merely blocking close inspection.
- Simulation UX: job/state mapping completeness; engine-option parity; frame/time identity; seek latency; playback stalls; overlay correctness; preserved user context when switching results.

## Open questions log

- **Q-VR-001 — Right-grip semantics (implemented, validate):** hold-for-expanded/release-to-restore. Reopen only if headset testing finds grip fatigue or trigger conflict.
- **Q-VR-002 — Smallest selection identity:** atom spheres and intra-residue bonds currently resolve to canonical Base because the design selection model has no atom ref. Before atom-level editing/simulation inspection, decide whether individual atoms become canonical design selections or transient tool/result picks beneath Base; do not infer atom identity from an atomistic draw index.
- **Q-VR-003 — Edit safety:** what confirmation, preview, cancel, and undo affordances should VR tools share with desktop editing?
- **Q-VR-004 — Handedness/accessibility:** should menus and tools auto-mirror by dominant hand, expose an explicit setting, or both?
- **Q-VR-005 — Lighting:** should photo shadows remain scene-locked, offer a head-light fill, or expose a small lighting menu for inside-model inspection?
- **Q-VR-006 — Simulation defaults:** which job fields, plots, overlays, and playback controls deserve persistent wrist/panel placement versus on-demand menus?
- **Q-VR-007 — FJC transform authority:** desktop visibly stretches relaxed ssDNA representatives along the live chord, while the older Python `transform_to_chord` currently only rotates/translates despite its docstring. VR intentionally matches desktop locally; decide in a separate science-aware change whether the shared Python helper should be corrected and migrated.
- **Q-VR-008 — Warning-marker style:** the current physical triangular sign stays in model space and scales with the design; when billboard support exists, decide whether unligated warnings should instead remain head-facing like desktop sprites or keep the spatial sign for depth stability.
- **Q-VR-009 — Right trackpad:** resolved for this checkpoint as hold-to-open radial Tools with release-to-activate. Selection remains on full trigger; the old Expanded Quick View click binding is removed. Validate sector acquisition, accidental activation, and dominant-hand comfort before freezing the gesture across controller profiles.
- **Q-VR-010 — Tool manipulation binding (provisional, validate):** explicit Preview arms right-trigger-only target manipulation; left trigger remains model grab and both triggers remain model resize. Reopen if headset testing finds mode errors, two-trigger transition jumps, or dominant-hand/accessibility problems.
- **Q-VR-011 — Cross-level tool semantics (design-aware sequenced preflight implemented, validate):** Move/Rotate has exact preview coverage for Cluster/Base/End/Domain/Strand. End Extrude and Cluster/End Twist/Bend now have scalar drafts, exact read-only geometry, non-executing desktop-operation descriptors, read-only preflight APIs, and target/config/design-aware sequenced native status feedback, but remain non-previewable pending physical gates and transaction attachment. Decide whether Base/Domain/Strand should gain explicit plane/footprint handles; Bond/Crossover/Atom remain refused rather than promoted.
- **Q-VR-012 — Atom edit semantics:** v11 now supplies stable transient `(base key, atom name)` and semantic atom-bond refs beneath canonical Base/Bond, but NADOC has no persistent per-atom design selection or transform owner. Decide whether atom editing should persist those semantic refs/overrides, remain a simulation-results-only interaction, or expose residue transforms with an atom-local handle.
- **Q-VR-013 — Expanded tool geometry (read-only exact poses implemented, validate):** A/B planes, the exact End locator, and the single-cell extrusion footprint now carry exact natural/Expanded geometry using the shared 5 nm per-helix translation. Physical gates remain required, and actual deformation/extrusion execution still needs an authoritative transaction contract; do not infer that every future tool handle supports Expanded pose from these read-only projections.
- **Q-VR-014 — Deformation plane geometry (natural/Expanded read-only frames implemented, validate):** validate both poses in the physical frame checkpoint before enabling a deformation preview. Decide whether the final controller gesture should remain point-then-trackpad or become direct plane-handle dragging.
- **Q-VR-015 — Periodic seams (launch parity implemented, validate):** the desktop End-to-End Crossovers toggle is now honored when creating the immutable native snapshot. Decide whether the final VR options page should expose a live seam-arc toggle; until then changing it requires relaunch so natural/Expanded identity sets remain immutable.
- **Q-VR-016 — Job panel persistence and actions (sequenced live status implemented, validate):** decide after the physical live-status gate whether the unified job panel should be a head-recentered modal, wrist/hand-attached view, or user-placeable world panel. Do not enable Run/Stop/Delete or result loading until confirmation, stale-job refusal, focus restoration, and desktop selection mirroring have explicit contracts.
- **Q-VR-017 — Transaction acknowledgement (priority):** Confirm must remain visually pending until the desktop-authoritative mutation response identifies the committed feature-log entry. Native should then expose committed/failed/cancelled status and enable Undo only for that exact transaction; a later desktop edit must make the VR Undo token stale rather than undoing unrelated work.
- **Q-VR-018 — Move/Rotate residue granularity (priority):** Base/End/Domain/Strand previews already resolve to exact residues. Persist the whole target set atomically as one feature-log/undo entry; do not loop single-residue endpoints or silently promote them to Cluster.
- **Q-VR-019 — Extrude scope after exact End (deferred expansion):** finish one-cell continuation first. Multi-cell slice footprints, overhang extrusion, new-bundle extrusion, and deformed-End continuation need separate discoverable target/footprint contracts and must not be hidden behind the current End action.

Master integration retains October 15–22 rendering, clipboard and upload-pacing
evidence in [the archive](project_native_vr_archive.md). The October 22 standard-24HB
recheck supersedes earlier baseline performance claims; physical comfort and strict
no-drop editing remain unqualified. Rediscover runtime identities before use.
