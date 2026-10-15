# Standard part feature history implementation

Scope approved October 14, 2026: implement standard-part validation, editability and agent enforcement first. [Assembly work is deferred](assembly_deferred.md). Part-local proteins, nanoparticles, duplexes, attachments and imports remain in scope; they are not assemblies merely because they contain multiple components.

## Delivery sequence

| Phase | Scope | State and exit condition |
|---|---|---|
| P0 | Inventory, field ownership and performance evidence | Source audit complete; initial recording benchmark captured. Add workloads as the affected subsystem changes |
| P1 | Standard-part recording transactions, executable replay registry and evidenced cleanup | Foundation implemented below. Retain legacy callbacks and compatibility recovery; no claim of general isolated evaluation |
| P2 | Explicit recipe roots/versions, authoritative-field classification, read-only verification and incremental dependencies | Implementation exit checks complete: independent nonempty replay, content-pinned roots, typed dependencies, fingerprints, bounded capture/jobs and stale/cancel handling. Supported-family expansion continues in P3/P4; validation debt below remains explicit |
| P3 | Complete native DNA command families and generated construction | 83 versioned command kinds, with action/method restrictions, native generated-part composition and independent regeneration implemented. Final validation below; compound branch generation and bounded CPD-conversion replay remain open, so P3 is not universally complete |
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

## Current implementation entry point

P0–P2 implementation exit checks are recorded below. P3 is underway with native bundle construction and its parameter-edit path; expand the remaining native DNA command families next. Keep unsupported contracts unverified, retain the import/native distinction, and keep all proof work off automatic edit, frame and scrub paths. Broad-suite/environment debt is separate from these implementation gates.

## P2 first increment — explicit provenance and assessment

P1 was committed and pushed as `bd9248cc`. This increment starts P2; it does not complete the phase or enable strict agent enforcement.

- `part_history_contract.py` defines a versioned empty-root schema with initial name/lattice. `POST /api/design` records this root at explicit empty-document creation. Existing files retain `recipe_root=None`; load, snapshot restoration and arbitrary scripting do not retroactively gain provenance. Roots survive JSON and recovery-snapshot serialization.
- All Design fields have explicit ownership. Authoring fields are compared in full, including nested metadata, connections, attachment settings and constraints. Metadata is conservatively included as a whole because it also contains authoring settings; even an unlogged name change currently gives a mismatch. Presentation, physical results/job configurations, and document identity are explicitly outside this proof. This is authoring reproducibility, not a general integrity or scientific-validity verdict.
- `POST /api/design/features/verification` runs only on demand. It isolates the document under the existing lock, then assesses outside it, binds the result to source revision/document identity, and downgrades stale results. No result is persisted or cached. One concurrent assessment is admitted; excess requests receive 429 without taking a document copy. Diagnostic traversal is bounded to 2,000 parent/child rows. The copy is still proportional to document size and briefly holds the shared lock: this is not a hard latency/memory bound or a background job system. UI invocation remains unwired pending larger-document measurements and cancellable jobs.
- Only an explicitly declared empty recipe with matching authoring state can currently verify. Missing roots, unsupported versions, historical cursors, unknown schema fields, empty routing clusters and every nonempty command history fail closed. Stored output snapshots/diffs are never decompressed as proof. Executor availability does not imply an audited proof contract.
- Identity audit entry points: `_build_bundle` calls lattice-frame registration, which can create frame/cluster identities; `_build_nick` creates strand fragments and assigns colors based on prior strand ordering/count; crossover placement uses default-generated IDs; joint-place already records `joint_id` and local-frame axes. Contracts must cover reconciliation, pending ligation retry and incidental fields before any of these executors are promoted to proof mode. No UUID monkeypatch or output-based ID substitution was introduced.
- Repaired the evaluator benchmark boundary: both replay engines now use the current response serializer. The frozen reconstruction/child-diff algorithms are unchanged. Removed the three obsolete copied serializers from the reference module. Regression tests assert current response fields, input/environment preservation, and that a deliberately different reference reconstruction still produces a detected mismatch. This benchmarks reconstruction through a shared renderer; it is not an independent test of that renderer.

Remaining P2 work: deterministic command/identity contracts, explicit import roots with content provenance, typed dependency indexes and invalidation, isolated command execution, exact recipe fingerprints, complete nonempty replay comparisons, cancellable bounded jobs, and realistic interaction latency gates. Standard-part command-family expansion remains P3/P4; assembly work remains deferred.

