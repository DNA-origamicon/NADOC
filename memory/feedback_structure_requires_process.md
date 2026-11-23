---
name: Structure without process is disallowed
description: Unilateral agent safeguard requiring complete, truthful feature history for every created structure, including reviews and candidates
type: feedback
authority: canonical
status: active
---

# Structure requires its complete process

## Mandatory quantitative bond review — November 22, 2026

User instruction: an imported design with **more than 20%** of its bonds marked
as forced ligations must trigger review. The same applies to any agent
reconstruction with **more than 20%** of bonds longer than a standard crossover.
This is an additional acceptance check; complete replay is still required.

Count unique realized covalent backbone edges from the actual strand paths, and
report both the whole-design fraction and the interhelix-junction fraction.
Apply the threshold to either denominator so ordinary intrahelix bonds cannot
hide systematic crossover substitution or stretch. Pending unligated crossover
records are not bonds. Use the existing conservative **1.2 nm Full-view O5′
endpoint separation** envelope: native HC crossover classes span approximately
0.749–1.085 nm. This measures displayed backbone geometry, not an O3′–P chemical
bond. Missing geometry is an incomplete review, never evidence of a pass.

Stop acceptance when flagged; inspect representative junctions in 3D, report
counts and examples using visible helix labels, and investigate lattice frame,
phase, bp origin, import classification and routing before continuing. Do not
remove/reclassify bonds merely to reduce the percentage. A legitimate exception
requires a documented review tied to the exact design and report; it cannot
waive provenance or authorize molecular changes. See
[the executable workflow](../docs/design_bond_review.md).

## Corner-motif interpretation — November 23, 2026

User clarification: D003's forced ligations are part of corner-motif construction,
mainly joining four differently oriented clusters. Intentional corner seams are
a valid reason for exceeding 20% forced ligations; the threshold requires review,
not automatic rejection. Agents must inspect cluster orientations and recorded
seam connections, account for all realized forced junctions, and document the
supported motif explanation in the exact-design review receipt. Retain the raw
fractions and distinguish user-provided intent from independently checked facts.
This explanation does not automatically resolve long bonds, incomplete geometry,
source/provenance failures, or authorize molecular changes. Follow the
[corner-motif review procedure](../docs/design_bond_review.md#intentional-corner-motifs-and-differently-oriented-clusters).

## Overhang and crossover semantics — November 22, 2026

User correction following the rejected Gür 2016 reconstruction: **overhangs must
never be created as extensions**. Use native overhang authoring, retaining the
source routing, attachment and overhang identities. Do not replace ordinary
crossovers with forced ligations to make a reconstruction pass validation.
The combination of widespread forced ligations and extensions standing in for
overhangs is a major diagnostic red flag, not an acceptable modeling shortcut.
Investigate importer classification, lattice coordinates, phase and bp-index
origins first. A replayable history or matching sequences cannot validate these
substitutions. The 865-command Gür review file was rejected despite those checks;
do not reuse it as a simulation seed or a successful construction precedent.

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
