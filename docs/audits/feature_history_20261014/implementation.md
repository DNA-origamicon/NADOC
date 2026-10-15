# Standard part feature history implementation

Scope approved October 14, 2026: implement standard-part validation, editability and agent enforcement first. [Assembly work is deferred](assembly_deferred.md). Part-local proteins, nanoparticles, duplexes, attachments and imports remain in scope; they are not assemblies merely because they contain multiple components.

## Delivery sequence

| Phase | Scope | State and exit condition |
|---|---|---|
| P0 | Inventory, field ownership and performance evidence | Source audit complete; initial recording benchmark captured. Add workloads as the affected subsystem changes |
| P1 | Standard-part recording transactions, executable replay registry and evidenced cleanup | Foundation implemented below. Retain legacy callbacks and compatibility recovery; no claim of general isolated evaluation |
| P2 | Explicit recipe roots/versions, authoritative-field classification, read-only verification and incremental dependencies | Pending. Add proof-mode replay, typed dependencies, complete-state comparison, bounded jobs and revision invalidation; unsupported entries remain unverified |
| P3 | Complete native DNA command families and generated construction | Pending. Cover helix/strand/domain/routing/sequence/loop-skip/pose/pattern/sweep/join operations, deterministic IDs and parameter editors |
| P4 | Standard-part assets and attachments | Pending. Explicit import provenance, duplex/protein/nanoparticle commands, physical-result separation and all current part authoring bypasses |
| P5 | Standard-part repair, drafts, desktop and part-mode VR | Pending. Revision-bound impact previews, failed/blocked diagnostics, reference replacement, last-successful-state display, undo/reload |
| P6 | Strict standard-part agent transactions and legacy retirement | Pending. Pure candidate execution outside long-held locks, expected-revision publication, registered command batches, bypass closure and explicit import exceptions |

Assemblies are not an exit condition for any phase above. Existing assembly compatibility tests may catch collateral changes to shared infrastructure, but new assembly features and fixes remain deferred.

## Implemented foundation

- `backend/api/feature_recording.py` owns common part-history recording and failure rollback. Both wrappers restore design, full bounded undo stack, redo, document revision and request revision/history marker on callback, reconciliation, encoding, diff, validation, or publication exceptions and cancellation.
- Publication happens after validation and recording. Reports containing integrity findings still permit editable drafts; this is not premature strict enforcement.
- Recording keeps the existing single design snapshot copy. Copying undo/redo deque entries copies references only; no additional full-design copy, dependency scan, or replay was added to ordinary edits.
- `backend/core/feature_registry.py` declares the six existing snapshot builders and 14 minor builders. `backend/api/part_feature_commands.py` adapts the same schemas, algorithms and reconciliation; `crud.py` retains compatibility entry points. Dependency replayability is derived from this registry.
- `GET /api/design/features/capabilities` exposes part executor availability and explicitly does not certify history. Existing frontend edit schemas are unchanged; deriving UI editor/repair capabilities is later work, not falsely represented by executor availability.
- Removed unused payload accounting/clearing helpers, the unused old eviction alias, unused delta-kind set, and obsolete snapshot-budget constant. Removed no-op eviction calls from part recording. Retained the no-op function used by the deferred assembly adapter and all legacy snapshot decoding.
- Replaced tests that monkeypatched an inert budget with direct recovery-payload retention tests, and strengthened oldest-snapshot seek to compare recorded topology rather than merely requiring nonempty geometry.

The recording transaction remains under the existing state lock and supports in-place callbacks. It is **failure-atomic recording**, not a pure candidate executor. Moving arbitrary existing callbacks outside the lock would introduce races; that change waits for registered pure builders and revision-bound commit. Full history reproducibility and agent enforcement are not enabled yet.

## Validation lifecycle

For every family: first characterize existing behavior and reproduce a gap, add a behavioral regression, implement the contract, and update or remove tests whose obsolete implementation assumptions no longer apply. Preserve independent restoration/regeneration oracles. Keep unsupported legacy cases explicit instead of deleting their tests to obtain a green suite.

Foundation regressions cover full undo capacity, redo preservation, new and appended routing clusters, failures before/after publication, invalid record schemas, cancellation, draft reports, builder/schema capability resolution, unknown commands and live-document isolation of direct builder replay. Existing feature snapshot, routing diff, dependency, edit and evaluation tests remain applicable.

