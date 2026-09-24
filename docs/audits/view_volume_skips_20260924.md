# Skipped-column cylinder remnants

Read-only inspection of `workspace/3x6SQ_norm_skips.nadoc` reproduced three
isolated cylinder runs within the saved stick volume: h_XY_0_1:38, h_XY_2_1:29,
and h_XY_2_0:27. Each is a declared skip with no nucleotide geometry. Spatial
membership previously inspected only nucleotides, leaving these columns at the
global cylinder representation.

`view_volume_points.js` supplies display-only skip samples using surrounding live
column centers. Consecutive skips interpolate between the nearest occupied columns.
Ordinary gaps and occupied columns are unchanged; unbracketed terminal skips are
not extrapolated. No design, molecular geometry, or topology changes are made.

Validation:
- Focused volume/cylinder tests: 52 passed.
- Browser regression: isolated test-owned copy of the reported design; confirms
  all three missing column keys are covered and no sub-0.5-nm clipped cylinder
  remains inside the stick volume. Passed; original file untouched.
- Full frontend: 6,876 passed, 1 skipped; existing quantum-dot PNG import failure.
- Lint passed. `main.js` LOC delta for this fix: 0.
- Smoke: 23 passed. Test workspace/history, bridge credentials, browser outputs,
  and temporary geometry diagnostic verified absent after cleanup.

The initial browser harness raced application startup and saw empty geometry;
waiting for the app test hook before importing resolved it. Workspace autosaves
use the `__e2e__` prefix and global teardown; disposable geometry diagnostics
and browser outputs are removed after validation.
