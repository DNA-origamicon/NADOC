# Expanded pre-2020 structure search

Research side project; not a production feature. Discovery baseline: November 2, 2026; ACS acquisition and design reviews expanded November 4. Recovery status is tracked separately in [README](README.md).

[Structure map](structure_map.html) · [Publication registry](publication_registry.html) · [Priority review gaps](priority_review_gaps.csv) · [Machine-readable coverage](search_coverage.json)

## November 5 durable research continuation

Current census progress is recorded in [RESEARCH_CHECKPOINT.md](RESEARCH_CHECKPOINT.md)
and the five `research/` ledgers; historical map counts below do not describe closure.
Author-history work prioritizes the requested laboratories; FNANO remains deferred.
Turberfield's Oxford provider pagination has now been enumerated through all38
pages:187 citation occurrences,169 pre2020/boundary/date-uncertain leads, including
four missing/uncertain dates. Duplicate works, versions, publication types and
primary dates remain to be reconciled; this is not exhaustive author coverage.
See `research/turberfield_bibliography_inventory.json` and batchAUTHOR0014.

## November 4 update

The current map contains **75 reviewed groups from 47 publications and 25 candidate groups**. Initial ACS review added 22 groups and promoted one existing candidate. Acquisition now retains **269 files from 244 publications**, including 151 files recovered when retrying the initial 145 HTTP 403 lookup failures. The broader 2,210-record discovery census was not rerun. [Access recovery](acs_access_resolution.json), [acquisition totals](acs_expansion_summary.json), [request history](acs_acquisition.json), [source-page index](acs_source_index.json), and [review decisions](expansion/acs_reviews.json) retain the evidence.

All 145 failed lookups completed: 135 matched deposits and 10 returned no matching deposit. Across the 272 selected ACS leads, 245 have matching deposits and 27 have no match; one matching deposit contains only deferred media. There are zero remaining lookup or document-download failures. Ninety-one media attachments remain deferred. Empty results do not demonstrate absent supplements. All 269 downloaded files passed publisher size/MD5 and retained SHA-256 verification.

No additional credentials or cookies were needed for recovery through the public supplement API. Direct journal pages still present a separate browser challenge. The new downloader uses sequential two-second request spacing, bounded retry/backoff, atomic checkpoints, and a 100 MiB per-file bound. The recovered 41 MB square-lattice supplement exceeds the older 35 MiB bound. Historical counts below describe the November 2 pass, not locally verified availability today. Newly retrieved files await design-specific review; acquisition does not change eligibility or sequence-completeness claims.

## November 2 result and interpretation

- 61 reviewed design groups from 36 publications: the original 32 image groups plus 29 sequence-based groups. Three original groups are conceptual images, not complete-structure specifications.
- 17 additional named design candidates from 17 publications, kept separate until scope or list verification is resolved.
- 2,210 deduplicated discovery records. These include reviews, methods, preprints, inaccessible articles, and out-of-scope subjects; they are **not** 2,210 eligible structure papers.
- 672 accessible full texts were automatically searched; 230 contain sequence-related contexts. These matches can refer to background literature, scaffolds, partial modifications or excluded structures.
- 180 locally retained supplement files are linked through the expansion inventory, including historical downloads and duplicate content obtained under different URLs. This is a file count, not a unique-source count.
- Six paper-mentioned GitHub repositories were checked. Eight files were retrieved from pScaf and ReuseDNA, including native designs and sequence CSVs. Analysis repositories are not treated as editable structure sources. See [file inventory](expansion_repository_files.csv) and the [repository audit](assets/sources/pre2020-expansion/repository_audit.json).

The search pass is recorded and reproducible, but the verified map is **not exhaustive**. The registry preserves the remaining evidence instead of silently discarding inaccessible papers. It does not claim complete per-variant staple lists or a closed census of every published structure.

## Scope and source verification

Publication cutoff is strictly before January 1, 2020. Include conventional honeycomb or square packing, including filled planar origami domains and conventional bundles bent by indels. Exclude DNA bricks, brick-named variants, wireframes, trusses and non-standard lattices. A mixed-design paper can contain both eligible and excluded structures.

A published staple list now suffices without a caDNAno/scadnano image. Sequence-only records have **null image scores**; author files, microscopy and sequence availability do not increase the image reconstruction score. Downloaded publication material, list location, scope review and complete variant matching are separate facts. No new entry is certified as a complete synthesis-ready sequence set.

Common cores and variant-specific extensions/replacements must be combined. Docking labels, material coatings and repeated use of a rectangle are grouped as variants or reused templates. The family field is a curation aid, not a proven identity graph; existing image groups retain their stable IDs and need further family reconciliation. Do not interpret row counts as unique geometry counts.

## Discovery coverage

Europe PMC queries were fully paginated and combined with the original discovery corpus:

```
(cadnano OR scadnano OR "DNA origami") AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]
("scaffolded DNA" OR "scaffolded origami" OR "DNA nanostructure" OR "DNA nanostructures") AND (staple OR staples) AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]
("DNA origami") AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]
```