### Performance evidence

`scripts/benchmark_feature_recording.py` compares the original recording functions at Git revision `dfa63eeb` against the extracted implementation, with unchanged state services and algorithms. It generates designs in memory and writes only compact JSON; it never opens user designs or stores model dumps on disk. [Raw paired samples](recording_benchmark.json) record 31 alternating paired batches of 10 iterations for snapshot and minor recording on 1-helix and 24-helix designs, with zero or 100 existing rows. Cyclic garbage collection is disabled only inside timed regions, matching the existing evaluator microbenchmark methodology. Separate tracemalloc measurements include fixture copying and exclude native allocations.

All six batched cases passed the existing median regression gate (both >5% and >0.05 ms); the largest candidate median increase was about 0.044 ms. Measured Python allocation peaks did not increase. The earlier [unbatched GC-enabled run](recording_benchmark_unbatched.json) is retained: it flagged the 100-row snapshot case (1.881 → 2.020 ms) and included a 21.681 ms candidate outlier. This motivated batching/GC-controlled diagnosis rather than a threshold increase. Batched microbenchmarks do not certify end-to-end GC pauses; retain that distinction in future interaction testing. This measures warm recording overhead, not network, rendering, future dependency evaluation or cold audits. New validation requires its own affected-work and interactive benchmarks before enabling it; the current result does not justify scanning full history on every edit.

### Execution results

- Focused final checks: **179 passed** across recording transactions (32), registry (24), snapshots (35), routing clusters (23), routing diffs (14), feature edit core (13), evaluator (17), dependencies (11), and seek previews (10).
- The existing evaluator A/B benchmark stopped at `Geometry mismatch: compact-one`; the same assertion reproduces on unchanged `dfa63eeb` ([evidence](evaluation_benchmark_baseline.json)). Its frozen reference lacks current preview response fields (`cluster_transforms`, `display_design`), so this run cannot certify preview performance. The reference was not weakened to obtain a pass; updating its response-contract adapter while preserving independent replay is validation debt for P2.
- Changed Python files pass Ruff; `git diff --check` passes. State shrank by 241 lines and crud by 118 lines; `frontend/src/main.js` line delta is **0**.
- `just test-smart` decision: **`FAST  (fast suite only)`**. **11,075 passed, 21 skipped, 23 failed, 8 errors** in 188.10 seconds; outer guard elapsed 207 seconds against a 90-second backstop.
- All 23 failing cases, all four preview setup errors, and the missing-file collection error reproduce with the five changed existing application modules loaded from unchanged Git revision `dfa63eeb` in memory. No checkout files were reverted. [Baseline reproduction details](baseline_failure_check.json). The broad run reports the collection error four times because four workers collect it; the single-process baseline reports it once (23 failures, 5 errors).
- Baseline causes: WSL native-VR restriction; absent native viewer binary; absent archived photoproduct evidence/CPD context fixture; existing junction-balance numerical assertions; existing cis-anti-I preview stereochemistry error. No geometry constants, archived scientific evidence, or validation assertions were modified to hide these failures.
- Aggregate timing triage followed `.claude/skills/triage-slow-tests/SKILL.md`: **zero individual budget violators**. Costs are distributed over 11,123 tests, including mock-runner orchestration, repeated native-join construction, and native representation exports. The largest file totals were 59.5 seconds/247 tests for oxDNA relaxation, 39.3 seconds/17 tests for cluster-join API, and 31.1 seconds/45 tests for headless oxDNA. There is no evidence justifying reclassification of a particular test; markers, budgets and guards are unchanged. Aggregate timing debt remains open.

The broad-suite deferral was:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

No frontend behavior was changed in this foundation; no molecular geometry algorithm or locked constant was altered. No browser/headset validation was run. Benchmark models stayed in memory; retained task evidence consists of compact JSON and documentation, with no model/capture dumps or user-design modifications.

## Next implementation entry point

P2 starts with a versioned explicit root and authoritative-field contract, then a read-only verifier over the supported part commands. Do not use saved feature outputs to prove those same commands. Inventory default/random ID generation and reconciliation effects before granting any verified status. Gate green status on complete coverage and exact recipe/source revision; missing contracts produce unverified, not success. Keep verification off pointer, frame and scrub paths.
