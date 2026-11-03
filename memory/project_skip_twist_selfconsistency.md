---
name: project_skip_twist_selfconsistency
description: Self-consistency loop that tunes square-lattice skips until the simulated mean matches the straight analytic geometry (option a)
metadata:
  type: project
---

# Skip/loop self-consistency validation loop (option a)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Goal (user, 2026-06-25): validate that the geometry a square-lattice design *depicts*
is what the sequence design *actually produces* — and iterate skip placement until the
oxDNA time-averaged structure matches the straight analytic geometry within a tolerance.
First target: square-lattice bundles that need skips to cancel global twist. Proxy for
loop mechanics = `2x3x40` seamless; full-scale validation = `3x6x400` seamless.

**Option (a)** = the target IS the design's own analytic (B-DNA) geometry; the loop
checks the relaxed mean against it (not against an external CAD shape).

<a id="architecture-build--relax--produce--measure--adjust--repeat"></a>
- [Architecture (build → relax → produce → measure → adjust → repeat)](details/project_skip_twist_selfconsistency/01-architecture-build--relax--produce--measure--adjust--repeat.md#architecture-build--relax--produce--measure--adjust--repeat)

## CRITICAL gotchas (cost real debugging — keep)

1. **Reference must be keyed like the SIMULATION, not the display.** The mean structure
   (`production_rmsf`/`read_configuration_full`) is keyed by the strand walk
   `_strand_nucleotide_order` + `resolved_nuc_map`. The render-feed `_geometry_for_design`
   disagrees on ~13% of keys (display-only phantom strands + a different `is_unpaired`
   convention). Building the reference from the display feed gave only 480/552 key overlap
   AND a false **−9° analytic twist**; building it via `resolved_nuc_map(design,
   _geometry_for_design(design, compact_skips=True))` over the strand-walk order gives
   100% overlap and **~0° analytic twist** (the straight depiction reads straight).
   `core_reference_geometry` does exactly this.
2. **`measure_bundle_twist` artifacts.** Per-helix backbone spiral (~34°/bp) + the lattice's
   per-helix phase offsets masquerade as a coherent cross-section rotation. Killed by
   collapsing each `(helix,bp)` to its **base-pair midpoint** (both strands → on-axis) +
   ~1-turn (3.5 nm) slabs. Slab-centre→slab-centre spans only `(1−1/n)` of the bundle →
   rescale to full axial span (else magnitude under-reads). Designed to be used
   DIFFERENTIALLY (`twist(sim) − twist(analytic)`) so any residual offset cancels.
3. **dsDNA core = both-strands-present, defined topologically.** A `(helix,bp)` column is
   core iff the strand walk emits BOTH directions there. Drops the floppy single-stranded
   ends a SEAMLESS route leaves (ill-defined time-average; not what skips control) without
   depending on display flags. Seamless `2x3x40` → ragged helices 43–62 bp, 72 ss display
   nucleotides; the topological core is clean.
4. **Build order**: bundle → `auto_scaffold(seamless)` → `full_autostaple` → apply periodic
   skips (needs crossovers + routed dsDNA intervals) → `full_sequence` (so the sequence
   matches the post-skip nucleotide count). Skips live as `helix.loop_skips` marks; geometry
   + oxDNA read them downstream — no separate strand-graph bake needed.

<a id="validation-status-2026-06-25"></a>
- [Validation status (2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#validation-status-2026-06-25)

<a id="frontend-autorefine-skipsloops-button-2026-06-25"></a>
- [Frontend: "Autorefine skips/loops" button (2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#frontend-autorefine-skipsloops-button-2026-06-25)

<a id="autorefine-ui--status--re-run-guard--deviation-map-2026-06-25"></a>
- [Autorefine UI — status / re-run guard / deviation map (2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#autorefine-ui--status--re-run-guard--deviation-map-2026-06-25)

<a id="first-iteration-seed--literature-standard-2026-06-25"></a>
- [First-iteration seed = literature standard (2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#first-iteration-seed--literature-standard-2026-06-25)

<a id="autorefine-applies-skips-to-the-design--per-job-deviation-map-2026-06-25"></a>
- [Autorefine applies skips to the design + per-job deviation map (2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#autorefine-applies-skips-to-the-design--per-job-deviation-map-2026-06-25)

<a id="full-scale-run-3x6x400-launched-2026-06-25"></a>
- [Full-scale run (3x6x400, launched 2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#full-scale-run-3x6x400-launched-2026-06-25)

<a id="stop--cancellation-2026-06-25"></a>
- [Stop / cancellation (2026-06-25)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#stop--cancellation-2026-06-25)

<a id="independent-skip-placement--already-supported-for-phase-5"></a>
- [Independent skip placement — already supported (for Phase 5)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#independent-skip-placement--already-supported-for-phase-5)

<a id="structure-blowing-up--production-stage-explosion-not-a-skip-bug-2026-06-26"></a>
- ["Structure blowing up" — production-stage explosion, NOT a skip bug (2026-06-26)](details/project_skip_twist_selfconsistency/02-validation-status-2026-06-25.md#structure-blowing-up--production-stage-explosion-not-a-skip-bug-2026-06-26)

<a id="critical--full-scale-revealed-the-rmsd-gate-is-too-loose-2026-06-25"></a>
- [CRITICAL — full-scale revealed the RMSD gate is too loose (2026-06-25)](details/project_skip_twist_selfconsistency/03-critical--full-scale-revealed-the-rmsd-gate-is-too-loose-2026-06.md#critical--full-scale-revealed-the-rmsd-gate-is-too-loose-2026-06-25)

<a id="autorefine-testing-finished--apply-route-deadlock-fixed--full-scale-re-validated-2026-06-26"></a>
- [Autorefine testing finished — apply-route DEADLOCK fixed + full-scale re-validated (2026-06-26)](details/project_skip_twist_selfconsistency/03-critical--full-scale-revealed-the-rmsd-gate-is-too-loose-2026-06.md#autorefine-testing-finished--apply-route-deadlock-fixed--full-scale-re-validated-2026-06-26)

<a id="autorefine-production-400--root-cause-was-under-relaxation-not-a-race-2026-06-26"></a>
- [Autorefine production 400 — ROOT CAUSE was under-relaxation, not a race (2026-06-26)](details/project_skip_twist_selfconsistency/03-critical--full-scale-revealed-the-rmsd-gate-is-too-loose-2026-06.md#autorefine-production-400--root-cause-was-under-relaxation-not-a-race-2026-06-26)

<a id="autorefine-job-ux--ar-tag--auto-select--stale--suppression-2026-06-26"></a>
- [Autorefine job UX — [AR] tag + auto-select + stale-⚠ suppression (2026-06-26)](details/project_skip_twist_selfconsistency/03-critical--full-scale-revealed-the-rmsd-gate-is-too-loose-2026-06.md#autorefine-job-ux--ar-tag--auto-select--stale--suppression-2026-06-26)

## Open / next

- Calibrate the geometry_match tolerance vs the oxDNA-CG-vs-B-DNA RMSD floor on a converged
  straight structure (the "degree of variability").
- Generalize beyond uniform periodic skips (per-region placement from spatial error — substrate ready,
  see above) and to bend as well as twist — deferred (Phase 5). See [[project_oxdna_extra_bases]],
  [[project_oxdna_benchmarks]].
