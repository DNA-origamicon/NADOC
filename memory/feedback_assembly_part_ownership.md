---
name: Assembly and source-part ownership
description: Edit source parts separately and update all instances; assemblies position and connect parts.
type: feedback
authority: canonical
status: active
---

# User clarification — November 27, 2026

Assemblies must not edit part definitions or part feature histories. Open the
source part in its part editor, make the change there, then update all instances
of that source in the assembly. Do not provide instance-only part edits or use
assembly controls to mutate a shared source implicitly.

Assembly authoring controls how whole parts are positioned, repeated, grouped,
and connected. Deformation and part-internal construction/topology tools belong
in the part editor. Their absence in assemblies is not a parity defect.

Part-authored interfaces can inform assembly operations: periodic seam strands
may dictate assembly polymerization. The part owns the interface definition;
the assembly owns repeated instances, placement and inter-part connections.
Preserve the prohibition on converting polymerization strands to extensions.

This supersedes conflicting shared-source/instance-only editing guidance and
historical selected-instance editing goals in project_assembly_feature_parity.md.
Existing embedded part edits are implementation debt to assess, not authorization
to extend that behavior. No runtime changes were requested in this turn.

## Pattern audit correction — fetched upstream verified November 27, 2026

Whole-origami Linear and Circular Pattern DO exist on origin/master, introduced
by commit 75d33dac (assembly: add whole-origami linear and circular patterns).
The earlier absence finding applied only to the stale em-adaptive-glow-controls
checkout and must not be repeated as a repository-wide conclusion.

Assembly menu entries reuse the pattern panels through assembly_pattern_host.js,
a read-only preview adapter. /assembly/linear-pattern and /assembly/circular-pattern
record assembly-linear-pattern and assembly-circular-pattern. The kinds are in
SnapshotOpKind, feature labels, assembly replay and history editing. They copy
whole instances with deterministic identities and preserve source designs/history;
existing mates remain on originals. Linear supports 1D/2D patterns; circular
supports arcs/full circles and an axis. Source inspection confirms these mappings;
this audit did not rerun upstream tests or browser checks.

Existing polymerization and group duplication are separate assembly features.
The audit initially searched only the current worktree and part-tool guards,
without checking branch freshness or upstream assembly-native implementations.
After fetching origin, git pull --ff-only reports the tracked feature branch
already current, but HEAD and origin/master diverge (5 local / 23 upstream commits
at inspection). Master was inspected directly; it was not merged into the heavily
dirty worktree. Preserve local work and reconcile branches explicitly before
claiming these tools are installed in this checkout.
