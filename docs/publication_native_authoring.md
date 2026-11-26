# Publishing reconstructed native designs

D005, D006, D007, D008 and partial D009 are saved native parts in `workspace/Shared Designs/`.
They were constructed from the supplement diagrams and sequence tables without
using archived caDNAno files as construction inputs. Independent replay uses
recorded native editor inputs, never captured output snapshots.

| Design | Supplement diagram/table pages | Saved commands | Native result |
| --- | --- | --- | --- |
| D005 | twist-supp.pdf 19/37 | 2,681 | 60 helices, 217 staples, 15,983 nt |
| D006 | twist-supp.pdf 20/39 | 1,434 | 20 tracks, 209 staples, 15,362 nt |
| D007 | shapes-supp.pdf 4/12 | 1,298 | 60 helices, 144 staples, 13,440 nt |
| D008 | shapes-supp.pdf 5/13 | 1,186 | 60 helices, 149 staples, 12,575 nt |

## General construction algorithm

The compiler and CLI default to continuous staple precursor pens on each
contiguous occupied helix interval, then published terminal nicks and native
crossovers. Gaps in published occupancy are not filled. Terminal nicks precede
crossovers to avoid intermediate cycles. Each final sequence assignment requires
an exact directed-route match to the extracted staple, not merely a matching
length or endpoint. Scaffold construction remains separately recorded.

Following the user's generalization of D006, same-helix staple joins between the
two extreme occupied scaffold bases are marked as periodic polymerization seams.
All domains of those staples are excluded from ordinary precursor strokes and
constructed separately. Interior jumps are never classified as periodic merely
because they are long. Other nonlocal staples also retain their own construction
without acquiring a periodic flag. Part files define seams; repeated instances
and polymerization operations belong to assemblies. No polymerization strands
are converted into terminal extensions.

`--no-continuous-staples` and `--no-periodic-staple-seams` expose explicit overrides.
Periodic classification uses the precursor planner; disable both to reproduce
the original domain-by-domain strategy. The archived D005 build retains its
original 2,681-command history and code snapshots. A new D005 compilation with
current defaults produces a different recipe; existing saved designs are not
silently migrated.

## Publication and replay

Example for a new D007 destination:

```sh
uv run python -m scripts.reconstruct_publication_design \
  --pdf experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf \
  --diagram-page 4 --table-page 12 --name D007 \
  --output 'workspace/Shared Designs/D007.nadoc' \
  --evidence .development-artifacts/d007-native-construction
```

Existing-file replacement requires `--expected-existing-sha256` with the exact
current hash. Publication goes through `scripts.agent_structure_guard.publish`;
the saved file is reopened, replayed and compared with extracted evidence. The
portable supplement, exact construction code snapshots and audits are retained
under `.provenance/Dnnn/`. Developer/browser evidence stays outside the shared
library. The welcome screen lists saved native documents, not README analyses.
The interactive Reconstruct button downloads selected PDF figure/endpoint-table
pairs as native designs with completion reports and portable source dependencies.
The command-line workflow also supports partial reconstruction by default.

Native loop counts accept 1–512 inserted bases, -1 for deletion, and 0 to remove
a mark. Replay stays bounded to 4,000 rows including group wrappers; recipes are
bounded to 3,800 commands. Existing process and geometry guards remain mandatory.

## Unpaired scaffold and D006 auxiliary tracks

Unpaired-scaffold analysis retains drawn routes and aligned sequences. It checks
reverse complements against unexplained staple table rows separately from short
repeats in already assigned staples. The default match threshold is seven bases,
or the whole run for shorter loops; this is not a thermodynamic prediction.
Supported terminal scaffold sites outside each helix's published staple band
remain ordinary scaffold domains. Interior gaps and unplaced tracks retain
separate admission guards. No missing oligos or terminal extensions are invented.

D006 has two independent source-row-19 excursions: 49 paired + 29 unpaired bases
from helix 0, and 49 paired + 17 unpaired bases from helix 1. No staple connects
them. Native viewer tracks 18 and 19 represent the two segments. Mapping retains
source addresses and rejects overlapping, missing or unresolved placements.

The approved placement search minimizes the sum of native Full O5 endpoint
spans at the source base register, including locked phase constants. It searches
vacant parity-compatible cells with an exhaustive triangle-inequality bound.
Both independent minima are unique; the earlier shared-center-distance tie is
only historical diagnostic evidence. Axial fitting, phase changes and flexible
loop geometry were not performed. Insertion-bearing attachment endpoints require
explicit copy selection.

D006 uses 18 body staple pens and two auxiliary-track pens, plus separate
polymerization staples. All 209 staple sequences and all source pointers match.
Its 18 end-to-end joins are marked as polymerization seams; four scaffold-loop
joins remain nonlocal, including 25–28 nm spans. Replay success does not certify
simulation-ready geometry. D005 likewise remains an idealized lattice model,
not a prediction of the experimentally twisted/relaxed conformation.

