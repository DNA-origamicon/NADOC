---
name: project_mrdna_panel
description: "mrDNA/ARBD coarse-grained relaxation job panel in the Dynamics tab — single Run button + display toggles, mirroring the oxDNA panel"
metadata: 
  node_type: memory
  type: project
  originSessionId: dd668d19-36d4-447d-b2af-4eda01216418
---

# mrDNA relaxation panel (Dynamics tab)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## Native-fixture/decoder maintenance (2026-09-19)

Native extension/extra-base tests now build the required nucleotide manifest with
the parameterized production bridge and surface ARBD/decoder errors as failures.
Fine-resolution extension smoke tests retain their root-distance assertions.
Coarse output without orientation particles uses the existing translation-only
mapping; it must not construct a unique fine nucleotide orientation for a bead
that represents several nucleotides. Focused native cases pass.

A newly runnable legacy per-helix zero-step oracle still reports mean position
error 0.691 nm against its unchanged 0.10 nm limit. `build_md_seed_override` still
uses that decoder, so it cannot simply be called obsolete. Scientific review is
pending; no phase constants, geometry or tolerance changes have been made.

October 30 diagnosis: the current list reader seeds DNA particles at paired CG
input midpoints; the manifest decoder instead subtracts native O5′ midpoints and
applies an unmatched 90° frame conversion. A read-only fine zero-step probe
reproduces both decoder errors. Isolated matched-frame transport recovers CG
sites to 7.24e-6 nm, but phase/nonzero atomistic and extended-site qualification
remain open. No production decoder is changed. See
[[project_mrdna_bead_model]] and `experiments/mrdna_zero_step_review.py`.

