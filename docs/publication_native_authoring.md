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

### Preferred scaffold insertion loops (November 26, 2026)

New reconstructions use the native **Add loop here / Edit loop** operation
(`strand-loop-set`) for multi-base insertion annotations whose anchor belongs to
one scaffold route and is unoccupied by the recovered staples. The compiler
requires a following scaffold nucleotide and an unambiguous local traversal
polarity. It records the loop after scaffold joins and before sequence assignment,
so loop bases consume their original sequence positions without shifting the
complementary strand or duplex register. Native aspect ratio 3 and rotation 0
use the loop feature's approved placement defaults.

Paired insertions and single-base corrections retain `loop-skip-insert`.
Unresolved anchors fail construction rather than silently receiving another
representation. This rule is evidence-based, not a D009-specific exception:
D009 selects two 39-base loops and D005 selects its 144-base scaffold insertion.
Already saved legacy designs are not bulk-converted. Routed auxiliary scaffold
tracks (D006) are a separate case and are not collapsed into insertion loops.

The completion report records the selected representation, source anchors,
lengths, directions, and limitations. Native NADOC save/reopen, display and
sequence CSV support these loops; simulation and cadnano/scadnano export
currently refuse them. This does not certify relaxed loop geometry.

### Module tables and raster source evidence

Header-driven Module/Notes/DNA Sequence tables are now imported across consecutive
pages with source row boxes, bold spans and vendor modification tokens intact.
Unlabelled rows remain possible continuations; variants and accessory modules
are selectable separately in the reconstruction dialog. Module selection records
report membership, not verified native strand assignment.

Raster evidence uses the PDF's visible composite and transforms skeleton paths
back to PDF coordinates, including rotated pages. Color junctions remain
ambiguous and neutral strokes remain unclassified. Pixel registration is not
helix/base calibration. An unresolved attempt includes `source-evidence.json`
and the source PDF in the reconstruction ZIP, alongside the failure report.

Lipid chemistry is unsupported. Known terminal dye tokens retain their native
modification key pending verified strand mapping; internal dyes and unspecified
labels are reported separately as unsupported. Handles/toeholds retain labeled
native-overhang intent and candidate functional spans, pending an independently
recovered unpaired interval. None of these notices invents a strand placement,
adds a chemical group, or substitutes terminal extensions for overhang DNA.

### D014 raster troubleshooting — 2026-11-26

Supplement Figure 31 (PDF page 45) has recoverable grid evidence; the earlier
statement that it lacked a readable base marker was too strong. A visual review
finds an apparent `21` marker in the upper-left panel. It has not been accepted
as an automated OCR result. Native-image grid-period probes give approximately
5.681, 4.786 and 5.339 pixels/cell in the upper-left, lower-left and flap panels.
Circle segmentation recovers 40, 21 and 42 row-label observations respectively.
Visual review identifies the overlapping helix 39 row in the left images and
the reversed even/odd ordering in the flap panel. The review oracle is separate
from extraction; these identities are not injected into a generated design.

The production tracer now preserves embedded native raster resolution up to a
4096-pixel page bound and reports whether that bound caused downsampling. D014
previously used 2.613 pixels/PDF point versus the source requirement of 3.397;
it now renders at 3.397. This fixes avoidable information loss, not connectivity.
Raw fragments increased from 14,902 to 19,988 and junction observations from
1,814 to 2,531. Neither metric counts physical strands or true crossovers.

A bounded font-template OCR experiment (0–199; no reference design or prescribed
row ordering) is insufficient: visually reviewed top-choice label agreement is
33/40 upper-left, 19/21 lower-left, and 23/42 flap. Some correct labels are absent
from its first three candidates. This diagnoses that OCR method, not a proof
that the source labels are unreadable. Grid-to-base origin and per-panel scales
also need independent validation; a coordinate-origin choice alone need not
prevent a later sequence-supported registration.

The main remaining work is a cadnano-specific raster graph: separate horizontal
scaffold/staple lanes, distinguish arrowheads/squares and crossover curves from
pass-through crossings, preserve similar/reused colors, and propose connections
between cropped panels. The caption explicitly splits channel and flap, but its
dashed editorial arrow does not encode individual endpoint pairings. Sequence
search must jointly score those alternatives and retain nonunique solutions.
The native compiler currently accepts calibrated vector graphs/endpoint tables;
its generic module-table path still stops before such a raster graph search.

