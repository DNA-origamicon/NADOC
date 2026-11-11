
# Mixed Representation — per-region representation for a single structure

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Status: **SHIPPED — PATH A COMPLETE** (probe-verified 2026-07-28). **Rank: P2 as of 2026-08-01**
(was P1). The renderer coverage holes that made it P1 — deformed/curved cylinders, impostor
beads, binding cylinders — are CLOSED, and the suspected photo-export bug was found and fixed
(photo mode dropped the per-instance alpha patch entirely). What is left is the un-guarded
photo-mode/override interaction, per-region extra bases, a test gap, and in-app verification —
real, but none of them silently wrong geometry.

## Zoom volume entry list (2026-11-10)

Zoom Volumes now owns a scrollable list of independent entries. Add captures the
current part or assembly selection; each row can rename, replace its selected
entities, change representation/coloring/opacity, toggle its inset and outline,
or delete itself. Inset options retain position, size, connector lines and nearby
structure/transparency controls. Master power/eye controls affect all entries.
View and zoom volume rows share icons, list bounds, input styling and control layout.
After integrating upstream `84227195`, every inset also owns its +/− camera zoom
(1.25× steps, clamped to ±8). Zoom survives representation rebuilds and does not
change other insets, the main camera, or selection bounds. Submodel-box events
create/update one dedicated entry; they never retarget the entire list. Upstream
trajectory synchronization is retained inside each entry.
One lazy WebGL renderer serves separate entry canvases; deleting an entry aborts
its build and removes its scene helpers and frame callback.
Zoom definitions now persist as display-only `zoom_volumes` in parts and assemblies,
including stable IDs, targets, inset settings and `zoom_step`. Serial compact metadata
writes retain the newest edit across stale full-document responses. Document switching
restores saved definitions. Keyframe selectors continue to reference stable volume IDs;
preview/playback visibility overrides do not change the saved lens or working visibility.
Insets live under the viewport so fullscreen presentation includes them. Editor GIF/WebM
and photo frame sessions composite fresh inset renders after awaiting builds, using the
same saved magnification and live trajectory geometry. This adds no authoring features.
Persistence/export validation: 10,290 frontend tests passed, one skipped (904 files);
85 focused backend checks passed. The backend selector chose FULL for shared models;
that broad sweep remains deferred. Browser preview/presentation/export-composition
and independent-entry/rapid-zoom workflows passed. Smoke: 22 passed, two skipped,
known assembly scaffold-mesh setup timeout. Cleanup verified; `main.js` LOC delta 0.
Evidence: `.development-artifacts/zoom-volume-persistence/validation.json`.

Validation after the pull: 10,261 frontend tests passed, one skipped; 15 focused
checks and the real-browser multi-entry workflow passed, including rendered
magnification, limits, all four corners and independent zoom settings. Lint passed.
Smoke repeated the two pre-pull setup/progress failures (21 passed, two skipped).
Cleanup and compact results: `.development-artifacts/zoom-volume-pull/validation.json`.

## Explicit presentation checkpoints (2026-11-06)

**Save to feature log** at the top of View Volumes records the complete volume list,
including bounds, rotation, representation, coloring, opacity, enablement and outline
visibility. Ordinary edits retain their existing autosave behavior. Parts and assemblies
use `view-volumes-state`; the **Annotations and view volumes** history filter defaults
off. Seeking and animation pins restore the latest saved volume configuration, empty
before its first checkpoint. Playback overrides are transient and restore on stop.
The matching annotation action records its own channel independently.

## Multi-view / multi-overlay crash (2026-11-09)

Reproduced on existing `workspace/duplex.nadoc`: recursive scene cloning left
`Box3Helper.box` undefined, so framing and rendering threw `isEmpty` and stopped
the animation loop. The shared comparison copier now copies box state, excludes
TransformControls before cloning, and retains helper-owned child references
without duplicating ArrowHelper geometry. Geometry/material copies remain isolated.
Split-view fitting now accounts for the narrowest pane's aspect/FOV; both modes
pass CSS-pixel viewport/scissor dimensions to Three.js (which applies pixel ratio).

Read-only browser regression: `frontend/e2e/duplex_comparison.spec.js`; verified
2/3/4 panes, overlay switching, Full selection and closing at 2x display scaling,
with no page errors. Inspected screenshots show the entire duplex in both split
panes and aligned overlay layers. Optional `NADOC_COMPARISON_REVIEW=1` holds
temporary screenshots for inspection; the standard reporter removes them.
No saved structures were created or changed. Verified cleanup of reports,
test credentials, playback scratch and session artifacts. Focused unit tests: 19 passed.
Final `just test-frontend`: 881 files passed; 10,170 tests passed, 1 skipped.

