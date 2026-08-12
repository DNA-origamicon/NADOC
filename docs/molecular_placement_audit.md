# Molecular Placement Audit

## Purpose

The Molecular Placement Audit is a read-only A/B view for reviewing proposed crossover-insert
placement changes before any production geometry is changed. Open it from **Help → Molecular
Placement Audit**.

The active design remains the Current model. Candidate geometry exists only in the audit response
and private audit scenes: it cannot be saved, exported, submitted to simulation, or made active.

## Four-panel review

| Panel | Default | Contents |
|---|---|---|
| Current | Full | Production geometry |
| Candidate | Full | The named diagnostic provider's output |
| Difference | Ball and Stick | Entire Current structure in cyan, affected Candidate atoms in magenta, and displacement vectors |
| Piercings / clashes | Ball and Stick | Exact detector atoms: pierced rings/intersecting bonds and non-bonded heavy-atom clash pairs |

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

## Initial candidate provider

`geometric-baseline-v1` is the already-existing raw geometric/Bezier placement. It removes the
calibrated local pose for one-residue crossover inserts. Longer insert runs already use this
baseline and consequently report zero displacement. This provider is diagnostic evidence, not an
approved replacement.

On the `2hb_1xT` quick-assessment fixture, the audit currently reports 40 displaced atoms and a
maximum displacement of about 0.773 nm. The visual/metric result is useful precisely because the
candidate is not automatically better: it leaves ring piercings and clashes unchanged at zero while
increasing the maximum bond length. No placement decision should be inferred from the existence of
the candidate.

## Isolation boundary

`GET /api/design/molecular-placement-audit` snapshots the active `Design`, builds Current, and
creates Candidate by adding transient `NucleotideTransform` records to an in-memory clone. The
response contains both atomistic feeds and the ordinary Full render feed. The frontend does not put
either candidate design or candidate atoms into the application store.

Production atomistic output is unchanged. The audit obtains native placement frames through an
optional observation sink on `build_atomistic_model`; the sink copies measurements but cannot
change placement. PDB-imported models return 409 because this candidate is defined only for authored
crossover inserts.

The current placement is fingerprint-locked by
`tests/test_crossover_placement_authorization.py`. That lock has no regeneration command. Changing
its fingerprint without explicit authorization is a test failure, not a routine baseline update.

## Validation

- `tests/test_molecular_placement_audit.py` proves the candidate is isolated, production atom and
  bond output is unchanged, only insert residues move, longer inserts remain unchanged, piercing and
  clash focus serials come directly from their detectors, and the API cannot mutate active state.
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
- `tests/test_crossover_placement_authorization.py` fingerprint-locks calibrated `1xT` placement.

Promotion of any candidate still requires a separate, explicitly authorized production-geometry
change after its visual and numeric evidence has been reviewed.
