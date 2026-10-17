# Native extrusion append through the immutable host — U51

**21/38 milestones complete; 17 remaining (8 core, 9 parked).** U51 is engineering
checkpoint 51 since B1. FH-28 remains open after seven checkpoints and continues
to be task-growth flagged. Delta +0 completed/+0 total; no exit was narrowed.

## Delivered behavior

The gated geometry API can now create an empty root, append any of the seven
native extrusion families, edit earlier features through the resulting suffix,
save, undo/redo and recover exact saved bytes. New append requests use
`POST /api/design/geometry-history/features` with kind, authored parameters and
exact expected design/revision. The request body cannot supply an output seed,
proof version, source receipt or candidate model. The host generates the feature
identity and binds the original session/source before body acquisition.

Creation normalization reuses the existing request schemas and strict extrusion
input rules, retaining original JSON types to reject legacy coercions. Native
receipts are bound against the independently regenerated prefix, after source
proof. The existing append evaluator reserves the history allowance, executes
one native definition, records recovery and independently proves the completed
candidate. There is no new command language or saved model authority.

The shared immutable host now distinguishes append from edit in its existing
admission. A checked append adds exactly one history row; edits preserve row
count. Both use the same bounded worker, source/policy checks, publication permit,
retention limits, cancellation and HTTP disconnect drain. Scalar reads still do
not decode or copy the source. Input/capture/deadline limits are unchanged.

Native bundle construction can assign a fresh model identity. The append adapter
now retains the document identity, as the existing history editor does, and uses
the existing document-state preservation helper. This adapter correction changes
no molecular builder or scientific output. Independent candidate proof runs
before publication, not merely as a test oracle.

## Evidence

**301 unique focused cases have passing results:**

- Append (initial 16), immutable host (37), worker (23): 76 passed in 19.96 s.
- Expanded append (18), input rules (52), evaluator (14), geometry HTTP (19),
  strict dispatcher (61): 163 passed/1 failed in 14.33 s. The failing old envelope
  case exposed missing revision admission; mandatory append revision fixed it.
- Evaluator (14), coating append (65), pattern history (12), expanded append (18):
  109 passed in 10.74 s. This includes the previously failing envelope case.
  Three existing ORJSONResponse deprecation warnings occur in evaluator setup.

New tests exercise all seven families against native replay, real subprocess
create/append/edit/save/undo/redo/recovery, stable host-owned feature/output seeds,
missing-reference diagnostics, malformed/protected inputs, request tampering,
cancellation and rejection when generic append lacks owned capture context.
The seven-family transport fixture controls process scheduling while executing
the real native evaluator; the complete workflow also uses actual subprocesses.

An initial run refused bundle append because the existing builder changed the
document identity. The adapter correction above resolved that failure without
relaxing preservation checks. No expectation was changed to accept the identity
loss. Existing generic envelope rejection also remains intact.

Changed-file Ruff and diff checks pass. Memory lint retains baseline six errors/
59 warnings; the project head is 200 lines. `main.js` remains 7350 lines, delta
zero. No frontend changes, molecular constants, lock fixtures or goldens changed.

`test-smart --dry-run` selected FULL from accumulated changes with FAST fallback;
zero broad tests ran. Literal notice (the dry run did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Remaining exit

**NOT VERIFIED IN APP.** Public gates stay off. These small-file and native-worker
checks do not establish desktop responsiveness or near-limit memory/latency.
The added independent candidate replay has a real cost which must be measured
within the existing bounds; no interactive speedup is claimed. Ordinary mutable
capture's GC risk remains open.

Next integrate the other priority tools (Sweep, Bend/Twist, Move/Rotate and Fine
Routing) with this same host and their existing owned evaluators. Full preserved
state, editor wiring, resource acceptance and public catalog qualification remain
required. Assemblies/VR and parked assets retain their agreed priorities. Seven
FH-28 checkpoints is a visible growth warning, not seven completed milestones.

Cleanup removed 607 completed pytest entries including 77 owned small
files (1,380,898 bytes). No readable same-user process referenced them; PIDs
435/436 remained uninspectable. Pytest scratch/shared memory are empty; user
designs, existing caches and managed jobs were preserved.
