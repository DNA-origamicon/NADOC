# Fresh-part VR Extrude and view-volume validation

The right Tools → Extrude entry opens a dedicated sidebar and the lattice painter.
Return, Confirm and Cancel stay pinned while the settings scroll. Length has
1 bp and 21 bp steps; direction, source plane, strand filter, ligation, painter
recall, freeform placement, model framing and Undo use the existing authoring
configuration and transaction backend. The part's lattice is displayed read-only.
Confirm requires the matching successful preflight; pending commits block edits.
Cancel and painter Exit both close the panel and clear the draft. The controller
tour verifies both exit/reopen paths before painting.

## Correct 6HB footprint

The earlier native authoring probe used six cells whose positions do **not** form
a regular hexagon. Counting helices and checking cell IDs did not detect this.
The new tour's independent radius/angle oracle rejected that footprint (3 nm
radius spread). The probe and its browser expectations now use
`[(0,1),(1,1),(1,2),(1,3),(0,3),(0,2)]`, matching `SIX_HB_CELLS` in
`tests/conftest.py`. This is the desktop mouse seed translated four columns,
which preserves honeycomb parity. Checks require six 42 bp helices, one lattice
frame, equal nonzero transverse radii, and six 60-degree angular gaps.
Existing fixture files are not changed or loaded by the new tour.

## Local representations

The document-bound volume feed now includes representation, coloring and opacity
(version 3, retaining native readers for versions 1/2). Native rendering uses
world-to-volume transforms in a texture buffer, avoiding a fixed uniform-array
volume limit. Fragment clipping removes the global style inside enabled volumes
and renders each volume's independent layer there. Box and hexagonal prisms use
the same orientation/dimensions as the saved records and trigger controls.
Meshes, sphere impostors, bonds and scene lines share the clipping predicate;
overlays are excluded. Existing GPU style buffers are reused and the original
global style restored after each eye. Zero-opacity/disabled volumes contribute
no layer; outline visibility is independent.

The existing native coloring set is strand/base/cluster/CPK; an overhang-only
volume coloring currently falls back to strand. Layers share the global scene's
shadow map. Many overlapping heavy representations require additional scene
passes; no large-volume-count performance claim is made by this small-model test.

## Isolated demo and validation

Debug → VR Tours & Tests → Tools · Authoring → Extrude a 6HB and inspect a volume.
The runner creates a temporary workspace and its own browser/backend on free
ports. File → New creates a blank part. ScryWrite uses actual controller input to
open Tools/Extrude, paint the ring, set 42 bp, Confirm and Frame model. It then
creates a volume, grabs its centroid and resizes three faces around the model.
A desktop dropdown changes the shared volume representation to beads. Native
On/Off controls compare both submitted eyes. No authoring API seeding or semantic
activation is used for the counted new-part workflow.

The pixel oracle reconstructs baseline design points from submitted-eye depth,
reprojects them into the other captured eye pose, matches only the same primitive
ID within one raster pixel, classifies them against the observed volume faces,
and requires changed interior
design pixels plus at least 95% stable exterior design pixels. Background, outline
and controller pixels cannot pass this check. Desktop checks require a nonempty
proper subset of nucleotide keys. Helices remain unchanged. Save/reload compares
both topology and view volumes; the saved part is retained only as an evidence
artifact. The tour saves the new part at its existing temporary-workspace path, preserving
its UUID, and stops the owned viewer before reloading into a separate document
or deleting temporary files. Early diagnostic runs used Save As, which changes
the UUID and correctly trips the live worker’s replacement-document guard; that
test-only identity change was removed.

Reviewed demo: `.development-artifacts/vr-extrude/demo-framed/` (passed).
Both eyes show the model and complete volume outline; 18,418 / 17,907 interior
pixels changed and 97.09% / 97.35% of exterior design pixels stayed stable.
Earlier diagnostic failures are retained in `pilot*` directories, including the
incorrect-ring rejection and the haptic-feedback/menu-exit regression.

Checks: 44 native CTests passed, including GL clipping and sidebar regression
checks; 30 focused Python tests passed; focused Ruff checks passed.
Four browser smoke checks also passed: the prior desktop mouse 6HB test and
three Debug launcher checks. The final four-profile validation report is under
`.development-artifacts/vr-extrude/validated-20260928/`.
The earlier complete registered four-profile pass is retained in
`validation-registered-20260928`; the final run additionally exercises both exit
paths and reloads the saved file into a separate document context.
The initial steady_deliberate run in `validation-20260928` rejected unregistered
exterior pixels (93.7%/94.4% stable). The captures recorded 0.18 mm of headset
drift while the model and volume matrices were identical. Pose registration with
same-primitive raster matching gives 99.30%/99.37% on those retained captures;
the 25-level color threshold and 95% exterior acceptance threshold are unchanged.
A fresh four-profile run uses the corrected comparison directly.
These are simulated-controller and submitted-eye results, not human comfort or
compositor acknowledgement, and not the historical 80-trial authoring campaign.

The intermediate exit-check matrix in `final-validation-20260928` passed both
steady profiles, then hit the bridge’s 3-second observation socket timeout during
native scene import. The retained native log shows 918,416 records parsed in
2.84 seconds followed by GPU setup and `VR_SCENE_APPLIED`; the transaction was
not replayed. The probe now retries only read-only observation within the existing
120-second commit/refresh deadline and records these stalls in `commit-timing.json`.
Controller reaches retain their original timing limits. Scene refresh can still
pause native rendering for several seconds; this change does not claim to remove
that existing synchronous import cost.

Final outcome: all four profiles passed with Cancel/Exit recovery, canonical ring,
volume manipulation, local representation pixels, desktop subset checks, and
same-path save/separate-document reload. Across eight eyes, 19,756–23,587 interior
model pixels changed; 99.07%–99.86% of exterior model pixels remained stable.
`validated-20260928/summary.json` aggregates the captures. Final cleanup confirmed
no active native viewer and no remaining tour temporary workspace directories.
