# Original-publication routing extraction

The agent-less extractor now reads original publication PDFs in addition to the
controlled Pointer benchmark. Native caDNAno files are independent validation
oracles; the extraction API does not accept them.

## Reproducible corpus audit

Run from the repository root:

```sh
uv run python -m tools.design_archive.publication_routing_benchmark \
  --assets experiments/origami_publication_catalog/assets \
  --output .development-artifacts/publication-routing-exploration/report.json
just test-focused tests/test_publication_routing.py
```

The local catalog assets must be installed. Corpus-dependent tests explicitly
skip when absent; synthetic contract tests still run. The report records source,
reference and implementation hashes. It contains evidence, not molecular files.

| Original supplement / figure page | Staple paths matched to table | Reference comparison |
| --- | ---: | --- |
| `shapes-supp.pdf` / 4, monolith | 144/144 | Full scaffold; 5,880 staple sites exact, 1,680 native staple sites missing |
| `shapes-supp.pdf` / 5, square nut | 148/148 | Full scaffold; 4,977 staple sites exact, 2,583 missing; one unclassified path |
| `shapes-supp.pdf` / 6, railed bridge | 187/197 | Full scaffold; 6,962 staple sites exact, 862 missing |
| `twist-supp.pdf` / 19, right-twisted 10×6 bundle | 217/217 | All 15,119 occupied scaffold/staple sites and their directed pointers exact; all 60 relative lattice cells and all 361 insertion sites/lengths exact |
| `twist-supp.pdf` / 20, straight 3×6 bundle | 209/209 | All 15,362 occupied sites and directed pointers exact; inset does not locate every helix |

There are no extra recovered sites or incorrect recovered pointers in these five
comparisons. Missing source evidence is not filled from the reference. The native
files for the first three contain additional staple routing; matching every
published table row does **not** imply complete native-design recovery.

For the right-twisted bundle, 360 visible insertion annotations are constrained
to one base by the published staple lengths. A remaining visible scaffold-only
loop is 144 bases by mass balance against the explicitly named p8064 scaffold.
This resolves all 504 inserted bases without consulting the reference, under an
insertion-only interpretation (no compensating deletions). The
validator compares occupied topology, insertion lengths and relative lattice
coordinates; empty caDNAno padding and absolute lattice translation are not
reconstruction targets. The reference has no deletions. General deletion
interpretation is still unverified in the product and is not certified by this
zero-deletion case.

## Algorithm

- Decode short numeric labels from the rendered glyphs against built-in digit
  templates. This handles broken embedded-font Unicode maps, including maps that
  return the wrong digit. Ambiguous matches are rejected.
- Normalize quarter-turn figure orientation and calibrate uniform rulers and
  numbered helix tracks. Trace line spans into occupied base sites; curves join
  their endpoints, including nonlocal intrahelix joins.
- Match published Start/End/Sequence/Length/Color table rows against path endpoint
  pairs. Test evidence-derived integer register translations and both directions;
  retain ties as unresolved. Square nut requires a four-base correction.
- Orient scaffold paths only with unanimous local antiparallel evidence from
  matched staples. Nonlocal joins do not vote as local backbone direction.
- Fit numbered circle insets to honeycomb coordinates. Reject missing labels,
  duplicate labels or nonunique fits.
- Detect small two-curve insertion annotations. Positive insertion lengths are
  constrained by staple lengths; only a single remaining observed scaffold loop
  can be solved from declared scaffold length. Multiple unknowns remain unknown.

## Application contract and remaining work

Upload the supplement, click **Detect designs**, select a figure and its endpoint
list. The real analysis API returns directed path evidence, lattice fits and
insertion constraints; the UI distinguishes endpoint evidence from sequence
complementarity. Multiple figures remain independently selectable.

This is not yet end-to-end molecular reconstruction. **Reconstruct remains
disabled.** Generic deletion interpretation, complete source validation, scaffold
sequence reconciliation and a recorded native authoring path remain unfinished.
No `.nadoc`/`.nass` artifact is created by these tests or benchmarks. The existing
Pointer sequence-supported flow remains separate and unchanged.

