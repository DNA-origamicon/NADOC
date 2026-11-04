---
name: Semantic document provenance without autosave noise
description: Record meaningful document operations separately from repetitive persistence
type: feedback
authority: canonical
status: active
---

# November 3, 2026 scope decision

The user expects autosave and does not want a feature-log entry for each save.
Extend provenance to meaningful document operations: renames, loadout creation
and other non-geometry actions. Initialization of an actual Main loadout is a
single semantic event; repeated persistence is internal bookkeeping.

Keep construction history and document-operation provenance distinct. The user
authorized the feature-log filter on November 3: Fine routing, Document ops,
and a disabled Annotations and visuals option. Document ops reveals the semantic
journal without autosave rows or geometry seek targets. Annotation creation/editing,
view-volume creation/editing and animation execution remain deferred.

This does not relax independent construction replay, physical-reference checks,
part/assembly ownership, or the prohibition on inventing historical operations.
