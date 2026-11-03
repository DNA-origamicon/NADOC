---
name: strand-animations
description: "Canonical captured-pose strand animations; synthetic playground retired, incomplete invader targets fail closed"
metadata: 
  node_type: memory
  type: project
  originSessionId: f51cea7d-868c-4c82-bb3d-73b546fae23c
---

# Strand Animations Testing

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## Current placement contract — 2026-10-06

Native DNA bead and slab placement has one backend authority. The standalone
`/strand-anim.html` playground is unavailable because it had no authoritative
document geometry. Its three `geometry_{straight,helical,displacement}.js`
generators and `buildStrandGeometry` export were deleted. The page displays an
explicit unavailable message and never creates a molecular preview. Earlier
claims below that its radius/groove/offset matched NADOC are historical and must
not be used to restore those removed positioning rules.

The main document's `overhang_strand_anim.js` and `overhang_unzip_overlay.js`
remain functional for captured molecular poses. `native_pose_transport.js`
transports each complete captured bead/base/slab pose by a rigid rotation and
translation; it never chooses a radius, groove, or bead-to-slab offset. Both
slab center and orientation move with the nucleotide, including hinge rotations.
`helixCtrl.setBeadOverrides` accepts complete validated poses and preserves
`copy_k` identity. Partial position/normal updates now fail before any displayed
matrix changes. Clear restores exact captured poses.

The lightweight `strand_renderer.js` accepts
`[{role, nucleotides: [complete_authoritative_pose, ...]}]`. It renders supplied
slab centers/quaternions directly. The old `{pos,tan,bn}` contract and independent
slab placement function have been removed.

Displacement previews require an actual captured, backend-authorized opposite
pose for every target site, including the toehold and loop-copy identity.
When any target is absent, animation stops with an explicit placement-integrity
error and report before moving or drawing molecules. It must never construct
an absent complement from averaged radius/groove or approximate a slab pose.
A future prospective-target backend API can support such previews; no fallback
is authorized. Existing overhang/binder unzip animation remains available.

Regression coverage lives in
`frontend/src/scene/strand_animation.native_placement.test.js`, with fixed
canonical Manual_Benchy poses in `fixtures/native_animation_positions.json`.
It checks actual renderer matrices, captured internal registration during
animation, hinge transport, exact restoration, loop copies, missing invader
target failure, and deletion of the synthetic generators. These tests use the
durable native-placement review gate; a passing rerun does not clear incidents.

<a id="historical-implementation-notes-superseded-where-they-describe-placement"></a>
- [Historical implementation notes (superseded where they describe placement)](details/project_strand_animations/01-historical-implementation-notes-superseded-where-they-describe-pl.md#historical-implementation-notes-superseded-where-they-describe-placement)

<a id="-integration-handoff-read-this-first--for-dropping-into-the-main-animation-toolset"></a>
- [⇒ Integration handoff (read this first — for dropping into the main animation toolset)](details/project_strand_animations/01-historical-implementation-notes-superseded-where-they-describe-pl.md#-integration-handoff-read-this-first--for-dropping-into-the-main-animation-toolset)

<a id="architecture-all-under-frontendsrcstrand-anim"></a>
- [Architecture (all under `frontend/src/strand-anim/`)](details/project_strand_animations/01-historical-implementation-notes-superseded-where-they-describe-pl.md#architecture-all-under-frontendsrcstrand-anim)

<a id="model"></a>
- [Model](details/project_strand_animations/01-historical-implementation-notes-superseded-where-they-describe-pl.md#model)

<a id="status--shipped-2026-05-29-both-forms-ball-and-slab"></a>
- [Status — shipped 2026-05-29 (both forms, ball-and-slab)](details/project_strand_animations/01-historical-implementation-notes-superseded-where-they-describe-pl.md#status--shipped-2026-05-29-both-forms-ball-and-slab)

<a id="phase-2--shipped-2026-05-29-bindunbind-φ-animation-in-the-design-editor"></a>
- [Phase 2 — SHIPPED 2026-05-29 (bind/unbind φ animation in the design editor)](details/project_strand_animations/01-historical-implementation-notes-superseded-where-they-describe-pl.md#phase-2--shipped-2026-05-29-bindunbind-φ-animation-in-the-design-editor)

<a id="phase-3--strand-animation-sidebar-section-on-real-overhangbinder-2026-05-29"></a>
- [Phase 3 — "Strand Animation" sidebar section on REAL overhang+binder (2026-05-29)](details/project_strand_animations/02-phase-3--strand-animation-sidebar-section-on-real-overhangbinder.md#phase-3--strand-animation-sidebar-section-on-real-overhangbinder-2026-05-29)

- [Phase 3 — "Strand Animation" sidebar section on REAL overhang+binder (2026-05-29) — continued detail](details/project_strand_animations/02-phase-3--strand-animation-sidebar-section-on-real-overhangbinder.md)

<a id="phase-4--rich-strand-anim--keyframe-timeline-integration-2026-05-30"></a>
- [Phase 4 — Rich strand-anim → keyframe timeline integration (2026-05-30)](details/project_strand_animations/03-phase-4--rich-strand-anim--keyframe-timeline-integration-2026-05.md#phase-4--rich-strand-anim--keyframe-timeline-integration-2026-05-30)

## Next (Phase 3 sandbox, deferred)
- Live anchor tracking for the unzip overlay (currently play-start/static).
- Per-driver `endFrom`/melt authoring controls; strand-displacement scenario as a driver.
- Assembly-scope bind/unbind (cross-part); part-context (assembly) authoring.
- Possible polish: 5′ cube markers for polarity, scale slab reach with W, real 150° minor groove option, sequence/base-letter coloring, auto camera-tilt on helical toggle so the 3D spiral reads without manual orbit, debug overlay (AxesHelper/junction marker).
