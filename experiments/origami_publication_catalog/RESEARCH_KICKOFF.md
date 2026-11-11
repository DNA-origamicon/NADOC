# DNA origami literature census kickoff prompt

Paste the following prompt into a new session opened at your NADOC checkout root.
Follow [machine setup](RESEARCH_SETUP.md) first when using another machine.
The supporting protocol and checkpoint live alongside this file.

```text
Set a persistent goal to build an auditable census of pre-2020 publications
presenting, modifying, or reusing DNA-origami designs, and progressively review
their designs and source material. Work toward completion across resumable
batches; do not stop after planning or after a single batch when useful work
remains. Do not assume a fixed upper bound on publications or designs.

First read AGENTS.md, CLAUDE.md, and these files under
experiments/origami_publication_catalog/:
  RESEARCH_PROTOCOL.md
  RESEARCH_SETUP.md
  RESEARCH_CHECKPOINT.md
  README.md
  SEARCH_COVERAGE.md
Inspect the actual registries and acquisition reports before trusting the
checkpoint's historical counts. If a matching goal already exists, continue it
rather than creating a duplicate. Do not impose an invented token budget.

Implement the durable screening and discovery ledgers described in the protocol,
preserving existing evidence and stable IDs. Then perform real literature review.
Start with unresolved named candidates and downloaded ACS supplements, while
rotating through the full backlog so low-keyword records are not neglected.
First exclude patents. Before detailed article/design review, check readily
available sources for a staple table/list with at least 100 DNA sequence entries.
If none is found, record no_qualifying_table_found and the sources checked, then
move on. Keep unavailable or unextractable sources explicit; do not equate them
with proven absence. Do not pursue extra access routes or human requests solely
to rescue these records. Reopen only on new source evidence or user instruction.
Passing this gate does not certify a complete design or catalog eligibility.

Record supported classifications, design-level evidence, and unresolved cases.
Distinguish broad literature relevance from the existing catalog's narrower
lattice and source eligibility rules; do not silently expand that catalog scope.

Finish bibliographic discovery without arbitrary relevance caps. Follow backward
and forward citations and search the publication histories of Carlos Castro,
Hendrik Dietz, Shawn Douglas, William Shih, Hao Yan, Peng Yin, Andrew Turberfield,
Mark Bathe, Tim Liedl, Lulu Qian, Friedrich Simmel, Philip Tinnefeld, Jonathan Doye,
Thomas LaBean, and Paul Rothemund. Defer FNANO programs and abstracts until other
search methods demonstrate diminishing returns. These routes
have NOT already been exhaustively run. Treat conference records as leads with
their own publication type and reconcile them to journal articles and preprints.
Never treat an attendee list or an abstract as proof of a complete design.

Use scripts for acquisition, extraction, indexing, deduplication, and checkpointing.
Make article and design decisions from inspectable evidence, not keyword matches
alone. Keep inaccessible and uncertain cases explicit. Validate saved outputs,
audit exclusions, and report progress using denominators with clear meanings.

Public ACS supplement retrieval is already working. Reuse the existing paced,
resumable downloader; do not restart successful downloads. CU Boulder VPN access
may be available through Windows, but verify current access before depending on
it. If private login is necessary, explain the exact blocked resource and give
the user a way to authenticate privately. Never request credentials in chat or
store credentials, cookies, or tokens in research logs. Continue independent work
while an access issue awaits resolution.

This authorizes literature research, source acquisition, catalog maintenance,
and the supporting research scripts. It does not request molecular reconstruction,
simulation, edits to production NADOC behavior, contacting authors, or remote
publication. Preserve unrelated worktree changes. Do not commit or push.

After every batch, save the ledger and update RESEARCH_CHECKPOINT.md with actual
counts, evidence paths, validation results, blockers, and a concrete next queue.
Keep working while meaningful unblocked tasks remain. At a session boundary,
leave a reproducible handoff. Do not declare the goal complete merely because a
batch finished or a search returned no more results; apply the protocol's closure
criteria and disclose any unresolved coverage gaps.
```