### P2 increment validation

- Final focused checks: 126 passed (26 provenance/verification, 2 benchmark-adapter, 14 model, 17 evaluator, 35 snapshot and 32 transaction checks). Ruff and whitespace checks pass. `frontend/src/main.js` delta remains 0; no frontend behavior or scientific geometry algorithms changed.
- `just test-smart` selected **FAST (fast suite only)**: 11,098 passed, 21 skipped, 23 failed, 8 errors in 186.82 seconds. The failing node set matches the P1 baseline-reproduced failures. This broad run preceded the final empty-document route wiring and benchmark adapter changes; those received the focused checks above.
- Aggregate guard: 206 seconds / 90-second backstop, zero individual violators. Following `triage-slow-tests`, the largest costs remain oxDNA mock orchestration (60.0 seconds / 247 tests), native cluster-join API (41.7 / 17), headless oxDNA (32.0 / 45), and missing-binary VR exports (26.6 / 14). No new shared delay was identified, and test budgets/markers were not changed.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

- [Repaired evaluator benchmark](evaluation_benchmark_p2.json): all 14 equivalence comparisons passed; the latency gate still fails for `poses-1000` and `poses-1000-mid`. [Loading the pushed application baseline](evaluation_poses_baseline_p2.json) reproduces both regressions against the older frozen evaluator (about 3.60 ms vs 0.64–0.68 ms). These are pre-existing evaluator performance debt, not a green benchmark; no threshold was changed.
- [On-demand assessment costs](assessment_cost_p2.json), 17 GC-enabled samples per synthetic case: 1 helix / 0 rows median copy 0.127 ms + assessment 0.039 ms; 24 helices / 100 rows 2.60 + 0.24 ms; 256 helices / 2,000 rows 43.21 + 4.67 ms. All helices have 84 bp; large protein/physical assets and network/render time are excluded. Copy time is the state-lock portion. This is descriptive evidence, not an interaction gate, and is a reason to keep automatic UI invocation disabled until bounded capture/jobs are implemented.

## P0–P2 exit audit (October 14 continuation)

The first P2 increment above was not phase completion. The following closes its implementation gaps before P3 command-family expansion:

| Exit requirement | Implemented evidence |
|---|---|
| P0 inventory and ownership | Initial route/field inventory retained; exhaustive Design field-role regression prevents silent unclassified additions |
| P1 recording transactions and cleanup | Snapshot/minor rollback tests retained, bounded undo/redo restoration retained; executable compatibility registry and removed no-op bookkeeping remain in place |
| P2 explicit roots | Versioned empty roots plus explicit content-pinned import roots; imported state returns `reproduced_import`, never native editability |
| P2 independent nonempty replay | Versioned joint-place/update/delete contracts use native builders, reconciliation and pending-ligation handling. Tests rebuild an imported-root recipe without reading snapshots, reject modified source bytes, and detect unlogged edits |
| P2 complete-state comparison | All authoring fields and nested values compared; recipe and authoring SHA-256 fingerprints are separate; unsupported versions/kinds fail closed |
| P2 dependencies | Typed resource identities, append-incremental writer/reader graph, transitive impact queries, prefix invalidation, conservative unknown-command barriers; graph belongs to its captured recipe/revision |
| P2 bounded jobs | One admitted worker, no unbounded queue, eight retained results, cancellation/deadline checkpoints, document-scoped lookup, stale-result invalidation both during execution and after completion |
| P2 capture/interaction isolation | No automatic edit/frame/scrub checks. Capture excludes recovery blobs and presentation/physics data, enforces node/byte/time admission limits, and rejects oversized inputs without claiming validity |
| P2 inherited performance debt | Removed missing-attribute lookups in Join/Pattern scans and an unnecessary no-op cluster copy. All 14 unchanged evaluator timing/equivalence gates pass in `evaluation_benchmark_p2_completion.json` |

Limits are explicit rather than hidden behind a green verdict: cancellation/deadlines are cooperative between commands; no hard preemption of arbitrary Python is promised. Capture admits at most 30,000 visited values / 2 MB conservative string bytes / 25 ms cooperative traversal; an individual copy boundary can slightly exceed the time limit. Oversized documents remain unverified, with HTTP 413. The job deadline is five seconds and results are not persisted. Large-scale capture expansion requires measured improvements, not raised interaction thresholds. Root-content storage/importer UX and asset-family coverage remain P4; the import proof contract itself is implemented here.

