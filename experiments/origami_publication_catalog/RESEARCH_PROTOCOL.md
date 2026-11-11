# DNA origami literature census protocol

Build a traceable census of publications and designs before January 1, 2020.
The deliverables are a screened literature registry, a reconciled design catalog,
source-file evidence, and an explicit account of remaining gaps. This protocol
directs future research; it does not certify the existing backlog as reviewed.

## Discovery priority — user clarification, November 5, 2026

Prioritize publication histories and citation/source review for Carlos Castro,
Hendrik Dietz, Shawn Douglas, William Shih, Hao Yan, Peng Yin, Andrew Turberfield,
Mark Bathe, Tim Liedl, Lulu Qian, Friedrich Simmel, Philip Tinnefeld, Jonathan
Doye, Thomas LaBean, and Paul Rothemund. These are priority seeds, not a scope cap.
FNANO programs are supplementary leads only after other search methods demonstrate
diminishing returns. Defer further FNANO enumeration and preserve acquired evidence
and unfinished queues. Do not infer diminishing returns from a single empty search;
record routes, reviewed yields and remaining coverage before returning to FNANO.

## Scope and units

### Rapid source triage — user clarification, November 5, 2026

Exclude patents from the active census and design-processing queue regardless of
sequence availability. Preserve prior evidence and IDs with an explicit user-scope
exclusion; do not mislabel their molecular relevance or remove linked journal work.

This is the mandatory FIRST screening step, before article/design deep review,
variant reconstruction, citation expansion for that record, or source-completeness
audits. Screen readily available sources for a staple table/list containing at
least 100 DNA sequence entries. Qualifying lists proceed; absent/smaller lists
leave the active processing queue. If a qualifying table cannot be found, record
`no_qualifying_table_found` with sources checked and move to the next record.
Do not pursue additional access routes, author histories, theses, or human download
requests solely to rescue that record. Existing readily accessible supplements and
direct public supplement links may be checked using the resumable downloader.
Do not repeatedly revisit deferred records; reopen only when new source evidence
arrives or the user requests it. This supersedes earlier exhaustive source-retrieval
and unresolved-source followup instructions for records failing this gate.
Record unknown availability or extraction failures separately, then move on. Missing local files
are not proof of no supplement. Inspect table context: scaffold line wraps and many
small independent tables must not be summed into a fictitious 100-staple list.
Image tables may receive a quick visual check; do not launch extended OCR or
transcription work at this gate. Candidate sequence counts are not verified
strand counts, design completeness, or a literature-relevance decision. Record
threshold, file hashes, page ranges, disposition and pilot yield; retain deferred
records as an audit trail, not an active source-recovery queue. Patent scope
exclusion overrides earlier queues. A passing table is necessary for further
processing, not sufficient proof that a design is complete or reproducible.

Use first online publication dates, resolving boundary cases against primary
metadata. Reconcile preprints, conference abstracts, and journal versions while
retaining their separate dates and identities. A pre-2020 abstract linked to a
later article is a pre-2020 lead, not evidence that the later full design was
publicly documented before the cutoff. Use 2006–2019 as the main discovery window;
retain earlier methodological references without treating them as eligible designs.

Screen DNA-origami literature broadly. Separately apply the existing catalog rules
in [README](README.md): standard honeycomb/square packing, filled planar domains
and qualifying bundles; exclude bricks, wireframes, trusses, and nonstandard
lattices from the accepted structure map. Preserve papers containing these objects
in the literature census with reasons. Mixed papers require design-level decisions.
Do not change these eligibility rules without a user instruction.

Count publication versions, canonical works, design groups, individual documented
variants, and verified source sets separately. Several papers may reuse one design;
one paper may report several designs. Existing group IDs and family labels are not
proof of distinct geometry. A relevant paper remains relevant even if no complete
staple list can be obtained; missing sources affect extraction status.

## Durable records

Implement these research sidecars before large-scale screening. They are proposed
outputs, not files already populated by this documentation task. Reuse compatible
existing fields and maintain explicit mappings to the current registry. Use atomic
checkpoints and stable keys. Preserve superseded decisions with their reasons.

| Record | Minimum contents |
| --- | --- |
| `research/publication_reviews.jsonl` | Registry key; normalized DOI or stable no-DOI key; canonical work and version links; publication type and date evidence; review stage; relevance; design contributions; catalog eligibility; evidence references; rationale; reviewer/run/date; unresolved questions; revision history |
| `research/design_evidence.jsonl` | Stable design ID; publication and variant links; originating/reuse/modified relationships with evidence; lattice decision; named objects; figures, tables and sheets; source files and hashes; core/variant composition; source-completeness state; outstanding checks |
| `research/discovery_runs.jsonl` | Run ID; route; exact query or seed; source URL; date; pagination/cursor and provider totals; retrieved count; deduplicated additions; failures; checkpoint; closure state |
| `research/discovery_edges.jsonl` | Source and target keys; relation such as cites, conference lead, author bibliography, or version; evidence URL and locator; reconciliation state |
| `research/batches.jsonl` | Batch ID; input keys; completed actions; before/after counts; exclusions audited and sampling method; validation; unresolved keys; next queue |

Evidence references must locate the original: URL/DOI, retained file and SHA-256
when available, and PDF page, XML section, figure, table, sheet, or archive member.
Store concise paraphrases and only necessary short quotations. Distinguish PDF
page numbers from printed page labels. Record negative searches by their actual
scope; an empty API response does not establish absence of a supplement.

