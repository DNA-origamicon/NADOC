# Shared NADOC design workspace

Before generating or modifying molecular documents, read the owning NADOC
checkout's `CLAUDE.md`, `memory/feedback_structure_requires_process.md`, and
`memory/feedback_polymerization_extension_scope.md`. Their construction,
document-ownership, geometry authorization and simulation rules apply here.

STRUCTURE WITHOUT PROCESS IS DISALLOWED. Publish agent-authored `.nadoc` parts
through `scripts.agent_structure_guard.publish`; reopen and independently audit
their complete recorded process. Do not create capture roots or fabricated rows.
Assemblies remain `.nass` documents with upstream histories and referenced parts.
If no valid authoring path exists, stop with `AGENT_PROCESS_REQUIRED`.

Shared reconstructions must be saved under `workspace/Shared Designs/`, which is
tracked by the main NADOC repository. Stage specific audited files from the NADOC
root; do not initialize a nested repository. Store native documents directly in
this folder, with one catalog in README.md. Keep required review evidence in
`.provenance/`, not nested design/run directories. Preserve historical source
references through the hash-bound read-only relocation manifest when moving files.

Keep all dependencies inside this shared folder. Use workspace-relative assembly
references beginning `Shared Designs/`, never another machine's absolute paths.
Preserve source IDs and existing histories. Do not rewrite existing documents to
make them portable without the applicable authoring/recording path.

Inspect Git status before synchronization. Never discard local edits, force-push,
or merge conflicting molecular JSON automatically. One machine owns each design
while editing. Save/close affected designs before pulling to avoid stale editors
overwriting synchronized files. Git is not a distributed edit lock.

Keep simulation jobs, trajectories and machine credentials out of this shared folder.
Record the design Git commit, NADOC code commit, generator parameters, input
hashes in each native feature log. Keep development inputs and reports outside
this shared folder under `.development-artifacts/all-origami/`. Transfer is not certification
of simulation readiness. Do not launch scientific simulations without a specific
user request.
