---
name: project-protein-conjugation-optimization
description: End-to-end optimization and measurable validation of protein import through ssDNA conjugation; rooted in the VoltronCoreArm duplicate-instance defect.
metadata:
  node_type: memory
  type: project
  rank: P1
---

# Protein import → ssDNA conjugation optimization

## Goal

Make every transition from PDB acquisition through a saved, rendered, simulated protein–ssDNA
conjugate deterministic, atomic, observable, and quantitatively valid. The same physical protein
instance must never multiply merely because its attachment target changes.

## Audit baseline (2026-08-25)

The reported defect is reproduced in `workspace/VoltronCoreArm.nadoc`: one embedded asset
(`a487c4b6…`) has two visible placements. The import feature owns free attachment `5164772c…`;
the later conjugation feature appended overhang attachment `8f7e5152…`. Thus the file contains
one molecular asset but renders two physical protein instances.

Root cause: unified PDB import intentionally creates a free `ProteinAttachment`, while
`POST /design/protein/conjugate` was append-only. The right-click and selected-protein entry paths
reduced the selected placement to `asset_id`, losing attachment identity. Conjugation therefore
could not distinguish “convert this placement” from “instantiate another copy.”

The immediate correction passes `source_attachment_id` through UI/client/API and atomically
replaces that placement (preserving its stable ID) while adding the binder strand. Library-only
conjugation still creates a new placement. Mismatched source/asset pairs are rejected.

Additional audit findings:

- Import semantics differ: `/design/protein/import` is library-only, while unified PDB import
  embeds an asset and creates a free placement. The UI must label these outcomes explicitly.
- Asset identity and placement identity are distinct but are visually conflated in several flows.
- A user can intentionally instantiate the same asset multiple times; deduplication must therefore
  operate on placement IDs and intent, never merely on `asset_id`.
- Conjugation correctly groups binder creation and attachment mutation in one feature-log entry,
  but needs stronger idempotency, occupied-overhang, redo, and failure-rollback oracles.
- Candidate quality reports solvent accessibility but the committed element stores only atom
  serial; it does not persist the candidate chemistry/accessibility evidence used for the choice.
- The viewer preview has no inferred bonds, while export does, creating a representation mismatch.
- Assembly-scope attachment is modeled but not implemented; it remains a separate gated phase.
- Existing manual checks (MV-CONJ, MV-15, MV-OX-PROT, MV-MD-PROT) do not yet form one traceable
  import-to-simulation acceptance chain.

## Measurement contract

Every run receives a correlation ID and records stage duration, result, and normalized error code
for: classify/download, parse, candidate analysis, preview, selection, conjugation commit, geometry
refresh, render, save/reload, undo/redo, and optional simulation export. Report p50/p95 latency,
success rate, retry rate, cancellation rate, rollback rate, and stage-specific failure counts.
No raw PDB content, sequence, or atom coordinates belong in telemetry.

Release gates for the process:

- 100% of mutations are atomic: a failed request changes neither topology nor placements.
- 100% request-to-render correlation in automated end-to-end runs.
- Zero duplicate submits while Apply is busy; one user commit produces one feature-log entry.
- Import-to-visible and commit-to-visible p95 targets are established from CI and a large real PDB,
  then ratcheted; no target may be invented without a recorded baseline.
- Save/reload and undo/redo reproduce canonical counts and IDs exactly.

Each committed conjugate exposes an element validation report with these metrics:

| Metric | Definition | Gate |
|---|---|---|
| placement cardinality delta | placements after − before for a conversion | 0 |
| asset cardinality delta | embedded assets after − before | 0 for an embedded source |
| stable placement identity | source ID equals committed attachment ID | true for conversion |
| asset referential integrity | attachment resolves to exactly one embedded asset | true |
| target integrity | overhang exists and attach end is valid | true |
| binder cardinality | newly created OH_BINDER strands | exactly 1 |
| sequence fidelity | binder sequence equals overhang reverse complement | exact |
| topology locality | unrelated strand occupancy changed | 0 |
| conjugation atom integrity | serial exists in asset and matches selected candidate | true |
| anchor error | distance from transformed conjugation atom to selected binder terminus | ≤1e-4 nm |
| orientation | protein COM lies on the outward side of the anchor plane | positive dot product |
| transform health | all pose/world-matrix values finite and rigid transform is orthonormal | true |
| render census | rendered protein atoms per visible placement equal asset atom count | exact |
| serialization parity | validation report before save equals report after reload | exact |
| undo/redo parity | undo restores pre-state; redo restores post-state | exact canonical hash |

## Execution phases

- [x] P0 reproduce VoltronCoreArm and identify the identity-loss/append-only root cause.
- [x] P1 convert a selected placement atomically; reject stale or mismatched placement IDs; add
  backend and frontend regression tests.
- [x] P2a build a pure `validate_protein_conjugate` report for cardinality, identity, references,
  target, binder, sequence, topology locality, selected-site accessibility, anchor error, outward
  orientation, rigid-transform health, and actual rendered-atom census. The API preflights it and
  returns the report; an invalid element is rejected atomically with the failed metrics.
- [x] P2b persisted-element revalidation: `GET /design/protein/validation` audits every free and
  anchored placement, detects orphan/duplicate assets, missing/ambiguous binders, and the legacy
  import→conjugate duplicate signature. The Properties panel exposes it on selected proteins.
  Audit reports are byte-equivalent across model serialization; the repair path is undo/redo-pinned.