Presentation follow-up: `frontend/e2e/duplex_overlay_share.spec.js` passed against
a real loopback presentation host and separate guest browser. Verified Full +
Cylinder layers, opacity/separation, guest orbit, live change to three layers
(including mrDNA Fine), and disabling overlay on the same invitation. Guest pixels
were inspected; no page errors. Sharing-focused unit tests: 32 passed. This checks
local presentation transport/rendering, not external DNS/Funnel connectivity.
Build `frontend/dist` before this test: the bridge replaces hosts whose viewer
build differs. Wait for Start to finish before opening the guest invitation.
The first setup attempts exposed that build mismatch, an initial `/scene` observer
filter that missed requests without queries, and an early invitation-open race;
the final regression corrects those test setup issues. No production sharing
code changes were needed. Test host, credentials, captures and temporary build
were cleaned; no design files were authored or modified.

## Crossover extras in view volumes (2026-10-16)

Full and Beads volume layers now build the shared crossover-extra meshes alongside
helix geometry (`view_volume_extras.js`). Previously the native extras yielded to
the volume's column mask, while its independent CG layer omitted their replacement.
The same layer builder serves assembly volumes. Full shows beads, slabs and rods;
Beads shows the backbone beads/connectors. Both endpoints must belong to the layer,
matching the existing crossover visibility policy. Local colors, opacity, cluster
alpha and hidden/reference endpoints are applied to the independent meshes.
Cylinders still omit individual residues by design. VDW, Ball & Stick, Stick and
Surface already retain extra atoms via their source-column metadata.
Validation: 52 focused tests pass. Full frontend suite: 7,961 passed, 1 skipped,
6 failures in unchanged viewer disposal (`_savedInner` is undefined). The browser
regression is retained in `frontend/e2e/view_volume_extras.spec.js`, but its run
was blocked before rendering by the persistent placement-integrity review gate.
**Not verified in app**; pixel/representation-matrix assertions have not executed.
Logs: `.development-artifacts/volume-extras/`. This change covers spatial view
volumes; legacy per-domain overrides and physical headset verification are separate.

## Independent volume display (2026-09-24)

Each volume persists its own `coloring` scheme (legacy records default to strand).
The card offers schemes supported by the selected representation. Dedicated CG,
atomistic and surface layers preserve independent coloring/opacity even when
volumes overlap; global coloring changes do not override them. Native CG yields
inside their column footprint. Membership falls back to current display geometry
when coarse global LOD has no backbone instances.
Skipped columns have no nucleotide positions, but domain cylinders still span
them. Volume membership supplies display-only samples interpolated from the
surrounding live column centers, preventing one-bp cylinder remnants inside heavy
volumes (reproduced on `3x6SQ_norm_skips`, h_XY_0_1:38, h_XY_2_1:29, h_XY_2_0:27).

Hull Prism opens the enabled volume's projected box/hexagonal outline along the
camera ray, so even an entirely enclosed volume remains visible. The mask follows
rotation, works in shared snapshots (package v6 / `hull-cutouts-v1`), and disappears
when the volume is disabled. Multi-overlay starts with the current representation;
additional default layers use cylinders. Validation and limitations are recorded
in `docs/audits/view_volume_display_20260924.md`.