Review stage: `unreviewed`, `metadata_screened`, `fulltext_reviewed`,
`design_sources_reviewed`. Track access separately: available, partial, unavailable,
or not attempted. A paper is not fully reviewed merely because it was downloaded
or text-indexed.

Relevance: `design_bearing`, `background_or_review`, `not_origami`, or `uncertain`.
For design-bearing papers, use a set of contributions: `new_design`,
`modified_design`, `reused_design`, `uncertain`. These can coexist within one paper.
Track catalog eligibility separately as `eligible`, `excluded`, `mixed`, or
`unresolved`. State exclusion reasons explicitly.

## Review batches

Start with 25 publications per screening batch; use smaller batches for complex
design extraction. A batch is a checkpoint, not a stopping condition. Prioritize
named candidates and acquired sources, then rotate across years, publishers, and
low-signal records. Do not indefinitely defer records lacking sequence keywords.

1. Select and persist the batch keys. Inspect prior decisions and available files.
2. Apply the mandatory first source gate above. If no qualifying table is found,
   note the result and move on. For passing records, read relevant article sections
   and supplements.
   Resolve uncertain cases with full text or leave them unresolved. Before a final
   background-only exclusion, inspect accessible methods/results and supplement
   context where origami use is plausible.
3. Record design contributions and evidence. Follow original-template citations;
   distinguish a reused rectangle from genuinely modified routing or geometry.
   Do not infer topology or complete sequences from appearance alone.
4. Inspect design-bearing tables and archive members. Check shared staples plus
   variant replacements/extensions; record whether their exact combination is
   verified. Sequence counts alone do not establish completeness. OCR output,
   especially nucleotide strings, requires source-image verification.
5. Save decisions, add discovered references to the queue, and integrate only
   supported catalog changes through maintainable generation paths.
6. Validate and checkpoint. Report newly resolved papers and designs separately
   from downloads and automated text matches.

## Discovery routes

Maintain a route ledger with pending, in-progress, exhausted, and blocked states.
“Exhausted” means the documented query/source was completed, not that the field is
exhausted. Log inaccessible conference years and provider limits.

- **Bibliographic searches:** complete pagination or documented date partitions;
  vary origami/scaffolded-structure terminology and search metadata beyond titles
  where supported. Europe PMC queries were paginated; the old Crossref queries
  were capped. Inspect API capabilities before implementing replacements.
- **Citation searches:** follow backward and forward edges from eligible papers,
  landmark papers, and relevant reviews. Do not restrict references to citations
  whose titles contain “origami.” Later reviews may supply leads to earlier works,
  but do not make later works eligible. Deduplicate and iterate newly found seeds.
- **FNANO:** locate official or archived programs/abstract books for each available
  year in the main window. Extract relevant talk/poster titles, authors, year and
  page; resolve journal counterparts and retain unresolved abstract-only records.
  Mark missing years as gaps. Do not guess URLs or claim coverage from snippets.
- **Authors and laboratories:** seed from eligible papers and relevant conference
  contributions; inspect public bibliographies and identity-resolved author
  searches. Record name variants, affiliations, and identifiers where available.
  Attendee status is only a lead. Reconcile likely duplicates without merging
  different people or different publications on name/title similarity alone.
- **Repositories and supplements:** follow paper-linked data repositories, lab
  archives and original-file links. Retain original assets with hashes and source
  URLs; later reconstructions remain labeled as such.

Combine screening and discovery throughout the campaign. Each batch should enqueue
new leads, and discovery rounds should report their yield of genuinely new eligible
works after review, not only raw search hits.

## Validation and exclusion audit

Check unique keys, valid cross-references, stable old IDs, decision evidence,
publication dates, source existence/hashes, and consistency between ledgers and
generated JSON/CSV/HTML. Ensure regeneration preserves saved decisions. Test new
research scripts with focused fixtures for deduplication, resume behavior and
failure handling; no production application suite is needed for documentation.

Re-review a reproducible 10% sample of final exclusions per batch, at least one
when exclusions occur, plus every conflicting or ambiguous exclusion. Record the
sampling seed and selected keys. A fresh review by the same agent is a second pass,
not an independent reviewer. If it finds a missed design paper, reopen that batch's
exclusions, revise the rule, and inspect prior decisions affected by that rule.
Do not claim a measured recall rate from this small audit.

Preserve the existing image scores, original files, IDs and reconstruction evidence.
Literature research does not authorize authoring or modifying molecular structures.
Any separately requested reconstruction remains subject to AGENTS.md and the
mandatory feature-history publication guard.

## Reporting and completion

Report discovered canonical works, versions, screened records, full-text reviews,
design-source reviews, eligible papers, mapped designs, exclusions and unresolved
cases. Recompute counts from saved records. Always name the denominator; the fraction
of known records reviewed is not the fraction of all literature discovered.

The operational closure criteria are:

1. Every collected record has an evidence-supported disposition or a specific
   unresolved blocker with attempted remedies.
2. Planned queries, citation queues, conference-year coverage and author queues
   are exhausted or have individually documented inaccessible gaps.
3. Two successive complete passes through remaining citation/author leads produce
   no new eligible works, with rounds and seeds recorded. Finding new eligible
   works reopens their discovery edges and restarts this saturation check.
4. Eligible papers have design-level extraction or explicit source gaps; duplicates
   and reuse relationships have been reconciled as far as evidence allows.
5. Exclusion audits and saved-output validation pass.

These criteria support “review complete for the documented search scope,” not proof
of universal discovery. With unresolved relevant records, report “reviewed accessible
corpus with N unresolved cases”; do not mark an unrestricted complete-review goal
achieved. Preserve the remaining queue for future access or evidence.
