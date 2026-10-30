# Round-2 placement incident review — acknowledged

The four native endpoint incidents from `20261023T052656` are reproducible consequences of test-fixture document-context leakage. The four original incidents have now been explicitly acknowledged with named automated review records; original reports remain intact.

## Cause and scope

`tests/test_part_evaluation_comparison.py::ready` selected a fresh `__comparison__...` document before preparing a private repair job. Its `try/finally` cleanup began only at `yield`, after `jobs.start`. In the FAST run, capture admission raised HTTP 413 (capture budget exceeded) during fixture setup for `test_part_comparison_routes.py::test_http_context_conflicts_preserve_current_state_and_private_candidate[draft]`. Pytest never reached the fixture's cleanup, leaving its document selected in that worker.

Direct calls such as `state.set_design` then wrote to the leaked document. `DocContextMiddleware` correctly selected `__default__` for HTTP requests without a document header. The two sides of subsequent endpoint assertions therefore operated on different designs. The result was missing helix/overhang HTTP 404s or comparing a newly populated lattice helix with geometry from another document. This does not show a numerical placement discrepancy within the same document.

[Original-fixture reproduction](round2_fixture_leak_reproduction.json) forces the same admission exception and verifies both leaked context and leaked session. [Endpoint reproduction](round2_endpoint_context_reproduction.json) independently reproduces **all four** incident assertion failures under that leak, then passes each with aligned context. Original fixture code is loaded from Git into the diagnostic process; no checkout files are replaced. The diagnostic does not acknowledge or redirect the incident ledger.

The faulty lifetime is in a pytest fixture, including importing test modules that reuse it. Production document middleware and placement producers are unchanged. Runtime and frontend test failures after the incident are the intended fail-closed effect of the shared review latch, not additional coordinate evidence. The original broad suite's other failures are not all resolved by this finding.

## Fix and verification

The fixture now registers a pytest finalizer immediately after binding context. It removes any created job/session and restores the context even if setup raises before `yield`. Job identity starts as `None`, so cleanup also handles failure before job admission. No capture budget, test budget, placement constant, geometry oracle or production fallback was changed.

- New forced-admission-failure regression: **1 passed**; [log](round2_fixture_cleanup_tests.txt).
- Comparison owner tests: **31 passed**; [log](round2_review_part_evaluation_comparison.txt).
- Comparison HTTP tests: **13 passed**; [log](round2_review_part_comparison_routes.txt).
- All native endpoint assertions: **5 passed**, covering demo/full/per-helix, empty/populated lattice, and unposed/posed overhang frame authority; [log](round2_review_native_placement_endpoints.txt). The command still returned **exit 1** because the incident latch remains open.
- Round-2 metadata controls previously matched full JSON bytes in 19 cases, with 57 geometry/compact/flexible tests passing. This supports unchanged output but does not substitute for completing the incident review.

## Completed scope and evidence

[Shared-frame image](round2_placement_shared_frame.png) was inspected: original/current backbone markers overlap for straight, bent, twisted, swept and partial designs, each with rigid transforms and insertion/deletion cases. [Per-site evidence](round2_placement_site_evidence.json) retains identity, expected/actual backbone/base/slab coordinates, axis/base vectors and slab quaternions for **808 sites**. All deltas are zero; JSON output, reload and per-helix partial selection match exactly. These are aligned-document controls; the failed cross-document HTTP comparisons have no meaningful physical displacement.

[Expanded focused checks](round2_review_scope_tests.json): **43 full-placement + 12 compact + 17 slab + 4 history + 21 VR assertions passed**. This covers moved/bent/twisted/scoped, full/compact/partial/reloaded records, undo/redo transient response authority, and serialized VR parity/failure checks. The fixture fix changes no production preview or rendering path; no physical headset acceptance is claimed. Native-marked commands initially returned exit 1 solely for the retained review latch.

Review JSON and exported acknowledgements are retained under `placement_review_20261023T052656-*.json` and `placement_acknowledgement_20261023T052656-*.json`, signed by name as **Codex (automated fixture-isolation review)**, not a human reviewer. Each references its immutable original report, reproduction, regression and shared-frame evidence. [Gate check](round2_placement_gate_check.txt) is clear. After acknowledgement, all **five endpoint assertions and the command passed**: [result](round2_endpoints_gate_clear.txt). No ledger redirection, deletion, oracle replacement or new molecular-placement authorization occurred.

The subsequent playback browser check reached rendering but has a separate pixel-hash discrepancy in one state. That mismatch was isolated to the duplicated-module harness condition; the independent historical-writer comparison with shared unchanged constructors subsequently passed 30 pixel states and picking. Both attempts are documented in rounds.md. The original broad-suite failures are not all cleared by this review.