- [x] P3 harden import/classification: explicit library-vs-place choice, duplicate-file fingerprint,
  parse warnings, atom/bond census, size limits, cancellation, and benchmark fixtures.
  Import now has an explicit **Place in design / Library only** selector (the old UI incorrectly said
  library while always creating a free placement), operation correlation IDs, and acquire/classify/
  parse/commit/total timings. Library-only is proven not to mutate the active design.
  Stable SHA-256 molecular fingerprints now ignore labels/IDs. Library-only repeats reuse one asset;
  repeated placed imports are reported as duplicate content but intentionally keep independent asset
  roots so feature deletion remains independent (a test caught and prevented unsafe coalescing).
  PDB input is capped at 50 MB and 250,000 atoms, with exact no-mutation tests for both limits.
  Parsing runs off the event loop, closing the import modal propagates an AbortSignal, and a server
  disconnect check immediately before commit proves cancellation cannot create a late placement.
  Imports enforce the design revision and operation ID; repeated IDs and callback faults preserve
  the design and undo/redo transaction exactly. Import metadata now reports input/filtered/malformed
  atom records, atom/bond census, and parse warnings.
- [x] P4 optimize candidate computation: cache by asset fingerprint and parameters, deterministic
  ranking, persist selection evidence, empty-result guidance, and large-protein performance gates.
  The commit/audit validator now uses an O(atom-count) selected-site SASA path rather than recomputing
  every candidate: real VoltronCoreArm audit dropped from 9.517 s to 0.172 s (~55×).
  Full default candidate analysis is now held in a bounded 16-entry content-keyed LRU, cleared on
  session close, returns defensive copies, and reports hit/miss + duration + candidate count. On the
  9,530-atom Voltron asset: cold 9.6261 s, warm 0.013932 s (~691×). New conjugates persist chemistry
  and accessibility evidence; legacy records infer it. Invalid site patches are atomically rejected.
  Empty results explain the supported Lys/Cys/N-terminal chemistry and recommend changing or
  engineering the construct rather than leaving the user at a dead end.
- [x] P5 harden commit idempotency and concurrency: operation IDs reject a duplicate commit and
  the UI supplies one; invalid selected sites are preflight-rejected with exact no-mutation proof.
  Occupied overhangs are now rejected by the precommit binder-cardinality gate with exact
  no-mutation proof. Validator-exception injection proves design + undo history unchanged; two truly
  concurrent identical requests prove exactly one 201, one 409, one attachment, one binder, one log.
  Stale-design revision is now enforced atomically inside the shared mutation lock and supplied from
  the frontend revision watermark; a stale preflight is 409-rejected with exact no-mutation proof.
- [x] P6 validate geometry/rendering: anchor-error and orientation oracles, preview/final bond parity,
  selection continuity, no origin ghosts, and VoltronCoreArm visual regression.
  Imported assets persist a deterministic inferred bond graph; legacy assets infer on read. Viewer
  and simulation/export paths now use the same bond pairs, and coordinate, anchor, orientation,
  transform, atom-census, selection-ID, visibility, and no-origin-ghost oracles are automated.
- [x] P7 validate lifecycle: save/reload, autosave, close/open, feature delete/cascade, undo/redo, copy,
  visibility, detach/reconjugate, and orphan-asset garbage-collection policy.
  Persisted audit serialization parity and duplicate-repair preview/apply/undo/redo are now pinned.
  Deleting a conjugate now removes its owned binder strand atomically, undo restores both, deletion
  of display-only overhang attachments preserves topology, and delete→reconjugate is clean. New logs
  carry exact attachment/binder ownership while unambiguous legacy logs remain repairable.
  A real save→clear-session→load cycle preserves attachment/binder IDs and an equivalent element
  audit (excluding runtime-only duration), not merely a Pydantic serialization round-trip.
- [x] P8 validate downstream engines: one canonical conjugate through oxDNA, coarse protein, and
  atomistic export; reconcile display and solver attachment coordinates quantitatively.
  A canonical conjugate now has a direct coordinate oracle: viewer atoms vs atomistic/MD export are
  within the viewer's 5-decimal quantum (max ≤1e-5 nm), and every oxDNA Cα bead matches its viewer Cα
  within 1e-5 nm. The broader protein MD/CG/oxDNA suite is included in the regression gate.
- [x] P9 explicitly gate assembly-scope proteins until shared assembly rendering prerequisites are
  complete. No import/conjugation UI or API creates an assembly target; persisted unsupported targets
  are reported as `unsupported_attachment_target` instead of being mistaken for a rendered element.
- [x] P10 establish CI-ready dashboards/baselines and one traceable acceptance artifact spanning
  MV-CONJ/MV-15/MV-OX-PROT/MV-MD-PROT, with performance/error budgets ready to ratchet.
  `GET /design/protein/metrics` now exposes a bounded 512-run, content-free aggregate for import,
  candidate analysis, conjugation, and validation: outcome counts, correlation coverage, total/stage
  p50/p95, max latency, and sample counts. Session close clears it. Raw operation IDs and molecular
  content are never returned. This project record is the acceptance artifact and pins the measured
  Voltron baseline alongside the automated import→viewer→export/solver gates.

## Required fixtures

Keep a tiny deterministic protein for unit tests, a medium multi-chain/heteroatom PDB for parsing,
a large real protein for performance, a sequenced one-overhang design for geometry, and
VoltronCoreArm as the permanent real-world regression. Do not silently rewrite VoltronCoreArm.
`POST /design/protein/validation/repair-duplicate` now defaults to preview, applies only an exact
audit-proven legacy pair, removes only the superseded free placement, keeps the conjugated placement,
and records an undoable feature-log repair. Real audit: 1 asset, 2 placements (1 free + 1 conjugated),
both elements individually valid, exactly 1 `legacy_unconverted_free_placement` error; audit 0.172 s
after the selected-site optimization (measured on this workstation, 2026-08-25).
