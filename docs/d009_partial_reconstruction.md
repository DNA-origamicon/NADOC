# D009 partial reconstruction

The reconstruction compiler can retain supported native routing when the full
source evidence does not converge. `--allow-partial` is enabled by default in
`scripts/reconstruct_publication_design.py`; strict compilation remains available
with `--no-allow-partial`. The article dialog downloads a ZIP containing native
parts, reports, PDF sources, and recipes. No active editor document is replaced.

Partial refers to source completeness, not construction-history completeness.
Every included strand is built through recorded editor operations. Unsupported
routes are omitted, never represented by invented placeholder strands. Native
publication and independent saved/reopened replay gates still apply. A failed
construction/publication returns a report without a misleading native model.

## Scaffold gaps and fine routing

Scaffold coverage is collected as an arbitrary number of disjoint intervals.
Unpaired staple portions in those gaps use native OverhangSpec/domain ownership,
just like portions beyond the outer scaffold ends. Routing coordinates, polarity,
and sequences are preserved; no terminal extensions are substituted. Internal
unpaired portions can have paired routing on both sides.

Initial ordinary staple pens span each helix's accepted staple extent, including
internal gaps. Recorded nicks isolate unsupported intervals, which are removed
by the ordinary strand-delete operation before final crossovers and sequence
assignment. Explicit nonlocal/polymerization staples remain separate.

## Table-only route search

The bounded search uses source table endpoints/length/sequence, the independently
aligned scaffold, recovered helix polarity/lattice, native crossover sites, and
exclusion of occupied staple sites. Paired bases must match exactly. Unpaired
bases use the supplied table sequence. Candidates cannot revisit a site.

Two witnesses establish ambiguity; an exhausted state budget never establishes
uniqueness. Individually unique routes are also checked against one another for
occupied-site conflicts. Uniqueness is conditional on this graph: nonlocal forced
joins and sequence mismatches are not silently admitted.

D009 has seven unique candidates, two ambiguous entries, and one with no route
under these constraints. Repeating the search with the seven accepted routes
occupied does not remove the remaining ambiguities. The two ambiguous entries have one strongly paired
candidate and a much less paired alternative; neither is silently chosen:

| Table endpoints | Result | Paired/unpaired bases in witnesses |
|---|---|---|
| 2[292] → 19[292] | Unique | 24 / 2 |
| 4[292] → 5[306] | No match | — |
| 6[300] → 13[292] | Ambiguous | 47 / 1; 8 / 40 |
| 8[292] → 9[292] | Unique | 24 / 2 |
| 12[286] → 13[272] | Unique | 28 / 0 |
| 15[273] → 7[292] | Unique | 33 / 1 |
| 16[292] → 17[272] | Unique | 33 / 1 |
| 18[292] → 17[292] | Unique | 24 / 2 |
| 19[273] → 3[292] | Unique | 33 / 1 |
| 20[292] → 21[272] | Ambiguous | 33 / 1; 5 / 29 |

The saved partial contains 194 of 197 table staples. The omitted three contain
119 bases. The source scaffold is represented by 7703 bases with two 39-base
insertions. The accepted p7704 one-base discrepancy is explicitly documented as
the nick-boundary alignment hypothesis: the unrepresented library index is
retained in the report and the recorded sequence assignment explains it. This
is not a claim that the omitted base's physical location is established.

Image/table conflicts remain notices, with strongest evidence winning and
T > A > C > G breaking equal-support ties. The report retains source observations.

## Native verification

`workspace/Shared Designs/D009.nadoc` passed exact included-route/sequence/overhang
comparison, guarded publication, and independent saved/reopened replay. It has
1592 recorded operations, 46 initial staple pens, 285 overhang bases and 14873
total nucleotides. All 14678 backbone edges have geometry; six exceed the 1.2 nm
display envelope (two nonlocal joins and four insertion-loop boundary edges).
The model is unrelaxed; these are not hidden by the partial-completeness label.

Validation completed: 67 focused backend checks, 13 UI tests, and two running-app
flows (welcome/open and real native reconstruction download). The browser
autosave and downloaded model both pass independent replay and included-source
comparison. Temporary workspaces/configurations were removed; the shared part
was unchanged apart from ordinary workspace identity stamps. The analysis
response in the download browser test uses previously computed source evidence;
native reconstruction calls the real endpoint and re-extracts the uploaded PDF.

Source colors and caDNAno row ordering are now preserved; see
[publication appearance](publication_appearance.md). The additional recorded
operation reorders display rows while retaining visible helix labels.
