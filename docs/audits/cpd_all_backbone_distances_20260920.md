# Full-view bead distances across 2hb_1xT_CPD

Historical audit before the O5′ landmark correction. The corrected actual-render
measurements are in [cpd_o5_projection_20260920.json](cpd_o5_projection_20260920.json).
The earlier sugar-origin fit was not the Full-representation landmark contract.

Measured after the CPD projection change, using headless Chromium's live Full-view
bead instance matrices and ball-and-stick atom instances. Each distance pairs an
atom with its own nucleotide's bead. All 96 atomistic residues matched a rendered
bead: 94 ordinary helix nucleotides and two CPD extras; there are no other extra
bases in this design. No source geometry was modified.

CPD 1: `__xb__:4a12dd44-bce2-46be-8296-093ce52d2ec9:0`.
CPD 2: `__xb__:54c5689d-127b-4693-bc11-f51121719fad:0`.

All distances are nm. Parentheses for ordinary nucleotides give the full range;
CPD parentheses give the ratio to the ordinary median.

| Atom | Ordinary median (range), n=94 | CPD 1 (ratio) | CPD 2 (ratio) |
|---|---:|---:|---:|
| P | 0.157 (0.143–0.705) | 0.579 (3.68×) | 0.625 (3.98×) |
| OP1 | 0.248 (0.174–0.824) | 0.637 (2.57×) | 0.660 (2.66×) |
| OP2 | 0.250 (0.230–0.624) | 0.584 (2.33×) | 0.746 (2.98×) |
| O5' | 0.010 (0.003–0.401) | 0.443 (45.36×) | 0.598 (61.25×) |
| C5' | 0.139 (0.135–0.164) | 0.475 (3.41×) | 0.502 (3.60×) |
| C4' | 0.222 (0.210–0.247) | 0.508 (2.29×) | 0.514 (2.32×) |
| O4' | 0.271 (0.266–0.293) | 0.488 (1.80×) | 0.485 (1.79×) |
| C3' | 0.262 (0.250–0.282) | 0.475 (1.81×) | 0.472 (1.80×) |
| O3' | 0.397 (0.134–0.413) | 0.608 (1.53×) | 0.600 (1.51×) |
| C2' | 0.295 (0.288–0.326) | 0.411 (1.39×) | 0.413 (1.40×) |
| C1' | 0.339 (0.332–0.365) | 0.494 (1.46×) | 0.496 (1.46×) |

Both CPD beads are farther from every listed atom than the ordinary median.
The previous fix preserves the legacy extra-base sugar-to-origin convention,
which differs from ordinary helix bead placement. The prior residual below
0.00002 nm describes agreement with that extra-base convention, not agreement
with the other beads in this design. Ordinary beads lie near O5′, whereas the
CPD beads remain 0.443 and 0.598 nm away. The very large O5′ ratios reflect its
near-zero ordinary median.

[Every per-residue measurement](cpd_all_backbone_distances_20260920.csv).

Reproduction:

```sh
CPD_AUDIT_FILES=workspace/2hb_1xT_CPD.nadoc \
CPD_AUDIT_OUTPUT=/tmp/cpd-all-beads.json \
  npm --prefix frontend run test:e2e -- cpd_bead_audit.spec.js
```

The capture includes `allBeads` and `allAtoms`, joined by canonical nucleotide key.
Use the `standard: false` record for the authored design; the second record is the
extra-base control with the CPD removed and is not included in this comparison.