<a id="assembly-visualization-2026-09-27"></a>
- [Assembly visualization (2026-09-27)](details/project_mixed_representation/01-assembly-visualization-2026-09-27.md#assembly-visualization-2026-09-27)

## Presentation surface policy and cancellation (2026-10-01)

Detail Surface is unavailable while the editor presents; Quick Surface remains
available. The menu/sidebar and surface transports enforce the ephemeral sharing
state. Leaving a heavy representation cancels outstanding surface transports and
cooperatively cancels backend work at a surface checkpoint. Cancel is exposed in
the surface progress popup and cancels the pending surface batch. Generation checks
prevent old heavy responses from restoring an obsolete selection, including
assembly instance responses; unneeded global atom downloads abort on switch-off.
Pinned region/volume atom consumers retain their shared load. See
`project_public_sharing.md` for validation and the native-call cancellation limit.

<a id="sharing-display-state-2026-09-24"></a>
- [Sharing display state (2026-09-24)](details/project_mixed_representation/02-sharing-display-state-2026-09-24.md#sharing-display-state-2026-09-24)

<a id="spatial-view-volumes-path-b-shipped-2026-09-01"></a>
- [Spatial View Volumes (Path B, shipped 2026-09-01)](details/project_mixed_representation/02-sharing-display-state-2026-09-24.md#spatial-view-volumes-path-b-shipped-2026-09-01)

<a id="bug-global-cylinders--region-override-2026-06-02--fixed"></a>
- [BUG: global-cylinders + region override (2026-06-02) — fixed](details/project_mixed_representation/02-sharing-display-state-2026-09-24.md#bug-global-cylinders--region-override-2026-06-02--fixed)

<a id="overhang--bridge-as-independent-per-region-reps-2026-06-02"></a>
- [Overhang + bridge as independent per-region reps (2026-06-02)](details/project_mixed_representation/02-sharing-display-state-2026-09-24.md#overhang--bridge-as-independent-per-region-reps-2026-06-02)

<a id="linker-bridge-cylinder-selectable-2026-06-02"></a>
- [Linker bridge cylinder selectable (2026-06-02)](details/project_mixed_representation/02-sharing-display-state-2026-09-24.md#linker-bridge-cylinder-selectable-2026-06-02)

<a id="region-selection-unified-through-_handlebeadhit-2026-06-02"></a>
- [Region selection unified through _handleBeadHit (2026-06-02)](details/project_mixed_representation/03-region-selection-unified-through-_handlebeadhit-2026-06-02.md#region-selection-unified-through-_handlebeadhit-2026-06-02)

<a id="rep-menu-flyout-submenu--non-standard-elements-2026-06-02"></a>
- [Rep menu: flyout submenu + non-standard elements (2026-06-02)](details/project_mixed_representation/03-region-selection-unified-through-_handlebeadhit-2026-06-02.md#rep-menu-flyout-submenu--non-standard-elements-2026-06-02)

<a id="surface--atomistic-as-per-region-reps-2026-06-02"></a>
- [Surface + atomistic as per-region reps (2026-06-02)](details/project_mixed_representation/03-region-selection-unified-through-_handlebeadhit-2026-06-02.md#surface--atomistic-as-per-region-reps-2026-06-02)

<a id="per-domain-cylinder-conversion--cylinder-aware-selection-2026-06-02"></a>
- [Per-domain cylinder conversion + cylinder-aware selection (2026-06-02)](details/project_mixed_representation/03-region-selection-unified-through-_handlebeadhit-2026-06-02.md#per-domain-cylinder-conversion--cylinder-aware-selection-2026-06-02)

<a id="pivot-to-column-based-resolution-2026-06-02--fixes-two-bugs"></a>
- [PIVOT to column-based resolution (2026-06-02) — fixes two bugs](details/project_mixed_representation/03-region-selection-unified-through-_handlebeadhit-2026-06-02.md#pivot-to-column-based-resolution-2026-06-02--fixes-two-bugs)

<a id="progress-2026-06-02"></a>
- [Progress (2026-06-02)](details/project_mixed_representation/04-progress-2026-06-02.md#progress-2026-06-02)

<a id="original-plan-below"></a>
- [Original plan below](details/project_mixed_representation/04-progress-2026-06-02.md#original-plan-below)

<a id="goal--use-case"></a>
- [Goal / use case](details/project_mixed_representation/04-progress-2026-06-02.md#goal--use-case)

## Decisions locked (2026-06-02, with user)

- A selectors: **strand(s)** and **cluster(s)**. (Not helix/domain in first cut.)
- Override rep palette: **cylinders** and **full beads+slabs** only. (No hull/atomistic/surface
  in overrides yet — those stay global-only for now.)
- Base layer = the existing global representation. Overrides sit on top.
- A before B, but **the keystone below is mandatory in A** so B drops in.

<a id="todays-constraint-why-this-is-new-capability"></a>
- [Today's constraint (why this is new capability)](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#todays-constraint-why-this-is-new-capability)

<a id="keystone-the-decision-that-makes-b-free"></a>
- [KEYSTONE (the decision that makes B free)](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#keystone-the-decision-that-makes-b-free)

<a id="architecture"></a>
- [Architecture](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#architecture)

<a id="1-data-model-saved-display-state-never-mutates-topology"></a>
- [1. Data model (saved display state, never mutates topology)](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#1-data-model-saved-display-state-never-mutates-topology)

<a id="2-resolution-pure-function-the-reusable-core"></a>
- [2. Resolution (pure function, the reusable core)](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#2-resolution-pure-function-the-reusable-core)

<a id="3-segmentation"></a>
- [3. Segmentation](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#3-segmentation)

<a id="4-rendering"></a>
- [4. Rendering](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#4-rendering)

<a id="5-ui"></a>
- [5. UI](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#5-ui)

<a id="required-touch-point--photo-mode"></a>
- [Required touch point — photo mode](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#required-touch-point--photo-mode)

<a id="suggested-implementation-order"></a>
- [Suggested implementation order](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#suggested-implementation-order)

<a id="test-points"></a>
- [Test points](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#test-points)

<a id="open-questions--gotchas"></a>
- [Open questions / gotchas](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#open-questions--gotchas)

<a id="related"></a>
- [Related](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#related)

<a id="per-region-axis-lines--crossover-arcs-follow-the-rep-shipped-2026-06-02"></a>
- [Per-region AXIS LINES + CROSSOVER ARCS follow the rep (shipped 2026-06-02)](details/project_mixed_representation/05-todays-constraint-why-this-is-new-capability.md#per-region-axis-lines--crossover-arcs-follow-the-rep-shipped-2026-06-02)

## Open items (rewritten 2026-07-28 against a codebase probe — this is the live list)

**Rank: P1.** Feature ships; these are the holes. Ordered worst-first.

> **2026-08-01 — item 6 (extra-base beads) is now half-closed.** They are still not *per-region*,
> but they are no longer invisible to the alpha/colour channel: `design_renderer` gained
> `_applyXoverClusterAlpha()` (lazy `installInstanceAlpha` on the three xover meshes) and a
> `'cluster'` branch in `_applyXoverColoring`. Wiring per-*region* overrides through the same two
> functions is now a small job rather than a new mechanism.
>
> **2026-08-01 — items 3, 4 and 5 are DONE.** They were fixed alongside per-cluster opacity,
> which rides the same `instanceAlpha` channel, so one fix served both features:
> - **3 (deformed/curved cylinders)** — the deform cross-fade owned `material.opacity`
>   absolutely, so any per-domain factor was clobbered on the next lerp frame. It is now a
>   compositor (`_fadeCurvedTube` stores the cross-fade base, `_refreshCurvedAlpha` re-applies
>   it against the current factors). `_curvedDomainCylData` / `_curvedOvhgCylData` and the tube
>   meshes' `userData` gained `domainIndex` + `bp_lo`/`bp_hi`, and `_effCol`/`_cylRepVis` were
>   hoisted to closure scope so the curved path uses the SAME column test as the straight one.
>   **Per-region overrides now reach deformed geometry.**
> - **4 (impostor beads)** — `iSpheres`/`iFluoros` are no longer skipped. The alpha patch is
>   composed inside `makeImpostorPhongMaterial` rather than assigned over it (an assignment
>   would have wiped the billboard patch); opt-in via `enableImpostorInstanceAlpha`.
> - **5 (`iLinkerBindingCylinders`)** — had no instance→domain array at all; `_bindingCylData`
>   now exists and the mesh is installed + written. Still not *column*-driven ("dsDNA only for
>   now" stands), but it fades with its cluster.
>
> The three absolute writers were also collapsed into one compositor: reference ghosting ×
> override visibility × cluster opacity multiply into one attribute, so a fourth factor is a new
> term rather than a fourth sweep that clobbers the other three. See `.claude/rules/rendering.md`
> for the full contract. **Remaining: items 2, 6, 7, 8** — photo mode still does not read
> `representation_overrides` (2), extra bases are not per-region though they now take cluster
> colour/alpha (6), `representation_overrides.js` still has no direct vitest (7), and no
> real-mouse-click verification (8).

- [Open items (rewritten 2026-07-28 against a codebase probe — this is the live list) — continued detail](details/project_mixed_representation/06-open-items-rewritten-2026-07-28-against-a-codebase-probe--this-is.md)

<a id="view-volume-interaction-contract-2026-09-01"></a>
- [View volume interaction contract (2026-09-01)](details/project_mixed_representation/06-open-items-rewritten-2026-07-28-against-a-codebase-probe--this-is.md#view-volume-interaction-contract-2026-09-01)
