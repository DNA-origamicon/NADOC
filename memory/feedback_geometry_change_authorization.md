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
