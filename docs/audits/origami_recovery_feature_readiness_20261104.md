# Recovered origami feature-process readiness — November 4, 2026

## Verdict and scope

None of the five previous image-recovery attempts is currently certified for
publication under the complete-process requirement. Their saved `.nadoc` review
files were deleted on November 2; retained reports and extraction traces exist.
This audit checks those actual traces, source hashes, recovery scripts and current
command/dependency implementations. It does not claim to have replayed deleted
files or to have rebuilt any design. The scope is D007, D008, D005, D006 and D021
in `experiments/origami_publication_catalog/recovery`, not every catalog entry.

All five source-PDF hashes match the retained recovery reports. The reusable
[read-only audit](../../experiments/origami_publication_catalog/recovery/audit_feature_readiness.py)
produces [machine-readable evidence](origami_recovery_feature_readiness_20261104.json).
Run it from the repository root:

```sh
.venv/bin/python -m experiments.origami_publication_catalog.recovery.audit_feature_readiness
```

## Common publication blockers

1. **Construction was never recorded.** `recover_first5.py` synthesizes caDNAno
   arrays from PDF strokes and calls `import_cadnano`; it then assigns helix labels,
   sequences and metadata directly. `recover_pin_partial.py` similarly assigns
   fragment names/notes. Both write `model_dump_json()` directly, bypassing
   `scripts.agent_structure_guard.publish`. A pinned import of these synthesized
   arrays would conceal the agent's construction rather than record it.
2. **Evidence must become explicit construction inputs.** Existing traces retain
   routes, stroke sequence numbers, slice coordinates and insertions. PDF hashes,
   page selection and calibration are in separate reports; glyph maps and the
   D006 placement exception are in Python. Neither D007 nor D008's trace retains
   the extracted nucleotide map, despite historical sequence assignments. Re-extract
   those glyphs from the pinned PDFs and retain their mapping to recorded sequence
   commands. Do not use the held-out staple tables to silently fill the gap.
3. **Native composition is missing.** Compile the extracted selections into ordinary
   recorded operations from an empty root: lattice helix creation, explicit strand
   domains, supported crossover/ligation operations, insertions and sequence edits.
   Preserve source-to-native identity mapping and the actual coordinate transforms.
   Importer-specific axis trimming, honeycomb coordinate normalization, phase and
   crossover/forced-ligation classification must be accounted for; it is not enough
   to copy final objects or append a private connectivity-derivation feature.
   These equivalences have not yet been demonstrated for the recovered designs.
4. **Acceptance checks are incomplete.** `validate_and_report.py` checks internal
   topology, sequence comparisons and serialization equality. It does not call the
   publication guard, independently replay commands, or check native dependencies.
   A historical validator pass and `PROCESS.txt` are not feature-log acceptance.

The recovery scripts remain historical evidence; this audit did not run them or
change their publication behavior. They must not be used to regenerate deliverables
until the above paths are replaced. Publication remains
`AGENT_PROCESS_REQUIRED: native construction and replay not established`.

## Design-specific findings

| Design | Retained evidence | Remaining gap |
| --- | --- | --- |
| D007 Monolith | 60 helices; 145 paths including scaffold; historically 145 assigned sequences and 144 exact staple-table matches | Best first rebuild target. No additional unsupported insertion found. Must re-extract/pin glyph assignments and prove complete native construction/reopen/replay; not yet certified. |
| D008 Square nut | 60 helices; 150 paths; historically 150 assigned sequences | Same process gap as D007. Published table coordinates are image coordinates +4; one image staple is absent from the 148-entry table. Keep image-local coordinates and explicit uncertainty until resolved; neither issue permits an inferred topology edit. |
| D005 Right-twisted 10×6 | 60 helices; 218 paths; 361 insertion sites, totaling 504 inserted bases | **Concrete command gap:** recovered helix 0, BP 70 has delta +144. Both the live recorder and replay builder for `loop-skip-insert` accept only −1, 0, +1. Unknown nucleotide sequences remain unassigned. |
| D006 Straight 3×6 | 19 helices including carrier 19; 210 paths; no assigned sequences | Carrier 19 is absent from the slice view. Its placement was taken from `protractor_0_v3.json` after an image-only failure, then hardcoded as helix 0 row−1, col+2. Pin the actual diagnostic source and selection alongside the recorded placement; do not describe it as purely image-derived. |
| D021 Pin pore | 55 slice positions and 62 unjoined scaffold fragments | Source-recovery blocker: no recovered staple routing, inter-helix connections, sequences or absolute register. A complete log could describe a partial evidence artifact, but cannot turn extraction boundaries into biological nicks or certify a complete origami. |

The D005 insertion is representable in the model and legacy importer, but that
does not supply an ordinary authoring command. Repeating +1 at the same position
overwrites the existing mark rather than accumulating to +144
(`loop_skip_calculator.apply_loop_skips`). `apply-loop-skips` realizes deformation
recipes; it is not an arbitrary insertion-list command. A proper multi-base
insertion operation needs its own user-facing semantics, recorder, replay,
dependencies and validation. Do not replace the loop with a strand extension or
change molecular placement to work around this gap.

## What the dependency check does and does not prove

Runtime probes of current `part_proof_commands.dependencies` recognize
`helix-add-at-cell`, `strand-add`, `loop-skip-insert` and `strand-sequence`.
All four are conservative whole-topology barriers, and the resulting dependency
index reports `complete=true`. This conservatism protects downstream operations
but does not establish fine-grained independence between unrelated helices/strands.

The +144 insertion probe also reports a known dependency contract even though its
executor rejects that parameter. This is a distinction between dependency coverage
and command validity, not evidence that the insertion works. Missing feature rows
cannot be detected or reconstructed by analyzing dependencies of the rows present.

## Required next validation

Start with D007 through the real recording paths and preserve the extraction
receipts. For each completed reconstruction, require exact topology/sequence
comparison to the evidence, complete command/dependency admission, guarded
publication, saved/reopened independent replay, and representative visual review.
Test deletion/edit impact against the resulting real log. Keep D005 blocked at the
multi-base insertion until its authoring path exists; keep D021 explicitly partial.
Unknown sequence is a valid recorded state, but not a complete synthesis sequence.

Only the read-only audit was executed in this task. No new molecular structure,
simulation, workspace part, application behavior change, or broad regression run
was produced. Existing recovery evidence and the pause record were preserved.
