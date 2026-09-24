# Placement comparison baseline — 2026-09-20

The former **New Positioning OFF** legacy viewer geometry is retired. Both
comparison slots now start from the accepted native placement, including CPD
O5′ beads, ring-centroid slabs, and the current measured ordinary nucleotides.

- **OFF:** baseline.
- **ON:** candidate (default); currently identical to baseline.

The toggle remains useful for future experiments. Candidate changes should be
introduced through `backend/core/display_placement.py` and compared with this
accepted baseline. It currently resolves both selectors to native measured
placement. Changing the switch alone cannot resurrect the old viewer geometry.
The existing `measured_positioning` query and header names remain compatible,
including clients sending `false` or omitting the setting. Design and assembly
geometry, mutation responses, atomistic display, audits, and VR snapshots apply
the same policy. Native atomistic construction no longer selects or silently
falls back to legacy duplex templates.

Browser preferences use `nadoc.newPositioning.v3`; the v1/v2 choices are deleted.
Authored designs and explicit molecular coordinates are not rewritten. Raw
helical-site projections and the calibrated extra-base/tail local templates are
still part of building the accepted geometry; they are not selectable viewer modes.

Verification compares actual rendered atom coordinates and bead/slab matrices
through OFF → ON toggles, including CPDs. Before retiring the branch, the native
coordinates, bonds, and Full geometry were captured for `cpd_2hb_1xt`,
`cpd_extra_pair`, and `Examples/6hb_test`; all remained exactly unchanged after
the cleanup. The atomistic false compatibility argument produces those same atoms.
The 6hb/18hb surface baselines now characterize the accepted native geometry.

```sh
.venv/bin/python -m pytest tests/test_display_placement.py tests/test_nucleotide_transforms.py -q
npm --prefix frontend test -- src/ui/new_positioning.test.js
npm --prefix frontend run test:e2e -- placement_comparison.spec.js
```