`capture_budget_p2.json` measures admitted captures at about 0.75 ms (1 helix), 4.32 ms (24 helices/100 rows), and safe rejection at 25.64 ms (256 helices/2,000 rows). This changes the earlier 43 ms unbounded-copy path. These are API capture measurements, not a browser latency claim.


P2 final validation before P3: focused proof engine (11), job lifecycle (7), compatibility verifier (26), recording transactions (32), evaluator (17), Join history, circular pattern (6), and cluster creation (2) passed. `just test-smart` selected FAST: 11,120 passed, 21 skipped, 23 failed, 8 errors / 189.64 seconds pytest, 207 seconds outer guard. The failure set matches the previously baseline-reproduced environment/scientific-data failures. Zero individual timing violators; top file costs remain oxDNA mock orchestration, native cluster joins and headless oxDNA. No budgets or markers changed. This is implementation completion with retained broad-suite/environment debt, not a claim that every repository test is green.

## P3 first native family — bundle construction

- New bundle creation records an explicit empty root and a UUID namespace in its parameters. The namespace is generated before construction; cluster/frame IDs derive from that namespace and logical membership. Native builders receive an explicit identity factory. No process-global UUID patch, snapshot-derived ID map, or saved-output substitution is used.
- Existing geometry/topology algorithms, helix/strand identities and molecular constants are unchanged. Builders without a seed retain their legacy ID behavior. Proof mode admits only versioned native commands; legacy records remain unverified.
- The existing bundle parameter edit path preserves the seed and contract version. Length edits retain frame/cluster identity and pass full authoring-state replay comparison. Existing recovery paths remain available.
- API capabilities now separate available recovery executors from audited proof commands (`bundle-create`, `joint-place`, `joint-update`, `joint-delete`). A capability list is not itself a certificate. Proof results explicitly state `authoring_reproducibility` and do not claim integrity/scientific validation.
- Bundle proof work is bounded to 512 cells and 50,000 cell-base-pairs before invoking the builder. Exceeding the budget produces an unverified `command_limit`, not an invalid-geometry verdict. Live construction limits are unchanged.
- Tests cover connected/disjoint cells, both clustering policies, payload-free native replay, save/reload, parameter editing, unlogged geometry changes, independent namespaces, a bundle→joint dependency chain, command budgets and independent Python hash seeds.

P3 is not complete: downstream producer/consumer edit regeneration is still open; this increment proves standalone bundle parameter edits and bundle→joint replay/dependency diagnostics, not arbitrary downstream edit repair. Remaining helix/strand/domain/routing/sequence/loop-skip/pose/pattern/sweep/join and generated-construction families must each receive audited contracts, deterministic identities where needed, and editor/regression coverage. Unsupported families remain unverified. No frontend files or assembly adapters were changed.


### P3 first-family validation and retained limits

Final `just test-smart`: **FAST (fast suite only)**, **11,132 passed, 21 skipped, 23 failed, 8 errors**, 190.87 seconds pytest / 205 seconds outer guard. Failures remain the previously reproduced baseline set; zero individual timing violators. Aggregate costs remain distributed (oxDNA mock orchestration 62.0 seconds / 247 tests, cluster-join API 39.9 / 17, headless oxDNA 31.9 / 45). Guards and markers remain unchanged. Final focused checks also cover the subsequent frame-ID optimization.

The initial seeded-ID microbenchmark is retained as `native_bundle_benchmark_p3_initial.json`: the 24-disjoint-region case exceeded the unchanged gate by about 0.24 ms / 8.4%. Fresh bundles have exactly one frame per placement cluster, so seeded frames now use `frame:<stable cluster ID>` instead of a second independent hash. `native_bundle_benchmark_p3.json` passes all three cases: approximately 0.152→0.166 ms (one cell), 1.964→1.970 ms (24 connected), 2.904→2.966 ms (24 disconnected). Thirty-one alternating batches of ten pure-builder iterations check native geometry/topology/membership parity; HTTP and rendering are excluded. No global UUID behavior changed.

Changed-file Ruff and whitespace checks pass. `just lint` has five existing unused-import findings; all five files are byte-identical to pushed HEAD. `frontend/src/main.js` delta is 0. No frontend, browser or physical VR validation is claimed. Task-specific fixtures remain in memory/session-scoped tests; retained artifacts are small JSON measurements and documentation, with no user design files created or migrated.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