The expanded Europe PMC union contains 1,849 records. Of these, 743 lack a PMC full-text identifier and 434 full-text retrieval attempts failed; neither state establishes that publisher copies or supplements are unavailable. The remaining 672 full texts were triaged for sequence statements, lattice descriptions, structures, characterization, repositories, supplements and origami-related references.

Crossref title queries `DNA origami` and `scaffolded DNA nanostructures` each retrieved the top 1,000 relevance-ranked records, filtered to publications through 2019. These queries are **capped, not exhaustive enumerations**. Title matching, DOI deduplication, curated primary metadata and backward citations expanded the registry to 2,210 records. Crossref title/date metadata may describe chapters or duplicate translated/version records; such records remain discovery leads.

Backward citation chasing extracted 30 DOI candidates absent from the initial Europe PMC union; 13 resolved through Crossref in this pass. Unresolved references and source-to-citation edges are retained in [citation results](assets/sources/pre2020-expansion/citation_chase.json) and [edges](assets/sources/pre2020-expansion/citation_edges.json). This is one backward-reference pass, not complete recursive citation closure.

Publisher pages were used to correct stale Nature supplement filenames. Accessible PDFs/spreadsheets were downloaded with hashes; primary text and sequence-table locations were inspected for the curated groups. Sequence-string counts are only indexing aids and do not demonstrate staple-list completeness. Author-hosted Rothemund 2006 supplements add pre-caDNAno designs explicitly excluded by the former image-only requirement.

## Imaging data

[Imaging resources](imaging_resources.csv) distinguish processed cryo-EM maps, atomic models and excluded-object evidence. Primary accession records checked include [EMD-1612](https://www.ebi.ac.uk/emdb/EMD-1612) for the controllable DNA box and [EMD-2210](https://www.ebi.ac.uk/emdb/EMD-2210) plus [PDB 4V5X](https://www.rcsb.org/structure/4V5X) for the square-lattice pointer. Their structures remain candidates here until the remaining list/scope checks are resolved.

[EMD-4653](https://www.ebi.ac.uk/emdb/EMD-4653) is a viral capsid map from a DNA-origami packaging study; it must not be assumed to resolve the encapsulated origami. Gerling EMD-0028/4354 records are retained as excluded brick-named-object evidence, not attached to eligible structures. Deposited maps/models are **not raw micrographs, particle stacks or localization tables**. No public raw dataset has been verified for the newly curated groups; this is not a claim that none exists. Supplementary images and movies, functional assays and cellular imaging are not automatically design-matched structural datasets.

## Remaining gaps

The [priority review list](priority_review_gaps.csv) exposes named candidates and sequence-evidence leads without a curated structure. The full registry also retains discovery-only records. Important unresolved cases include the square-lattice block paper, the cryo-EM pointer's full synthesis list, the box and folding-pathway design-specific scope checks, uncertain hexagonal-versus-honeycomb assignments, and inaccessible ACS/RSC/Wiley/PNAS supplements. Preprints require reconciliation to journal versions. Files in mixed-design publications require sheet/table-level mapping before accepting every variant.

## Reproduce and validate

Run from the repository root. Bulk sources live through the `assets` symlink on the mounted Archive volume; keep that volume mounted. Network scripts retain their query and retrieval logs under `assets/sources/pre2020-expansion/`.

```bash
python experiments/origami_publication_catalog/expansion/search_pre2020.py
python experiments/origami_publication_catalog/expansion/crossref_search.py
python experiments/origami_publication_catalog/expansion/chase_citations.py
python experiments/origami_publication_catalog/expansion/fetch_supplements.py
python experiments/origami_publication_catalog/expansion/retry_publishers.py
.venv/bin/python experiments/origami_publication_catalog/expansion/index_supplements.py
python experiments/origami_publication_catalog/expansion/check_repositories.py
python experiments/origami_publication_catalog/expansion/curate_structures.py
python experiments/origami_publication_catalog/expansion/build_map.py
python experiments/origami_publication_catalog/expansion/finalize.py
```

The curation script contains explicit review decisions; automated retrieval does not make new inclusion decisions. The small landmark and curated-metadata snapshots were retrieved separately and are retained with source URLs/hashes. Rebuilding the map from retained inputs requires only `build_map.py` and `finalize.py`. Validation checks referenced files and hashes, local HTML links, stable unique structure IDs, date cutoff, null scores without reviewed images, and the paused/deleted recovery workspace. No production application code is changed.
# Rapid source pilot — 2026-11-05

SEQ0001 screened ten previously unreviewed records with available PDF supplements,
using frozen keys in `research/sequence_pilot_0001_keys.json`. Seven have substantial
staple lists and proceed to detailed processing; three defer under the100-sequence
gate. See `research/sequence_pilot_0001_report.json` for file/page evidence and
limitations. This availability-selected sample does not estimate whole-corpus yield.
Raw DNA strings are not strand counts: scaffold text, wrapped sequences and many
small unrelated tables require context checks. An image-only table was checked
visually. Literature relevance remains undecided by this gate. All three known
patent-type records are now excluded by explicit user scope; prior patent queues
are superseded, evidence retained. FNANO remains deferred.
