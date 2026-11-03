# Memory length cleanup — October 17, 2026

User-requested documentation maintenance is complete: `just lint-memory` now
reports **0 errors and 0 warnings**, down from 0 errors and 60 size warnings.
The 200-line target and 1,000-line error threshold are unchanged. Lint now checks
nested supporting pages as well as top-level memory files.

## Organization

- Reorganized all 60 oversized topic files, preserving their existing filenames
  and original heading destinations for incoming references.
- Reduced routine topic-head reading from **23,201 to 6,843 lines** (about 70.5%).
  The largest edited head is 190 lines.
- Added **210 bounded supporting pages** under `memory/details/<topic>/`:
  186 supporting contract/evidence pages and 24 explicitly historical archive pages.
  Every new page, including archives, is at most 164 lines.
- Retained active contracts, safety rules, open work and current sequencing in
  the heads or their explicitly indexed relevant sections. Sections are linked
  by their original subject headings; existing topic-index entries still work.
- Marked retired BLADE/propagator work and dated investigation/build plans as
  historical. Reorganization does not authorize old campaign or rollout steps.
- Preserved numerical measurements, thresholds, identifiers, provenance, source
  references, unresolved scientific questions and recorded validation limits.
  No scientific evidence was pruned. Relative links were rebased; obsolete paths
  without a file are now explicitly recorded paths rather than broken hyperlinks.
- Moved the test policy out of malformed YAML frontmatter into visible prose.
  Current focused/broad/scientific rules and CPD exclusion remain visible.
- Updated the memory index and hygiene guide to explain supporting pages versus
  historical archives. The feature-history handoff records the new lint state;
  S04 remains unstarted and milestone counts remain 21/38, delta +0/+0.

## Checks actually run

| Check | Result |
|---|---|
| `just lint-memory` after cleanup | 0 errors, 0 warnings |
| `bash -n scripts/lint_memory.sh` | Passed |
| Temporary nested 201-line document | Correctly reports one length warning |
| Temporary nested 1,001-line document | Correctly reports one error and exits nonzero |
| Temporary nested broken Markdown link | Correctly reports missing target and exits nonzero |
| Original-content accounting | All 23,201 source lines assigned once to head/detail ranges; all nonblank content retained after reversing recorded link changes and ignoring one removed trailing space |
| Detail navigation and original heading destinations | 746 detail links resolve; every original heading anchor remains reachable from its original head |
| Local links in the reorganized heads and details | No missing targets, including source-code links and archived pages |
| Recursive size check independent of lint | All 60 heads and all 210 new pages below 200 lines |
| `git diff --check`, plus new-file whitespace checks | Passed |
| Existing unrelated dirty/untracked files | SHA256-identical to the startup snapshot |

The nested fault probes are disposable files, removed in `finally`; the final
zero-warning run occurred after removal. The checks exposed and corrected one
moved duplicate heading anchor and pre-existing broken source/fixture links.
No warning suppression or threshold relaxation was used.

Routing was inspected for the hygiene guide's five retrieval questions: topology
and frontend verification still route through `CLAUDE.md`; MD visualization's
open-work section remains in its head; RunPod preflight/teardown safeguards remain
visible; recurring failures still route through the unchanged LESSONS index.
This is an in-session routing review, not a claimed fresh-agent evaluation.

## Scope and retention

Only memory documentation, its hygiene guide, the handoff's lint-status note and
recursive memory lint were changed. No application/scientific source behavior,
geometry, test guards, rollout gates, user jobs or workspace data changed. No
backend/frontend suite, browser run, simulation, commit or push was performed.
Older pass/fail evidence retains its original dates; it was not revalidated here.

Compact file/range/hash inventory, validation outputs and recursive-lint probe
results are retained in `.development-artifacts/memory-length-cleanup-20261017/`.
Disposable original-content copies and migration scripts are removed after their
preservation checks; the reorganized documentation retains the evidence itself.
