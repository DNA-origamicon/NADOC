# Mandatory agent construction provenance

Read `CLAUDE.md` and `memory/feedback_structure_requires_process.md` before
creating, modifying, or delivering any NADOC structure.

**STRUCTURE WITHOUT PROCESS IS DISALLOWED.** Every agent-created structure must
have a complete, truthful, ordered feature log accounting for its construction,
inputs, selections, parameters, transforms, connections, and subsequent changes.
This applies equally to examples, diagnostic/review copies, candidates, flattened
assemblies, generated parts, and files written directly by scripts.

- Use the real feature-recording command paths. Preserve upstream part and
  assembly histories through derived structures.
- Automated authoring must compose user-facing operations valid in the target
  editor. Internal simulation/export helpers are not authoring commands; do not
  invent private diagnostic features to bridge a missing user operation.
- Preserve document ownership: a `.nadoc` part may define periodic seam strands;
  repeat instances and polymerization belong to a `.nass` assembly. Do not insert
  assembly operations or a flattened assembly into a part feature history.
  Simulation/export materialization is a derived assembly artifact, not an
  authored part. Complete replay does not waive this boundary.
- Polymerization strands must not be converted into ordinary strand extensions.
  Dedicated simulation handling and long-extension geometry remain separate
  development work; read `memory/feedback_polymerization_extension_scope.md`.
- Never clear history, replace construction with a captured/import root, attach
  prose-only provenance, fabricate feature rows, or hide unrecorded molecular
  changes in an atomistic reference to satisfy this requirement.
- Before delivery, verify the actual saved/reopened feature log and independently
  replay its recorded process. A nonempty log alone is not proof of completeness.
- Publish agent-authored parts through `scripts.agent_structure_guard.publish`;
  `python -m scripts.agent_structure_guard PATH.nadoc` independently audits an
  existing part. This checks physical atom references as well as authoring state.
  It also refuses private diagnostic and assembly commands in a part log, even
  when independent diagnostic replay succeeds.
  Never bypass its refusal by calling `write_text`/`to_json` directly.
- If an operation lacks a truthful recorded/replayable path, stop publication
  with an explicit `AGENT_PROCESS_REQUIRED` error and implement that path first.
  Do not offer a history-free file as a temporary workaround.
- No agent may infer an exception from a request for a full design, quick demo,
  geometry review, imported snapshot, or isolated candidate. Earlier snapshot
  exceptions are superseded by the user's November 1, 2026 instruction.

Reading an existing legacy file for diagnosis is permitted; it does not authorize
creating another history-free structure. Molecular-geometry authorization remains
a separate requirement and cannot be bypassed by adding a feature log.
