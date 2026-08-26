# Molecular Placement Audit

## Purpose

The Molecular Placement Audit is a read-only A/B view for reviewing crossover-insert placement
changes. Open it from **Help → Molecular Placement Audit**. It remains a pre-production review
surface for new candidates; for the authorized 2xT v7 placement it also shows the active
production geometry and whether another proposal is pending.

To inspect actual extra-base poses from selected trajectory frames and crossover IDs, use
**Help → Extra-Base Metrics Audit** instead. Its reusable trajectory sample feed is documented in
[`extra_base_sample_audit.md`](extra_base_sample_audit.md).

Opening the audit never changes the active design. For 1xT, Current is production and Candidate is
the diagnostic geometric baseline. For 2xT, both panels are labeled **Production v7** because the
reviewed flexible-linker clearance is now the implemented default and no placement proposal is
pending. Ordinary rendering, persistence, export, and simulation all use Production v7.

## Four-panel review

| Panel | Default | Contents |
|---|---|---|
| Current | Full | Production geometry |
| Candidate | Full | The named read-only diagnostic provider's output |
| Difference | Ball and Stick | Entire Current structure in cyan, affected Candidate atoms in magenta, and displacement vectors |
| Constraint planes / defects | Ball and Stick | Orange midpoint-bp planes plus exact pierced rings/intersecting bonds and non-bonded heavy-atom clash pairs |

Every panel can show one translucent orange disk per reciprocal crossover pair. Its center is
halfway between the centers of the two adjacent crossover records and its normal is their
normalized mean helical axis. A **Midpoint plane** checkbox independently toggles the annotation
in each panel. Unpaired crossover records do not create a plane. The disk itself is an annotation;
the audit also classifies atom-level signed-side violations, and the promoted 2xT default is locked
to zero crossings on the reviewed fixtures.

Every panel can independently switch between **Full** and **Ball and Stick**. All four panels share
one exact camera state: orbiting, panning, or zooming any quadrant copies its position, target,
orientation, clipping range, and zoom to the other three. **Reset views** fits Current once and
copies that same view to all four quadrants.

Both representations use the same strand colors. Ball and Stick no longer falls back to CPK element
colors in the audit: it resolves persisted strand colors and active strand/group overrides, then
uses scaffold blue and the ordinary staple palette for otherwise unassigned strands. Piercing and
clash overlays in the defect panel remain detector annotations layered over those strand colors.

The defect panel uses identities emitted by the detectors themselves rather than reconstructing a
selection from proximity. A piercing row names the covalent bond and ring, draws the intersecting
bond thick, and outlines the ring polygon. A clash row names both atoms and their separation; the
view places a wireframe sphere on each atom and links the pair. Current markers are blue and
Candidate markers are magenta. When neither model has either defect, the panel says so explicitly
rather than showing unrelated "affected" atoms.

Because the defect panel now uses the exact same camera rather than a separate close-up, highlighted
atoms stay in their true spatial context and at the same scale as the other three views.

The metric strip reports the exact candidate provider plus displacement, ring-piercing, heavy-atom
clash, and maximum-bond results. Current-to-candidate counts use `current → candidate`. Red means
the candidate still has a detected defect; green means that candidate diagnostic is clear.

### Active defect model

Catenation and winding are no longer NADOC metrics. Their artificial end closures did not measure
the local molecular defects this review needs, so no linking score is displayed, validated, or used
to gate a simulation. Historical result files may retain those terms as archival provenance, but
the detector, CLI, seed gate, and metric-specific regression suites have been removed.

The active local diagnostics are ring piercing and exact heavy-atom clashes. A ring piercing is a
covalent bond intersecting the interior of a nucleotide sugar or base ring. It is independently
checked for atomistic simulation seeds and refused by default; **Build despite a ring piercing** is
the explicit Job Wizard override. The helical-phase regression deliberately includes both clean and
pierced native placements and verifies that the gate passes or refuses each measured model without
repositioning its atoms.

### Scaffold Holliday-junction clearance

The fast atomistic display normally interpolates crossover linker atoms along the straight
`C3′ → C5′` chord. For reciprocal scaffold crossovers, the audit now predicts the opposing
`P/OP1/OP2` positions before applying that interpolation. If any pair would fall below the 0.08 nm
heavy-atom clash threshold, the two `O3′–P–O5′` paths receive equal and opposite sine-tapered bows
away from their common Holliday-junction center. The bow magnitude is solved per pair as the
minimum required for 0.09 nm clearance. It does not move the `C3′/C5′` anchors, ribose rings, bases,
staples, non-reciprocal crossovers, or already-clear junctions. The surface point-cloud path uses
the identical construction.

This clearance adjustment belongs only to the fast display/surface bridge path. The exact
minimized bridge used for PDB export and MD seeds is unchanged, as is the calibrated `1xT`
extra-base placement.

On `24hb_1xT.nadoc`, this moves 110 flexible linker atoms by at most 0.61 Å and changes the Current
heavy-atom clash count from 11 to 0 while retaining 0 ring piercings.

## Candidate provider

`crossover-insert-default-v2` remains the raw geometric/Bezier comparison for one-residue inserts.
For two-residue inserts, the audit shows the authorized production v7 default in both panels until
a new candidate exists. Runs longer than two remain unchanged.

