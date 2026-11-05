# DNA origami literature census checkpoint

Prepared November 4, 2026 for a new research session. The kickoff documents are
ready; the systematic review campaign and its proposed sidecar ledgers have not
been started by this documentation task. No persistent goal has been created here.

## Verified starting state

| Measure | Baseline | Evidence |
| --- | ---: | --- |
| Discovery records, including peripheral works and versions | 2,210 | `publication_registry.json` |
| Article full texts automatically searched | 672 | Registry `fulltext_status` |
| Publications with ACS PDF text indexed | 243 | `acs_source_index.json` |
| Publications with either of those scans, removing 27 overlaps | 888 | Union of registry keys and indexed ACS DOIs |
| Share of current discovery records automatically scanned | 40.2% | 888 / 2,210; not global literature coverage |
| Publications with mapped design groups | 68 | `structure_map.json` |
| Publications with accepted reviewed groups | 47 | `structure_map.json` |
| Reviewed groups / candidate groups | 75 / 25 | `structure_map.json`; not distinct architecture counts |
| ACS files / publications with downloaded files | 269 / 244 | `acs_expansion_summary.json` |

The article scan and ACS PDF index identify evidence leads; they are not complete
paper reviews. Recompute these figures at session start because other sessions
may update the shared catalog.

## Access and tooling

ACS public Figshare acquisition recovered all 145 previously failed lookups. The
selected 272-lead acquisition has zero outstanding lookup/download failures,
27 no-match results and 91 deferred media attachments. No-match is not proof that
supplements do not exist. Direct ACS journal pages may still present a browser
challenge. See [access resolution](acs_access_resolution.json).

Reuse `expansion/fetch_acs_repository.py`, `index_acs_sources.py`,
`integrate_acs.py`, and `validate_acs.py`. Explicit ACS review decisions live in
`expansion/acs_reviews.json`. The existing scripts are not a complete classifier.
Review their input/output behavior before running them; older builders must not
overwrite newer decisions. Some historical acquisition inputs may be unavailable.

Bulk assets use a machine-local `assets` directory or symlink. Follow
[machine setup](RESEARCH_SETUP.md) and verify local files before relying on saved
download statuses. Check the selected filesystem's free space before downloads;
do not silently redirect a missing external mount to the system disk. Windows
Cisco VPN was connected in the prior session; its current state is not guaranteed.
No credentials are stored in these documents.

## Known unfinished work

- Crossref searches were relevance-capped at 1,000 results per query.
- Citation discovery ran one limited backward pass; systematic forward/recursive
  coverage is unfinished.
- FNANO programs and author/laboratory publication histories have not been
  systematically searched.
- Newly acquired ACS PDFs need substantive design review. Other publishers retain
  unresolved access and supplement-discovery gaps.
- Existing broad status labels are not equivalent to the protocol's review stages.
  Preserve them as legacy decisions until evidence supports a more precise state.
- Catalog eligibility excludes some DNA-origami literature. Preserve those papers
  in the broad census rather than silently widening accepted structure scope.

## First session queue

1. Verify current files and counts, then create or continue the persistent goal.
2. Implement the minimal research ledgers and resumable batch selection from
   [the protocol](RESEARCH_PROTOCOL.md). Import existing evidence without claiming
   new review. Preserve legacy labels and decision provenance.
3. Complete a first 25-paper screening batch from named candidates and acquired ACS
   sources; extract designs for supported cases and audit exclusions.
4. Save the batch and continue. Start a recorded FNANO year inventory and repair
   capped discovery while rotating through the remaining screening backlog.

## Required handoff after each batch

Replace this starting queue with actual next keys and actions. Record the last
completed batch ID, ledger paths, counts before/after, new eligible works and
designs, sources inspected, exclusions rechecked, validation actually performed,
and access blockers. List interrupted work and resumable cursors explicitly.
Retain prior batch history in `research/batches.jsonl`; do not overwrite it with
prose summaries. Never report proposed work as completed.
