# Deferred assembly feature history work

User decision, October 14, 2026: assemblies are not yet used for real work. Defer assembly implementation until requested or needed; standard-part progress must not wait for assembly parity. Preserve existing behavior and compatibility. Shared modules should remain reusable without introducing assembly machinery into the part hot path.

This explicitly narrows the earlier audit plan and the general assembly parity rule for this initiative.

| Work | Audit evidence | Reentry requirement |
|---|---|---|
| Replay capability drift | Four advertised kinds have no dispatcher branch | Reproduce mismatch, migrate assembly capabilities to executable contracts |
| Pure assembly evaluation | Some replay temporarily replaces live session state | Extract builders, prove no revision/undo/file effects during evaluation |
| Full assembly command coverage | Only 12 general replay branches | Cover instances, connectors, joints, bindings, duplexes, polymerization, groups, gears and belts |
| Shared source transactions | Instance replacement writes shared source files | Pin source revisions/content; atomic publication; invalidate all affected instances |
| Assembly field coverage | Diff encoder represents instances/joints only | Reproduce non-instance/joint revert gaps at large-assembly threshold; version format |
| Assembly validation caching | Many instances can reference one source | Validate each source revision once; preserve placement/mate semantics |
| Assembly UI and strict policy | Selected source and assembly histories differ | Adapt part diagnostics and repair policy, then add cross-part references |
| Scale validation | Compact snapshots, skip-pre and source deduplication already exist | Benchmark shared/distinct sources and large assembly interactions |

Do not prune assembly replay, state, file adapters or legacy decoders as part of the standard-part cleanup. The no-op `_evict_oldest_payloads_if_over_budget` remains as an assembly compatibility shim until its assembly caller is migrated. No assembly files were changed in the initial standard-part foundation.

On reentry, reuse the part registry/transaction/verification concepts and refresh the audit; do not assume the October source inventory still describes all current code.