The reviewed v6 rigid-residue arrangement remains part of production v7. Each
inserted residue remains rigid. Base `k=0` and
base `k=1` receive separate local poses selected by the crossover's two possible frame polarities;
the same two poses are mapped through both reciprocal strands' right-handed
`(bow, axial, chemical 3′→5′)` frames. Thus the strands remain directionally symmetric without
using a world-coordinate reflection. Exact MPA acceptance requires zero
atom-level midpoint-plane crossings, external heavy-atom clashes, ring piercings, and
insert-associated overstretched bonds after a complete candidate rebuild. Isolated end inserts
without a midpoint-plane mate are preserved unless their own exact diagnostics require a small
local repair. Same-crossover canonical bridge contacts are excluded from the nonbonded clash count.

Its promotion evidence was `300 → 0` plane-crossing atoms, `44 → 0` target clashes,
`15 → 0` target ring piercings, and `8 → 0` target overstretched bonds for
`workspace/6hb_2xT.nadoc`; and `120 → 0`, `29 → 0`, `4 → 0`, and `8 → 0`, respectively, for
`workspace/2x3SQx32_2xT.nadoc`. Production authorization was granted by the owner on 2026-08-12
and is pinned by the crossover-placement fingerprint test.

The 2xT provider is `reciprocal-phosphate-clearance-production-v7`. Production v7 moves only the
five flexible atoms associated with each colliding terminal
phosphate bridge: `P/OP1/OP2` receive the full equal-and-opposite clearance displacement, while
incoming `O3′` and outgoing `O5′` receive a sine-tapered fraction. Rigid ribose/base atoms and the
authorized 2xT placement frames do not move. The non-bonded detector excludes direct and
bond-angle (1–3) covalent pairs, matching force-field exclusions instead of misclassifying a local
bond angle as steric overlap.

The promoted clearance changes whole-structure clashes from `4 → 0` on `workspace/6hb_2xT.nadoc` and
`3 → 0` on `workspace/2x3SQx32_2xT.nadoc`, with zero ring piercings and midpoint-plane crossings.
It moves 40 and 30 flexible linker atoms, respectively, by at most 0.0324 nm and 0.0216 nm. It is
owner-authorized for production as of 2026-08-12. The first two panels default to Ball and Stick,
while every panel retains its representation toggle.

### Production v7 NAMD preflight

Production v7 was also validated through the ordinary NAMD package path, rather than only through
the placement diagnostics. Fresh full CHARMM/psfgen systems were solvated with TIP3P water and
150 mM NaCl; both charge audits reported `production_ready: true` and neutral final systems. Local
NAMD Git-2025-12-04 (`b856a9378ca44bcf5aa708d4b681af4ceb86d8ca`) on an RTX 3080 Ti produced:

| Design | Solvated atoms | Minimization | Minimized potential | 4 fs HMR startup |
|---|---:|---:|---:|---:|
| `6hb_2xT` | 180,601 | 2,000 steps in 14.02 s | −844,991.685 kcal/mol | 1,000 steps, 103.3 ns/day |
| `2x3SQx32_2xT` | 76,866 | 2,000 steps in 5.64 s | −380,796.248 kcal/mol | 1,000 steps, 219.6 ns/day |

The startup checks used the generated HMR PSFs, `rigidBonds all`, a `1e-8` constraint tolerance,
GPU-resident mode, and the minimized coordinates. Both reached step 1,000 and NAMD's normal
`End of program`, with no RATTLE failures, fatal errors, constraint failures, or NaNs. These were
short preflight cells sized with `free_ns=0`; long unrestrained production must be re-solvated for
its intended duration so the rotation-safe cell rule is applied.

On the `2hb_1xT` quick-assessment fixture, the audit currently reports 40 displaced atoms and a
maximum displacement of about 0.773 nm. The visual/metric result is useful precisely because the
candidate is not automatically better: it leaves ring piercings and clashes unchanged at zero while
increasing the maximum bond length. No placement decision should be inferred from the existence of
the candidate.

## Isolation boundary

`GET /api/design/molecular-placement-audit` snapshots the active `Design`. For 2xT it builds
ordinary Production v7 once and deep-copies the same model into the no-pending-proposal panel. For
1xT it retains the transform-only geometric comparison. The response
contains both atomistic feeds and the ordinary Full render feed. Neither feed enters the application store.
PDB-imported models return 409 because this comparison is defined only for authored crossover
inserts.

The current placement is fingerprint-locked by
`tests/test_crossover_placement_authorization.py`. That lock has no regeneration command. Changing
its fingerprint without explicit authorization is a test failure, not a routine baseline update.

## Validation

- `tests/test_molecular_placement_audit.py` proves the comparison is isolated, only insert residues
  differ, longer inserts remain unchanged, piercing and clash focus serials come directly from their
  detectors, and the API cannot mutate active state.
- `frontend/src/ui/molecular_placement_audit.test.js` pins the four-panel layout, both representations
  and strand-color resolution in every panel, exact four-way camera copying, defect identification,
  metrics, safe error rendering, and cleanup.
- `frontend/e2e/molecular_placement_audit.spec.js` imports the real `workspace/2hb_1xT.nadoc`, opens
  the Help toggle, exercises four WebGL panels, validates their representation controls, and captures
  `frontend/e2e/screenshots/molecular-placement-audit-2hb.png` plus the all-atomistic
  `frontend/e2e/screenshots/molecular-placement-audit-2hb-atomistic.png` for visual review.
- `tests/test_ring_piercing.py` sweeps both one- and two-base reciprocal-crossover fixtures over a
  complete helical turn and proves the seed gate agrees with the measured piercing report without
  changing placement.
- `tests/test_holliday_bridge_bow.py` pins the display-only scaffold clearance and proves the exact
  MD bridge path is not given a bow.
- `tests/test_crossover_placement_authorization.py` fingerprint-locks calibrated `1xT` and promoted
  `2xT` placement.

Future placement candidates still require separate explicit production authorization after visual
and numeric review.