Final focused rerun after the frame-ID optimization: **83 passed** (11 native bundle, 28 lattice-frame, 11 proof-engine, 7 job-lifecycle, 26 verification checks). Repository memory lint retains six errors in unchanged files and 60 warnings; the touched feature-history memory head was already over the 200-line warning target. No memory lint threshold was changed.


## P3 continuation — native contracts and producer regeneration

The P2 foundation and first P3 increment were committed and pushed as `6336d1fe` before this continuation.

`part_recipe_edit.py` now rebuilds fully covered recipes from their explicit root, preserving feature/child identities and regenerating all recovery snapshots and routing diffs. It never decodes saved outputs. Producer edits rebuild consumers; command deletion reports dependent feature IDs before an explicit cascade. Child parameter edits use the existing edit endpoint with `sub_index`. Failed reference resolution, a nonreproducible source, admission limits, or a concurrent revision/document replacement prevent candidate publication. Undo/redo remains one operation. Presentation, physical-result and document-identity fields are retained; this does not certify their validity after topology changes.

Compatibility is deliberate: documents without roots and histories containing unsupported rows continue using established recovery editors. They remain unverified. This avoids prematurely applying P6 strict enforcement and preserves the specialized sweep/pattern editors for mixed histories. The original unsupported-history regeneration limitations have **not** been solved by this fallback.

| Contract group | Covered commands |
|---|---|
| Construction | `bundle-create`, `sweep`, `circular-pattern`, `linear-pattern` |
| Joints | `joint-place`, `joint-update`, `joint-delete` |
| Helices | `helix-add`, `helix-update`, `helix-delete`, `helix-reorder` |
| Strands/domains | `strand-add`, `strand-update`, `strand-delete`, `strand-delete-batch`, `domain-add`, `domain-delete`, `domain-shift`, `strand-end-resize`, `strands-color-bulk`, `strands-reference` |
| Routing | `nick`, `nick-batch`, `crossover-place`, `crossover-place-batch` |
| Loop/skip | `loop-skip-insert`, `loop-skip-twist`, `loop-skip-bend` |
| Sequence | `assign-scaffold-sequence`, `assign-staple-sequences` |

Pattern namespaces and crossover IDs are selected before construction and recorded as inputs. Sweep edits retain their namespace and persist schema-normalized detachment parameters. Sweep request parsing accepts only the known version receipt while still forbidding other extra inputs; the receipt is not a new user-facing request option. No topology or molecular geometry algorithm was changed.

Routing uses conservative whole-part dependencies because reconciliation can affect overhangs, domains and pending ligations. Consequently a deletion preview can include independent commands; explicit cascade remains required. Parameter edits replay the whole admitted recipe, including independent commands. Finer dependencies and reusable prefix execution remain necessary before claiming minimal affected-work regeneration.

### Remaining P3 exit work — not deferred to assemblies

- Complete extrusion/continuation/frame/circle/overhang construction identity inputs, including helpers whose IDs currently depend on document identity or random suffixes.
- Complete remaining helix/strand/domain/ligation/crossover operations, strand/overhang sequence edits, and loop/skip application variants.
- Version pose/deformation/grouping/overhang-rotation inputs and preserve their specialized edit semantics during downstream regeneration.
- Audit auto-scaffold/autostaple/break/merge/routing, joins, photoproduct and other P3 rows in `coverage.md`; do not silently mark dispatcher availability as reproducibility.
- Replace generated nick/result shortcuts and partial construction comparisons with native execution and complete authoring comparisons. Existing generator compatibility remains necessary until this passes.
- Complete family-specific editor/preview coverage and independent-deletion behavior. The new routing-child parameter API has no new frontend control in this increment.
- Add broader hash-seed, large-document and interactive measurements for these remaining families. Existing ordinary recording gates are not evidence for every new regeneration workload.

P3 therefore remains **in progress**, not complete. Assembly work remains deferred; strict agent enforcement remains P6.

### Validation for this continuation

Focused regressions cover producer→joint regeneration, poisoned recovery bytes, cascade and child deletion, invalid downstream references, unlogged changes, concurrent publication, undo/redo, native routing, sequences, patterns, sweeps, stable crossover identities and parameter edits. Legacy history, joint, pattern, sweep, detach, headless and VR API suites remain in the regression scope. No browser/headset validation or molecular simulations were performed; `frontend/src/main.js` LOC delta is **0**.

