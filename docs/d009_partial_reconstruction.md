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


## Strand-owned insertion loops — November 26, 2026

The shared D009 was rebuilt from the supplement using the new native
`strand-loop-set` feature for both 39-base scaffold insertions at visible helices
30 and 42, base 119. The same 1,592-command process now records these loops after
scaffold routing and before assigning its sequence. Source route/sequence and
saved/reopened replay checks pass; staple colors, row order and the three omitted
staples are unchanged. No helix-wide insertion marks remain.

This is the general reconstruction preference for multi-base scaffold-only
insertions. Paired and single-base insertions retain their previous semantics.
Native NADOC persistence/display are supported; simulation and cadnano/scadnano
export of these loops remain unavailable. The bond report still records six
spans above 1.2 nm, including four loop-root spans of about 1.25–1.26 nm.

Cold-open performance limitation observed in the real app: with the approved
ring-priority loop geometry, the isolated welcome/open flow returned native
geometry at about 239 seconds after navigation and completed autosave at about
265 seconds. The 90-second check and then its 240-second autosave observation
both expired; the second run nevertheless rendered all 14,873 nucleotides and
successfully saved. The longer visual inspection is diagnostic, not a claim
that normal interactive latency passed. No fit, geometry rule, or production
request timeout was weakened. Evidence is local under
`.development-artifacts/d009-strand-loops/`.

The longer browser observation completed the 3D loop checks (39 rendered bases
per loop), inspected close-ups, and verified caDNAno loop counts, all staple
colors and row order with no app errors. Its inherited 360-second suite limit
expired during teardown, so this is visual/behavioral evidence, not a clean
Playwright runner pass. The actual browser-saved copy subsequently passed independent replay and source
comparison. Cleanup verified removal of the temporary workspace, configuration
and test script, with the shared file unchanged by the browser. No production timing limit was changed.
