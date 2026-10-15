# P4 topology imports and capture admission

Read-only audit, October 15, 2026. No importer, scientific algorithm, molecular
constant, geometry lock, fixture or user design changed during this audit.
Runtime measurements below are proposed unless explicitly identified as existing
evidence. Assemblies remain deferred.

## Recommended order and current contracts

1. **Single-chain aptamer import.**
   `backend/api/routes_design_interchange.py:481` appends `aptamer-import` but
   records only template ID/name. `backend/core/aptamer.py:58` parses first-model
   DNA into editable strand topology and source-derived native residue sites.
   `template_content` reads mutable `backend/data/aptamers/{template_id}.pdb`.
   The importer allocates a random `apt_...` helix ID, Strand ID and cluster ID.
   Existing route behavior imports privately, then merges helices, strands and
   clusters through feature recording. Its no-document path first installs a
   rootless empty Design; native admission must instead preserve explicit
   new-empty provenance and avoid leaving a partial initialized session on
   failure. Existing non-native designs must not acquire an invented empty root.
2. **caDNAno.** `backend/api/crud.py:1831` replaces the active document after
   `backend/core/cadnano.py:374`, `_recenter_design`, `autodetect_all_overhangs`,
   `_autodetect_clusters` and `require_import_integrity`. Helix IDs encode grid
   coordinates and strand IDs encode source starts. Cross-helix junctions use
   the optional `routing_identity.identity_scope`; same-helix ligations in
   `backend/core/conversion_integrity.py:190` still allocate model-default IDs.
   Cluster detection allocates additional IDs. Preserve the complete existing
   pipeline in a shared pure adapter, including normalization and diagnostics.
3. **scadnano.** `backend/api/crud.py:2055` calls
   `backend/core/scadnano.py:153`, detects overhangs, backfills their sequences,
   recenters and detects clusters before replacement. Helix IDs use source
   indices; strand IDs use source strand order. Extensions, explicit loopout
   ligations and clusters still allocate random IDs. Existing strict source
   validation rejects unsupported transforms/groups, asymmetric modifications
   and circular non-scaffold backbones. Warning branches inside the importer
   are not permission to weaken those source checks.
4. **DNA PDB.** `backend/api/routes_design_interchange.py:34,116` replaces or
   merges imported DNA, then installs a separate atomistic display result.
   `backend/core/pdb_to_design.py:535,797` allocates a random helix namespace,
   strands and cluster. `_detect_wc_pairs` includes a greedy fallback;
   `_analyze_duplex_pdb` uses NumPy SVD. Existing warnings explicitly describe
   skipped unpaired residues and unusable duplexes. This requires a declared
   loss policy, a numerical reproducibility decision, and source provenance for
   the separate display result. It is not the smallest next contract.

## Smallest independent aptamer contract

Add a pure `part_aptamer_commands.py` adapter using the existing `aptamer-import`
kind. Record strict `_proof_version`, `aptamer_version`, `importer_version`,
`source` descriptor, exact `name` and `source_label`, `_helix_id`, `_strand_id`
and `history_seed`. The source descriptor identifies admitted immutable PDB
bytes by SHA-256 and length; template name, path and URL are provenance only.
Read a bundled template once at admission and retain its exact bytes. Replay
must not consult the catalog, filesystem or network.

For the first contract require exactly one imported helix, strand and cluster.
Call `import_aptamer` unchanged and replace only those identities and explicit
references. Derive cluster identity from `history_seed`. Check output identity
collisions and preserve unrelated design fields. The existing generic identity
protection already covers `_helix_id`, `_strand_id` and `history_seed`.

Preserve first-model selection, blank/A alternate-location policy, TER/segment
and insertion-code handling, backbone-continuity checks and RNA rejection.
Native residue coordinates, source residue addresses, sequences, metadata and
placeholder helix axes must equal the existing importer output exactly after
identity normalization. No pairing, polarity, placement, relaxation or
scientific algorithm is added or changed. Broader multi-chain identity mapping
is a subsequent versioned contract; existing legacy import remains available
without a new native reproducibility claim.

All imported shapes remain `reproduced_import`, even when the recipe starts
empty. Downstream supported native features remain independently editable.
Source hashing establishes immutable evidence, not native construction or
trustworthiness of the file's author. P6 must not let scripts obtain a
native-only certificate by wrapping arbitrary coordinates in an import.

## Measured file evidence and proposed admission

Read-only lexical inspection of bundled sources found:

| Template | Raw bytes | First-model ATOM/HETATM records | DNA residues | Logical chains | Base64 string charge under current capture |
|---|---:|---:|---:|---:|---:|
| 148D | 60,680 | 488 | 15 | 1 | 323,632 bytes |
| 1C35 | 125,793 | 506 | 15 | 1 | 670,896 bytes |
| 2HY9 | 88,868 | 843 | 26 | 1 | 473,968 bytes |