## Exhaustive scaffold sequence alignment (2026-11-25)

Publication analysis now selects a scaffold explicitly named in a table from the
local sequence library, or uses the user's supplied sequence. It expands resolved
insertions and tests every cyclic offset in both scaffold traversal directions.
Every candidate is scored against every comparable base of every matched staple;
there is no sampled-anchor filtering. Ties, mismatches, invalid oligo lengths and
unknown partners prevent a resolved result. The UI displays candidate counts,
best and runner-up mismatch counts, register and direction.

D005 with the local p8064 sequence: 16,128 candidates; a unique exact match for all
217 staples and 7,919 paired bases. The recovered direction and offset 0 win; the
next-best candidate has 5,551 mismatches. Sequence index zero maps to visible
helix 1, base 97, insertion offset 0. This is a sequence-origin mapping, not an
instruction to cut or move the physical scaffold nick. The scaffold-only loop
sequence follows from the aligned library sequence; it is not independently
validated by staple pairing. Geometry and native construction remain unfinished.

Focused tests: `just test-focused tests/test_publication_sequence_search.py`.
The general user authorization is recorded in
`memory/feedback_bounded_sequence_search.md` and linked from CLAUDE.md.

## Cross-design sequence robustness (2026-11-25)

The same bounded search has now been applied to D005–D009, without native design
files as extraction/search inputs:

| Design | Scaffold candidate | Candidates | Exact staples | Paired bases | Next-best mismatches |
| --- | --- | ---: | ---: | ---: | ---: |
| D005 | p8064, named in paper | 16,128 | 217/217 | 7,919 | 5,551 |
| D006 | p7704, named in paper | 15,408 | 209/209 | 7,658 | 5,366 |
| D007 | p7560, length-matched library hypothesis | 15,120 | 144/144 | 5,880 | 4,120 |
| D008 | p7560, length-matched library hypothesis | 15,120 | 148/148 | 4,977 | 3,483 |
| D009 | Not searched | — | — | — | — |

The first four have unique zero-mismatch alignments in the recovered direction,
with offset zero relative to their recovered scaffold walks. D009 retains two
unresolved insertion lengths (visible helices 30 and 42, base 119); a register
search over guessed lengths would not be a validated result. Ten of its 197
published staple routes also remain unmatched. Existing topology/lattice gaps
in D006–D009 are not repaired or certified by sequence agreement.

