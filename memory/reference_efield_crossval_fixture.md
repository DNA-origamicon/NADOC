---
name: reference_efield_crossval_fixture
description: "workspace/6hb_e_test.nadoc — the anchored-E-field cross-validation standard (both end overhangs pinned, transverse field bows the bundle); bow = existing shared descriptors."
metadata: 
  node_type: memory
  type: reference
  originSessionId: b547ff68-e48e-4a03-b88e-93e7dde264ae
---

`workspace/6hb_e_test.nadoc` (user-created 2026-07-06) is the reference fixture for
**anchored electric-field cross-validation** across engines.

- **Structure:** 6-helix HONEYCOMB bundle, ~410–430 bp long, 77 strands, with **two
  overhangs, one on each axial end**, meant to be used as the anchors.
- **The experiment:** pin BOTH end overhangs (anchors) → apply a transverse uniform
  E-field → the mid-span **bows** into a symmetric arc (a simply-supported beam under a
  distributed transverse load, unlike the single-end cantilever in the C2 oracle
  `tests/test_cando_field.py`).

**The "bowing degree" the user proposed is already the shared metric — no new estimator
needed.** It falls straight out of the sim-coverage descriptors:
- **`shape_metrics.field_response_profile(...)` → `free_proj_along_field_nm`** — mean
  deflection of the free (mid-span) region along the field = the direct "how far it bowed"
  scalar; its `per_nt` map is the full bow profile. (Measure on the RAW clamped-solve frame,
  NOT the display frame — see the C2 lesson in [[project_cando_fem]] / sim_coverage_log.)
- **`shape_metrics.compute_shape_descriptors(...)` → `bend_angle_deg` + `bend_radius_nm`** —
  the geometric bow of the centreline (chord–sagitta).
- **Cross-engine agreement:** run the SAME anchored-field job in oxDNA and CanDo on this
  fixture, then `compare_field_response(cand, ref)` → **cosine similarity** (do they bow the
  same direction/shape?) + **magnitude_ratio = CanDo_bow / oxDNA_bow** (does the cheap FEM
  predict the same bow the CG-MD gives?). That ratio IS the M-CANDO-FIELD / M-ALL-ANCHORS-FIELD
  headline agreement number, made concrete on a real design.

**Where it slots:** a future `/continue-coverage` task — `C5` (emit CanDo's field-source
bundle) + oxDNA's field-source on THIS fixture → the comparison card shows the first real
oxDNA-vs-CanDo bow-agreement row. Not new metric code; just this fixture as the standard.
Related: [[project_oxdna_efield]], [[project_cando_fem]].