<a id="visualization-card-2026-08-12"></a>
- [Visualization card (2026-08-12)](details/project_mrdna_panel/01-visualization-card-2026-08-12.md#visualization-card-2026-08-12)

<a id="fine-job-progress-and-restart-recovery-2026-08-12"></a>
- [Fine-job progress and restart recovery (2026-08-12)](details/project_mrdna_panel/01-visualization-card-2026-08-12.md#fine-job-progress-and-restart-recovery-2026-08-12)

## The single-button UX decision (user, 2026-07-02)
mrDNA's **coarse** stage begins from an energy minimisation, so it IS the
relaxation — there's no need for a separate "relax then run" split. So: **one
"Run mrDNA relaxation" button, one stage (`coarse`, `fine_steps=0`), no
production/field/child-job machinery.** The original display offered independent
deform + CG-cloud toggles; the 2026-08-12 visualization card superseded them with
mutually exclusive modes.

<a id="architecture-mirrors-the-oxdna-trio-simplified-to-one-stage"></a>
- [Architecture (mirrors the oxDNA trio, simplified to one stage)](details/project_mrdna_panel/02-architecture-mirrors-the-oxdna-trio-simplified-to-one-stage.md#architecture-mirrors-the-oxdna-trio-simplified-to-one-stage)

<a id="frontend"></a>
- [Frontend](details/project_mrdna_panel/02-architecture-mirrors-the-oxdna-trio-simplified-to-one-stage.md#frontend)

<a id="validation"></a>
- [Validation](details/project_mrdna_panel/02-architecture-mirrors-the-oxdna-trio-simplified-to-one-stage.md#validation)

<a id="display-reconstruction--show-the-real-relaxed-shape-fix-2026-07-02"></a>
- [Display reconstruction — show the REAL relaxed shape (fix 2026-07-02)](details/project_mrdna_panel/02-architecture-mirrors-the-oxdna-trio-simplified-to-one-stage.md#display-reconstruction--show-the-real-relaxed-shape-fix-2026-07-02)

<a id="feature-coverage-skipsloopsoverhangslinkersextra-bases--audited-2026-07-02"></a>
- [Feature coverage (skips/loops/overhangs/linkers/extra-bases) — audited 2026-07-02](details/project_mrdna_panel/02-architecture-mirrors-the-oxdna-trio-simplified-to-one-stage.md#feature-coverage-skipsloopsoverhangslinkersextra-bases--audited-2026-07-02)

<a id="fine-stage-display-collapses-a-tight-bundle-helix--coarse-fallback-fixed-2026-07-04"></a>
- [Fine-stage display collapses a tight-bundle helix → coarse fallback (FIXED 2026-07-04)](details/project_mrdna_panel/03-fine-stage-display-collapses-a-tight-bundle-helix--coarse-fallbac.md#fine-stage-display-collapses-a-tight-bundle-helix--coarse-fallback-fixed-2026-07-04)

<a id="overstretched-backbone-bonds-partial-mis-assignment--same-coarse-fallback-generalised-2026-07-04"></a>
- [Overstretched backbone bonds (partial mis-assignment) → same coarse fallback, generalised (2026-07-04)](details/project_mrdna_panel/03-fine-stage-display-collapses-a-tight-bundle-helix--coarse-fallbac.md#overstretched-backbone-bonds-partial-mis-assignment--same-coarse-fallback-generalised-2026-07-04)

<a id="beadless-helix-end--flat-ring-fixed-at-the-source-by-straight-extrapolation-2026-07-04"></a>
- [Beadless helix-end → flat ring; fixed AT THE SOURCE by straight extrapolation (2026-07-04)](details/project_mrdna_panel/03-fine-stage-display-collapses-a-tight-bundle-helix--coarse-fallbac.md#beadless-helix-end--flat-ring-fixed-at-the-source-by-straight-extrapolation-2026-07-04)

<a id="far-end-single-stranded-scaffold-crossovers--stretched-bonds-fixed-by-ssdna-harvest--both-ends-anchor-2026-07-04"></a>
- [Far-end single-stranded scaffold crossovers → stretched bonds; fixed by ssDNA harvest + both-ends anchor (2026-07-04)](details/project_mrdna_panel/03-fine-stage-display-collapses-a-tight-bundle-helix--coarse-fallbac.md#far-end-single-stranded-scaffold-crossovers--stretched-bonds-fixed-by-ssdna-harvest--both-ends-anchor-2026-07-04)

<a id="curvature-checking-loopsskips--two-buttons--readout-2026-07-02"></a>
- [Curvature checking (loops/skips) — two buttons + readout (2026-07-02)](details/project_mrdna_panel/04-curvature-checking-loopsskips--two-buttons--readout-2026-07-02.md#curvature-checking-loopsskips--two-buttons--readout-2026-07-02)

<a id="md-seed-handoff-2026-07-02--seed-an-md-run-from-a-fine-stage-job"></a>
- [MD-seed handoff (2026-07-02) — seed an MD run from a fine-stage job](details/project_mrdna_panel/04-curvature-checking-loopsskips--two-buttons--readout-2026-07-02.md#md-seed-handoff-2026-07-02--seed-an-md-run-from-a-fine-stage-job)

<a id="seed-reconstructed-as-an-untwisted-ladder--impose-ideal-twist-around-the-relaxed-axis-fixed-2026-07-04"></a>
- [Seed reconstructed as an untwisted ladder → impose ideal twist around the relaxed axis (FIXED 2026-07-04)](details/project_mrdna_panel/04-curvature-checking-loopsskips--two-buttons--readout-2026-07-02.md#seed-reconstructed-as-an-untwisted-ladder--impose-ideal-twist-around-the-relaxed-axis-fixed-2026-07-04)

<a id="extra-base-atomistic-seed-bug--inline-threading-fixed-2026-07-04"></a>
- [Extra-base atomistic-seed bug — inline threading (FIXED 2026-07-04)](details/project_mrdna_panel/04-curvature-checking-loopsskips--two-buttons--readout-2026-07-02.md#extra-base-atomistic-seed-bug--inline-threading-fixed-2026-07-04)

## Three-Layer Law
mrDNA output is **Physical / display only** — relaxed positions deform the render
via `applyFemPositions` and draw the bead overlay; NEVER written into topology.
The MD-seed handoff is likewise Physical-layer: the relaxed structure is a
NAMD/GROMACS INPUT artifact, never topology. Same discipline as the oxDNA + MD displays.

See also: [[project_mrdna_arbd_setup]] (install), [[project_mrdna_bead_model]]
(1 bead/bp fine-stage caveat — but this panel uses the COARSE 5bp/bead stage),
[[project_md_engines_panel]] (mrDNA/ARBD install rows), [[feedback_cg_pipeline_lessons]].

## Periodic-boundary continuity (fixed 2026-08-12)

ARBD's default 5000 Å cell was only slightly longer than VoltronCoreArm (~4200 Å).
The coarse structure crossed a periodic face; mrDNA passed wrapped restart coordinates
directly into the fine bead regeneration, creating genuine 125–258 nm bonds. New jobs
set `model.dimensions` from the design bounds with 5000 Å clearance on every side.
All NADOC mrDNA trajectory consumers also graph-unwrap PSF-bonded components with
minimum-image edges before alignment, display reconstruction, ssDNA placement, or bead
extraction. Display cache version 9 regenerates older wrapped caches; a fine stage already
corrupted during handoff remains unusable, but the unwrapped coarse fallback is clean.