These are source counts, not parser, capture or worker performance measurements.
A provisional 150 KB source / 1,000 first-model atom-record ceiling covers all
three templates. Finalize admission only after measuring complete output and
capture costs. Bound text/record work before allocating parsed molecular data.

The existing `input_capture_benchmark_p4.json`, generated by
`scripts/benchmark_part_inputs.py`, measures a 241-byte, three-atom PDB repeated
across 1/32/128 independent asset features. Its capture medians are approximately
1.07/3.97/14.06 ms and maxima 2.26/5.15/19.78 ms. This is useful scaling evidence
but does not establish that a 250 KB / 1,000-atom protein or an aptamer fits the
25 ms capture budget.

## Independent bottlenecks

| Boundary | Current limit / implementation |
|---|---|
| Source table | 50,000,000 decoded bytes per descriptor; approximately 66.7 MB cumulative base64; 256 records, `core/part_input_sources.py` |
| Lock-held capture | 30,000 nodes, 2,000,000 charged bytes, 25 ms cooperative allowance, `core/part_verification_capture.py` |
| Worker input | 2,000,000-byte internal pickle, `api/part_verification_worker.py` |
| Operation parameters | 256,000 charged bytes, 10,000 nodes, depth 64, `core/part_operation_input.py` |
| Evaluation candidate | 16,000,000 bytes, `api/part_evaluation_worker.py` |
| Rebuilt recovery | 8,000,000 cumulative encoded bytes, including discarded attempts, `api/part_recovery_budget.py` |

Capture charges strings at four bytes per character. An embedded base64 source
therefore consumes approximately 5.33 times its raw byte length before parsed
authoring output. The new 256 MiB document transport ceiling is intentionally
independent and does not increase any proof or capture budget.

Example caDNAno files are 7,780 bytes (`Honeycomb_6hb_test1.json`), 87,248 bytes
(`6hb_cadnano_native_test1.json`), 336,838 bytes
(`18hb_symm_p7249_21_even_spacing_sequential_coloring.json`) and 2,034,577 bytes
(`Ultimate Polymer Hinge 191016.json`). The 336,838-byte source alone would
consume about 1.8 MB of capture allowance. The scadnano
`Examples/cadnano/Voltron_Core_Arm.sc` is 183,136 bytes. File metadata was read;
these examples were not imported, edited or benchmarked during this audit.

## Measurement and regression completion gates

1. Measure each bundled aptamer, repeated imports sharing one source, and
   near-limit synthetic inputs with the existing budgets. Report capture
   median/max and refusals, parsed node count, actual pickle size, fresh-worker
   proof status, recovery payload sizes, candidate bytes and publication cost.
   Keep fixtures in memory; serialize validation through the parent agent.
2. Compare all authored output against the unchanged importer after identity
   normalization. Run existing `tests/test_aptamer_import.py`,
   `tests/test_aptamer_connections.py` and `tests/test_aptamer_history.py` as
   appropriate, plus cold replay with poisoned saved outputs, changed/absent
   template files, stable IDs, source corruption, downstream missing references,
   source edits and atomic rejection. No scientific simulations are required.
3. Repeat admission measurements using small/medium caDNAno examples before
   choosing its source and topology-work bounds. scadnano bounds must count
   domain spans, insertions, loopouts and extensions before string/range
   expansion; byte limits alone do not bound a tiny JSON's declared work.
4. Admit larger sources only after an independent immutable-resource/capture
   design is demonstrated. Dedicated source transport alone does not remove
   parsed geometry from capture, equality comparison or recovery encoding.
   Complete revision-scoped fingerprints require an immutable representation
   and all authored fields, including bonds, serials, metadata and site choices.
   Do not omit atom arrays, trust a partial asset fingerprint or raise global
   deadlines to claim support.

## Existing numerical pins and CAD precedent

Both `core/part_cpd_contract.py` and `core/part_duplex_relax_contract.py` hash
`core/aptamer.py` in their implementation manifests. Duplex relaxation also
hashes `core/feature_identity.py`; both include `core/models.py`. Even an
identity-only change to those files invalidates older numerical pins. The
single-chain adapter can avoid those edits: the snapshot kind already exists
and the generic protected identity fields suffice. If later work changes
manifest-covered code, retain the old pin and report incompatibility; never
silently refresh an authored recipe's engine hash. Perform consequential changes
after a reversible checkpoint and rerun the relevant numerical regressions.

Onshape exposes an explicit Import feature with editable import settings and
an explicit source-update operation. Downstream features are reapplied where
possible and remain visibly broken when the replacement source invalidates
them. Imported geometry does not gain the source system's parametric history.
This supports NADOC's separate imported provenance and downstream native-edit
claims. [Onshape: Working with Imported CAD](https://cad.onshape.com/help/Content/Document/working_with_imported_cad.htm)