`recording_benchmark_p3.json` passes all six unchanged timing gates against `dfa63eeb` (31 alternating batches × 10 iterations). Candidate medians are about 0.257/0.298 ms for 1-helix snapshot/minor recording, 1.521/1.723 ms for 24 helices, and 2.024/2.301 ms for 24 helices/100 rows. The comparison explicitly allows the intentional minor-command version receipt while comparing authoring and recovery output. No timing threshold changed; HTTP, rendering, cold imports and recipe regeneration are outside this benchmark.


Final broad validation selected **FAST (fast suite only)**: **11,163 passed, 21 skipped, 23 failed, 8 errors**, 189.10 seconds pytest / 205 seconds outer guard. All failing node IDs match the retained baseline (`validation_p3_continuation.json`). The initial run exposed 50 additional compatibility failures; the corrections above removed them. The aggregate timing warning remains, with **zero individual violators**; no test markers, guard thresholds or scientific assertions were weakened.

After that broad run, focused validation found and repaired a first-helix provenance gap: response-time default-cluster creation was outside the logged command. Helix creation now invokes the shared pure structural builder, which includes deterministic default-cluster creation before recording. The new empty-root regression failed before this correction and passes afterward. Sweep parameter-normalization errors now return HTTP 400 without publication. The final targeted group passed **75 tests** (26 native routing/construction, six recipe-edit, 11 proof-engine, 32 recording-transaction). Previously failing legacy joint/history/pattern/sweep/detach suites and the corrected headless/VR API suites also passed focused reruns. This last small correction was covered by focused tests after the broad run; the broad count does not include its new regression.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

Native recipe edits are bounded by the same capture admission and a five-second cooperative regeneration deadline. Large recipes can therefore be refused without mutation; eliminating that editing limitation requires incremental/prefix evaluation and larger-document evidence. This is an open P3 usability limit, not a claim of universal edit latency or complete coverage.

Final additional checks: **26 cadnano-editor API tests passed** after the first-helix correction. All **14 evaluator equivalence/latency gates passed** (`evaluation_benchmark_p3.json`); combined with six recording gates, all 20 measured gates passed unchanged. Changed-file Ruff and whitespace checks pass. This remains backend validation; no browser/headset or end-to-end latency claim.


## P3 expanded native coverage — October 15 continuation

This section supersedes the 30-command continuation above. The registry now exposes **83 command kinds** and **16 explicit overhang-bulk actions**. These are available contracts, not a coverage percentage or a certificate for a document. Method restrictions, source roots, full-history coverage, complete authoring comparison and admission limits still apply.

- Shared pure builders now cover frame/continuation/circle extrusion, cell/helix extent and scaffold painting, all active Fine Routing CRUD/ligation/crossover variants, strand/overhang sequences, loop/skip planning/application/clearing, auto routing/autostapling, joins, cluster paste, poses, nucleotide transforms, flexible marks, overhang subdomains/bindings/linkers, and selected refinement marks. Original routers are thin adapters to the same algorithms; the extracted duplicate bodies were removed. `linker-patch` and loop-clear actions now record history instead of changing authoring state invisibly.
- Identity namespaces are selected before construction. Routing uses a nested, thread-local context only around opted-in constructors; legacy callers retain their original random identities. Continuations record explicit source-helix references. Cross-process hash-seed and thread/nesting tests cover determinism and isolation. Molecular geometry algorithms and locked constants were not changed.
- Pure refinement selection no longer reads or changes the live document. Framed cluster copy now carries/remaps the referenced frames and placements. Compatibility imports still used by other modules remain; the unused `lattice.Crossover` import was removed after checking importers.
- Deletion replays surviving commands to identify actual failures instead of deleting every possible dependent from the coarse graph. Independent later work survives. The source verification retains one independently rebuilt prefix per edit; suffix regeneration never reads poisoned snapshots. There is no cross-request cache or per-frame proof work.
- Generated ordinary extrusion, sweep, auto-scaffold, autostaple, nick, overhang and sequencing steps execute native commands. Scoped input references plus an identity namespace isolate generated DNA from existing independent work; no arbitrary Design/Python command or stored geometry is supplied to the executor. All authoritative fields are compared. Sequence recording no longer decodes generated result snapshots. Old generated-v1 compatibility remains active.
- Native extrusion's inherited cluster membership is now explicitly released before independently transporting a generated carrier. Recovery respects payload boundaries: old membership/name/appearance setters cannot overwrite membership added by a later extrusion. Regression checks cover both recovery modes and backward/forward scrubbing.
- `GET /api/design/features/capabilities` now describes the history-edit API, routing-child target, existing specialized UI fields, API-only editors, supported bulk actions and method restrictions. This is static information, not a document scan. No frontend code changed; `main.js` LOC delta **0**.

