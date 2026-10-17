# Standard part feature history implementation

Scope approved October 14, 2026: implement standard-part validation, editability and agent enforcement first. [Assembly work is deferred](assembly_deferred.md). Part-local proteins, nanoparticles, duplexes, attachments and imports remain in scope; they are not assemblies merely because they contain multiple components.

October 15 resumption: the user explicitly deferred VR/headset validation to a
later machine-specific session because this machine is not VR capable. Retain
that validation debt without making it a prerequisite for continued standard-part
implementation here. Desktop validation and automated software checks remain in
scope. The pushed pause checkpoint is `d5a53734`; its unfinished tests and broad
regression debt are recorded in [the checkpoint evidence](validation_pause_checkpoint.json).

## Delivery sequence

Progress accounting uses the fixed [FH milestone ledger](remaining_standard_part_checkpoints.md#progress-baseline-and-mandatory-update-counts--october-16-2026),
with completed/estimated-total counts and visible scope changes after every major
update. Historical sections below are evidence, not additional completion credit.

**Active delivery order:** core geometry and Fine Routing precede asset expansion.
Use [G1–G6](remaining_standard_part_checkpoints.md) for current sequencing; the
original P-phase table below retains architectural scope, not queue priority.

The current grouping checkpoint preserves empty placement owners through a
specific `cluster_create` v2 contract while retaining exact saved v1 behavior.
Explicit verification now reports reproducibility and bounded structural
reference validity separately, and history-edit/repair publication refuses
invalid final closure. Numerical pins use a disclosed exact-manifest schema
compatibility transition. Explicit live-part grouping repair is implemented.
FH-19 now connects bounded saved-file definition admission and private recovered-
copy evaluation to an isolated HTTP worker and File → Recover recipe from file….
The user reviews explicit grouping repairs and excluded data, evaluates, then
downloads exact server-encoded text as a separate valid copy. Original bytes and
the open document are preserved; ordinary typed loading is unchanged. The shared
worker slot remains held through child/buffer cleanup and final response send.
See the [contract](saved_recipe_recovery_contract.md) and
[delivery evidence](validation_saved_recipe_delivery.json).
Progress is **18/38 complete**, with **20 remaining (11 core, 9 parked)**; FH-19
closed its bounded implementation exit after two checkpoints, with no total
change. Its desktop/latency qualification remains in FH-27/MV-49. The latest
checks passed 305 distinct focused backend cases and the full frontend suite
(8,496 passed/one skip); no app exercise or broad backend pass is claimed.
Assemblies, VR validation and further nanoparticle feature expansion remain
deferred. Neither this checkpoint nor the private editor tests establish desktop
interaction or latency qualification.

The October 16 continuation connects complete private bend/twist controls to the
existing history entry point behind a default-false qualification gate. Preview
uses fixed feature-stage context; its dedicated camera layer excludes later
canonical geometry, including sibling arcs/labels. Apply errors preserve inputs;
lost replies expose status/refresh actions. Native group retargeting records the
same membership for preview, Apply and cold replay without reinterpreting saved
operations. See [editor evidence](validation_deformation_history_editor.json).
Neither HTTP nor ordinary editor rollout is enabled, and ISSUE-100 remains open.
Desktop/timing checks are still pending, with Archive unavailable. Assemblies and
machine-specific VR remain deferred; `main.js` has zero added lines.

The preceding editor checkpoint's save/reload tests reproduced ISSUE-106: exhausting a default group's
membership can remove a retained lattice-frame placement owner. Equivalent
reproduction is not structural validity. The version-aware prevention and live
repair work above address that defect; broader group deletion/membership/pose
closure (FH-18) still prevents calling G1 complete. Old v1 output is unchanged.

| Phase | Scope | State and exit condition |
|---|---|---|
| P0 | Inventory, field ownership and performance evidence | Source audit complete; initial recording benchmark captured. Add workloads as the affected subsystem changes |
| P1 | Standard-part recording transactions, executable replay registry and evidenced cleanup | Foundation implemented below. Retain legacy callbacks and compatibility recovery; no claim of general isolated evaluation |
| P2 | Explicit recipe roots/versions, authoritative-field classification, read-only verification and incremental dependencies | Implementation exit checks complete: independent nonempty replay, content-pinned roots, typed dependencies, fingerprints, bounded capture/jobs and stale/cancel handling. Supported-family expansion continues in P3/P4; validation debt below remains explicit |
| P3 | Native DNA command families and generated construction | DNA implementation exit checks recorded below, including joined/connectivity input compilation and bounded native-source CPD conversion/relaxation. Registered kinds retain method/action restrictions; their count is not universal operation coverage. Generated asset/attachment histories remain in P4 |
| P4 | Standard-part assets and attachments | In progress. Source-free gold/thiol, pinned small protein/catalog/aptamer inputs, supported protein conjugation and duplex lifecycle/relaxation implemented. Pending NP and ordinary overhang connection contracts pass independent replay. Bounded applied NP lifecycle/rename and finite ordinary linker Apply/reapply are implemented. Finite ordinary Apply/reapply has a private default-disabled route with 244 focused passes. A shared reference-walker lifetime refactor passes 247 cases and removes the observed median regression in the compact benchmark; HTTP tails and app qualification still keep rollout closed. Applied NP route migration remains open. Owned oxDNA preparation is also wired behind a default-disabled host gate; 182 focused cases pass, with live capture/HTTP responsiveness still under qualification. Full import/attachment coverage and complete physical-input receipts remain open |
| P5 | Standard-part repair, drafts, desktop and part-mode VR | Saved draft evaluation/apply, reference selection, source staging/restoration and persistence pass. Desktop UI-1 and narrow invalid-gold repair pass. Private gold/QD/free-protein and complete DNA comparisons pass automated checks; broader invalid-family selectors and desktop app review remain open. VR/headset validation is explicitly deferred to a later capable-machine session |
| P6 | Strict standard-part agent transactions and legacy retirement | Private policy/permits, closed strict HTTP dispatch, immutable internal ownership and outside-lock evaluation/publication pass. Atomic typed records and pending-safe autosave pass. Cold-qualified recovery and durable initial creation pass focused lifecycle checks. Private byte transport moves source decode/projection into the admitted worker; recovery now also performs full canonical preparation there, with exact one-shot host handoff (384 focused cases). Public immutable creation/batch stay disabled pending responsiveness and retained-memory qualification. Catalog expansion, explicit imports and later replay reuse remain open |

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

Resumed October 15 from `d5a53734`, with VR/headset validation deferred by the
user. Applied NP rename (`8f1ca5a9`) passes all 31 new and 231 related focused
checks while preserving normal reconciliation. The previously failing API/coating
order now passes 258 checks after correcting the cold test's process-owned
numerical pin setup; production runtime checks remain unchanged. Four existing
heavy replay/packing entries and the corrected five-worker coating lifecycle
are classified through the slow-test registry without changing budgets. These
focused checks do not clear the outstanding broad regression/app debt; see
[resumption evidence](validation_resume_regressions.json). Subsequent checkpoints
implemented shared bounded capture accounting (`3e12323f`, 114 regressions),
private full-archive oxDNA input capture (`9fbb392a`, 176 cases), and finite native
ordinary linker Apply/reapply with dependency/edit/cold-proof checks (`921e4acc`,
`b46104b2`, 157 cases). Their ordinary route integration and latency qualification
remain separate. The duplicate private repair-definition admission walk was
removed in `b91f7390`; 95 repair/planning/job cases preserve the source and final
admission checks.

P0–P3 implementation exit checks are recorded below; chronological entries retain
their original phase status. P4–P6 proceed in independently reversible slices,
following [the remaining standard-part checkpoints](remaining_standard_part_checkpoints.md).
Keep unsupported contracts unverified, retain the import/native distinction, and
keep full proof off automatic edit, frame and scrub paths.

The next P6 memory diagnostic retained two independent 15,899,997-byte cold-proved
recovery results beside 31,995,904 bytes of background source/undo across three
cycles. All six recoveries and cleanup passed. Sampled RSS increments stayed
within the provisional 256 MiB allowance, but 116.4 ms sampling gaps prevent a
hard memory-bound claim. Parent preparation took 167–191 ms and concurrent scalar
reads reached 157.64 ms despite sub-millisecond state-lock holds. Exact phase
attribution is the next diagnostic; do not advance to thirty-cycle qualification
or enable public gates on these results. The read seam was memory-only, with
disk access and durable publication tripwired. See [reviewed evidence](validation_immutable_recovery_memory.json).

The bounded instrumented repeat locates this delay in full-document JSON decode,
canonical encoding, exact roundtrip and recipe hashing; ordinary authoring
admission has a 0.122 ms median and final proof capture 1.324 ms. Six preparations
took 164–187 ms, with 145–158 ms concurrent reads wholly inside preparation and
state-lock holds below 0.206 ms. All six cold proofs and cleanup passed again.
Keep the existing checks and move preparation plus proof into one admitted
spawned recovery worker, following [the reviewed boundary and transition plan](immutable_recovery_worker_plan.md).
No recovery production boundary changed in this diagnostic checkpoint; public
gates remain closed. [Phase evidence](validation_immutable_recovery_phases.json)
retains nested timing, correlation and sampled-memory limitations.

Recent completed checkpoints include pending NP motion (`a24b60b7`, 204 focused
cases including 35 new), cold-qualified strict recovery (`d52a30a7`, 318 distinct
cases), durable initial strict creation (`05707b38`, 283 distinct cases), and
strict byte worker transport (`d412e402`, 64 cases). The host wiring continuation
(`78386957`, 147 distinct cases) keeps the exact sealed source reservation in the
request process and moves source decode/projection into the admitted child.
Existing mutable capture remains unchanged; the obsolete parent-only immutable
capture helper was removed. Repeated HTTP latency, retained-memory and concurrent
light-request measurements must pass before public storage/batch enablement.

Complete native DNA comparison has a bounded lossless version-2 DTO and private
renderer (`eefe292f`). Focused frontend 195, full frontend 8,291 (one skipped),
and three actual Python/Node/HTTP cases pass. Exact response serialization
reduced the largest observed concurrent scalar request from 165.58 to 16.46 ms
across nine actual HTTP comparisons, with no output or byte-limit change.
The first CPU scene run is retained as an explicit-GC memory diagnostic;
natural-GC timing and browser/GPU/native VR qualification remain separate.
The public version-two comparison gate remains false.

Nanoparticle lifecycle ownership corrections (`91756139`) passed 181 distinct
cases; new applied-native and ordinary pending-overhang contracts are now being
implemented from reproduced failures. The strict cold-DNA serializer correction
(`72815c1d`) passed 115 distinct cases, including cancellation during owned
decode. Its corrected three-repeat byte benchmark completed 12 publications and
four independent cold proofs. All 12 scoped RSS observations stayed within the
predeclared +256 MiB target, but these small-source cases do not qualify full
retention or repeated latency. Public storage/batch gates remain false.

Broad-suite/environment debt is separate: the resumed non-VR FAST selection at
`b46104b2` ran 14,076 passing tests with nine failures and eight errors, all matching
retained baseline evidence. The UUID-parametrization collection mismatch was
already corrected in `cc5e96e9`. Missing Archive/CPD fixtures and existing
junction-balance/preview failures remain; this is not a broad-suite pass. One
four-worker durable-creation integration test is now individually classified
slow/headless, with its lightweight fault siblings kept fast. The timing recheck
passed 14,075 cases with the same baseline failures/errors; a 5.04-second native
connectivity pipeline identified its two-case module as genuine integration work
(two cold workers per case). Both still pass focused checks (9.97 seconds), and
slow collection retains them. The final non-VR FAST run passes 14,101 cases with the same nine baseline failures
and eight errors, zero individual timing violators, and 229.92 seconds pytest /
240 seconds guard time. Aggregate suite timing remains over its backstop; the
existing distributed costs do not justify further arbitrary reclassification. See
[backend evidence](validation_backend_resume.json) for timing triage and the
verbatim FULL deferral. Archive, live app and browser validation remain unavailable;
VR validation is explicitly deferred by the user.

Private oxDNA routing now captures one owned reference-filtered archive for all
preparation consumers and rechecks its source immediately before lineage. The
new 28 route cases include actual writer-thread alias mutation, reference
filtering, stale/session races, cancellation and compatible scientific guards;
182 focused/regression cases pass. The default-disabled route benchmark passed
310 correctness/isolation checks and 123 equal successful response pairs, but a
256-row history captured during major-GC overlap refused after a 68.69 ms lock
hold; a concurrent read reached 71.48 ms. Keep the rollout gate false. See
[route validation](validation_oxdna_preparation_route.json) and
[HTTP measurements](validation_oxdna_preparation_performance.json).

The existing whole headless regression file and FAST sweep produced bulk test
fixtures outside Archive, contrary to the storage constraint. All 14,689 regular
files in those two completed pytest roots were inventoried, checked for active
references and removed (520,930,134 logical bytes); no user designs/jobs were
touched. Further bulk/native integration and broad sweeps here require mounted
Archive scratch or a separately reviewed bounded selection. New route tests and
diagnostic benchmarks use in-memory substitutes with no package files.

The natural-GC shared-capture A/B diagnostic compared 186 alternating pairs on
six in-memory sources. All 371 successful captures matched completely and all
372 source-immutability checks passed. No workload crossed both predeclared
median regression thresholds; median differences ranged from -0.036 to +0.117 ms.
One historical capture refused and two current successful captures exceeded
25 ms with major-GC overlap; cooperative budgets are not hard wall-time bounds.
No tail, HTTP, memory or public responsiveness qualification is claimed. See
[reviewed evidence](validation_capture_graph_performance.json).

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

## P3 typed composition and native branch construction — October 15

New scope receipts use version 2. A declarative model-field schema distinguishes
typed identities/references from names, sequences and arbitrary metadata. It
checks nested ownership and input closure, handles canonical CPD base keys and
functional linker IDs, preserves independent objects, and composes the native
selected subsequence order. Old receipts execute only when the corrected mapping
and order agree with their historical semantics; unsafe definitions remain
unverified without silent rewriting. Unsupported nonempty compatibility payloads
still fail closed. Native minor steps use the existing Fine Routing schema.

Sparse branch seed and section routing now have native input contracts. Curved
forks retain each selected numeric path recipe and compile separate path,
crossover-constraint, routing, curvature-encoding and optional budget-fitting
features. Saved path arrays are never accepted as inputs. Existing scientific
builders and formulas are unchanged. Output IDs survive edits while consumer
references, such as a constraint selected for deletion, remain editable.
Declared native no-ops remain in history because upstream edits can make them
effective. Native seeds also author their deterministic default cluster before
publication and snapshot encoding; legacy response serialization could otherwise
add a random cluster and invalidate an otherwise successful edit.

Independent-section construction and bounded selected-section routing add two
more contracts for subsequent Join compilation. They retain the established
even-column address separation independently of physical axes and preserve
outside state. Joined materialization, indexed crossbar paths, connectivity and
CPD conversion/relaxation remain P3 exit work. There are now 92 registered kinds,
with existing action/method restrictions; this is not 92 complete UI editors or
a completed P3. Assets, repair UI and strict automation policy remain P4–P6.

Measured scope overhead remains within both unchanged gates: warm command medians
are 1.24 ms versus 1.34 ms for six helices and 3.91 ms versus 4.38 ms for 24 helices
with 100 history rows. Full authoring output agrees. These are paired in-memory
command measurements, not cold startup or HTTP/rendering latency. See
[scope evidence](generated_scope_benchmark.json).

The composed fork regression verifies separate features across cold worker
processes, edits radius, preserves IDs/independent work, checks semantic no-op
retention and undo. Shrinking the fixture reduced its call from 7.21 to 5.85 s;
native routing/curvature plus two spawned checks remain genuine integration
work, so it is registered in the slow headless group. Focused development still
runs it. No guard budget or assertion was weakened.

Broad-suite debt remains explicit: Archive is still unavailable, and a fresh
selector dry run still chooses **FULL (test-dedicated session OPEN)**. The known
broad suites produce bulk fixture artifacts, so no further broad execution was
started on unapproved fallback storage. The prior FAST baseline comparison above
does not certify this increment. Focused results are recorded with this checkpoint.

Final focused checks: **122 passed** across typed scope/reference compatibility,
native branch/path/section adapters, cold replay/edit/cascade tests and existing
generated-design compatibility. [Validation detail](validation_branch_scope.json)
records each file and duration. Changed code has no new lint findings; repository
lint retains five unrelated unused imports and memory lint its six existing
errors. No frontend or molecular placement algorithm was changed, and no visual
inspection or physical simulation was run for this contract-only increment.

## P3 native DNA construction and bounded jobs — October 15

Joined sections and connectivity generation now emit separate native features:
seed, numeric path, group/pose, constraints, selected-section routing, Join,
curvature, budget and sequence steps. Ordinary cluster creation and moves use
their actual overlay definitions; destination composition independently executes
them and compares every authoring field. Saved samples, candidate Designs and
recovery snapshots are not proof inputs. Legacy generated construction remains
explicitly unsupported. The reported planning-to-runtime cluster map preserves
the old candidate summary and resolves the actual materialized identities.

The real joined triangle generation regression passes, including its fixed-center
attachment checks. The new budget guard initially rejected all references from a
scaffold to a Join. It now verifies that a distant native terminal trim preserves
each referenced nucleotide, direction, backbone neighbors, rigid owner and
realized directed ligation. Consumed sites, ambiguous occupancy and pending Join
constraints fail atomically. The existing fitting/placement algorithms are
unchanged; a small exact-parity fixture covers every attachment family emitted
by native Join. The full triangle test takes 187.66 seconds including setup.
This measures the complete planning/materialization regression, not added
validation overhead or ordinary edit latency. Joined compilation still performs
an additional destination execution to establish equivalence; no broad speedup
claim is made.

Native-source CPD conversion and relaxation have strict inputs, explicit endpoint
references, pinned template/implementation/numerical-runtime contracts and source
atom admission. The real regression creates, independently replays, relaxes and
replays both features in fresh spawned workers, with poisoned recovery and an
unusable physical reference. Complete authoring values agree exactly. Its
starting molecular topology is an explicit import, so the result correctly
remains `reproduced_import`; it does not prove native construction of that fixture.
The existing molecular solvers, export qualification and physical-reference
behavior are unchanged. The unreachable direct conversion branch in the ordinary
photoproduct adapter was removed, with a regression preventing its reuse.

`/api/design/features/evaluation/jobs` supports explicit verify, CPD append,
historical parameter edit and deletion. Jobs share the single proof admission
slot and process supervisor, run outside the document lock, retain bounded
candidates, and publish only through an explicit revision-bound commit. Commit
checks exact authoring reconstruction, cancellation, expiry, source identity and
revision, preserves unrelated presentation/physical state, and adds one undo
step. Polling omits candidate bytes. State-lock contention cannot block worker
deadline/cancellation supervision. Native workers are terminated and reaped
before admission is released; dead-worker cleanup retries are bounded.

Ordinary proof keeps its five-second policy. Long jobs have a 180-second whole-job
deadline, 2 MB input transport, 256 KB operation input, 8 MB cumulative recovery
encoding, 16 MB candidate transport, two retained results and a 15-minute result
lifetime. These are admission/retention limits, not a hard process heap cap.
Source/reference validation happens before a CPD long-job refusal, without
atomistic construction. No full replay was added to normal edits, scrubbing,
rendering or selection. One independently regenerated prefix is reused within
an evaluation; saved materialized output never substitutes for it.

P3 delivery is the native DNA construction/execution foundation. It does not
certify complete generated NP/attachment histories, supply new desktop/VR
controls, restore old numerical runtimes, or make every numeric edit individually
valid. A path extent change needs matching upstream seed parameters; coordinated
repair/batch editing is later work. Rootless legacy receipts remain unverified
until an explicit provenance decision. P4 asset/attachment contracts, P5 repair
and P6 strict automation remain active implementation work.

See [validation detail](validation_native_jobs.json) and the
[evaluation API guide](../../part_recipe_evaluation.md). The latest selector dry
run remains **FULL (FULL suite) [test-dedicated session OPEN]**. Archive is still
unavailable; broad artifact-producing suites were not rerun on fallback storage.
Earlier broad baseline results do not certify this checkpoint. Focused checks
are serialized; genuinely heavy native integration cases remain in the existing
slow groups without raising guards. No frontend or molecular algorithm changed,
`main.js` LOC delta is zero, and no visual inspection or physical simulation is
claimed. P4–P6 audits are recorded in `asset_import_plan.md`,
`duplex_contract_plan.md`, `repair_plan.md` and `automation_policy_plan.md`.

## P4a source-free gold particles — October 15

Create, patch and delete for an uncoated gold particle now record strict complete
inputs and explicit stable identity, using the existing native builders. Diameter,
pose and gizmo choices are retained. Missing/ambiguous targets and owned DNA or
connection dependencies fail before mutation. Decorated particles and QDs retain
their legacy routes and remain explicitly unverified; kind registration alone
does not upgrade old receipts. Source-free commands use conservative dependency
barriers because shared postprocessing can retry pending ligations.

There are now 99 supported versioned kinds, subject to their documented scopes.
The new regressions prove complete native-builder equality, preservation of
unrelated DNA, early diameter editing through a later move, stable feature/object
IDs, cold replay without recovery, actual-reference cascade and failure-atomic
recording. Existing particle/conjugation/connection/serialization tests pass.
Final focused checks: **51 passed** (new native particle proof 29 in 3.50 s,
existing nanoparticles 18 in 3.44 s, generated-native compatibility 4 in 2.55 s).
No full proof or new snapshot copy was added to ordinary particle edits. No
scientific placement algorithm changed. No frontend changes or visual checks;
`main.js` LOC delta remains zero. Broad validation debt above remains open.


## P4b pinned inputs and reversible duplex authoring — October 15

Portable pinned protein sources now regenerate parsed assets and supported free/
part-overhang placements, without a mutable library or network fallback. Source
admission is bounded and revision checked; source bytes, asset and feature row
publish atomically. Input resources survive worker capture, generated scopes,
undo, project revision/peer transfer and all native package modes. Whole-part
provenance records imported sources. Corrupt or missing evidence stays unverified
with an exact source reference and is never a cascade-deletion reason.

Duplex create/connect/patch/delete and explicit selected-binding sync now record
complete inputs. Missing/ambiguous endpoints fail before mutation; register
tracking uses exact retained nucleotide offsets and rejects unprovable changes.
Saved relocation topology is typed separately from live references, allowing
namespaced restoration without inventing live geometry or rewriting labels.
The existing direct-relax solver has a bounded native-source contract, explicit
selected joints/clusters and numerical pins. It uses the shared evaluation job
lifecycle; the older synchronous relax route remains a compatibility path until
UI/strict-route work. Shared runtime fingerprint helpers were extracted from
CPD without changing solver settings or formulas. Engine pins include changed
source modules, so old pins are not silently refreshed.

Loading and response formatting no longer infer authoring changes for documents
with explicit roots. Rootless legacy migrations remain available, and duplicated
load handling was consolidated. Required default clusters are authored by native
builders. Recipe publication preserves display/physical data while removing only
presentation links to attachments deleted by that operation; undo restores them.
The source blob cache is optional and cannot obstruct a portable save because of
cache-specific filesystem damage.

There are 109 registered versioned kinds with explicit scope restrictions; this
is not whole-application coverage. Large input transfer, inactive-loadout source
checks, further protein/NP/topology import/copy contracts and physical-source
provenance remain P4 work. P5 repair drafts/UI and P6 strict automation remain
pending, and assemblies stay deferred. No frontend or scientific algorithm
changes are included in this checkpoint.

`input_capture_benchmark_p4.json` records nine warm samples of independent pinned
protein imports sharing one 241-byte input. Median capture/proof time was
1.07/0.42 ms for one feature, 3.97/7.38 ms for 32, and 14.06/30.26 ms for 128;
all cases reproduced their imported source. Existing 30k-node/2 MB/25 ms
cooperative capture limits were unchanged. These small synthetic cases do not
qualify large protein throughput or interaction latency. No proof, full hashing
or dependency scan was added to ordinary edit/render/scrub paths.

Focused validation: **643 passed** across 35 files, including real
spawned duplex relaxation and separate cold replay, and native CPD conversion/
relaxation after the shared runtime extraction. Changed Python files pass Ruff;
`git diff --check` passes. Memory lint remains at its existing 6 errors/60
warnings. Detailed results and limitations are recorded in
`validation_inputs_duplex_p4.json`. Existing broad-suite/archive limitations
remain open; no browser/headset or physical simulation run is claimed.

## P4c conjugation, catalog inputs and document boundaries — October 15

There are now 112 versioned command kinds, with additional strict discriminators
for owned protein lifecycle and catalog particle operations. Small captured
proteins can form native conjugates, retain exact attachment/binder/group IDs,
move through the existing constrained delta solver, change visibility, and be
deleted only after typed strand and directional residue dependency checks.
Unrelated groups survive deletion. Existing free-placement conversion conflict
responses and atomic rollback behavior are retained. Legacy cleanup now prefers
current explicit binder ownership over historical guesses. Live orchestration
was extracted into `part_protein_recording.py`; routes remain thin adapters.

Unbound source-free thiol grafts record complete input choices and exact old
ownership for replacement/removal. Stable site IDs are supplied to the existing
native builder. Larger, coupled and genuinely opaque unsupported selections
retain legacy unverified behavior before admission; a native error never retries
through legacy mutation. Quantum-dot recipes pin the selected catalog entry and
use unchanged native size/pose calculations. Replay needs no mutable library or
network. Catalog metadata counts as imported evidence, with editable native
parameters; source hashes alone cannot certify changed particle outputs.

Document input decoding now has independent byte bounds before JSON parsing,
including gzip/base64, revisions, packages and peer transfer. ZIP64 and streamed
simulation members retain the standard-library path. An explicit source audit
reports missing/corrupt inactive branch evidence without discarding drafts.
Only activated state gets load warnings; ordinary edits and proof never decode
inactive snapshots. These transport bounds do not increase proof/capture limits
or claim to cap process heap usage. See [transport details](document_transport.md).

Nine warm samples at 1/128/100 handles (8/1,024/50,000 bases) had median native
build times of 0.23/8.12/5.83 ms, capture times 1.19/14.51/11.51 ms and proof
times 0.58/14.50/10.78 ms. All final samples verified; the largest observed build
sample was 41.9 ms. These include ordinary Python allocation behavior and are
not hard latency promises or HTTP/render qualification. Capture budgets stay
unchanged; [raw evidence](thiol_capture_benchmark_p4.json).

Focused validation: **708 passed across 36 files**. Changed-file Ruff and
whitespace checks pass; global lint retains five unchanged unused imports, and
memory lint retains six errors/60 warnings. Corrected findings are recorded in
`validation_conjugates_transport_p4.json`. The selector still requests the FULL
suite; Archive remains unavailable, so no broad pass is claimed. No frontend or
scientific algorithm changed; `main.js` LOC delta is zero. Shared identity edits
invalidate prior duplex numerical pins conservatively; their explicit upgrade
workflow remains P5 work, without silently substituting a newer engine.

P4 remains open. Prioritize ordinary unbound thiol particle movement/resizing,
then the [bounded topology-import sequence](topology_import_plan.md). Coatings,
biotin/coupled attachment contracts, typed rigid copy, larger asset capture and
physical-source provenance still need independent admission/validation. P5
repair drafts/UI and P6 strict automation are pending. Assemblies remain deferred.

## P4d pinned aptamers and unbound particle motion — October 15

The registry now admits 113 versioned kinds with explicit scope limits.
Single-chain aptamers reconstruct the unchanged importer's native sites from
captured UTF-8 PDB bytes. The contract retains the first-model, alternate-location,
residue-address, backbone and RNA rules, and replaces only generated identities.
The selected name/source annotation remain editable; output helix/strand/cluster
IDs remain stable. Replay never resolves a template name or filesystem path.
Deposited coordinates retain `reproduced_import` provenance; a matching source
hash cannot certify changed output sites. Larger/multiple-chain or opaque legacy
imports keep their compatibility path without a native receipt.

First imports now initialize and publish through one shared atomic recording
boundary, for native and legacy aptamer routes. Cancellation or failure restores
the no-document state, full undo/redo, revision and request markers. Existing
documents retain their roots and metadata. Successful initialization creates one
undoable feature; undo returns to the explicit empty part for native imports.

Unbound thiol particles now retain exact conjugation selectors during move/resize.
Shared ownership checks resolve each owned strand/helix/overhang and refuse
external consumers before native geometry work. Missing supported references
produce structured failures; unsupported larger/coupled/opaque cases choose
compatibility before mutation. Existing native pose/resize calculations are
unchanged. One known existing limitation is explicitly retained: resize updates
axes/coverage but not `SurfaceStrand.sulfur_local_nm`. Reproducibility does not
qualify the chemical correctness of that existing resize behavior.

The 150 KB/1,000-first-model-record aptamer admission was qualified against all
three bundled templates, repeated imports and an adversarial complete boundary
fixture. Of 90 warm capture/proof attempts, 85 reproduced their imported inputs
and five hit the existing cooperative capture budget. All ten separate fresh
workers reproduced their inputs. Single-import median capture was 3.9–7.2 ms;
atomic recording was approximately 6.6–11.4 ms, excluding the route's initial
parse and response rendering. Candidate JSON stayed below 873 KB and captured
pickle below 378 KB in these cases. Four-copy growth and all refusals remain in
[raw evidence](aptamer_capture_benchmark_p4.json); there is no hard latency claim.

Thiol movement admission medians were 0.06/2.95/2.25 ms for 1/128/100 handles,
with build medians 0.21/4.43/3.30 ms. Twenty-six of 27 warm proof attempts verified;
one 128-handle capture refused on time. [Raw evidence](thiol_motion_benchmark_p4.json)
retains the 43.5 ms capture and 90.1 ms proof maxima. No global capture, worker,
recovery or transport limit was increased. No full proof was added to ordinary
editing or rendering.

Focused validation: **461 passed across 24 files**. Changed Python files pass
Ruff and whitespace checks. One new RNA fixture initially selected a PDB header
mentioning an atom name; selecting an actual ATOM record corrected the test,
without changing importer behavior. Details are in
[validation evidence](validation_aptamer_motion_p4.json). The selector still says
**FULL (FULL suite) [test-dedicated session OPEN]**; Archive remains unavailable,
so no broad pass is claimed. Memory lint retains six errors/60 warnings. No
frontend changes, visual/headset check or physical simulation; `main.js` LOC delta
is zero. Molecular algorithms and numerical pin source files were unchanged.

Next work is [typed rigid copy](element_copy_plan.md), then independently bounded
larger-source/coating and [lattice import contracts](cadnano_scadnano_input_plan.md).
Coating assets already exceed the default capture node budget before timing;
their admission needs a separate measured design. P4 remains open, P5 repair and
P6 strict automation remain pending, and assemblies remain deferred.

## P4e typed same-part rigid copy — October 15

There are now 114 versioned kinds. `element-paste` has an explicit same-part
contract for free unconjugated proteins with selected atoms and undecorated
gold/catalog particles. It resolves typed source IDs from the replay prefix,
shares existing assets and uses the unchanged batch-width/paste-index transform.
Only declared output IDs and poses change; labels and metadata are not string
remapped. Existing frozen clipboard paste remains a separate legacy operation.

`POST /api/design/features/copy-elements` requires expected design identity and
revision, allocates output IDs on the host and publishes one undoable feature.
Missing or ambiguous selections fail before placement, and failed native work
never falls back to clipboard snapshots. Upstream source/parameter edits retain
output identities. Copied protein, gold and QD objects pass ordinary move/delete
and cold replay, preserving source objects and imported provenance.

The initial 16,000-atom experiment cost about 40 ms for copy and 119 ms for atomic
recording with distinct assets. Its evidence is retained in
`element_copy_benchmark_provisional_p4.json`. Admission now caps the total selected
protein work at 4,000 atoms (counting each placement), alongside 16 elements and
the existing 1,000-atom/4,000-bond per-asset bounds. Repeated asset validation is
shared within one call without sharing mutable copied objects or changing math.

The final six paired cases preserve complete authored output. Small copy medians
were approximately 0.23 ms both with and without unrelated DNA/history; the
16-particle case was 0.64 ms. Protein work at the 4,000-atom bound was 10.1–11.2 ms,
with atomic recording at 11.9–30.2 ms. The distinct-asset boundary still exceeded
the separate whole-document capture node limit in all five samples. These are
capture refusals, not proof failures or successes. New validation adds about
0.09 ms in the 16-particle case and 1.7 ms for distinct protein assets compared
with the old unchecked copy builder. No existing clipboard path changed and no
global budget was increased. Allocation/GC outliers and this overhead remain
visible in [final measurements](element_copy_benchmark_p4.json).

Focused validation: **303 passed across 13 files**, including 105 new command,
route and cold-replay cases. Independent review found and closed admission of
free legacy proteins without an atom selection: their ordinary native pose
patch was unsupported. Boundary and atomic 413 regressions were added. Shared
identity, native particle/protein, legacy copy, numerical duplex and hash-seed
determinism checks pass. See [validation evidence](validation_element_copy_p4.json).
The identity protection addition conservatively changes duplex numerical pins;
no old pins are refreshed silently.

The [coating experiment](coating_capture_experiment_p4.json) confirmed that one
tetramer exceeds ordinary node admission but fits current worker transport under
an experimental capture profile. A separately gated explicit job is the next
qualification target; ordinary budgets remain unchanged. Sixteen embedded assets
exceed node, worker and recovery bounds and need a separate storage design.
P5 pure repair/explicit numerical-upgrade work starts alongside remaining P4
contracts because older pinned recipes need that deliberate path. No repair job,
draft UI or strict automation policy is yet claimed. Assemblies remain deferred.

## P4f inputs and P5a repair checkpoint — October 15

There are 115 versioned kinds. Pinned `cadnano-import` reuses the complete native
import/recenter/overhang/cluster/integrity pipeline, then normalizes typed output
identities. The extracted recenter helper is unchanged and still re-exported by
CRUD. Limits are 100 KB source, 32 helices, 8,192 array slots, 16,384 declared
nucleotides, 128 strands, 512 conservative domains and at most one module
scaffold. Source replacement deliberately invalidates output IDs; name changes
retain them. Imported topology remains `reproduced_import`.

The new raw-JSON endpoint requires a fresh empty active part and exact document/
revision guards. It bounds streaming before retaining bytes, prepares the full
recipe/response outside the state lock, then publishes one undoable replacement.
The fresh-empty restriction avoids snapshotting arbitrary large old documents
under the global lock. Existing ordinary import routes are unchanged. Retained
sources, history, physical and presentation data require a new empty tab.

Seven admission cases passed all 63 warm and seven cold replays. Capture medians
were 0.98–7.76 ms; max was 8.82 ms, with no refusals. The 87 KB representative
source prepared in 93.9 ms and had a 222,350-byte worker input. HTTP/commit-lock
latency qualification remains separate. See [raw evidence](cadnano_benchmark_p4.json).

`part_recipe_repair` reuses `regenerate` and its existing recovery budget. It
accepts at most 64 explicit nonoverlapping input replacements or server-selected
CPD/duplex numerical upgrades. Protected identities/scopes and command versions
remain unchanged. A broken source can be repaired without proving its saved
geometry. Only a fully executed candidate is publishable; failures identify the
first issue, successful prefix and later `not_evaluated` rows. The existing
worker, admission, expiry, cancellation and commit paths are reused. Polling
returns changed fields/counts and pin provenance, never candidate geometry.
Transport decoding also checks exact recipe/root/source state before repair
publication. A real spawned duplex upgrade retained old pins until commit,
cold-reproduced after reload, and restored the old pin with undo. This does not
prove old-engine output or complete visual comparison/draft UX.

The pure coating contract admits one unowned gold particle and pinned complete
1STP/optional coverage bytes, with set/repack, move and remove actions. Native
preparation/packing is extracted without changing math or evaluation order. Set
requires a fixed-family implementation/runtime pin because seeded random samples
and discrete clash decisions are not portable across arbitrary runtime upgrades.
Source audits report each missing input with its own repair path. No production
capture profile or public append adapter is enabled.

Focused validation: **622 passed across 26 files**. Global lint retains the same
five unrelated F401 findings; changed Python and whitespace pass. Full-suite
selection remains **FULL (FULL suite) [test-dedicated session OPEN]**; Archive is
unavailable, so no broad pass is claimed. No frontend/visual/headset change or
physical simulation; `main.js` LOC delta is zero. Shared model/identity changes
conservatively change numerical pins; old pins are not refreshed automatically.
[Validation record](validation_inputs_repair_p4_p5.json).

**Qualification failure retained for the next checkpoint:** the 24-stage coating
benchmark reproduced in-process, but every cold script worker refused the
single-thread runtime contract. Script spawn imports can initialize NumPy before
the worker sets environment variables. The child needs to enforce the existing
thread policy against already-loaded libraries. Experimental capture also had
one 110 ms refusal; its approximately 49–51 ms median is not ordinary interaction
latency. [Initial evidence](coating_contract_benchmark_initial_p4.json) remains
unchanged. Fix and requalify before enabling larger coating jobs. P4, P5b–d and
P6 remain open; assemblies remain deferred.

## P4 worker and publication qualification — October 15

The script-spawn numerical initialization failure above is fixed in the isolated
worker. Runtime thread limits apply after spawn-time imports; the parent remains
unchanged. The corrected coating benchmark passes all 24 warm and 24 cold stages.
The 64-site boundary fits unchanged worker/recovery transport, but experimental
capture still refused once at 147.52 ms, with active-coating medians 48–59 ms.
The initial failed run remains as evidence. No ordinary capture limit or live
coating entry point is expanded. Explicit coating set/repack engine upgrades
join CPD and duplex upgrades; a spawned repair/reload/cold-proof regression passes.

The caDNAno HTTP benchmark publishes 27 isolated imports and confirms cleanup.
Median publication-lock holds were 0.065–0.112 ms; the maximum was 1.337 ms.
Concurrent lightweight request medians rose to 2.98–6.32 ms from 0.92–1.06 ms
baselines. The 87 KB case had a 52.79 ms concurrent p95 and 97.79 ms maximum,
despite negligible lock waits. CPU and HTTP scheduling costs remain visible;
these results do not establish zero overhead or browser-wide responsiveness.
See [route evidence](cadnano_route_contract.md) and
[coating qualification](coating_input_plan.md#worker-qualification-update-2026-10-15).

P5b's pure reference-selection foundation rebuilds the exact preceding prefix
and returns bounded typed candidates. It does not use saved geometry or recovery,
does not evaluate a solver for each candidate, and never returns a publishable
Design. Initial reviewed slots cover simple gold/QD targets, free protein
asset/attachment targets and same-part rigid-copy inputs. Compound, owned and
generated-scope selectors remain explicitly unsupported. Full repair decides
whether a selected replacement actually makes the recipe valid. The pure module
passes 62 focused tests; job integration is a following increment.

The post-checkpoint validation record separates these new checks from the prior
622-test checkpoint. P4, P5 and P6 remain incomplete; assemblies remain deferred.

## P5b selection jobs and P5c draft foundation — October 15

Typed selection now uses the existing bounded isolated job lifecycle. A host-held
nonpublishing flag prevents commit even if a worker accidentally returns a
candidate. Stale, busy or cancelled results clear their replacement choices.
The API exposes the initial reviewed direct-ID catalog and its unsupported
boundaries; selection never claims that a candidate repairs the whole command.

Repair action schemas moved into core without changing the evaluator contract.
A portable bounded draft schema and separate durable fingerprint now preserve
root inputs, ordered feature/group/child identities and published input source
availability/integrity. Recovery, geometry and draft-only sources are excluded.
Malformed source descriptors explicitly refuse this initial fingerprint; valid
descriptors with missing/corrupt bytes remain identifiable for repair. These
helpers are not yet a Design field, saved draft endpoint or UI.

Prepared-model publication now rolls back on any exception/cancellation after
the model swap, preserving the source object, full bounded undo/redo stacks,
revision and request markers. It retains one undo snapshot. Every evaluated
candidate also compares independent pre-decode authoring and recipe hashes;
shared nested decoder aliases cannot hide changed inputs. Hashing is outside
the state lock and only on explicit job commits. See ISSUE-83.

The fixed single-coating capture policy is wired only to explicit evaluation
jobs, with expected-revision admission before copying. Ordinary verification,
editing, scrubbing and rendering retain their original budgets. Scope/profile
tests pass; live-lock qualification is still pending, so this checkpoint is not
permission to enable ordinary coating routes. No public coating append or
capture-limit request option is exposed.

Focused validation: **423 passed across 15 files**. Changed Python and whitespace
pass; global lint retains the same five F401 findings. The dry-run selector now
reports **FAST (fast suite only)** and defers FULL because the prior test session
is no longer open; no fast or full sweep was executed with Archive unavailable.
The verbatim debt and fixture correction are retained in
[validation evidence](validation_selection_drafts_p5.json). No frontend, visual,
headset or molecular change; `main.js` LOC delta is zero. P4, P5c/d and P6 remain
open, with broader P5b selector families also pending. Assemblies remain deferred.

## Shared repair planning, registered batches and capture cost — October 15

Draft preparation now captures only root/definition inputs and named sources;
its metadata host uses explicit design/revision/draft-generation guards and
never guesses replacement expectations on rebase. Draft preparation and the
repair worker share one target/path/overlap/protected-input planner. Numerical
pin selection remains in the isolated worker. The temporary duplicate planner
and equivalence oracle were replaced by one implementation and direct behavior
tests. Design persistence and publication wiring remain pending.

The initial pure registered-batch compiler admits seven reviewed command kinds:
helix/strand additions, source-free gold create/patch/delete, whole-helix group
creation and cluster pose. It rejects arbitrary model/code/output payloads and
private proof inputs. Typed declared producer UUIDs remain separate from
host-generated feature IDs. A source proof executes once, then the existing
regenerator/recovery budget executes ordered ordinary rows. No intermediate
candidate publishes; cold replay tests independently reproduce the mixed log.
This is a pure foundation, not a public transaction API or strict session policy.
See [batch contract and remaining gates](registered_batch_foundation.md).

Capture accounting now processes the exact nine-scalar atom record at one
cooperative boundary, preserving identical node/byte admission and copied
aliases. The second live run has active medians 36–37 ms and p95 96–99 ms;
two of 120 captures still refused the deadline. All 150 separately prepared
publications and five live complete jobs passed; cancellation/source-change
cases reaped in approximately 53–55 ms and refused commit. The public coating
append gate remains closed pending retained-history/recovery qualification.
The two earlier failed experiments remain in the audit record; no limits or GC
policy were changed. These timings do not establish a hard latency ceiling.

This checkpoint passes **315 focused cases across 12 files**: repair/draft 214,
batch 73 and capture/proof 28. Changed Python and whitespace pass. Broad-suite
and existing lint debt remain explicit; no physical simulation or visual/headset
validation was run. An unrelated remote Alpine continuation/progress update was
merged without conflicts and preserved; it is not part of these phase claims.
P4/P5/P6 remain incomplete. [Validation record](validation_draft_batch_p5_p6.json).

## Portable repair proposals and explicit metadata API — October 15

Repair proposals now persist as a separate Design/branch field through JSON,
server sessions, loadouts, project revisions and packages. Proof, numerical
authoring projections, import roots and feature recovery exclude this field.
Ordinary same-branch geometry recovery retains the current proposal and staged
source bytes, including explicit absence after discard; branch navigation
restores the destination proposal. Source-union refusal happens before undo
stacks change. Broader pre-existing undo exception atomicity is not claimed.

The explicit metadata API creates, updates, rebases, reads and discards bounded
proposals. Preparation hashes definitions outside the document lock; publication
checks session/source identity, revision and draft generation, then assigns one
revision without geometry execution, a feature row or a geometry undo snapshot.
Protected simulation branches remain read-only. Ordinary responses expose only
a constant-size pending/unchecked summary. Source staging and draft-bound apply
remain pending; matching draft metadata never certifies a rebuilt part.

The checkpoint passes **187 focused cases across 13 files**, including independent
CPD/duplex cold rebuilds and all affected persistence boundaries. The new model
field changes conservative numerical source pins without changing algorithms;
old pins require explicit upgrade. Changed Python Ruff and whitespace pass.
The selector dry-run still reports FAST and deferred FULL; neither broad suite
ran, and Archive is unavailable. See the [API](../../part_repair_drafts.md),
[boundary audit](draft_document_boundary.md) and
[validation record](validation_draft_persistence_p5.json).

## Qualified coating jobs and guarded batch integration — October 15

The narrow coating append job entry point is enabled after actual retained
history qualification. Its 64-site history reached 14 rows before the unchanged
8 MB recovery budget refused row 15 atomically. A further run includes portable
repair proposals near node/byte limits: 90 prepared publications and three
complete native jobs passed; capture p95 was 93.6–98.3 ms with one of 90 deadline
refusals; publication p95 was 11.6–18.4 ms. Real cancel/stale workers reaped in
about 53 ms and refused commit. Occasional longer lock/HTTP outliers remain;
this does not establish a hard deadline or qualify mixed-part ordinary routes.

That benchmark first exposed ISSUE-84: sparse draft envelopes could fit while
serialized optional defaults exceeded the same limit. Canonical persisted-form
admission fixes it without raising limits or bypassing snapshot validation.
The aborted attempt and failing regression evidence are retained.

Evaluation jobs now retain the host-admitted operation independently of worker
results. Verify/selection/unknown jobs cannot become publishing jobs through a
forged ready result. Registered batches reuse capture, worker supervision and
one exact candidate publication; the public batch gate remains closed for its
separate responsiveness qualification. Source proof executes once; candidate
composition is not mislabeled as an independent cold replay or strict policy.

The checkpoint passes **306 focused cases across 13 files** (237 lifecycle and
69 canonical-draft/persistence cases), plus the retained-draft benchmark. Changed
Python Ruff and whitespace pass. Broad-suite debt remains unchanged. See
[batch API](../../part_registered_batches.md),
[coating evidence](coating_jobs_benchmark_drafts_p4.json) and
[validation](validation_guarded_jobs_p4_p6.json). P4/P5/P6 remain open.

## Saved repair evaluation and explicit source repair — October 15

Saved proposals now start the existing isolated repair lifecycle after an
explicit base-fingerprint check outside the state lock. The host passes the
same captured source and session identity into job admission. Evaluation never
silently rebases a proposal or rewrites its expected old values. Apply publishes
the exact candidate once, with one undo, and retains the proposal for deliberate
review/discard. An HTTP regression repairs a missing native reference and then
reproduces the result in a second fresh process with poisoned recovery.

Named source inspection/staging/restoration accepts original bytes only for
reviewed command inputs. Each upload binds to the part/revision/proposal and an
explicit receipt for the old encoded bytes. Published-source restoration requires
explicit rebase; proposed-only staging leaves the published base unchanged.
Acquisition has one nonqueued slot and a bounded body deadline. Hashing and
preparation occur outside the lock; publication adds one metadata revision and
no geometry undo or feature. Current admitted source-owning kinds are snapshots;
real minor children cannot invent an input contract by carrying source JSON.

Evaluation now binds to a host-only session identity as well as source/revision.
Close/reopen cannot revive a stale candidate or committed handle, and a rejected
late commit cannot recreate the closed document (ISSUE-85). Default capture and
ordinary verification remain compatible. Repair metadata publishers share one
small compare-and-swap/rollback helper instead of duplicating transaction tails.

The checkpoint passes **331 focused cases across 17 files**. The source fixture
corrections and dry-run selector's verbatim FAST/deferred FULL output are in the
[validation record](validation_saved_repair_jobs_p5.json). Neither broad suite ran;
Archive is unavailable. No frontend/main.js, molecular algorithm, numerical pin
or global-budget change. P4 coverage, P5 UI and P6 enforcement remain incomplete.
See [saved evaluation](draft_evaluation.md) and [source contract](repair_source_staging.md).

## Gated original-source protein workflow and repair regression — October 15

The experimental ordinary free-protein importer records original PDB bytes and
two independently editable native steps: import and placement. It parses once,
prepares privately and publishes both rows/source/library changes in one guarded
undo transaction. Missing or corrupt earlier source declarations cannot be healed
implicitly by a later import. Rootless prefixes remain explicitly unverified.
The ordinary route retains its existing behavior because the server-owned
`NATIVE_FREE_IMPORT_ENABLED` gate is **false**; request data cannot open it.

Retained-state benchmarks exposed occasional capture deadline refusals, including
a failed final fixture setup in the optimized run. The existing scalar-atom copy
optimization now covers protein assets with exact generic node/byte accounting
and alias-isolation tests, but does not eliminate those outliers. No deadline,
node/byte allowance, global GC policy or automatic retry was changed. Subsequent
optimization must first distinguish redundant candidate allocation from necessary
locked source isolation. All failures remain in the compact benchmark evidence.

The saved-source repair regression now restores original missing bytes, requires
explicit rebase, evaluates/applies once and independently cold-replays the result
after JSON persistence with poisoned recovery. Capability descriptions were
corrected for already implemented draft/source APIs and bounded coating jobs.

This checkpoint passes **173 focused cases across six targets**. Changed Python
Ruff and whitespace pass. The selector dry-run reports FAST/deferred FULL; neither
broad suite ran. Archive remains unavailable, and no app/visual/headset check or
scientific simulation ran. `main.js` LOC delta is zero. P4/P5/P6 remain incomplete.
See [contract](protein_free_import_contract.md),
[initial report](protein_free_import_benchmark_p4.json),
[retained-state failures](protein_free_import_benchmark_optimized_p4.json), and
[validation](validation_gated_protein_p4.json).

## On-demand repair input catalog — October 15

An explicit revision-bound endpoint now exposes reviewed scalar, pose, reference
and named-source fields for one selected definition. It returns exact input paths
and old values, shares upload limits with source admission, and grants no proof or
publication authority. The bounded lock-owned read never visits geometry, recovery
or source bytes; schema discovery runs privately afterward. Unknown, legacy,
generated and malformed definitions remain explanatory rather than receiving a
generic JSON editor. Broader invalid-scalar recognition is a separate follow-up.

**63 focused cases pass**: 27 input-metadata cases and 36 existing source-policy
cases. Changed Python Ruff and whitespace pass; frontend app/visual work is still
in progress and not validated here. `main.js` LOC delta is zero. See the
[endpoint contract](../../part_repair_inputs.md). P5 remains incomplete.

## Private publication authority and measured capture cleanup — October 15

Host-owned immutable policy configuration now survives session recreation. Private
admission handles bind the actual request, source, session, revision and policy
generation. Registered batch publication requires a one-use permit for the exact
decoded candidate and rechecks source/candidate scope, cancellation and deadline
before assignment. The rollback bracket consumes a permit only after successful
publication. Saved labels and caller-supplied actor/native flags grant no authority.

Strict generic callbacks, direct recorders, silent writes, undo/redo, source/draft
publication and known legacy create/load/save/loadout routes refuse before their
side effects. Default compatibility is preserved. This is a host foundation, not
a complete HTTP boundary: global file routes, unreviewed reads and mutable aliases
still require a closed strict application. The first admitted host slice is batch
plus read-only verify and explicit empty creation; the public batch gate is false.

Full-source batch publication is bounded to 64 source/candidate rows including
group headers, reviewed native families, default excluded state and the existing
8 MB retained recovery allowance. Read-only verification still ignores recovery.
The final permit-aware benchmark produced 120 correct prepared publications and
four real jobs that cold-replayed. One 50,000-residue capture refused after a
46.25 ms lock hold; publication lock p95 ranged from 0.91 to 1.19 ms. Earlier
63-row and other refusals remain in the evidence. No hard latency ceiling is claimed.

Private protein candidate admission now shares exact source-capture node/byte
accounting while omitting a redundant isolated copy and its second time allowance.
Source capture retains the original 25 ms deadline. A 30-attempt retained-protein
probe had 29 correct imports; the refusal coincided with a measured 45.08 ms
generation-2 GC pause inside source capture, and subsequent cold capture refused.
The smaller nine-attempt diagnostic passed. No GC policy/limit/retry changes;
native ordinary import stays gated. Strict immutable revisions after read/write
closure are the planned way to reduce lock-owned graph allocation.

**527 focused cases across 22 files pass**, with changed Python Ruff and whitespace
clean. Real benchmark cleanup passed. Repetitive successful samples were pruned,
retaining outcome distributions, every unexpected result and timing maxima; GC
evidence retains every major collection and phase/generation maxima. Broad-suite,
app, visual and headset debt remains unchanged; Archive is unavailable.
See [validation](validation_publication_foundation_p6.json),
[policy audit](strict_publication_checkpoint.md),
[batch evidence](registered_batch_jobs_benchmark_permits_p6.json) and
[GC evidence](protein_free_import_benchmark_admission_2000_gc_p4.json).
P4/P5/P6 remain incomplete; assemblies are deferred.


## Closed strict HTTP and lossless repair expectations — October 15

The outer ASGI dispatcher now selects an exact strict route table before legacy
handlers or body acquisition. Only explicit empty creation, scalar policy/revision
reads and existing batch/verification job lifecycle handlers are admitted. JSON
acquisition is byte/time bounded; unknown routes, WebSockets, multipart bodies and
unsupported operations refuse without compatibility fallback. The existing
lifespan and session/job services remain shared. Policy generation is rechecked
inside locked job admission and final publication. This is a host construction
policy, not authentication; an agent-only surface needs a dedicated strict default.

Browser repair actions now retain canonical `expected_old_json` text so JavaScript
number serialization cannot turn unchanged `12.0` into a false conflict. Exact
backend expectation, identity, schema and whole-envelope bounds remain in force.
The real Node action builder passes HTTP draft save/reload/rebase and native repair
preparation. Invalid-value contract recognition remains the next independent step.

**478 backend cases across 18 files and 12 pure frontend cases pass.** The
500-request in-memory dispatch probe completed with cleanup: strict revision
median 1.076 ms, p95 1.362 ms, maximum 1.730 ms. Paired compatibility overhead
median -0.006 ms is measurement noise, not a claimed speedup. This probe excludes
large capture, publication, network and rendering; the public batch gate remains
false. Immutable strict session storage is the next ownership/performance step.

The selector was a dry-run: FAST/deferred FULL, neither suite executed. Full
desktop integration is a separate pending checkpoint after the first full Vitest
run exposed six metadata-summary failures (8,155 passed, one skipped). Archive is
unavailable; no app, browser, headset, native or scientific check ran. `main.js`
LOC delta remains zero. All test fixtures are scoped and benchmark models stayed
in memory; only compact evidence is retained. See [validation](validation_strict_http_repair_transport_p5_p6.json)
and [dispatch measurements](strict_http_benchmark_p6.json). P4/P5/P6 remain open.


## Exact cache document identity — October 15

ISSUE-88 reproduced cache path collisions (`a/b` and `a_b`, or truncated IDs)
and dot IDs addressing the cache root/parent. A shared pure validator now requires
exact 1–80 character ASCII alphanumeric/underscore/hyphen/period IDs excluding
`.` and `..`. Cache writes refuse before capture; unsafe autosave logs a bounded
diagnostic and lets valid documents continue. Strict HTTP refuses these contexts
before body acquisition/session creation. Normal UUID/default/named/headless IDs
retain their exact paths. No existing cache files were moved or deleted; startup
restore/pruning behavior is unchanged.

The baseline was 29 failed/nine passed. All **122 focused regressions pass**,
including existing cache pruning and strict dispatch. Changed Python Ruff and
whitespace pass. Only tiny pytest-owned sentinels were used; no production cache
thread or workspace writer ran. This closes the identifier prerequisite for
immutable persistence; it does not itself enable native restore or public batch.
See [validation](validation_cache_identity_p6.json). P4/P5/P6 remain open.


## Desktop repair workflow UI-1 — October 15

The feature-log launcher now opens a modular standard-part repair workflow with
explicit Check, earliest-error navigation, reviewed scalar/reference/source
inputs, saved proposal/rebase/discard, evaluation/cancel and Apply. Metadata
acknowledgements do not fetch or replace displayed geometry. The controller binds
all work to document/design/loadout/revision and an epoch; no readiness is saved.
Two superseded local parameter-builder helpers were pruned after the backend
input catalog became authoritative. `main.js` remains unchanged.

ISSUE-87 is fixed: Apply retains the actual publication receipt and privately
refreshes the exact committed design/geometry before one normal synchronization.
Read failure offers explicit Refresh. Lost commit transport retains an unknown
publication state and original job for explicit status resolution, never an
automatic recommit. Default-document null maps to the exact server `__default__`
sentinel; missing/other server identities refuse. Protected/history contexts and
numerical upgrades requiring separate molecular review remain explicit.

**86 focused cases pass; full Vitest passes 8,181 tests with one skipped across
708 files (309.16 seconds).** Earlier red/null/default-document evidence is
retained. `NOT VERIFIED IN APP`: Archive is not mounted, so browser/smoke/headset
work remains MV-45. A prefixed, failure-cleaned isolated Playwright scenario is
prepared but unrun. No app models, screenshots, native builds or scientific
outputs were created; normal tiny Vitest caches and existing placement journal
are preserved. Visual candidate comparison and native VR are the next UI slices.
See [validation](validation_repair_ui1_p5.json) and [UI contract](repair_ui_plan.md).
P4/P5/P6 remain open.

## Internal immutable session storage — October 15

The staged strict storage path keeps one sealed immutable full-document revision
in `session.design`, with no mutable mirror. Explicit internal empty creation
reserves the actual empty session, prepares content outside the shared lock, then
compares session identity, revision and host policy before publication. Closing
or replacing that reservation cannot recreate it. Mutable getters, old capture
and persistence facades refuse this internal representation explicitly; scalar
document/revision metadata remains available and compatible.

Native replacement retains immutable source handles for undo instead of copying
models. Retention admission precedes mutation, preserves the immediate source,
and rolls back exact handles/stacks/revision on failure. The provisional 32 MB
cumulative allowance is not a public memory qualification. Populated immutable
sessions refuse a silent strict-to-compatibility policy transition.

**276 parent-run focused/regression cases pass.** Changed Python Ruff and
whitespace checks pass. Public immutable creation remains false, and current
strict HTTP creation retains its existing mutable representation. This is an
internal reversible checkpoint: typed sibling persistence, pending-record
protection, independent cold restore, job integration and measured HTTP/GIL
responsiveness must precede public enablement. Existing files and cache pruning
behavior are preserved. See [validation](validation_immutable_state_p6.json),
[storage plan](immutable_part_revision_plan.md) and
[durability plan](immutable_part_persistence_plan.md). P4/P5/P6 remain open.

## Private finite-linker route and HTTP qualification — October 15

Existing-version finite ssDNA/dsDNA Apply/reapply now has a default-disabled
native adapter. One bounded source inventory and owned selection feed the
existing failure-atomic recorder: one undo, two recovery encodes and the original
reconcile/retry/CPD/validation behavior. Missing or ambiguous references refuse
before recording. Unsupported families and source bounds retain compatibility
dispatch; an admitted failure never retries through legacy. Exact input,
conflict and generated-output identities make the resulting row replayable.

**244 focused cases across nine files pass**, including independent input-only
replay, real cold proofs, rollback, protected context, output collisions,
conflict-boundary fallback and exact full-response behavior. The stale comment
claiming partial finite-linker geometry was corrected: connection-list changes
actually force the established full geometry path. Scientific helpers and
numerical pins remain unchanged.

The final complete-HTTP benchmark passes 124 paired full authoring/response
comparisons, 496 successful Apply/reapply requests and four fresh input-only
replays. Its initial ds response mismatch was isolated to an unquoted random ID
in an existing occupancy warning; a bounded diagnostic preceded the exact-token
oracle correction. Original warning content and initial evidence are retained.

Rollout remains closed: 16-cell ss reapply measured 144.27 ms native versus
96.30 ms legacy median, after an initial 145.20 versus 73.26 ms result. Both
arms have natural-GC tails; neither overlapping GC nor pure correctness is a
latency exemption. Reference inventory allocation and benchmark lifetime effects
are the next measured investigation. No UI or app rendering was exercised.
Repository lint retains its five existing unused imports. The backend selector
was FAST/deferred FULL in dry-run only; prior broad failures/debt remain separate.
VR is deferred by the user, assemblies remain deferred, and P4–P6 remain open.
See [the route plan](ordinary_connection_owned_route_plan.md) and
[validation](validation_finite_connection_apply_route.json).

## Reference inventory lifetime and measured follow-up — October 15

The dependency reference walker retained each temporary set in a recursive
closure cycle. Moving only that visitor to module scope releases the scratch
storage when the call returns, preserving complete typed-reference semantics,
saved-owner subtraction and fail-closed diagnostics. **247 focused cases pass**;
the immediate-lifetime test failed before the extraction. No cache, scientific
algorithm, numerical manifest, limit or GC policy changed.

A separate benchmark profile now releases large decoded client responses before
the next request while retaining exact parity digests. Its baseline and final
31-pair runs each pass 496 successful requests, 124 comparisons and four fresh
input-only replays, with complete cleanup and no dropped GC events. Native
16-cell ss reapply median fell from 125.83 to 72.99 ms; the final legacy median
was 71.30 ms. This resolves the observed median regression in that profile,
without qualifying long tails: native ds Apply still reached 181.68 ms. Both
profiles share server and client allocation, so neither replaces app validation.
The route gate remains false; initial and failed evidence is retained. See
[the analysis](reference_inventory_lifetime.md) and
[validation](validation_reference_inventory_lifetime.json).

## Recovery preparation and owned worker handoff — October 15

The near-cap recovery diagnostic isolated 164–187 ms of parent canonical
preparation, with scalar reads delayed up to 158 ms. Recovery now performs that
unchanged preparation and native proof in its existing disposable child. The
parent retains the exact original bytes and lease, and seals them only from the
closed worker's original one-shot observation. Copying metadata, tickets,
observations or a returned proof dictionary grants no publication authority.

**384 focused cases across twelve recovery/storage/worker/permit/session files
pass**, including real spawned empty/gold/DNA input replay, parent decode traps,
full metadata equality, crash/overflow, concurrent observation/consumption,
cleanup and stale-context failures, original five-second deadline and eviction.
Existing commit, lease and rollback checks remain. A separate 17-case finite-
linker cold replay target passed in the same extended run. Changed-file checks
pass; repository lint retains five existing unused imports. Broad validation is
FAST/deferred FULL in dry-run only; Archive remains unavailable for broad/bulk
outputs and app checks. VR remains explicitly deferred.

This is a correctness checkpoint. The near-cap memory/HTTP harness must now
allocate independent input bytes per simulated file read and avoid retaining
closed worker objects and their input tickets. No source limit, native algorithm,
deadline, memory target or public gate changed. Retained-memory and whole-request
qualification remain open. See [the worker plan](immutable_recovery_worker_plan.md)
and [validation](validation_immutable_recovery_worker_stage2.json).


## Recovery transport lifetime and 30-cycle diagnostic — October 15

Recovery now copies its source once from the shared input and closes the child
mapping before unchanged preparation/proof. Common framing retains exact
length/hash/canonical checks and accepts platform allocation padding. A close
failure cannot reach preparation. The parent still seals its exact original
bytes only from its owned closed-worker observation.

**168 unique recovery cases plus five sampler controls pass.** The updated
scalar probe stays active through completion and reports its discrete coverage.
The same-harness three-cycle sampled RSS maximum fell from 284.73 to 253.10 MB.
The subsequent 30 cycles completed 60 proofs and cleanup, all below the existing
256 MiB incremental target (255.45 MB maximum). Start p95 was 8.48/7.54 ms;
state-lock maximum was 1.304 ms. No budget, scientific helper or public gate
changed. Detailed gaps and late-phase overlaps remain explicit; these results
do not establish hard peak memory, durable-file or full-app qualification.

Changed-file checks pass; repository lint retains its five existing F401s. The
backend selector remains FAST/deferred FULL in dry-run only. Archive is absent;
no new broad/bulk/app run occurred. VR and assemblies remain deferred. Completed
owned pytest fixtures were removed after reference/lock checks (39 files,
87,233 bytes); historical locked data remains untouched. See the
[worker plan](immutable_recovery_worker_plan.md) and
[validation](validation_immutable_recovery_transport.json).


## Ordinary nanoparticle application correctness checkpoint — October 15

Apply, active rename, Unapply, Reapply, applied Delete and combined create/apply
now have an ordinary route adapter behind a disabled private gate. It records
exact command inputs through the existing single transaction and shares the
pure builder's preparation/selection/materialization. Structural compatibility
fallback ends before native work. Missing references, output collisions or late
failures cannot silently switch implementations or publish a partial edit.

**224 unique cases across eight files pass**, including authentic HTTP lifecycle,
conflict switching, undo/redo, exact authoring parity, independently spawned
input-only replay while applied, source/session guards and atomic failure.
Stale pending-route traps were replaced with checks at the actual preparation
seams. No scientific helper, numerical pin or budget changed.

Normal application behavior remains on its existing path. Complete response and
following geometry parity, latency/resource measurements and desktop checks are
still pending; the next benchmark is proposed but not implemented. Repository
lint retains five existing unused imports. Selector result is FAST/deferred FULL
in dry-run only, with no new broad-suite execution. Archive remains absent;
VR is user-deferred and assemblies remain deferred. Owned completed pytest
folders were empty and removed after lock/reference checks; historical locked
data was preserved. The persistent goal is paused at the user's requested
stopping point. See [the route plan](ordinary_np_application_route_plan.md) and
[validation](validation_np_application_routes.json).


## Geometry-first priority reset — October 15

The user resumed work and explicitly moved extrude, sweep, bend, twist,
move/rotate and Fine Routing ahead of nanoparticles and assets. The revised
persistent objective and G1–G6 acceptance sequence are in
[the active delivery map](remaining_standard_part_checkpoints.md). Existing
native command availability is not full desktop lifecycle completion. G1 begins
with regression reproduction of grouping history omissions and deformation
preview/Apply/cancel interactions; G2 covers the legacy editor restrictions.
No private gate, source pin, budget or scientific algorithm changes in this
planning checkpoint. Nanoparticle work stays at `c9f1d185`; assemblies and VR
validation remain deferred.

## G1 ordinary grouping checkpoint — October 15

Ordinary cluster-panel, selection-menu and headless creation now always records
one versioned `cluster_create` input. The `log` argument remains accepted for
compatibility but is ignored; false cannot create an unlogged group. The thin
route delegates to `part_group_recording.create_group`, which uses the existing
pure overlay builder under one owning state lock and the lock-owned replacement
publisher. It does not call `state.set_design` while already holding that
non-reentrant lock. Validation/publication failure and cancellation preserve the
source, history, undo/redo and revision. No whole-history proof or topology
reconciliation is added to ordinary grouping.

Grouping is explicitly latest-history-only: a historical outer or child cursor
returns HTTP 409 `historical_cursor` before allocation/building, instead of
guessing a branch/truncation policy. Native inputs preserve exact helix/domain
membership and intentional overlap. Existing rootless documents remain
unverified; a new grouping row cannot supply their missing construction history.
The extra grouping row correctly separates earlier and later Fine Routing
operations. Generated compilers already emit grouping commands directly and do
not pass through this ordinary route, so they gain no duplicate entries.

The first green focused run passed **101 cases, 108 warnings, 5.57 s**. An additional
nicks→group→nick chronology and independent-replay test was then added; the group
file rerun passed **16 cases, 16 warnings, 2.88 s**. The runs overlap, yielding
**102 unique focused passes**, not 117. Existing headless/harness assertions
requiring unlogged creation were replaced with mandatory-recording assertions
and an explicit missing-receipt negative control. See ISSUE-99 in the root
ledger and `tests/test_geometry_group_history.py`. The
[validation record](validation_geometry_group_history.json) preserves the earlier
red runs, interrupted nested-lock attempt, cleanup and remaining lint/selector
debt alongside these green results.

**G1 is still in progress.** The ten bend/twist cases in
`tests/test_geometry_history_preview_lifecycle.py` include characterization of
the current broken desktop request sequence. Preview removal/update/disposal
leaves canonical state without its committed deformation; history Apply returns
`recipe_not_reproducible` (409). Cancel restores the overlay by seeking history,
but adds undo and clears redo. Direct native edits and their undo/redo controls
work. These passing characterizations reproduce ISSUE-100; they are not a
preview fix or the desired user contract. The next increment is the bounded
isolated preview described in the [active delivery map](remaining_standard_part_checkpoints.md).

**No app, broad-suite or performance qualification was performed for this
checkpoint.** MV-48 retains desktop validation debt. `frontend/src/main.js`
delta is **0**. No molecular formula, numerical source pin, limit or private
rollout gate changed; assets, assemblies and machine-specific VR remain deferred.

## G1 forced-ligation recording continuation — October 15

The ordinary forced-ligation route now resolves its actual source, endpoint
labels and partial-response scope under one recording lock. A thin adapter
delegates to `part_routing_recording`, the existing pure ligation builder and
lock-owned `record_minor`; one snapshot, reconciliation and pending retry remain.
This prevents a prebuilt candidate from discarding an intervening nick and
refuses protected loadouts before building. Geometry, seam behavior, errors and
the extension full-response fallback remain unchanged.

All **107 related cases, including 14 new cases,** are green. The
[continuation evidence](validation_geometry_integrity_continuation.json) retains
the three-defect red run, combined 141-case run (139 passed/two preview-fixture
failures, 86 warnings, 5.23 s) and corrected two-case rerun. ISSUE-101 records
the test scope. No app, broad-suite or performance qualification is claimed;
MV-48 remains pending and `main.js` delta is **0**. G1 remains ongoing, with
batch-nick skipping, resize reference admission and prebuilt auto-crossover
publication still separate follow-ups.

## G1 private deformation evaluator and legacy pruning — October 15

`part_deformation_preview.prepare_from_capture` takes independently owned input
captured under the host's lock. It inventories stable parent/child IDs and native
coverage, then executes only the prefix before the selected feature. Repeated
`evaluate` calls copy that bounded prefix and definition, apply the existing
native deformation command and validate it. They do not decode recovery,
regenerate the suffix, access live state or establish source equivalence.
Returned metadata explicitly leaves both source equivalence and downstream
evaluation unchecked. Consumer mutation and failed native work cannot alter the
next evaluation.

This private slice admits empty native roots and bundle/group/pose/deformation
prefixes, fixed target membership, 128 commands, 16 helices, 1,024 prospective
sites, 64 overlays and a 1,024-bp frame span. Existing 30k-node/2MB capture
accounting stays unchanged; native work has a one-second cooperative allowance.
These are internal admission limits, not interactive latency measurements.
There is no route, retained host cache, lease, render/control DTO or UI wiring.
Expand core prefixes, establish document/session/revision ownership and guarded
Apply, then preserve all existing controls before enabling the editor.
**ISSUE-100 remains open.**

All 34 private cases and 46 existing native/edit controls pass. The
[continuation evidence](validation_geometry_integrity_continuation.json) keeps
the initial module-absent red, corrected fixture/oracle failures and identity/
input-limit controls. An independent ownership review found no blocker in this
limited private scope.

Caller review also proved `state.set_design_silent_reconciled` unused in
production. Removed that obsolete publication path, its sole denial-test case
and current guidance/audit entries; historical provenance is retained. All 38
remaining publication-state checks pass. Across private preview, forced ligation
and publication tests there are **225 distinct passing cases**; these overlap
earlier checkpoint targets and must not be added to their totals. Changed-file
Ruff/diff checks pass; repository lint retains five pre-existing F401 imports.
The selector dry run reports FAST with accumulated FULL debt and executes no
suite. App, broad regression and measured responsiveness remain open; `main.js`
delta is zero. Completed disposable fixtures were empty and removed after active
reference checks; no designs, captures or simulation outputs were retained.

## G1 core geometry lifecycle continuation — October 16

Live nick batches now require every selected nick to succeed; resize uses the
same terminal-reference guard as native replay. Both record atomically and
derive partial-response scope from their owned source. Missing targets return
typed 404 diagnostics and inapplicable targets return 422 with parameter paths.
Valid native math, empty-batch behavior and tolerant legacy replay are preserved.

Automatic crossover now builds on one detached full source copy outside the
state lock, then compares source/session/revision and host policy generation
before the existing recorder publishes. An intervening nick is preserved and
the stale automatic result is refused. Protected and strict-policy refusals
precede work. This adds one source copy beyond the recorder's undo copy; its
larger-design cost remains unqualified. No full proof is added to these edits.

Private deformation previews now have a bounded host lifecycle and complete
native DNA/control DTO: one prefix/document, two total, 60-second leases, one
nonqueued work slot and bounded scalar cancellation tombstones. Weak source,
session, revision and policy identities prevent stale admissions. Late responses
cannot revive cancelled or superseded work. Apply re-captures and proves the
original inputs, reserves its commit and performs one failure-atomic publication;
Cancel reports a commit already in progress rather than claiming to stop it.
An unchanged-source failure preserves the unexpired editor lease. Full undo
copy cost is separate from the authoring-capture budget.

The DTO preserves native nucleotide orientation, slab placement, loop/reference
metadata and every scoped axis sample. It reuses pure projection/inventory logic
under a separately named/versioned preview schema; existing comparison v2 stays
unchanged and gated. Controls-only requests avoid geometry allocation. Complete
responses, including host envelopes, are budgeted outside the state/catalog
locks. Source equivalence, downstream evaluation and physical validity are never
claimed by this local preview.

There are **411 distinct backend passes and one existing conditional skip**.
The [checkpoint evidence](validation_core_geometry_lifecycle.json) records red
runs, the corrected mistyped test target, warnings, overlap accounting and
frontend validation. Typed errors now display direct explanations instead of
raw JSON; existing array/fallback behavior is preserved. Current guidance for
the previously removed silent-reconciliation helper is also corrected.
Full frontend validation passed **8,300 tests / one skipped in 717 files,
345.21 s**. Repository lint retains exactly five pre-existing unused imports.
Completed test folders contained no files/bytes: 204 empty directories and four
symlinks were removed after checking active references. Historical pytest and
placement-review evidence was preserved; no e2e cleanup roots remain.

**ISSUE-100 and G1 remain open:** no public preview route or editor integration
is enabled. Standard-tool prefix expansion, complete controls, document-bound
transport/controller/renderer and actual desktop/latency qualification are next.
The existing 60-second lease and private admission bounds are not a final UX
qualification. Assemblies, machine-specific VR and lower-priority assets remain
deferred. `main.js` delta is zero; scientific algorithms, models and source pins
are unchanged. MV-48 retains all unperformed app checks and the broad backend
suite remains separate debt.

## G1 private deformation integration checkpoint — October 16

The isolated preview now accepts ordinary extrusion, sweep and Fine Routing
prefixes through the unchanged shared native executors. Prospective admission
counts actual helix extents for end edits and repeated routing targets, reuses
native continuation lookup for existing helices, and bounds gaps before native
allocation. Sweep path sampling has a separately named 1,024-sample allowance;
it is an additional work restriction, not equivalent to the nucleotide limit.
Its native feasibility preflight is performed once during prefix preparation.
All original capture/site/operation/time limits remain unchanged.

The DTO now validates its closed scalar host envelope before native work and
charges the combined response once. Standalone projections remain bounded.
The disabled HTTP adapter acquires bounded JSON, checks document/policy context
before work, and performs projection plus explicit response serialization in a
worker thread. It is deliberately not registered in the main app. After Apply,
the existing bounded lease drops its prepared prefix and retains a scalar receipt
with weak published-source identity until the original expiry. Status distinguishes
active Apply, refusal and completed publication; unknown outcomes are resolved
without another commit. Undo or any later source/session/policy change invalidates
the receipt's refresh authority.

The frontend transport and controller own a caller-known nonce, server lease,
stable feature identity, one active evaluation and one latest pending input.
Prepare, preview and Cancel do not synchronize canonical geometry. Apply drains
the latest evaluated draft; known failure keeps the editor usable. Published
data is read privately between two exact lease/status checks and adopted only
after a final local document check. Apply/Cancel races preserve an already known
receipt and permit only one display adoption. Full control-envelope validation
remains a required injection; these factories are not wired into the editor.

The private renderer shares native construction/disposal with the existing DNA
comparison adapter. A separate closed preview v1 schema preserves scoped axis
samples; comparison v2 remains strict and unchanged. Native shaft mode selects
the existing curved display, while nucleotide placement stays native. Before
and candidate layers own their buffers/materials and palette identity. Teardown
restores visibility only on the same live renderer, preserves shared templates,
and cannot change a replacement document's scene. Seven memory-only Python-to-
JSON-to-Three.js checks compare real native matrices and axes, including grouped,
selected and single-helix twist cases. No molecular calculations, models,
constants, source pins or visual goldens were changed.

ISSUE-100 remains open until the existing popup/editor uses this complete flow.
ISSUE-105 records the newly identified group retargeting gap: current native
`edit_entry` preserves old affected helices when only cluster IDs change. The
private DTO keeps that capability false. Next finish the closed control validator,
use the historical prefix for every control and plane, correct authored group
membership with existing selectors, and connect the desktop lifecycle. Explicit
target membership stays protected. Actual interaction/latency and larger-design
qualification remain required; private tests are not a rollout certificate.
Assemblies, VR-machine validation and lower-priority assets stay deferred.

Final focused validation passed **350 backend tests (91 warnings, 14.58 s)**.
Full frontend passed **8,360 tests / one skipped across 721 files (342.59 s)**.
The [integration evidence](validation_deformation_preview_integration.json)
retains red cases, corrected fixtures, cross-language checks and limitations.
Apply now returns only its scalar receipt; the unused report traversal was
removed after caller audit. Extreme retained sweep coordinates produce a typed
limit refusal before integer conversion. Scoped Ruff and diff checks pass;
repository lint retains the same five F401 errors. Selector dry-run reports FAST
and accumulated FULL debt without executing a broad suite. `main.js` delta is
**0**. Completed disposable output contained no files: 544 empty directories and
four symlinks were removed after active-reference checks; historical evidence
was preserved. No bulk/browser output or shared-server mutation occurred.

## Ordinary organized patterns — U15, October 16

Linear/circular patterns now declare copied named groups separately from their
existing whole-helix placement inputs. One extraction provides exact ancestry;
instance identities remain stable through count edits. An owned ordinary host
uses the existing isolated source proof/rebuild and one guarded publication,
including recovery-independent historical edits. Complete current/straight
candidate geometry avoids unbound display fetches. Shared candidate decoding
replaces duplicate commit logic; still-used legacy editing remains available.

The [contract and remaining exits](group_placement_migration_plan.md#u15-ordinary-patterns--fh-18-checkpoint-13)
and [validation](validation_group_patterns.json) are authoritative. **18/38
milestones complete, 20 remaining (11 core, 9 parked); +0 completed, +0 total.**
U15 is engineering checkpoint 15 since B1 and checkpoint 13 on still-open FH-18;
task growth remains flagged. New-group movement, generated core consumers and
qualification retain their original exit. Public organization rollout stays off.
`main.js` delta is 0. No molecular algorithms, manifests or goldens changed.

Final software checks passed **362 distinct backend cases** (105 new, 257
related; 26 warnings) and **8,826 frontend tests / one existing skip across 745
files**. All 21 changed Python files pass scoped Ruff; repository lint retains
five existing F401 findings and memory lint retains six errors/59 warnings.
Selector dry-run executed zero tests and retains broad backend debt.
**NOT VERIFIED IN APP:** the required Archive mount is unavailable. Desktop,
complete HTTP/geometry latency and retention qualification remain open.
Cleanup removed 215 empty task directories and four symlinks (zero files/bytes);
shared caches, runtimes, workspace state and historical evidence were preserved.


## Complete ordinary extrusion history editor — U16, October 16

FH-21 is complete at its defined implementation boundary. Seven ordinary native
extrusion families expose their full saved inputs and regenerate eligible earlier
features through subsequent history, retaining feature identity without recovery
snapshots. Source-frame/cell edits rebind continuation dependencies to the proved
prefix; missing sources and broken downstream references fail atomically.

The [contract](extrusion_history_editor_plan.md) and
[evidence](validation_extrusion_history_editor.json) record the finite scope.
Patterns and extrusion edits now share one isolated evaluation/publication host;
the frontend shares source-bound response adoption. Duplicate host/request logic
is pruned; still-used legacy recovery editors remain. Molecular builders, pinned
numerical manifests, schemas and constants are unchanged. `main.js` delta is 0.

**19/38 milestones complete; 19 remaining (10 core, 9 parked).** This update is
**+1 completed, +0 total**, engineering checkpoint 16 since B1. Two milestones
have closed since B1; FH-18 remains open and growth-flagged after 13 checkpoints.
The movement/generated audit earns no completion credit and changes no exit.
Next is the existing finite FH-22 Sweep history editor.

Final checks: **401 distinct backend passes** across 17 files (81 warnings), and
**8,874 frontend passes / one existing skip** across 748 files. Changed-file Ruff
passes; repository lint retains five existing F401 findings, memory lint six
errors/59 warnings. Selector dry-run reports FAST with FULL deferred and executes
zero tests; broad backend debt remains. **NOT VERIFIED IN APP:** Archive is not
mounted, so browser/smoke/representative latency and memory acceptance remain
FH-27/MV-50. Organization rollout stays disabled; no performance improvement is
claimed from tiny native test timings.

Cleanup removed 64 disposable test files (86,029 bytes), 624 empty directories
and four symlinks after active-reference checks. No task output remains; shared
caches, runtimes, workspace designs/jobs and historical provenance are preserved.

## Complete owned Sweep history editor — U17, October 16

FH-22 is complete at its fixed implementation boundary: full ordinary native
Sweep controls, input-based isolated preview, recovery-independent Apply/Cancel
and downstream rebuild. See [the contract](sweep_history_editor_plan.md) and
[validation](validation_sweep_history_editor.json). The historical prefix supplies
source ends, cells and frames; the current display cannot leak later geometry
into those controls. Private native DNA display and path manipulators share the
existing preview lifecycle, bounded HTTP transport and guarded publication host.

Apply proves the full source and rebuilds later recorded inputs, retaining exact
feature identities and one undo. A later nick keeps its recorded address; missing
helices identify the failing feature and refuse publication without discarding
the draft. This differs explicitly from still-used legacy snapshot rebasing.
The shared host also checks its final deadline after document preservation.
Private picker callbacks cannot author through hidden legacy controls, and old
cleanup cannot hide a newer view. Native numerical algorithms remain unchanged.

**20/38 milestones complete; 18 remaining (9 core, 9 parked).** Delta **+1 completed,
+0 total**. Seventeen engineering checkpoints since B1 close three milestones;
FH-18 remains growth-flagged after thirteen, with movement/generated/qualification
exits unchanged. Next is the finite FH-23 move/rotate matrix, then Fine Routing.

Final checks: **554 distinct backend passes** across 24 files (122 warnings) and
**8,918 frontend passes/one existing skip** across 753 files (323.55s). Actual
Python display packets pass the JavaScript validator. Seventeen changed Python
files pass Ruff; repository lint retains five existing F401 findings and
memory lint retains six errors/59 warnings (current project 199 lines). The
selector dry-run reports FAST/FULL deferred and executes zero tests; broad backend
debt remains. Two partial frontend runs were intentionally stopped for concrete
ownership corrections and receive no pass credit. `main.js` delta 0; numerical
manifests/goldens unchanged.

**NOT VERIFIED IN APP:** Archive is unavailable; desktop/latency remains
FH-27/MV-51. Both Sweep rollout gates stay false. Cleanup removed 194 empty task
directories and 4 symlinks, zero files/bytes; exact paths are verified absent.
Shared caches, active runtimes, workspace state and historical evidence remain.

## U18 — native movement history primitives, FH-23 remains open

The [full move/rotate audit and four batches](transform_history_editor_plan.md)
retain placements, selected nucleotide moves, batches, resets, constraints,
complete display and FH-18's required new-group movement integration. No exit
was narrowed to make this first checkpoint complete the milestone.

The four existing history roles now share strict input validation and owned
prefix binding. The existing native history API uses that helper, independently
proves the source and rebuilds downstream inputs with atomic undo/reload. Typed
failures identify missing/ambiguous dependencies and the failing feature. Reset
target metadata follows the exact selected prefix transform; contradictory
explicit receipts refuse. Extra-base crossover targets are editable references,
while genuine output IDs retain their existing protection. Native math is unchanged.

Private feature-stage evaluation shares the bounded prefix executor. Inserted
sites are charged before native allocation; evaluated objects cannot mutate the
retained source. Full proof is not performed during selected-operation evaluation.
Successful native replay uses one occupancy check per requested target; the exact
missing-target failure triggers diagnostic enrichment. No new transform route,
lease, DTO or frontend owner exists yet. Organization nucleotide admission and
complete CPD/joint/duplex/tether coverage remain explicit work, with arbitrary
group movement still behind its scientific authorization boundary.

**20/38 complete;18 remaining (9 core,9 parked);+0 completed,+0 total.** Eighteen
engineering checkpoints since B1 close three milestones. FH-23 has spent one;
FH-18 remains growth-flagged after thirteen. Next: complete owned movement
display/control data and lifecycle, followed by controls and Fine Routing.

[Validation evidence](validation_transform_history_primitives.json): **649 distinct
focused backend passes**,97 warnings,25 files. This includes actual native history
edits, one undo/reload/cold proof, exact refused-source preservation, shared
preview/permit regressions and a four-worker Sweep check. The actual standard
`just test-smart` selected **FAST** but executed zero tests: collection failed on
missing Archive-backed CPD data and a prior Sweep test's randomized import-time
UUID. The latter is fixed; the unavailable fixture and **FULL deferred** debt remain.
The complete selector message is retained in evidence, with no full-suite pass claim.

All13 changed Python files pass Ruff; repository lint retains five existing F401
findings and memory lint six errors/59 warnings. `main.js` delta0; no frontend
behavior or numerical pins/goldens changed. No app, bulk capture or simulation
started without Archive. Cleanup verified513 empty task directories and4 symlinks
removed,0 files/bytes; active runtimes, user workspace and historical data preserved.
ISSUE-123/124 record the input/receipt and test-collection corrections. Still-used
legacy UI paths remain until their complete replacement is qualified.

## U19 — owned movement host and native display data, FH-23 remains open

Four movement roles now share the existing session catalog, work slot, source
guards, Apply proof and atomic publication lifecycle. A closed family-work module
replaces repeated deformation/Sweep branches. Transform packets identify their
stable feature and command kind; batch/reset operations have no invented single
deformation identity. Legacy wire shape and post-evaluation lease timing remain.

The versioned transform component preserves complete admitted native Full records
and axes, including slabless extensions and explicit extra-base/CPD/flexible/linker
companion requirements. Native controls carry joint axes, pivot choices, tethers,
movable links and exact source inputs with frame provenance. Repeated helper
traversals are charged before work; graph/byte/time limits remain provisional
admission, not measured interaction latency. Wire/admission modules live in API,
without new core-to-API dependencies or changes to comparison schemas.

Historical joint/flexible commands now replay in the bounded prefix. All three
nucleotide roles qualify existing conserved-material organization lineage,
retaining native builder/reconcile/retry order. Tests prove preview limit25 versus
latest limit90, downstream reconstruction, one undo, normal reload and cold proof.
Compatible DS linkers project through unchanged native helpers; the existing
mixed-end duplicate-occupancy output refuses as a whole (ISSUE-126). Scientific
polarity/formulas and numerical source pins/goldens are unchanged.

**20/38 complete;18 remaining (9 core,9 parked);+0 completed,+0 total.** Nineteen
engineering checkpoints since B1 close three milestones. FH-23 remains open after
two; FH-18 stays growth-flagged after thirteen. Full private renderer/controls,
explicit complete linked-owner pose recording (ISSUE-125), remaining producer
prefix contracts and arbitrary new-group motion keep their original exits.
Projected owned-model coverage does not imply input-only historical replay for
extensions/CPD/duplex/linker producers. Transform rollout remains disabled.

[Checkpoint evidence](validation_transform_history_host.json) records **656 distinct
focused backend passes**,25 warnings across26 files. The actual standard FAST run
has **17,489 passes,27 failures,9 errors,21 skips** (250.37s); FULL remains deferred.
Four stale expectations now pass with exact dependency/source/undo checks. The
remaining23 failure nodes and4 CPD preview errors have historical reproduction;
current exact causes are not all proven. Four Archive collection errors remain.
One repair-job setup error did not reproduce in its8-case focused file and remains
unresolved. No subsequent broad-pass claim is made.

Timing triage found zero individual5s violators; aggregate work was888.6 test-seconds
across4 workers. The260s guard overrun does not justify arbitrary slow marking,
threshold changes or an interactive latency claim. No frontend/app exercise or
machine-specific VR validation; Archive remains unavailable. `main.js` delta0.
Cleanup verified63 empty task directories and4 symlinks removed,0 files/bytes;
user workspace, runtimes, caches and historical evidence were preserved. The
shared-host branch cleanup is complete; used legacy UI paths remain until their
full replacement is qualified.

## U20 — connected private movement editor, FH-23 remains open

The owned history editor now connects the existing Move/Rotate panel, native
placement and nucleotide gestures, complete private native rendering and the
shared preview/publication controller. Five roles retain exact historical inputs,
feature identity and source authority. Numeric controls, group deltas, joint and
tether context, pivots, Reset, Apply/Cancel and comparison transitions have one
private owner. Controls suspend when a full accepted geometry pane is unavailable.
Confirmed publication survives a conflicting late transport response; a failed
Apply retains the draft without applying group movement twice.

An explicit upgrade from an old single-owner pose adds a versioned
`placement-poses` definition containing every accepted selected/auxiliary owner
pose, exact parent/driver frame and authoring provenance. Fixed-owner motion
refuses. Upgrade retains the feature ID and inherited primary metadata; normal
edits cannot retarget that primary anchor. Replay applies accepted absolute poses
through unchanged native placement behavior without rerunning a constraint solver.
Apply independently proves the source and rebuilds the suffix with one undo.

The validator bounds native records, repeated axis work and companion allocation
before rendering. Real Python packets exercise the actual JavaScript validator
and native Three.js rendering, including extra bases, CPD, flexible arcs and
compatible linkers. Pane resources and shared gizmo layers have explicit cleanup;
unused new preview-gizmo plumbing is pruned. Used legacy UI remains until the
replacement qualifies. `main.js` adds only one lazy getter, reaching7350 lines.

The schema changes by one operation-kind literal. Captured before manifests and
the previous17-edge policy support20 exact direct compatibility edges for the
three native engines. Independent same-kernel worker checks pass; stored pins,
runtime/template checks, molecular calculations and geometry goldens are unchanged.
This establishes engineering schema compatibility, not historical-binary parity.

**20/38 complete;18 remaining (9 core,9 parked);+0 completed,+0 total.** Twenty
engineering checkpoints since B1 close three milestones. FH-23 remains open after
three and is now task-growth flagged; FH-18 remains flagged after thirteen.
Containment retains the existing historical-prefix/actual-constraint matrix and
the separate shared arbitrary-group movement matrix, without another solver,
registry, milestone or reduced exit. See the [fixed ledger](remaining_standard_part_checkpoints.md#u20-progress-and-mandatory-containment-review)
and [movement contract](transform_history_editor_plan.md).

[Validation evidence](validation_transform_history_integration.json) records
**466 distinct focused backend passes** across13 files, including24 real
Python→JavaScript/native-render cases and3 native compatibility cases. Required
`just test-smart` selected **FAST**: **17,582 passed,23 failed,8 errors,21 skipped**
(249.45s); **FULL deferred**. The23 failure nodes match retained VR, photoproduct
and junction-balance debt. Four Archive collection errors and four CPD preview
stereochemistry errors remain; the prior repair-job setup error did not recur.
There is no broad-backend green claim. Timing triage found zero individual5s
violators; summed882.8s work over4 workers explains an aggregate floor above90s.
The260s guard warning does not justify changing thresholds or marking arbitrary
tests slow, and does not measure interactive latency.

The full frontend run passes **9,088 tests with one existing skip across760
files** (330.01s). All18 changed Python files pass Ruff and all32 changed JavaScript
files pass syntax checks. Repository lint retains five existing F401 findings;
memory lint retains six errors/59 warnings, with the current project head200 lines.
The ledger check confirms38 unique milestones:20 complete,9 core remaining,9 parked.
The final diff check is clean.

**NOT VERIFIED IN APP:** Archive is unavailable; both transform rollout gates
stay false. Desktop/latency qualification remains FH-27/MV-52 and VR remains
deferred by the user. The standard backend suite unexpectedly retained system-temp
scratch, including a sparse2GiB boundary fixture. Cleanup verified12,263 regular
files (2,432,869,457 logical bytes;322,805,760 allocated bytes),26,508 directories,
2,531 symlinks and2 test-special nodes removed after reader/dependency checks.
Future broad pytest runs require mounted Archive temp from the start. User
workspace, managed jobs, runtimes, shared caches and historical evidence remain.

## U21 — native movement producers, constraints and terminal history

Actual empty-root histories now exercise flexible tethers, historical joint
limits, movable duplex links, compatible SS/DS linkers and child-driver root/taut
pivots. Real native renderer/gizmo output crosses back into the owned backend
lease: Evaluate, Apply, downstream replay, one undo, save/reload and independent
cold proof. These tests verify adapter/authoring parity, not physical validity.
They exposed and corrected joint interim/final pose and arriving-response baseline
races, plus rigid-only junction completeness and duplicate flexible chords in the
private renderer. Existing native helpers supply the poses/arcs; scientific
coordinates, constraints, constants and molecular kernels are unchanged.

Shared prefix admission now bounds ordinary OH/connection/linker/duplex producers
before native allocation, including insertion-copy work, future spans and saved
restoration inputs. Existing1024-site/16-helix/64-operation/span/time limits stay.
Terminal extension CRUD/batch previously bypassed feature history; closed upsert
and delete commands now retain authored identities, typed failures and cold replay.
The route refactor removes duplicated mutation code. Valid repeated termini keep
last-item-wins, every supplied item validates first, and explicit clearing retains
its contract. Delete keeps synthetic-only geometry and skips reconciliation/retry;
upsert retains global postprocessing and therefore a conservative dependency barrier.
New model schema is exactly two literals, with23 exact direct compatibility edges
and captured prior policy/manifests. Stored pins, runtime/template checks and
numerical outputs remain unchanged in independent same-kernel worker controls.

This is **FH-23 checkpoint4**, not milestone completion. **20/38 complete,
18 remaining (9 core,9 parked);+0 completed,+0 total.** Twenty-one engineering
checkpoints since B1 close three milestones. Both FH-23 and FH-18 remain growth
flagged. Long numerical producer Prepare AND Apply need existing owned-worker
integration; arbitrary new-group movement and post-conversion extension-upsert
lineage/placement remain original shared exits. Earlier terminal history UI and
repair selectors stay in existing FH-24/FH-26. No split earns new completed credit.
See the [fixed ledger](remaining_standard_part_checkpoints.md#u21-containment-and-remaining-acceptance)
and [finite next batch](transform_history_editor_plan.md#u21-native-prefix-and-constraint-acceptance).

[Validation evidence](validation_transform_native_prefix_constraints.json)
records **767 distinct focused backend cases across25 files**, including9 real
native gesture/Apply cases,24 existing Python→native-render cases and3 numerical
schema worker cases. Shared transactions, recipe editing, exact source ownership,
HTTP receipts and deformation preview regressions contribute650 passing cases.
The new prospective inserted-work controls were observed failing before the fix;
all32 producer admission cases pass. Renderer/gesture focused coverage passes40
cases, including missing-companion and unrelated-junction negative controls.
The final full frontend run passes **9,108 tests with one existing skip across760
files** (328.45s); the repeat follows the observed real-source renderer fixes.

**NOT VERIFIED IN APP:** Archive is still absent. No browser/bulk scratch fallback
was used; transform and organization rollout gates remain false. The required
backend selector dry-run selects **FAST** and declares **FULL deferred**; it runs
no suite. Broad FAST is also deferred here because its prior system-temp scratch
must be moved to mounted Archive from the first byte on a future run. Retained
U20 broad failures and FULL debt are not cleared by focused passes. Desktop,
HTTP/render/lock/memory performance remain FH-27/MV-52; machine-specific VR stays
deferred by the user. No observed time/heap regression claim follows from budgets.

Changed Python and JavaScript checks pass; repository lint retains five existing
F401 findings and memory lint retains six errors/59 warnings. The current memory
head stays200 lines; the ledger independently counts38 unique milestones.
`main.js` stays7350 lines (delta0). After reader/dependency checks, current pytest
scratch was removed:26 policy files,223,850 logical/303,104 allocated bytes,
803 directories and16 symlinks; the pytest output root is empty. Native workers
asserted process/shared-memory cleanup and Node gesture harnesses closed their
private scenes/browser resources without network, broadcast or file output.
User designs/jobs, runtimes, shared caches and historical evidence remain intact.

## U22 — private numerical movement workers and cleanup ownership

**20/38 complete;18 remaining (9 core,9 parked);+0 completed,+0 total.**
U1–U22 are22 engineering checkpoints closing three milestones since B1. FH-23
remains task-growth flagged after five checkpoints; FH-18 remains open after13.
No milestone exit, priority or denominator changes. See the
[fixed delivery map](remaining_standard_part_checkpoints.md#u22-containment-and-remaining-acceptance).

The closed private worker pair reconstructs transform prefixes with native CPD
create/relax or duplex-relax and independently proves/rebuilds the entire edited
recipe on Apply. Both use the existing bounded shared-memory transport and native
thread policy. Original capture, selected definition and explicit draft bind
results; prepared inputs are cheaply rebound on the decoded prefix. Shared
occurrence-based admission bounds serialization before hashes/dumps/decoding,
including expanded aliases. Native builders, engine pins and numerical manifests
remain unchanged. Typed failures preserve the relevant feature and input path.

Actual empty-root producers, poisoned recovery, repeated selected-only evaluation,
edited suffix, save/reload and independent cold proof pass. New live host/gesture
publication and undo qualification are not claimed. The first CPD measurement was
about47s Prepare/46s Apply; the final serialization-guard run measured42.19s/42.56s.
Duplex measured roughly1.2–1.4s and selected-only evaluations roughly1ms. These are
small worker probes, not end-to-end responsiveness or physical qualification.

Consequently the worker is not wired into the existing short-lived lease yet.
The [researched lifecycle decision](transform_history_editor_plan.md#u22-numerical-worker-boundary-and-researched-lifecycle-decision)
requires separate bounded computation, fresh ready editing, and published receipt
recovery inside the same catalog, with visible cancellation and exact source
guards. Ordinary1s/5s limits remain unchanged. No new job registry is planned.

ISSUE-132 removes the shared supervisor's obsolete three-retry escape after child
death. Admission remains held until buffers also close/unlink; a persistent OS
cleanup failure stays visibly stopping. Tests cover repeated failures and actual
shared-memory cleanup, replacing the prior premature-release expectation.

[Validation evidence](validation_transform_numerical_workers.json) records446
distinct focused backend cases across18 files:442 in the shared regression run,
two additional native negative controls and two slow numerical chains. Later
targeted reruns validate diagnostic feature attribution and actual numerical
transport. Red failures, corrected fixture assumptions and overlap are explicit.
No frontend code changes; `main.js` remains7350 lines (delta0). The required selector
dry-run selects FAST and declares FULL deferred but executes no suite. Broad FAST
also awaits mounted Archive scratch; prior broad debt remains. NOT VERIFIED IN APP:
Archive is unavailable, all rollout gates remain false, and MV-52/FH-27 desktop,
HTTP/render/lock/heap qualification remains open. Assemblies and VR stay deferred.
