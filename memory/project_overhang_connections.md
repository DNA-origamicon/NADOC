---
name: Overhangs Manager feature (overhang-overhaul branch)
description: Tools menu → Overhangs Manager (renamed 2026-04-30) — metadata + linker complement strands + 3D arc; selection-driven prepopulation; new StrandType.LINKER
type: project
originSessionId: 4eb5150c-d5c5-448a-9b7f-709c431b0162
---

# project overhang connections — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Branch: `overhang-overhaul` (off `master`, created 2026-04-29). First feature is **Overhangs Manager** (renamed from "Overhang Connections" 2026-04-30).

**UI / authoring flow lives in [[ct_tab]]** (Connection Types tab — selected-linker model, bridge_sequence field on `OverhangConnection`, live-computed Sequence column, 12 icon variants covering all 4 attach combos × {ss, ds}, dsDNA strand selection). This file documents the underlying **topology + geometry** generation; the tab file documents how the user interacts with it.

## Cylinder-rep rendering of linkers (2026-05-21)

All in [helix_renderer.js](../frontend/src/scene/helix_renderer.js) `buildHelixObjects` cylinder pass — so BOTH the per-design view AND the assembly linker group (which calls `buildHelixObjects` via `_rebuildLinkerHelices`) get it from one place.

- **Binding (complement) domains → half-cylinder, linker strand colour, opposite the overhang half.** A linker complement (`strand.strand_type === 'linker'` && helix NOT `__lnk__`) used to draw as a full white cylinder overlapping the overhang. Now deferred (`_deferredBindings`) and drawn into `iLinkerBindingCylinders` (GEO_HALF_CYL) using the paired **overhang's** captured pose (`_ovhgBuildXform`, keyed `helixId|lo|hi`) rolled π about the cyl axis (`_QUAT_ROLL_PI`) → overhang half (its colour) + binding half (linker colour) = one two-toned full duplex cylinder. The user explicitly chose "opposite half / split duplex" + "linker strand's own colour".
- **ds bridge → one simple full cylinder per `__lnk__` helix** in `iLinkerBridgeCylinders` (GEO_UNIT_CYL), spanning the bridge duplex axis recovered by **averaging the paired bridge beads at min/max bp** (the `__lnk__` helix is skipped in the axis-arrow loop, so it has no normal domain cylinder; built from `geometry` nucs so it tracks relax/cluster transforms on rebuild). ss bridges are untouched — still the FJC bead chain in `overhang_link_arcs.js`.
- Both meshes are dedicated + build-time-only (not woven into the revert/unfold/physics recompute passes); they re-track via the full rebuild that fires on any geometry change. Shown only at coarse LOD (level 2), wired in `setDetailLevel`.
- **Fallback** (no paired overhang in this `buildHelixObjects` call — e.g. the **assembly linker group**, whose synthetic design has the complement but not the part's overhang; or a curved overhang helix): place the binding half from the complement's own arrow + π-roll. Visually fine; not guaranteed perfectly opposite the part-clone overhang since that's a different renderer path.
- **Assembly LOD:** `_rebuildLinkerHelices` ([assembly_renderer.js](../frontend/src/scene/assembly_renderer.js)) now builds the linker group at the rep the part instances use (`_CG_LOD[inst.representation]`, non-CG → cylinders) and calls `setDetailLevel` on the captured `linkerHelixCtrl` (stored on `_linkerGroup.userData.helixCtrl`). Before, the linker group was always built at 'full' (beads) regardless of the assembly rep. A rep change re-runs `rebuild → rebuildLinkers`, so the linker LOD self-syncs.
- **Latent bug fixed in passing:** ds bridge domains were previously COUNTED into `_domainCylCount` but never emitted (no arrow) → phantom zero-matrix cylinder at the origin in cylinder rep. Now excluded from the count.
- Verified in-app (Playwright `e2e/linker_cylinder_rep.spec.js` + screenshots): `dsdna-link-sel-test.nadoc` + `Ultimate Polymer Hinge.nadoc` (parts) and `Linker_Assem_test2.nass` (assembly). `__NADOC_DBG__` now also exposes `controls` + `animateCameraTo` for camera framing in tests.

<a id="ds-linker-bridge--cg-vs-atomistic-alignment-2026-05-05"></a>
- [ds-linker bridge — CG vs atomistic alignment (2026-05-05)](details/project_overhang_connections/01-ds-linker-bridge--cg-vs-atomistic-alignment-2026-05-05.md#ds-linker-bridge--cg-vs-atomistic-alignment-2026-05-05)

<a id="data-model"></a>
- [Data model](details/project_overhang_connections/01-ds-linker-bridge--cg-vs-atomistic-alignment-2026-05-05.md#data-model)

## Generation rules — CRITICAL

`generate_linker_topology(design, conn)` in [backend/core/lattice.py](../backend/core/lattice.py) produces the SAME complement domains for ss and ds; only the bridge differs:

| | ss | ds |
|---|---|---|
| Strand `__lnk__<id>__a` | `[complement on OH-A real helix]` | `[complement on OH-A real helix, bridge FORWARD on virtual]` |
| Strand `__lnk__<id>__b` | `[complement on OH-B real helix]` | `[complement on OH-B real helix, bridge REVERSE on virtual]` |
| Virtual `__lnk__<id>` helix | not created | created (length = `linker_bp`) |

**Complement domain construction** (`_make_complement_domain`): same `helix_id` and bp range as the OH domain, but `start_bp`/`end_bp` SWAPPED and `direction` flipped. This puts the linker bead at the same `(helix_id, bp_index)` as the OH bead but with opposite `direction` — antiparallel pairing.

**Why ss has no virtual helix in v1:** the bridge is purely the frontend arc; ss-bridge strand topology will be added later when arcs are materialised into real ss/ds strands (per user direction).

**Length conversion** (`_length_value_to_bp`): `bp = round(value)`; `nm = round(value / BDNA_RISE_PER_BP)` (0.334 nm/bp). Same conversion for ss and ds (pragmatic v1 — ssDNA contour length differs but not modelled).

<a id="validation-rules--unified-watson-crick-polarity-test-2026-05-02"></a>
- [Validation rules — unified Watson-Crick polarity test (2026-05-02)](details/project_overhang_connections/02-validation-rules--unified-watson-crick-polarity-test-2026-05-02.md#validation-rules--unified-watson-crick-polarity-test-2026-05-02)

## Cross-cutting LINKER policy

| Subsystem | Behaviour |
|---|---|
| `Design.scaffold()` | naturally excludes (LINKER ≠ SCAFFOLD) |
| Validator | skips LINKER strands in helix-ref + sequence-length + loop-strand checks |
| Geometry pipeline | `_geometry_for_helices` skips `__lnk__` helices in helix loop. `_strand_nucleotide_info` does **NOT** skip LINKER strands (critical — needed so complement nucs render) |
| Default color | `#ffffff` (set on strand creation) |
| Auto-scaffold / auto-crossover / autobreak / cluster autodetect / sequence assignment / caDNAno+scadnano export / oxDNA / atomistic | **NOT YET** updated to skip LINKER. Defer until a tool is run on a design with linkers and breaks. Forced ligation explicitly allowed. |
| Undo/redo | none. `FeatureLogEntry` discriminator not extended. |
| Sequence | linker strands stay `sequence=None` → 'N's at assignment time. No auto-update on overhang sequence change. |

<a id="api"></a>
- [API](details/project_overhang_connections/03-api.md#api)

<a id="frontend"></a>
- [Frontend](details/project_overhang_connections/03-api.md#frontend)

<a id="critical-gotcha--currentgeometry-shape"></a>
- [Critical gotcha — `currentGeometry` shape](details/project_overhang_connections/03-api.md#critical-gotcha--currentgeometry-shape)

<a id="debug--tests"></a>
- [Debug + tests](details/project_overhang_connections/03-api.md#debug--tests)

<a id="files-modified--created"></a>
- [Files modified / created](details/project_overhang_connections/03-api.md#files-modified--created)

<a id="status"></a>
- [Status](details/project_overhang_connections/03-api.md#status)

## Next steps (deferred)

<a id="1-ss-linker-replace-tube-arc-with-rendered-bridge-nucleotides--resolved-2026-05-11"></a>
- [1. ss linker: replace tube arc with rendered bridge nucleotides — RESOLVED 2026-05-11](details/project_overhang_connections/04-1-ss-linker-replace-tube-arc-with-rendered-bridge-nucleotides--re.md#1-ss-linker-replace-tube-arc-with-rendered-bridge-nucleotides--resolved-2026-05-11)

### 2. Other deferred work

3. Linker sequence generation (currently `None` → 'N').
4. Add `LINKER` skip guards to auto-scaffold / auto-crossover / autobreak / cluster autodetect / sequence assignment / caDNAno+scadnano export when those tools are run on linker-bearing designs.
5. Cross-part / assembly-level connections.
6. Undo/redo via `FeatureLogEntry` discriminator extension.

<a id="relax-linker-shipped-2026-05-01-ds--1-dof-only"></a>
- [Relax Linker (shipped 2026-05-01, ds + 1-DOF only)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#relax-linker-shipped-2026-05-01-ds--1-dof-only)

<a id="joint-angle-range-re-added-2026-05-09"></a>
- [Joint angle range (re-added 2026-05-09)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#joint-angle-range-re-added-2026-05-09)

<a id="future-relax-v2"></a>
- [Future: relax v2](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#future-relax-v2)

<a id="ds-linker-bridge--real-geometry-pipeline-shipped-2026-05-03"></a>
- [ds-linker bridge — real geometry pipeline (shipped 2026-05-03)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#ds-linker-bridge--real-geometry-pipeline-shipped-2026-05-03)

<a id="anchor-lookup-rule-corrected-2026-05-03"></a>
- [Anchor lookup rule (corrected 2026-05-03)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#anchor-lookup-rule-corrected-2026-05-03)

<a id="bridge-axis-offset-for-native-b-dna-radius"></a>
- [Bridge axis offset for native B-DNA radius](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#bridge-axis-offset-for-native-b-dna-radius)

<a id="cross-helix-arc-dedup"></a>
- [Cross-helix arc dedup](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#cross-helix-arc-dedup)

<a id="right-click-on-bridge-bead--linker-context-menu"></a>
- [Right-click on bridge bead → linker context menu](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#right-click-on-bridge-bead--linker-context-menu)

<a id="debug-overlay-help--show-linker-anchor-debug"></a>
- [Debug overlay (Help → "Show Linker Anchor Debug")](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#debug-overlay-help--show-linker-anchor-debug)

<a id="critical-gotcha-for-future-linker-work"></a>
- [Critical gotcha for future linker work](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#critical-gotcha-for-future-linker-work)

<a id="relax-loss-must-be-chord-magnitude-only-decoupled-from-bridge-offset"></a>
- [Relax loss MUST be chord-magnitude-only (decoupled from bridge offset)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#relax-loss-must-be-chord-magnitude-only-decoupled-from-bridge-offset)

<a id="multi-minima-selection-in-1-dof-relax-shipped-2026-05-03-commit-7d8e093"></a>
- [Multi-minima selection in 1-DOF relax (shipped 2026-05-03, commit 7d8e093)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#multi-minima-selection-in-1-dof-relax-shipped-2026-05-03-commit-7d8e093)

<a id="bridge-axis-side--_bridge_phase_offset-shipped-2026-05-03-commit-7d8e093"></a>
- [Bridge axis side / `_BRIDGE_PHASE_OFFSET` (shipped 2026-05-03, commit 7d8e093)](details/project_overhang_connections/05-relax-linker-shipped-2026-05-01-ds--1-dof-only.md#bridge-axis-side--_bridge_phase_offset-shipped-2026-05-03-commit-7d8e093)

### Critical gotchas summary

1. **Three anchor implementations must agree** — `_anchor_pos_and_normal` (linker_relax), `_anchor_for` inside `_emit_bridge_nucs` (crud), `_linkerAttachAnchor` (overhang_link_arcs.js).
2. **`bridge_axis_geometry` is the single source of truth for bridge axis math** — don't duplicate.
3. **Relax loss MUST be chord-magnitude-only** — folding boundary offset in creates a degenerate `chord ≈ 0` minimum.
4. **`_BRIDGE_PHASE_OFFSET` must match across `_bridge_boundary_radials` and `_emit_bridge_nucs`** — diverging breaks geometric self-consistency.
5. **`_optimize_angle` enumerates ALL grid minima for 1-DOF, not just the global** — there are typically two equivalent chord-minima per joint period; the smaller-|θ| one usually avoids cluster clashes.
6. **JS `_makeDsLinkerMeshes` only draws connector arcs** — re-adding bridge mesh synthesis double-renders.
7. **OH rotation must be co-applied to ALL binding-partner domains** (updated 2026-06-29) — `apply_overhang_rotation_if_needed` (deformation.py) builds the synthetic Layer-1 transform `domain_ids` from the OH domain PLUS every partner from `_overhang_binding_partner_refs` (renamed from `_linker_complement_domain_refs`). The predicate now matches **`d.binds_overhang_id == oh_domain.overhang_id`** (legacy `strand_type == LINKER` fallback), NOT strand type — so it co-rotates LINKER complements, standalone OH_BINDER strands, AND end-to-root binders spliced into a **STAPLE** strand (`apply_end_to_root_binder`; STAPLE-typed, so the old `strand_type == LINKER` filter missed them and they rendered un-rotated). A binder extending past the OH on the same helix (toehold) rides along because the domain mask uses the binder's OWN full bp range. Layer-2 (`_linker_complement_for_bp_range`, sub-domain θ/φ chains) is deliberately left LINKER-only (slice-truncation would shear a past-the-tip binder). Frontend live-preview parity: `ovhgBinderDomainIds` (design_queries.js, keyed on `binds_overhang_id`) is folded into all 4 orientation-panel preview sites via `domsForOverhang`. Regressions: `tests/test_overhang_linker_rotation.py` + `tests/test_overhang_binder_rotation.py` (OH_BINDER-with-toehold + end-to-root, both proven red under the old filter); `design_queries.test.js` (`ovhgBinderDomainIds`).
8. **`patch_overhang` extrude branch must look up junction bp from `design.crossovers`** — never assume "junction at helix bp_start". −Z extrudes have the junction at the helix's high bp end. Resize the *other* domain endpoint and rebuild axis around the invariant junction world-position. Regression: `tests/test_overhang_sequence_resize.py`.