## D007 bare scaffold ends

The user confirms that D007's extra terminal labels are bare scaffold positions.
The reconstruction retains all 7,560 scaffold bases and only the 144 published
staples (5,880 bases). There are 1,680 unpaired terminal scaffold bases, 28 per
helix and 840 per bundle end. They remain in their drawn native domains.

The separately consulted reference contains 70 additional terminal staples
(20×12, 20×24 and 30×32 nt). These are intentionally absent from the published
reconstruction. All scaffold pointers and all 144 published staple routes and
sequences agree; reference-only staples are not an extraction target.

All 13,295 native backbone edges were measured, including 780 interhelix joins:
zero forced ligations, missing geometry or Full O5 spans above 1.2 nm. This is
an idealized model, not physical relaxation of the bare ends.

## D008 unlisted drawn staple and D009 limitations

D008 has 148 table-listed staples and one additional drawn 38-base route,
helix 27[60] to helix 17[55]. The general recovery method admits an unlisted
route only with a complete exact scaffold alignment, full scaffold coverage of
its bases, unanimous antiparallel direction, and no overlap with existing staples.
It derives the sequence from scaffold complementarity, records that origin, and
does not count the derived sequence as independent table evidence. D008 now
retains all 149 drawn staple routes and 2,545 bare terminal scaffold bases.

Repeated numbered lattice insets are fitted independently. All copies must
contain the full label set and agree after translation normalization; incomplete,
conflicting or internally duplicated labels remain blocked. D009's five copies
agree on all 46 helices, resolving that parser limitation.

D009 still lacks drawn routes for ten table entries. Its 276 staple bases without
scaffold partners comprise 233 terminal and 43 internal bases. These require
explicit native unpaired-staple handling; they are not silently replaced with
ordinary extensions. The two 39-base loops remain sequence-supported, while the
7,703-base represented scaffold differs from p7704 by one base. Confidence stays
80.96/100 with the discrepancy penalty. No complete native D009 is published.



## On-helix staple overhang sequence evidence

The user-authorized general rule classifies drawn staple positions without a
scaffold partner as on-helix overhangs, including internal unpaired segments.
The corresponding subsequence is selected by directed path position and expanded
insertion counts, never by searching for a convenient matching substring.
Visible A/C/G/T glyphs are decoded independently of PDF Unicode mappings, using
color-isolated raster shapes and standard font templates. Uncertain glyphs stay
unreadable; fonts unavailable on a machine may reduce image coverage. The table
provides an explicitly recorded fallback when letters are absent/unreadable.
Readable image/table conflicts are retained as non-blocking notices. The
strongest evidence selects the base; equal evidence uses T > A > C > G.
Neither fallback nor image agreement is counted as scaffold complementarity.

D009 has 276 such bases: 266 image/table matches, eight table fallbacks (no image
letter at the mapped position), and two readable conflicts. At visible helix
8[117] and helix 9[118], image A conflicts with table T. Both positions select T under the user's tie-break policy. All 276 overhang
bases are assigned; the original A/T disagreements remain in the report. The independent scaffold
alignment still has 6,686 comparisons and 129 fully paired exact staples; those
counts are not inflated. Sequence-evidence confidence is 84.92/100 with the
one-base discrepancy and ten unmatched rows still penalized. The UI distinguishes
image matches, table assumptions, conflict notices, selected bases and reasons.

This section records the earlier evidence stage. The subsequent partial native
implementation supports these overhangs, including internal segments, and records
all included routes. Ordinary terminal extensions are never substituted.
Local reproducible evidence and the two-letter review crop are under
`.development-artifacts/d009-overhangs/` and `.development-artifacts/d008-d009-recovery/D009-overhang-conflict.png`.


The reusable `publication_base_conflicts.resolve_base_evidence` ranks positive
evidence support first. Equal support uses T → A → C → G regardless of whether
the preferred base came from the image or table. Duplicate labels from one
source do not create additional votes. Readable image and table bases each
contribute one vote by default; glyph-recognition confidence controls readability,
not biological evidence weight. Source observations and original table sequences
are immutable; selected run sequences are recorded separately. Length, routing
and polarity failures remain blockers. D009's updated audit is retained under
`.development-artifacts/d009-base-conflicts/`.

The earlier blockers and ten table-only routes are listed in
[D009 reconstruction readiness](d009_reconstruction_readiness.md); current results
are in [D009 partial reconstruction](d009_partial_reconstruction.md). Analysis and
native planning now share the supported loop-count handoff.

## Partial reconstruction and scaffold gaps

See [D009 partial reconstruction](d009_partial_reconstruction.md). Native authoring now supports arbitrary scaffold coverage gaps and explicit partial output. The dialog can download selected figure/table reconstructions with reports; CLI partial output is enabled by default. D009 contains 194/197 staples; ambiguous and unmatched routes remain in the report.
