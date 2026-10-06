# VR Twist

Choose **Tools → Twist**. The persistent panel reuses Bend's plane picking,
paired controls, thumbwheel input, and Confirm / Cancel / Return layout.

1. The panel retains the full selection of clusters, strands, and domains,
   including mixed selections, and initializes planes at its outer bp bounds.
   **Change selection** enables the existing filters and selection volume;
   **Use selection / Pick planes** resumes editing. **Clear selection** appears
   in selection mode. Choose **Plane 1** or **Plane 2** and hold a trigger near
   a selected element to choose its bp index. Picking never adds a new target.
2. Turn the mint handle on **Plane 2** around its axis. Plane 1 stays fixed;
   the planes keep their positions and normals. Only one controller owns the
   handle at a time. Releasing retains the draft. Grips still move the scene.
3. Drag **Amount** for signed 1° steps, or 0.1°/nm steps in density mode.
   The paired buttons step by ±5° or ±0.5°/nm. **Reverse direction** changes
   the sign; **Zero twist** clears the amount. Switching units preserves total
   twist and requires ordered planes. It refuses conversions outside the existing
   supported amount range.
4. The mint pair of curves previews the amount and direction of torsion; it is
   a guide, not a live atomistic deformation. **Confirm** applies the standard
   desktop Twist deformation, records one feature, and refreshes VR geometry.
   Release the handle or wheel before confirming.
5. **Undo** reverses that exact feature, refusing an intervening desktop edit.
   **Cancel** resets the draft to the selected bounds. **Return to tools** leaves the panel.

Handle editing uses natural geometry. Expanded or inspection layouts disable
handle grabs. Existing desktop deformation mathematics and molecular constants
are unchanged.

## Guided tour and ScryWrite validation

Open **Debug → VR Tours & Tests → Tools · Authoring → Twist between two planes**,
or run:

```sh
just vr-twist-demo
just vr-twist-test
```

Demo uses `steady_fast` with review holds. Test runs `steady_fast`,
`steady_deliberate`, `variable_fast`, and `variable_deliberate` in one physical
OpenXR viewer, restoring the original design with Undo between profiles.
SteamVR needs a focused tracked headset; an existing NADOC viewer must be closed.
The tour creates a temporary two-helix part and cleans up its viewer and workspace.

Checks cover trigger-held bp movement, touchpad navigation, fixed-plane rotation,
both wheel units, signed coarse steps, reversal, zeroing, desktop geometry and
feature history, save/reopen, and exact Undo. Stereo checks require colored handle
pixels at projected locations and reject an offscreen negative. Panel/model
separation is checked in each eye after moving the model with ordinary grips.

Evidence, including failed attempts, is retained under
`.development-artifacts/vr-twist-tour/`. Pass `--output <new-directory>` to select
an evidence directory. Submitted-eye captures and synthetic controller input do
not establish through-lens comfort.

Other checks:

- `just test-focused tests/test_vr_routes.py`
- `just test-focused tests/test_vr_tours.py`
- `cd frontend && npx vitest run src/scene/vr_bend.test.js`
- CTest `nadoc-vr-bend-panel`, `nadoc-vr-bend-viewer`, and
  `nadoc-vr-twist-viewer` (production controller methods and GL preview pixels).

Multi-selection uses the same exact scope, stale-selection guards, persistence,
and registered [Bend / Twist multi-selection regression](vr_bend.md#multi-selection-regression)
as Bend. One shared signed twist is applied to the selected union.
