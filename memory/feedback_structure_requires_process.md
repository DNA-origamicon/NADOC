---
name: Structure without process is disallowed
description: Unilateral agent safeguard requiring complete, truthful feature history for every created structure, including reviews and candidates
type: feedback
authority: canonical
status: active
---

# Structure requires its complete process

User correction, November 1, 2026: the purpose of the feature revamp is that no
structure can be generated without a complete feature log. A final geometry
without the operations that produced it cannot be diagnosed. This is a hard
agent/LLM requirement, not a presentation preference.

Every agent-created deliverable must preserve the full ordered construction and
all subsequent changes: tool names, exact inputs and selections, parameters,
source histories, transforms, routing, 5′/3′ attachments, and molecular candidate
steps. Use actual feature-recording execution; verify the saved/reopened log and
independent replay. An import/capture row, descriptive notes, camera tour, script
link, nonempty log, or a snapshot that merely reproduces itself is insufficient.

Never clear `feature_log`, substitute an import root for authored construction,
invent historical actions, silently mutate the graph after logged operations,
or embed an unrecorded atomistic override. Derived/flattened structures retain
the process of their input parts plus assembly/materialization operations.
Candidate placement requires its own isolated, explicit process as well as the
unchanged source construction; a log does not authorize production promotion.

If the complete process cannot be recovered or recorded, fail publication with
`AGENT_PROCESS_REQUIRED` naming the missing stage. Repair the recording path or
rebuild through supported commands before delivering a structure. Do not hand
over a history-free temporary substitute. Existing legacy evidence may be read
without treating it as a compliant new artifact.

This supersedes the earlier full-design snapshot exception in
`feedback_geometry_change_authorization.md` and the FH-27 review generators that
cleared history. No agent may waive this rule unilaterally, even for diagnostics.
The six FH-27 files delivered earlier were noncompliant; do not cite their
atom/camera checks as feature-history acceptance.

## Part and assembly ownership clarification

Further user correction, November 1, 2026: polymerization in a `.nadoc` part is
limited to the periodic seam strands that inform assembly polymerization.
Repeated part instances and their joins belong to the `.nass` assembly and its
feature history. A flattened assembly prepared for simulation/export is derived
assembly output; do not publish it as an authored part or insert assembly steps
into a part's history. Preserve upstream process in the appropriate documents.

The reconstructed FH-27 Terminal linker pair violates this boundary despite
passing independent process replay. Its diagnostic F7 creates an in-memory
assembly, F8 polymerizes three repeats, and F9 (`assembly-flatten`, misleadingly
displayed as `Prepare NAMD`) replaces the part with the flattened assembly.
The flattener supplies the missing halves of unmatched terminal staples as
`StrandExtension` objects. This is a materialization policy, not an instruction
to convert a source part's periodic seam strands into extensions.

Treat that pair as retained diagnostic evidence, not accepted part deliverables.
The original publication guard checked replay completeness without document
ownership. On November 2, `scripts.agent_structure_guard.audit` and `publish`
also reject private `diagnostic-process` and assembly commands as part-authoring
operations. Standalone diagnostic replay remains available for inspecting old
evidence; it is not a publication certificate. The saved diagnostic files were
not rewritten, and the shared simulation materializer needs its separate fix.

November 2 follow-up: automated authoring is restricted to user-facing operations
in the correct editor context. No private diagnostic feature may substitute for
a missing operation. The user rejects polymerization-strand conversion to ordinary
extensions, and defers general long-extension molecular geometry beyond the
feature-log/dependency overhaul. Read
[the scope decision](feedback_polymerization_extension_scope.md).
