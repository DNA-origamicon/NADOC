---
name: Molecular geometry changes require demonstrated authorization
description: Show current versus candidate structures and defect-local evidence before asking the user to authorize molecular placement changes
type: feedback
originSessionId: full-test-2026-08-11
---
# Molecular geometry changes require demonstrated authorization

Descriptions such as "calibrated", "native", "ring-safe", or "lower-clash" are not sufficient
evidence for a molecular-placement decision. They often fail to identify what is actually moving
or why an oracle changes verdict.

## Binding gate

Before changing production molecular geometry:

1. Keep the current production placement byte-for-byte locked.
2. Implement any proposed placement only in an isolated diagnostic/candidate path. It must not be
   selectable by ordinary representation controls, serialized into `.nadoc`, exported, or passed
   to a simulation.
3. Produce an A/B evidence bundle in a shared coordinate frame. It must include current,
   candidate, and displacement-overlay views; highlight the exact intersecting bond and ring or
   clashing atom pair; and report per-junction displacement, bond-length, clash, and piercing deltas.
4. Show representative 2HB structures plus the full helical-phase sweep. A clean aggregate count
   without inspectable positive and negative examples is insufficient.
5. Ask for explicit authorization of the demonstrated candidate. Authorization of an investigation
   or diagnostic view is not authorization to promote its geometry.
6. Only after that authorization may production placement change and geometry/visual goldens be
   regenerated. The implementation must preserve a comparison artifact or regression fixture that
   can go red.

The preferred review surface is the implemented Help-menu Molecular Placement Audit described in
`docs/molecular_placement_audit.md`: Current, Candidate, whole-structure Difference, and an
independent ring-piercing/clash close-up, each switchable between Full and Ball and Stick. If that
surface cannot represent a future candidate, extend its isolated evidence schema or generate the
same artifact bundle offline; do not substitute prose.

## Review presentation (user correction, 2026-10-21)

Never ask the user to open a bare HTML file and infer a decision from unexplained 3D
geometry. Every authorization request must explain what Current and Candidate mean,
what construction and feature-log actions produced each state (including selections,
resets, replacements and ordering), and the specific difference to focus on in plain
language. Keep a readable feature sequence visible alongside the comparison; raw JSON
is supplementary evidence, not the explanation. Distinguish authored native history
from a diagnostic candidate program and identify the limits of the requested approval.
Provide a verified one-click viewing link or an exact copyable bash command that opens
the review. Restate the comparison and decision in the request itself. Do not infer
physical validity from an ordering demonstration or seek broader approval than shown.

User refinement (2026-10-21): prefer NADOC itself for explaining construction and
ordering. Supply one or two representative real `.nadoc` files with readable,
replayable feature logs and saved step-by-step animations, so the user can inspect
and experiment. Keep phase sweeps as engineering validation, not a long menu of
review cases. Clearly distinguish native behavior from an unsupported candidate.

User-facing naming (2026-10-21): always call operations by their UI tool names in
conversation and reviews. Feature-log rows must start with `F<position>: <Tool>
<tool occurrence>` and may append explanatory text, e.g. `F1: Extrude 1 [two
helices]`. Internal recipe identifiers are implementation details, not tool names.

Make Cluster (2026-10-21): show membership creation as its own `F<x>: Make
Cluster <n>` entry, without moving geometry, followed by a regular Move/Rotate
entry. Do not hide a move inside creation or call the feature Create Placement.