For the source-defined Top_A+inner+cyl*/flap* selection (219 rows, 7,886 bases),
local matches to candidate M13mp18 cover 4,427 bases at k=12 and 6,601 at k=8.
At k=8, 681 matching windows have multiple scaffold positions, affecting 185
oligos. These windows are not independently verified domains; uncovered sequence
is not automatically an overhang. Thus simply shortening the sequence-match
threshold cannot certify routing.

Reproducible probes and compact results are retained under
`.development-artifacts/d014-reconstruction-exploration/` (`registration_probe`,
`label_probe`, `resolution_probe`, `short_domain_probe`). No D014 native model
has been published. This is primarily an extraction/search implementation gap;
unique full recoverability or irrecoverability has not been established.

### Registration research and sequence fallback — 2026-11-26

Tested established methods rather than interpreting the figure with an agent:

- [Phase correlation](https://scikit-image.org/docs/stable/api/skimage.registration.html)
  recovered a controlled source-image translation to 0.05 pixel per axis.
- [SIFT](https://scikit-image.org/docs/stable/auto_examples/features_detection/plot_sift.html)
  with [RANSAC](https://scikit-image.org/docs/stable/auto_examples/transform/plot_matching.html)
  produced sparse, unstable or degenerate cross-panel matches on D014's repetitive
  grids. Its superficially plausible left-panel scale still selected the wrong
  vertical region. It is not accepted as a registration here.
- [Normalized cross-correlation](https://scikit-image.org/docs/stable/auto_examples/features_detection/plot_template.html),
  after independent grid-pitch normalization, found the shared left-panel strip:
  correlation 0.8719 versus 0.5449 for the next spatially separated peak. The
  transform maps the lower-left asset into the upper-left asset at scale 1.1870,
  translation approximately (1.53, 1014) native upper-image pixels. This agrees
  with the separately reviewed helix-39 overlap. The flap comparison has weak,
  competing peaks (0.4530 and 0.4430) and is not accepted as an overlap.

`publication_panel_registration.py` generalizes grid detection and correlation
screening into source evidence. A supported image overlap is explicitly distinct
from a molecular connection. Scores and margins are heuristic screening criteria,
not probabilities. This implementation currently recognizes upright panels with
orange row markers; unsupported styles remain unregistered.

`publication_sequence_domains.py` provides a bounded alternative when a raster
route is unavailable. It enumerates split exact alignments to a circular scaffold,
retains competing domain boundaries, tests 8- and 6-base minimum domains, and uses
[SciPy/HiGHS mixed-integer optimization](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
to prevent multiple staples claiming the same scaffold base. A second optimization
looks for an equal-score assignment. Beam pruning, transition budgets and solver
timeouts are reported. Unassigned bases are not automatically declared overhangs.

D014's source-defined Top_A/inner/cyl*/flap* selection was tested against candidate
M13mp18. At beam width 8, compatibility searches reached optima within their
retained pools at 4,152 (8-base minimum) and 4,683 (6-base minimum) paired bases;
both have equal-score alternatives. Expanding the 6-base search to beam width 32
and a 60-second solver budget reached an incumbent of 5,243 paired bases, with
approximately 2% solver objective gap remaining. The candidate pool itself was
pruned. None of these numbers is a reconstruction completion percentage or proof
that no better contact map exists.

When modules are selected, failed native reconstruction packages now include the
bounded sequence fallback and ambiguity results alongside table and raster
observations. With no module selection, the fallback requests design membership
rather than globally combining variants/accessories. The default scaffold is
explicitly an M13mp18 hypothesis. Native routing remains unresolved until domains
can be mapped to image locations and a permitted crossover graph.

A directly relevant external method was also located:
[REVNANO](https://revnano.readthedocs.io/en/latest/), described in
[Shirt-Ediss et al., 2023](https://doi.org/10.1016/j.csbj.2023.07.011).
It reconstructs sequence contact maps using routing trees, constraint propagation,
and shortest paths. Its input requires explicit dangle/loopout annotations.
Source-only upstream trials are isolated in development artifacts; no published
example design/contact map is supplied as an oracle or solver input, and the
geometry/schematic-generation stages are not run.

REVNANO trial results (unmodified upstream solver, commit
`36a72c13670004a23bc7aad0db44c2ab36c1b207`; contactmap helper commit
`8bd39737d2341f1d47dba8456fc1ce8f9bb86150`): raw Top_A selection reached the
180-second timeout. Marking the 438 bold functional bases on 32 selected staples
as non-scaffold-binding is an explicit source-annotation hypothesis, not silently
accepted topology. With that input, MU_MIN=6/SIGMA=4/BETA=0.3 resolved 78/219
staples in stage 1, then stopped at its GAMMA=0.65 prerequisite (35.6% resolved).
SIGMA=2 resolved 73/219 and stopped at the same prerequisite. Runs took 82.75 and
50.73 seconds respectively. Neither returned a final contact map. Both runs used the default GAMMA=0.65. Scaffold identity remains an
M13mp18 hypothesis; these failures do not prove irrecoverability on other inputs.
REVNANO remains an isolated research comparison, not a new required app dependency.

Tesseract 5.3.4 was also tested in an isolated extracted runtime, using cropped
numeric labels and three binarization thresholds. Some readings improved over
font templates, but the thresholds produced conflicting/missing digits, especially
in the flap. No OCR readings were silently promoted to verified helix identities.
The temporary OCR binaries were removed; package hashes and recreation script
remain with the evidence.

Because the exact scaffold sequence is not explicit in the consulted paper text,
the same source-marked REVNANO input was also tested against the installed p7560
and p8064 hypotheses. p7560 resolved 68/219 staples before the same stage-2
prerequisite stopped it (114.51 s). p8064 reached its 120-second trial cap during
routing-tree construction; that is an incomplete trial, not a no-solution result.
The source-only tests do not establish scaffold identity or unique recoverability.

The production package probe on the full PDF and all 219 selected rows completed
in 10.64 seconds. It returned one supported panel overlap (correlation 0.8763,
next peak 0.5401), both sequence-search passes and their equal-score alternatives.
The slight correlation difference from the exploratory probe reflects production
grid-pitch estimation. No native part was emitted because image-to-domain placement
remains unresolved. PDF images are decoded through PyMuPDF's PDF engine: this also
handles a source asset that Pillow rejected as a broken image stream.

### Stable sequence anchors and targeted expansion — 2026-11-26

`publication_sequence_anchors.py` intersects **base mappings**, rather than whole
candidate identities, across compatible assignments. Thus a changed domain
boundary can retain its common interior. Missing/unassigned staples count against
support. Every supplied assignment is checked for reverse complementarity and
unique scaffold occupancy. Each core's exact occurrences are counted over the
entire circular scaffold independently of beam pruning. Repeated sequences and
single-solution observations are not promoted to provisional anchors.

The report separates sampled agreement, circular sequence uniqueness, active
counterexamples, necessity within a retained candidate pool, and solver-budget
exhaustion. Counterexample searches exclude every candidate containing the core
and allow all other staples to move. Their objective window is the best supplied
incumbent plus four paired-base penalties, with domain count as the secondary
objective. A timeout is inconclusive; even an infeasibility certificate applies
only to the retained pool and that score window. These are not calibrated
confidence probabilities or verified helix placements.

Anchor-conditioned alignment generates additional candidates, then combines them
with **all original alternatives** for global occupancy optimization. No provisional
anchor is frozen. Local refinement selects unresolved staples and their current
occupancy blockers, allows joint reassignment, and records the fixed outside
context. Larger timed-out searches preserve the best prior feasible incumbent.
Residual circular scaffold intervals include neighboring table-row identities;
unassigned sequence is not automatically classified as a loop or overhang.

D014 exploration, using the original 8-base/6-base pools and expanded beam-32 pool:

- Initial agreement: 1,679 base mappings, 68 cores of at least 12 bases, 67 with a
  unique circular scaffold occurrence. Sixteen whole-core exclusion challenges
  at two seconds each were inconclusive; none certified global necessity.
- Anchor-conditioned expansion across 62 rows added 818 candidates. Its 30-second
  global search found 5,681 compatible paired bases. A control combining the
  original pools **without** those new candidates reached 5,800 in 30 seconds.
  Both searches timed out without proving optimality. Do not attribute the
  coverage increase to anchors: the control did better within this budget.
- Eight local neighborhoods on the expanded pool preserved the 5,800-base
  incumbent without further pairing gain. They completed in approximately 0.63 s.
- Across six supplied assignments, 59 unique cores (961 bases) survive, with
  1,530 shared base mappings overall. The best incumbent leaves 1,449 scaffold
  bases in 219 intervals; the longest is 44 bases. Scaffold identity remains the
  M13mp18 hypothesis.
- Image screening found 115 sufficiently long horizontal color spans. Even the
  longest surviving core has three length-compatible spans, with multiple start
  offsets and both directions unresolved. Color paths have unclassified endpoint
  identities and can include scaffold or annotation strokes. Length matching is
  therefore reported only as candidate evidence, even if a future case has a
  single surviving span; it does not create native routing.

The default upload-to-report path uses smaller explicit budgets: the existing
8-/6-base passes, four one-second anchor challenges, at most 12 anchor-guided rows
with beam width 16, and two one-second local neighborhoods. The larger exploration
above is not the default request-time completion claim. Source evidence and the
compact reconstruction report include anchor, refinement, gap and image-matching
results. No D014 native part is created until strand identity, image lane/register
and crossover connectivity are supported. Evidence and reproducible probes are
under `.development-artifacts/d014-stable-anchors/`.

Visual correction after inspecting the length-screen candidates (2026-11-26):
the three spans for the 27-base `cyl_lip / Pal` core (`p49-r230`) follow **blue
scaffold strokes**, at visible helices 80, 89 and 0. They are not three supported
staple placements. The current length-only screen does not classify scaffold vs
staple lanes or recover whole-strand endpoint/crossover identity. Describing this
as three physically plausible staple alignments overstates the result. The next
required image step is lane/strand classification and connected-path recovery.
The original numerical report is retained; the visual review is recorded in
`.development-artifacts/d014-alignment-review/review.json` and the annotated
source figure `alignment-issue.png`. No native structure or algorithm changed
in this visual-review task.

### Scaffold/staple classification and connected tracing — 2026-11-26

The ISSUE-265 raw-stroke matching path has been replaced. New
`publication_lane_classification.py` detects two horizontal lanes per observed
row, identifies a recurrent scaffold-color/alternating-lane pattern, and requires
local color evidence before classifying each row. The scaffold hue is learned,
not fixed to blue. Blue staples can therefore remain staples; contradictory or
insufficient evidence leaves rows unclassified. These are layout hypotheses for
supported upright caDNAno panels, not helix-label or molecular-polarity inference.

`publication_staple_tracing.py` renders each panel's **visible PDF composition**,
so overlapping assets cannot reveal hidden strokes. It traces the chromatic pixel
skeleton without closing gaps. Distinct-color four-way intersections can be
paired only when each color has two coherent, opposite continuations and the
lane roles do not conflict. Same-color junctions, unsupported color changes and
missing pixels remain unresolved. Connected traces retain their source points,
hue evidence, horizontal domains, primitive IDs, crossing evidence and endpoint
degrees. A trace ending at a junction is a fragment; even an unbranched trace is
not a complete strand because terminal markers and crop/compression breaks are
not yet distinguished. Truncated graphs never claim unbranched staple traces.

Sequence-to-image screening now accepts only classified staple domains on traces
with supported color continuity. Scaffold, mixed-role, unclassified and
color-uncertain strokes are excluded; missing classification never falls back to
the old raw length screen. Reports retain trace/domain IDs, possible offsets and
both traversal senses. The Detect designs evidence panel displays supported
placements and staple trace counts, explicitly warning that these may be
fragments rather than complete strands.

D014 source-only verification (Figure 31, PDF page 45):

- All three previously highlighted false positives are classified as scaffold
  and excluded from matching. The original source file hash is unchanged.
- Two of four image placements support the lane pattern: 32 observed rows in
  the flap and 30 in the upper-left panel. The two overlapping lower-left asset
  placements remain unsupported in the visible composite; hidden original
  pixels are not substituted to make them pass.
- 309 staple trace observations are retained, including 99 unbranched pixel
  traces. These are **not counts of recovered staples**. Dense crossings and
  compression still produce fragments. One coherent connected fragment spans
  the staple lanes at visible helices 64 and 67; it is shown in the source review.
- One distinct-color crossing is resolved in the source; many junctions remain
  ambiguous. Synthetic source-image tests cover additional distinct-color and
  same-color crossing cases, missing-pixel gaps, alternate scaffold colors,
  blue staples, occlusion and trace-budget exhaustion.
- The anchor screen excludes 303 scaffold-domain observations. The longest
  27-base core now has one length-compatible **staple** fragment, at visible
  helix 89, with multiple offsets and both directions unresolved. This does not
  establish that it belongs to the table's cyl_lip/Pal staple.
- Full-page registration/classification/tracing plus anchor screening took
  approximately 6.22 seconds in the focused probe. No native D014 part was made.

Reproduction and annotated source review:
`.development-artifacts/d014-staple-tracing/`. Native routing still requires
terminal-marker recognition, ambiguous-junction recovery, table-strand identity,
absolute base registration and sequence-supported polarity.

### Same-helix offset connector evidence (D014)

The tracer now recognizes continuous same-lane detours with flanking segments
or terminal lane contacts. Drawing excursions are excluded from paired-domain
lengths: their pixel length is not a nucleotide count. A bounded graph search
retains competing attachments without merging ambiguous branches. Separate
annotations retain partial offset runs and small dark endpoint-marker observations;
neither proximity nor a marker creates a native ligation or assigns polarity.
Dark neutral ink is screened against local empty-grid brightness.

Source regressions cover the user's lower-base-side examples at visible helices
86 and 89. Helix 89 yields an offset-run hypothesis with unresolved left attachment
continuity; hue quantization separates some nearby green/teal ink. Helix 86 retains
a weak marker observation: one pixel passes the current dark-ink threshold. This
is a detector limitation, not evidence that the source has no further information.

The full-page probe takes 7.44 seconds and retains five partial connector
hypotheses, zero complete connector drawings, and 325 staple trace observations
(95 unbranched). These are not recovered-strand counts. The upper-left connector
search reaches its 12,000-state cap; marker observations reach their 100-per-panel
cap in both supported panels. Truncation and uncertainty remain in source evidence.
The full 219-row production package takes 19.80 seconds, retains 4,721 compatible
paired bases in its bounded candidate pool, and produces a report without a native
part. No additional native route or coverage gain is established by this update.
Absolute registration, strand identities, endpoint continuity and polarity remain
unresolved. Two of four panel placements still support lane classification.

Review and reproducible probes are in
`.development-artifacts/d014-connector-drawings/`, including `connector-review.png`.
The real-PDF regression is marked slow/headless after a 5.2-second observation;
focused validation includes it explicitly. Synthetic geometry tests remain fast.

### Correction: base-index labels and sequence-supported continuity

The user identifies the previous helix 86 dark-pixel observation as a bp-index
label, not an endpoint. Single-pixel neutral components are now excluded from
endpoint-marker hypotheses; this is a noise/glyph rejection rule, not an OCR
claim about every isolated pixel. The previous annotated review is superseded
on this point. The source-PDF regression asserts that this false marker is absent.

Small gaps in raster ink are not evidence of strand breaks. The sequence stage
now enumerates same-lane, same-color fragment pairs separated by up to three
missing pixels, retaining both directions and possible registers when an exact
table/scaffold core spans both fragments. Sequence mismatches, larger gaps and
other rows do not pass this screen. The source image scale is retained so that
"three pixels" is measured in the actual extraction raster. Original fragments
remain available, and no native topology is changed by this candidate search.

Partial offset-connector evidence, including the user's helix 89 example, is
sufficient to continue checking sequences without perfect pixel continuity.
Reports include `sequence_fallback.image_continuity` with conditional continuity
candidates and endpoint-supported sequence checks. Exact scaffold complementarity
is checked against table bases; image identity and absolute register are separate
unresolved constraints. A short core match must not be presented as proof of an
entire table staple's placement. The current small-gap search handles fragment
pairs; multi-gap chain assembly and global image-register resolution remain work.

Endpoint-adjacent fragments below the stable-core cutoff also receive a bounded
exact search of table substrings against the circular scaffold reverse complement.
This retains up to 32 matches per connector (with truncation explicit), including
both image traversal directions. Short matches are candidate identities only;
repeats and missing absolute registration prevent uniqueness claims.

D014 verification of this update: two conditional small-gap candidates and 32
endpoint-adjacent exact matches for helix 89, reaching the per-connector cap.
These are ambiguous short matches, not 32 recovered staples. The full 219-row
package takes 20.07 seconds; native routing remains unresolved. Focused tests:
42 passed, then 11 affected tests passed after adding short-fragment searches.

## Output classification

Downloads now include a per-package index and a readable result summary.
See [reconstruction output and source triage](publication_reconstruction_triage.md)
for the issue schema, D014 feasibility assessment and source comparisons.