### Explicit remaining limitations and phase boundaries

1. **P3 compound branch generation remains open.** Existing `generate-design` branch/section/budget variants still lack complete native feature inputs. The compiler leaves these unverified and returns `history_unverified_steps` with reasons. They have not been relabeled as assemblies or as valid native recipes. Generated NP/duplex/attachment operations also remain unverified, but those are the separately planned **P4 part-local asset** work.
2. **CPD conversion is not admitted to replay.** A small conversion-plus-replay regression took 70.70 seconds and overran the synchronous verification deadline during native placement. Ordinary verification rejects `photoproduct-create` with method `convert` before calling that solver. Native preflight authoring and deletion have contracts; conversion remains available through its existing endpoint with explicit identity inputs. A bounded conversion contract is still required; neither the ordinary worker deadline nor a saved placement is treated as proof.
3. Historical parameter editing requires the API for families without existing specialized history controls. Existing desktop/VR editors retain their current field sets and later-snapshot restrictions. Historical preview and mixed/rootless histories retain recovery editors. These are explicit editor limitations permitted by the per-family exit criterion; P5 owns unified UI diagnostics/repair. No browser or headset behavior is claimed.
4. Capture remains bounded (30,000 values / 2 MB / 25 ms), verification has the existing cooperative deadlines, and edits use a five-second regeneration deadline. Large edits may be refused atomically. Prefix reuse is measured; fine-grained independent suffix reuse and interactive end-to-end latency are not claimed. No budgets or guard thresholds were raised.
5. `element-paste` in the original inventory is protein/nanoparticle paste (`routes_nanoparticles.paste_rigid_elements`), so it belongs to P4. The old `auto-scaffold` and near/far-end literals have no active native recording route; persisted compatibility types are retained. Unknown overhang-bulk actions (including connection-version asset application) stay unverified.

P3 has therefore advanced substantially but is **not marked fully complete** while items 1–2 remain. P4/P5/P6 and assembly implementation have not been silently folded into this continuation. Strict agent enforcement is still P6.

### Current validation evidence

The compact completion-attempt report and benchmark JSON files record the final checks for this continuation. Earlier reports above remain historical evidence. Focused tests include native empty-root replay, poisoned recovery payloads, stable identities, producer edits, cascades/independent survival, generated scoped construction and non-strand tamper rejection, annotation/subdomain/linker/binding lifecycle, frame/cell/copy compatibility, and recovery membership boundaries. No molecular simulations were run. The absent Archive mount prevents bulk browser artifacts; no browser run or user-workspace design mutation was attempted.


Final broad run: **FAST**, **11,227 passed, 21 skipped, 24 failed, 8 errors** in 181.00 s pytest / 197 s guard. Twenty-three failed nodes and all eight errors match the retained baseline. The additional Join proof test hit the intended synchronous 0.5 s deadline under parallel load; it now uses the existing bounded worker and passed focused verification without changing production deadlines. Zero individual timing violators; the aggregate timing warning remains. Full-suite debt remains:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

All **22 measured latency/equivalence gates pass**: six recording, fourteen recovery/geometry, and two prefix-edit cases. The larger prefix case measured 14.8 ms versus 15.3 ms full replay; this is a selected in-memory workload. Final generated compatibility (2), native generated proof/tamper/scope (4), native annotations/admission (10), overhang/binding/linker/recovery (8), routing (34), refinement (4), hash-seed/thread isolation (2), and Join-worker (1) focused checks pass. Changed-file Ruff and whitespace checks pass. Repository lint retains five unused imports in unchanged files; memory lint retains six errors in unchanged heads. Evidence: [validation_p3_expansion.json](validation_p3_expansion.json), [recording](recording_benchmark_p3_completion.json), [evaluation](evaluation_benchmark_p3_completion.json), [prefix edits](recipe_edit_benchmark_p3.json).

## Architecture review and hardening checkpoint — October 15

