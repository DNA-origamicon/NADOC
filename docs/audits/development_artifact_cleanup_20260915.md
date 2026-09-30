# Development artifact cleanup

Completed across 2026-09-15/16. Retained development folders were atomically moved
from the user workspace to `/media/jojo/Archive/NADOC_archive/runtime/development-artifacts`,
accessible through the gitignored repository alias `.development-artifacts/`.

43 folders retained: gold/electrode/PEG campaigns, literature sources, native
build evidence, old MD validation and MIG benchmark evidence. Deleted the empty
`workspace/playwright_tests` directory. User designs, application-managed jobs,
benchmark job records, runtime plugin registry and active application state remain
in place. Files named “test” were not assumed disposable.

The [relocation index](development_artifact_relocation_20260915.json) records old
and new paths, regular-file counts, bytes and repaired symlinks. Historical JSON
and hashed simulation inputs remain unchanged; use the relocation index to resolve
old paths in those records. Live code defaults and readable documentation links
were updated. No compatibility symlinks were left in the user workspace root.

Verification: retained directory inodes and regular-file inventories preserved;
pinned ether asset hashes and installed electrode plugin hash match. 354 existing
symlinks repaired. Scoped electrode/native/PEG/gold tests: **37 passed**.
`git diff --check` passed.

Required `just test-smart` decision and result:

```
decision: FAST  (fast suite only)
27 failed, 8537 passed, 110 skipped, 9 errors in 24.42s

  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The full fast suite is not green. Its reported failures are in the existing
aptamer/fixture/oxDNA areas; the cleanup-related scoped tests pass. No heavy suite
was launched or its guard bypassed.

Future cleanup rule: [project memory](../../memory/feedback_development_artifact_cleanup.md),
also linked from `CLAUDE.md` and the memory index.
