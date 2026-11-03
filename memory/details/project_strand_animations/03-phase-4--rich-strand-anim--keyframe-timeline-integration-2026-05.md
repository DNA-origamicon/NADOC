# Phase 4 — Rich strand-anim → keyframe timeline integration (2026-05-30) — supporting detail

[Topic head](../../project_strand_animations.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phase 4 — Rich strand-anim → keyframe timeline integration (2026-05-30)
The right-sidebar Strand Animation panel's full parametric model is now capturable into
left-sidebar Animation-tab keyframes and replayed by the player (NOT the simplified
`overhang_unzip_overlay` `binding_states` path — that stays for OH↔OH linker hinges; the two
coexist on disjoint beads). User-confirmed UX: **only φ varies per keyframe**; the "how it
looks" (mode/form/melt/splay/...) is saved ONCE per overhang. Two capture buttons (**Add
keyframe** / **Update last**); capture writes **just the selected overhang's** φ, merged.

Data model (both display-only, auto-persist):
- `OverhangSpec.strand_anim_setup: Optional[Dict[str,Any]]` — full param dict + resolved
  `binder_strand_id`. Endpoint `PATCH /design/overhangs/{id}/strand-anim-setup`
  (`StrandAnimSetupBody{setup}`, mirrors `patch_binding_display_pose`, `mutate_and_validate`).
  Client `patchOverhangStrandAnimSetup` in `overhang_endpoints.js`.
- `AnimationKeyframe.strand_anim_phi: dict[str,float]` (overhangId→φ) — SEPARATE from
  `binding_states` (whose keys are binding/connection ids). Wired into Create/PatchKeyframeBody.

Playback: `initMultiOverhangStrandAnim(deps)` (new export in `overhang_strand_anim.js`) holds
one single-instance driver per overhang (no math fork; `setBeadOverrides` merges by key so
disjoint drivers are safe). Player `_applyAt` lerps `strandAnimPhi` per overhang using its
`strand_anim_setup`; `stop()` calls `multi.clear()` (restores beads + hides displacement
invaders). main.js creates it next to `overhangUnzipOverlay`, passes `getMultiOverhangStrandAnim`.
Capture wiring: `strand_anim_panel.js` gets `api` + lazy `getAnimContext` (→ `animPanel.getKeyframeContext()`
= `{animId, lastKfId, lastKfPhi, isDesignMode}`).

**Special-keyframe rendering** (`animation_panel.js _makeKfRow`): a kf with non-empty
`strand_anim_phi` renders distinctly — magenta accent border + "Strand" chip in the top row; the
"State" row's feature-log/config selector is replaced by a read-only summary
`_strandAnimSummary(strandAnimPhi, design)` → e.g. "OH1 (Unzip, Helical) φ=1.00" (mode/form from
each overhang's `strand_anim_setup`, one clause per overhang); the generic binding-φ driver rows
are suppressed. Pose + spin + timing rows stay editable. Edit the un/hybridization settings/φ in
the right-sidebar panel then "Update last".

Tests: 7 new in `test_animation.py` (φ create/patch/clear/defaults, setup roundtrip/clear/404,
model roundtrip); full suite 1626 passed (2 fails = pre-existing router flakes `test_advanced_seamed_*`
+ `test_teeth_closing_zig`, confirmed identical on clean HEAD). Frontend builds clean.
**NOT yet visually click-tested in a live browser** — playback of the rich un/hybridization from a
keyframe, multi-overhang concurrency, and displacement-invader teardown on Stop need a human smoke
test on `workspace/OH6hb_test.nadoc`. Note: the `_kfSignature` step in the plan was a misread —
no such resume-signature exists; `strand_anim_phi` is computed live per frame like `binding_states`.
