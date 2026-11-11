# Durable census ledgers

Research sidecars preserve the legacy registry, map, IDs, scores and source evidence.
They do not certify complete molecular designs or change production behavior.

- `publication_reviews.jsonl`: all known publication/version records, including raw
  bibliographic hits. Canonical work keys are provisional until reconciled.
- `design_evidence.jsonl`: stable legacy design IDs plus newer source extraction.
- `discovery_runs.jsonl`: exact queries, cursors, totals, failures and route scope.
- `discovery_edges.jsonl`: citations, conference leads, reuse and bibliography links.
- `batches.jsonl`: saved input queues, outcomes, audits and next actions.
- `reviewed_records.csv` and `counts.json`: generated readable projections.

A `design_sources_reviewed` stage means the cited source sections were inspected;
consult outstanding questions before interpreting completeness or eligibility.
Conference schedule records remain uncertain leads. A downloaded document, text
match, sequence count or query hit is never an automatic inclusion. No keyword-based
final exclusions are implemented. The legacy structure map is intentionally retained;
`catalog_sync` marks newer sidecar decisions requiring integration, notably S041.

Run from the repository root:

```sh
python3 experiments/origami_publication_catalog/research/ledger.py init
python3 experiments/origami_publication_catalog/research/ledger.py select
python3 experiments/origami_publication_catalog/research/ledger.py validate
python3 experiments/origami_publication_catalog/research/export_reviews.py
python3 experiments/origami_publication_catalog/research/checkpoint.py
```

`init` only adds absent legacy keys and preserves saved reviews. `select` resumes
an active batch. Starting with B0003, batches reserve slots for low-signal and broad
records across year/publisher buckets. A batch is a checkpoint, not completion.
Only one writer should operate on these ledgers at a time. Writes atomically replace
a complete JSONL file; upserts preserve superseded rows and revision reasons.
JSONL delimiters are literal LF; Unicode separators inside titles must not be split.

Explicit manual decision recipes are in `review_batch_0001.py`,
`review_batch_0002.py`, `review_batch_0003.py`,
`review_batch_0003_rotation.py`, the `review_batch_0004*` scripts, and `review_fnano2019.py` / `review_fnano2018.py`. Evidence extraction scripts do not
make those decisions. `index_sources.py` retains parser diagnostics separately.
`review_lally_voigt_sources.py` records selected thesis/SI sections and two new
research-only design groups. `reconcile_forward_local.py` matches explicit PMID/DOI
pairs without title-based merging; the remaining targets stay pending.
`review_fnano_counterparts.py` and `record_shaw_correction.py` retain tentative
conference-to-journal links and a publisher-confirmed correction without merging
presentation identities.
Source assets and raw API pages live under ignored `assets/`, with SHA-256 manifests.
Follow `../RESEARCH_SETUP.md` when moving machines; committed records do not prove
local source availability.

`discover_crossref.py` fully pages individual `origami` and `scaffolded` queries for
2006–2019. These are documented alternatives to the much broader multiword results,
not a claim to have exhausted their generic DNA tails. No relevance cap is imposed.
The downloader resumes immutable pages; saved records deduplicate replayed pages.
Expired cursors remain explicit failures requiring a new identified run. Original
query and raw-page evidence remain intact. Full citation, author and conference
closure remains unfinished.

Focused checks:

```sh
python3 experiments/origami_publication_catalog/research/test_ledger.py
python3 experiments/origami_publication_catalog/research/test_discover_crossref.py
python3 experiments/origami_publication_catalog/expansion/test_restore_acs_assets.py
```

See `../RESEARCH_CHECKPOINT.md` for actual progress and the active queue. Do not
rerun legacy map builders or overwrite newer review decisions to regenerate these
sidecars. No commit, push, author contact or remote publication is authorized.