The persistent completion goal remains active. See [architecture review](architecture_review.md)
for researched CAD precedents and [remaining native contracts](remaining_native_contracts.md)
for the branch/connectivity decomposition. P3 is still incomplete; no P4–P6 or
assembly completion is claimed.

Strict replay now rejects missing and partially missing batch selections and
returns typed references with parameter paths. Conservative graph reachability
is labelled possible impact, not proven blockage. Deletion previews retain the
structured issue. Generated scopes reject ambiguous retained/generated identity
aliases before running a builder. Ordinary permissive live batch tools remain
unchanged; they cannot gain a native certificate by silently skipping inputs.

Background verification now runs in one spawned child, supervised without a
work queue. Input/results have explicit byte limits and shared-memory buffers;
normal completion, cancellation, stale source and timeout reap the process and
unlink buffers before freeing admission. The five-second budget includes cold
startup. Sync verification and history edits still have cooperative limits;
CPD conversion remains unadmitted. OS-uninterruptible processes can delay reaping;
admission stays held rather than launching additional work.

Focused checks at this checkpoint: reference failures 22, proof 14, recipe edits
8, verification 26, routing 34, overhang 8, generated proof 4, generated alias
checks 3, worker isolation 10 and lifecycle 12 pass. Both unchanged prefix
benchmark gates pass (`recipe_edit_benchmark_hardening.json`). Repository lint
still has the same five unrelated unused imports.

**Open validation finding before the next checkpoint:** the real Join-worker
test now reports a `flexible_connections` mismatch across processes. Its prior
thread-based pass did not establish cross-process determinism. Pure derivation
probes confirm that unordered set traversal reverses A/B anchors and bead order
under different hash seeds. Checkpoint this state before choosing a canonical
traversal. Preserve connectivity/constants/formulas; do not weaken comparison or
remove the field to hide the mismatch. Broad validation follows the correction.

### Join cold-replay correction

The mismatch above is resolved by retaining the actual preview's discrete anchor
orientation and component order as reference-only inputs. Native replay still
derives connectivity, contour, identity and bead membership itself, then resolves
and applies the chosen ordering. No stored coordinate array, derived connection
object or recovery payload is accepted as proof. Missing, ambiguous, repeated or
incomplete choices fail explicitly. Indexed matching scales with native beads and
choice count. Existing molecular placement/display formulas remain unchanged.

Preview inputs are bounded to 16 receipts of 128 KB for five minutes, scoped to
document, design and revision. A content token cannot silently replace different
choices. Failed atomic commits can retry their receipt. Both preview and apply
choose the same explicit bridge identity; precursor Joins now honor that identity
as routed Joins already did. Older receipts without choices remain unverified;
saved documents are not migrated or silently assigned a new displayed choice.

Focused validation: 19 reference-choice tests, six preview-cache tests, 17 Join
API compatibility tests, 14 precursor/constraint tests, and two real spawned-worker
proof-and-edit cases pass. The latter cover routed and precursor Joins from an
empty native root across processes. The two original synchronous geometry
algorithms remain unchanged. This checkpoint precedes generated-scope schema
refactoring; required broad validation is still pending for the combined changes.

At `afe9cb5d`, guarded **FAST** completed with **11,301 passed, 21 skipped,
23 failed and eight errors** in 181.39 seconds. All failed/error nodes match the
retained baseline; both new Join cold-replay cases pass. There are no individual
five-second timing violators; aggregate runtime is comparable to the prior
181.00-second run. No marker, threshold or assertion was weakened.

`just test-smart` initially selected **FULL** because a preexisting user-opened
test session was active. It was interrupted after 48.13 seconds (1,031 passes,
four missing-fixture collection errors) because the required Archive mount is
unavailable. FULL did not complete. The explicit `just test-fast` run above then
finished; its preexisting tests also produced bulk temporary fixture data. Both
runs' task-owned pytest directories were removed and absence verified. Further
broad artifact-producing runs require Archive-backed scratch; focused in-memory
checks can continue. No user designs, production jobs or historical artifacts
were removed. Details: [validation_hardening.json](validation_hardening.json).

The next CPD decision is documented in [the conversion contract audit](cpd_conversion_contract.md).
Conversion and `photoproduct-relax` can consume a physical atomistic reference;
native proof must explicitly declare its geometry source, template and engine,
and use a separate bounded long job. The prior 70.70-second measurement included
conversion plus replay, not one solve. Extending the ordinary deadline or
storing solved coordinates cannot resolve this missing input contract.
