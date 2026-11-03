
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
