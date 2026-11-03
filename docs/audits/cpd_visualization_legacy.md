# CPD visualization and legacy export audit — 2026-10-18

Scope: NAMD job visualization, coordinate export, box/solvent estimates, and their legacy PDB/PSF dependencies. This is not a repository-wide removal of every compatibility path called “legacy”. No simulation job or saved design is migrated by this change.

## Fixes

- Box details called `md_box_preview._design_pdb → pdb_export.export_pdb`, which correctly rejects CPDs for legacy simulation output. Coordinate-only rendering now has an explicit `export_coordinate_pdb` entry point. It retains atom positions, serials, CPD CONECT bonds, coloring, and viewer-terminal behavior, with a coordinate-only remark for CPDs. The legacy simulation export and PSF guards remain.
- Migrated box preview, dry VRAM/system-size estimates, standalone and visualized PDB downloads, oxDNA coordinate/frame downloads, and the multiframe coordinate template. These are geometry consumers, not force-field builders.
- The static MD renderer now supplies current coordinates to the weld overlay, including when enabled after frame loading. Fixed marker visibility bookkeeping; previously newly drawn markers were hidden immediately.
- The weld overlay previously recognized only reciprocal extra-base candidate pairs and applied reactant propensity/sub-vdW warnings to formed products. Formed CPDs now resolve from their explicit nucleotide keys and topology segment identities, including ordinary-base/same-strand pairs. They display the isomer and geometry in cyan without a formation propensity or reactant collision warning. Trace distances/angles remain available; propensity is not reported for formed products.
- KIMMDY candidate discovery excludes residues already consumed by a formed CPD. Remaining unreacted thymines retain the existing candidate analysis.

## Dependency decisions

| Legacy code | Actual callers | Decision |
| --- | --- | --- |
| `namd_solvate.get_solvation_stats` | No application calls. One unused import in `experiments/exp22_btube_md_benchmark/run_solvated.py` (removed). | **Ready for deletion upon user approval.** Marked at the definition. Current estimates use `md_vram.estimate_profile_from_design`; prepared counts use `package_solvation_profile`. |
| `pdb_export.export_pdb` | Legacy NAMD ZIP, heavy-atom solvation compatibility branch, periodic-cell builders, preconditioning, inline MD export, obsolete stats helper; tests and experiment scripts. | Retain guarded simulation compatibility wrapper. Coordinate-only callers migrated. Deleting now breaks actual export/simulation workflows. |
| `pdb_export.export_psf` | PSF download, legacy NAMD/inline export, `complete_psf`, periodic-cell builders, preconditioning. | Retain. Heavy-atom graph is not equivalent to full CHARMM hydrogen/patch/improper topology; do not remove CPD rejection. |
| `namd_helpers.complete_psf` | Legacy NAMD ZIP, compatibility solvation, empty-system graphene/two-electrode/reference preparation; obsolete stats. | Retain. Empty electrolyte systems are valid callers even with no DNA. Future retirement must replace empty-PSF construction and migrate the simulation compatibility paths together. |
| `namd_helpers._complete_psf_from_stub` | `complete_psf`, periodic-cell builders, preconditioning, periodic-cell benchmark. | Retain. Periodic wrap bonds require dedicated migration/validation, not the ordinary finite-DNA builder. |
| `namd_package.build_namd_package` | Public `/design/export/namd-complete` route, tests/scripts. | Retain pending an explicit API retirement or migration to the managed full-topology package workflow. No current frontend literal route caller found, but the public API is still exposed. |
| Saved-job snapshot fallback, appended-production migration, old protocol metadata | Loading old jobs and interpreting historical outputs. | Retain: these are data compatibility paths, not the box-preview failure. Removing them would strand old results. |

Do not remove the legacy simulation guards as a way to enable CPD visualization. Visualization geometry does not establish force-field completeness or validate an unsupported simulation engine.

## Evidence

Persistent browser screenshots/results: `.development-artifacts/cpd-visualization/`.
Regression logs: `.development-artifacts/cpd-visualization-tests.log`, `cpd-box-regression.log`, `cpd-metrics-regression.log`, and `cpd-visualization-frontend-tests.log`.

Verified regression results: four isomer geometry/coordinate/guard checks; 35 weld-metric tests; 9 KIMMDY tests; 20 PDB export tests (one unrelated skip); 20 trajectory-export tests; four box-cache/preview regressions. Frontend geometry/renderer/control suites pass, including static-frame activation and actual marker visibility.

Desktop browser results: all four persistent isomer jobs passed box-details, periodic-image toggles, live MD display, water, ions, periodic cell, and formed-CPD readout checks (4 passed, 3.0 minutes). Cis-anti-I also exercised Full, VDW, Stick, Ball-and-stick and trajectory scrubbing. Requests for Beads and Surface are rejected by the shared simulation representation policy; the initial test did not assert the return value, and its screenshots labelled beads/surface show the preceding representation. They are not evidence of molecular-surface rendering. The original static-overlay failure screenshot is retained as `cis-anti-I-first-failure.png`; the corrected view is `cis-anti-I-job.png`. Same-strand ordinary-base identity regression also passes (five CPD visualization tests total).

RMSF was visibly verified on the completed cis-anti-I job (96 bases, 150 frames). Occupancy clouds and photoproduct propensity are deliberately production-only (`md_jobs_panel._updateVizToggles`, `mdHasProductionRun`); these relaxation jobs have no production to analyze. Nanopore ion-path/vector views require a nanopore. These gates remain intact. The initial analysis smoke test incorrectly tried to click disabled occupancy, timed out, and retained its screenshot; corrected coverage asserts the prerequisite gate. No production or nanopore run was fabricated to bypass it.

The shared simulation renderer permits Full, VDW, Ball-and-stick, Stick, oxDNA and mrDNA comparison styles. Beads, cylinders, hull and molecular-surface styles are globally disabled while a simulation display owns the scene (`scene/simulation_representations.js`, `ui/representation_switcher.js`). This applies to every job, not specifically CPDs. Retain this explicit policy; enabling those modes requires a separate rendering-capability change, not removing a legacy export guard. Corrected browser coverage asserts rejected representation requests rather than claiming those screenshots rendered surfaces. Final RMSF/prerequisite review passed (one browser test, 38.7 seconds).

Final prerequisite assertions passed in `cpd-analysis-browser-gates.log`: RMSF visible, occupancy/propensity production gates retained, Surface/Beads requests explicitly rejected. No legacy function was deleted; only the unused experiment import was removed.
