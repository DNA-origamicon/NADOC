# CPD Full-view backbone bead audit

Historical audit before the O5′ landmark correction. The corrected actual-render
measurements are in [cpd_o5_projection_20260920.json](cpd_o5_projection_20260920.json).
The earlier sugar-origin fit was not the Full-representation landmark contract.

Headless Chromium measurements of the actual bead instance matrices and rendered
atom instances confirm a projection discrepancy in `workspace/2hb_1xT_CPD.nadoc`.
The current saved design and `2hb_1xT_CPD_relaxed_v2.nadoc` give identical results.
This audit does not change either design or the renderer.

| Endpoint (crossover ID prefix, extra index 0) | Bead displaced from sugar-ring-based placement | Bead–P distance | Standard bead–P distance |
|---|---:|---:|---:|
| `4a12dd44` | 0.112 nm | 0.478 nm | 0.378 nm |
| `54c5689d` | 0.188 nm | 0.508 nm | 0.321 nm |

A standard bead is an abstract residue origin, not the P atom or sugar centroid.
The reference therefore uses the same design with CPDs and endpoint poses removed,
then rigidly fits the five standard sugar-ring atoms (C1′, C2′, C3′, C4′, O4′) onto
the rendered CPD sugar ring and carries its standard bead through that fit. Sugar
fit RMS errors are 0.008 and 0.011 nm. The discrepancy is positional: the beads are
actually *closer* to C1′ and C4′ than in the standard representation, while farther
from P. “Farther from every backbone atom” would be an incorrect interpretation.

The Full-view bead uses the whole-residue rigid transform stored by
`backend/core/cpd_design.py::_store_product_pose`. That fit compromises between
base, sugar, and phosphate atoms. After independent torsional relaxation, that
single rigid transform cannot represent both the base slab and backbone origin
faithfully. `frontend/src/scene/crossover_connections.js` still applies it to the
undeformed standard bead. A correction should derive the backbone placement from
the deformed sugar geometry independently of the slab's base-ring placement.

Detailed positions and alternative fits are in
[the measurements](cpd_backbone_bead_measurements_20260920.json).

Reproduce the rendered-coordinate capture without using the live backend:

```sh
CPD_AUDIT_FILES=workspace/2hb_1xT_CPD.nadoc,workspace/2hb_1xT_CPD_relaxed_v2.nadoc \
  npm --prefix frontend run test:e2e -- cpd_bead_audit.spec.js
```

The audit defaults to the repository CPD fixture when `CPD_AUDIT_FILES` is unset.
It writes `/tmp/cpd-bead-render-audit.json` (override with `CPD_AUDIT_OUTPUT`).
Only temporary `__e2e__` documents are imported; saved source designs are untouched.

## Correction

The display now independently projects the canonical sugar ring to its standard
bead origin and the canonical thymine base to its standard slab centroid/frame.
The saved atomistic coordinates are unchanged. Repeating the actual-instance audit
on both designs gives sugar-based bead-placement residuals below 0.00002 nm
(previously 0.112 and 0.188 nm). The small residual is consistent with coordinate
rounding in the atomistic display path. Phosphorus need not become closer: its
independent torsion changes its relationship to the sugar, while the abstract bead
retains the standard sugar-based placement rather than snapping to P.

Backend tests pin standard-template projection under independent sugar/base
rotations. Frontend tests pin standard slab dimensions, frame axes, arc refresh,
and live transforms; Chromium covers saved designs and fresh conversion.