The p7704 sequence was extracted as literal data, without executing upstream
code, from [caDNAno's pinned sequence library](https://github.com/cadnano/cadnano2/blob/76644f36595b649583f31937150f78d33ac8b7ba/data/dnasequences.py).
`backend/core/p7704.source.json` records the commit and upstream/sequence hashes.
It is an additional reconstruction reference; the general authoring scaffold
selector remains unchanged.

When a table does not name a scaffold, all length-compatible library sequences
are explicitly tested as hypotheses. A named but unavailable/ambiguous scaffold
never silently falls back. Equal best matches across scaffold candidates remain
ambiguous. Custom sequence input still takes precedence. Results distinguish a
resolved alignment of recovered routes from complete validation of supplied table
rows. Invalid oligos, unmatched rows and unknown partners cannot produce a full
validation result. Duplicate occupied staple sites and duplicate insertion
annotations are rejected rather than counted as extra evidence. Mismatches include
bounded per-base diagnostics (up to 100 entries, with truncation indicated).

Tests cover shift batch boundaries, both directions, real D005 virtual-nick
rotation, staple reordering, a single-base error, inconsistent lengths, repeated
sequence ties, unknown partners, duplicate evidence and equal library candidates.
The browser flow exercises all five designs and preserves D009's blocker.

Reproduce the PDF-only audit:

```sh
uv run python -m tools.design_archive.publication_sequence_benchmark \
  --assets experiments/origami_publication_catalog/assets \
  --output .development-artifacts/publication-routing-exploration/all-design-sequence-search.json
```

## D009 loop and one-base discrepancy candidates (2026-11-25)

This supersedes the D009 sequence-search blocker described above. The search now
considers positive lengths at observed scaffold-only insertion annotations, all
cyclic shifts, both directions, and length discrepancies of at most one base.
Bounds are explicit: three unresolved loops, at most 512 bases per loop and 4,096
partitions. Segment register costs score the combinations efficiently. Exceeding
the bound is reported; incomplete library searches cannot certify a solution.

D009 independently yields 39 inserted bases at visible helix 42/base 119 and
helix 30/base 119. The candidate has 7,703 represented scaffold bases against
p7704's 7,704, offset zero, and zero mismatches over 6,686 comparable bases.
Forcing equal lengths instead selects 40/39 bases and introduces 408 mismatches.
The native reference is not a search input. A separate full-route comparison
checks the winning loop candidate after the segmented search.

The one-base gap is placed at the observed nick boundary for alignment only.
Its physical location and cause remain unverified; human error is one possible
explanation. Original routing and source annotation evidence remain intact.
No molecular model, nick movement or sequence correction is written. Longer
one-sided scaffold loops remain loops, not ordinary strand extensions.

Candidate ranking prioritizes observed mismatch counts; length discrepancy breaks
an otherwise equal match. The confidence penalty is applied separately so that
hundreds of sequence mismatches cannot outrank an exact match merely because the
former has equal total lengths. The score is **sequence evidence**, not calibrated
probability or whole-design confidence:

- Base score: percentage agreement among compared bases.
- One-base discrepancy: minus 10 points (explicit policy constant).
- Unmatched table rows: minus their percentage of supplied rows.
- Unknown staple partners: minus their percentage of routed staple bases.
- Invalid rows, tied best hypotheses and incomplete candidate searches retain
  additional explicit penalties and cannot produce complete validation.

D009 scores 80.96/100: 100 - 10 - 5.076 (10/197 unmatched rows) - 3.964
(276/6,962 staple bases without recovered scaffold partners). Its two loops are
sequence-supported, but full validation remains false: ten table entries, unknown
partners and lattice/routing gaps remain. Only 129 staples are fully checked;
other recovered staples have unknown partner bases. The UI displays the loop
hypothesis, both lengths, penalty breakdown and the unverified-error explanation.

Regression tests: `tests/test_publication_loop_search.py`, including unchanged
inputs, both directions, nonzero shifts, exact-length loops, +/-1 cases, bounds,
ambiguous partitions and paired-base mutations. PDF-only sequence-audit reports
now hash the loop-search implementation as well.

## Saved native construction (2026-11-25)

D005 is now published through ordinary recorded editor operations and independently
replayed. See [native publication workflow](publication_native_authoring.md).
D006, D007 and D008 are also published through recorded native construction. D007
retains its bare terminal scaffold domains and only the 144 published staples.
D009 remains blocked; the interactive Reconstruct button is still disabled.
Native publication currently uses the documented command-line workflow.


D008/D009 recovery follow-up: D008's unmatched 38-base figure route is now
classified using the fully aligned scaffold and assigned its derived complement,
explicitly distinguished from 148 independently supplied table sequences. It is
published as 149 staples with no extra terminal staples. D009's five repeated
cross-section insets agree after independent fitting (46 helices); that blocker
is resolved. Ten table routes, 276 unpaired staple bases (233 terminal/43 internal)
and the penalized one-base scaffold discrepancy still prevent complete native
publication. Diagnostic evidence: `.development-artifacts/d008-d009-recovery/`.


On-helix overhang follow-up: unpaired staple positions now receive explicit
on-helix overhang classifications and table-indexed sequences. Independent visible
glyph decoding verifies image letters despite damaged PDF Unicode maps. D009:
266 image matches,8 table-only fallbacks,2 A/T conflicts (8[117],9[118]);272 bases
accepted across complete segments. Confidence84.87 retains other penalties. No
D009 native design is published. See the native authoring workflow for limits.


Conflict policy update: source disagreements are non-blocking notices. Equal
evidence selects T > A > C > G; stronger evidence overrides that preference.
D009 retains two imageA/tableT notices, selects T at both sites, accepts all276
overhang bases, and scores84.92. Original observations and independent alignment
counts are preserved. Ten missing table routes and the one-base discrepancy
remain unresolved.
