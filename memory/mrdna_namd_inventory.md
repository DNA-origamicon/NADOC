# mrDNA / Multi-Resolution Pipeline Inventory for NAMD Geometry

Date: 2026-05-21

## Current Status

The repo already has several multi-resolution pieces that can help NAMD starting
geometry, but they are at different maturity levels.

### Usable Building Blocks

- `backend/core/mrdna_bridge.py`
  - Builds an mrDNA `SegmentModel` directly from NADOC topology.
  - Can return a nucleotide index map.
  - Provides multiple ways to convert mrDNA/ARBD outputs into
    `nuc_pos_override` dictionaries for `build_atomistic_model()`.
  - Best current bridge is `nuc_pos_override_from_arbd_strands()`: it aligns
    fine-stage ARBD bead positions back to NADOC, fits per-helix splines, and
    includes crossover terminal keys.

- `backend/core/cg_to_atomistic.py`
  - Provides oxDNA-style CG to atomistic bridge.
  - The PCA axis refit path is documented as insufficient.
  - The useful path is per-domain Gaussian-smoothed position overrides.

- `backend/core/atomistic.py`
  - `build_atomistic_model(design, nuc_pos_override=...)` already accepts
    per-nucleotide CG-informed positions.
  - `Design.atomistic_reference` can persist a relaxed all-atom reference and
    make future PDB/PSF/NAMD exports use that coordinate set automatically when
    the topology hash matches.

- `experiments/exp23_periodic_cell_benchmark/scripts/extract_atomistic_reference.py`
  - Converts a selected MD frame into a persisted `.nadoc`
    `atomistic_reference`.
  - Handles trajectory/PDB coordinate sources, alignment modes, and periodic
    nearest-image placement.

- Monitoring and validation pieces:
  - `experiments/exp25_full_origami_relaxation/scripts/basepair_monitor.py`
  - `experiments/exp25_full_origami_relaxation/scripts/watson_crick_monitor.py`
  - `backend/core/md_health.py`
  - `backend/core/namd_metrics.py`

### Existing Evidence

- `memory/periodic_md.md` records that MD-derived atomistic references improve
  starting poses relative to the raw analytic template.
- Full B-tube minimized reference `F001` was the cleanest early reference:
  lower strain than raw CAD, but not production-equilibrated.
- Explicit solvent/Mg made warmup numerically viable, but unrestrained full
  B-tube still lost base-pair chemistry from the current starting pose.
- C1' distance is a coarse tripwire; Watson-Crick heavy-atom reference-relative
  metrics are the stricter gate.

### Environment Availability

- Current environment has `MDAnalysis`, `scipy`, and `numpy`.
- mrDNA is now installed editable from the persistent checkout
  `/home/jojo/Work/mrdna-tool` instead of the fragile old `/tmp/mrdna-tool`
  location.
- NADOC's mrDNA bridge defaults to `/home/jojo/Work/mrdna-tool` and can be
  overridden with `MRDNA_TOOL_PATH`.
- The restored checkout required small compatibility patches for the current
  Python/NumPy stack: `np.trapezoid` fallback, `np.isin`, `float` finfo,
  scalar RNG seed generation, `rmsd_threshold`, and robust version fallback
  when `git describe` is unavailable.
- Smoke tests on 2026-05-21:
  - `import mrdna` reports `/home/jojo/Work/mrdna-tool/mrdna/__init__.py`,
    version `1.0a.dev212`.
  - `mrdna --help` works.
  - A 2hb NADOC bridge ARBD smoke run wrote PSF/PDB/DCD under
    `/tmp/nadoc_mrdna_actual_smoke`.
  - Exp27 dry-run preconditioning on `Examples/2hb_xover_val.nadoc` wrote
    NAMD-facing PDB/PSF/maps/restraints and `precondition_report.json` under
    `/tmp/nadoc_exp27_mrdna_smoke`.
- `pytest tests/test_md_precondition.py tests/test_mrdna_pipeline.py -q -m 'not integration'`
  currently reports `13 passed, 15 skipped`.

## How This Can Help NAMD

Recommended path:

1. Use mrDNA or oxDNA as a visible, explicit geometry pre-relaxation stage.
2. Convert relaxed CG/fine bead positions into `nuc_pos_override`.
3. Build atomistic coordinates from the unchanged NADOC topology.
4. Run short NAMD minimization/warmup.
5. Persist a successful relaxed all-atom frame as `Design.atomistic_reference`.
6. Use that reference for all later NAMD explicit/implicit/GBIS packages.

This respects design intent:

- No hidden nucleotides.
- No hidden topology changes.
- User-specified `extra_bases` remain the only way to add thymine/linker bases.
- Geometry changes are recorded either as a CG-derived coordinate override or
  as an explicit atomistic reference.

## Immediate Gaps

- mrDNA is not installed in the current runtime.
- The existing `/design/debug/mrdna-roundtrip` route uses the older coarse
  override path; the fine-stage `nuc_pos_override_from_arbd_strands()` is the
  better candidate for NAMD starting geometry.
- There is no first-class NAMD package path that says:
  "run mrDNA pre-relax, rebuild atomistic, write NAMD package, and attach
  diagnostics."
- Crossover strain diagnostics should be included before and after CG
  pre-relaxation so users know whether the designed crossover/linker geometry
  is still incompatible with atomistic bonded geometry.

## Proposed Next Implementation

Add a product path:

- `backend/core/md_precondition.py`
  - `build_mrdna_preconditioned_atomistic_model(design, ...)`
  - `build_oxdna_preconditioned_atomistic_model(design, ...)`
  - return atomistic model, override coverage, crossover diagnostics, and
    before/after geometry metrics.

Add API/export path:

- `/design/export/namd-preconditioned`
  - mode: `none | oxdna | mrdna-fine`
  - output: NAMD bundle plus `precondition_report.json`.

Short-term fallback when mrDNA is absent:

- Use existing oxDNA CG relaxation path and `_smooth_cg_positions_per_domain()`
  to generate NAMD coordinates.
- Use mrDNA fine-stage path once `/tmp/mrdna-tool` is restored.

## Exp27 Test Workflow Added

- Added `WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY` in
  `backend/core/md_precondition.py`.
- Added guard/report helpers that reject designs with crossover `extra_bases`
  by default.
- Added experiment script:
  `experiments/exp27_mrdna_namd_precondition/scripts/mrdna_coarse_to_namd.py`.
- The script can run mrDNA coarse or reuse existing mrDNA PSF/DCD, generate a
  `nuc_pos_override`, rebuild atomistic coordinates without changing topology,
  and write NAMD-facing PDB/PSF/maps/restraints plus `precondition_report.json`.
- This workflow remains explicitly scoped to direct-crossover designs. It does
  not add hidden nucleotides.

## Exp27 B-tube Closure Test

Full B-tube mrDNA coarse preconditioning was tested on 2026-05-21:

- Command output:
  `experiments/exp27_mrdna_namd_precondition/results/B_tube_coarse_1k/`
- mrDNA/ARBD ran on the GPU with 1,914 coarse particles for 1,000 steps.
- Coarse override coverage was complete at the helix level: 24/24 helices.
- Atomistic override entries were 12,802 after excluding 1,618 crossover
  endpoint keys.
- All 809 checked direct crossovers were still geometrically strained by the
  pre-rebuild diagnostic.
- Bond-geometry evaluation:
  - raw max covalent bond: 0.3634 nm
  - mrDNA-preconditioned max covalent bond: 0.3634 nm
  - raw bonds >0.30 nm: 104
  - mrDNA-preconditioned bonds >0.30 nm: 104
- A short NAMD GBIS startup/minimization check completed, but began with 3,412
  bad-contact atoms and VDW energy around `3.5e9` kcal/mol, so this should not
  be considered a production-ready unrestrained start.

Conclusion: the usable mrDNA coarse path is not sufficient by itself to solve
the full B-tube atomistic start problem.  It can relax coarse helix paths, but
the current B-tube blocker is local atomistic crossover endpoint and
sugar-phosphate strain.  Next useful work should target crossover endpoint
geometry/restraint handoff or an all-atom/local-fragment relaxation stage, not
longer coarse mrDNA runs alone.
