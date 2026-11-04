---
name: project_autoscaffold_single_strand
description: ISSUE-8 autoscaffold single-strand rework — why crossover-merging fails and the validated decompose+2-opt-splice approach
metadata: 
  node_type: memory
  type: project
  originSessionId: e8eafa48-297e-4c65-8397-7de37a254477
---

# Single-scaffold routing

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## End-turn staple clearance — 2026-11-03

Continuation follow-up: editing `test.nadoc`'s last Sweep point to `(8,38,36)`
shortens its tracks from 232 to 221 bp. Automatic matched ends demanded 22–26 bp
of far extension on eight tracks, exceeding the existing 21-bp honeycomb window.
Automatic seamed routing now retries the existing closed local end-turn route
from fresh input when its first candidate exceeds that window. Explicit matched
requests still refuse; all continuity, single-scaffold, junction, seam, clearance
and window checks remain. Windows are measured against the existing structural
reset, so prior route caps cannot ratchet the allowance on repeated routing.
Regression: `tests/test_scaffold_continuation_fallback.py` includes new-loadout
history edit, unchanged Main, guarded publication/reopen/replay, explicit matched
refusal and idempotence. Implementation is in the November3 integration worktree.

Seamed/matched candidate selection checks the final normalized crossover site on
both helices against `MIN_SSDNA_MARGIN`. A near candidate that moves too close
when normalized to bow-right is skipped for the next outward legal site. Far-end
translation reserves clearance after the existing left-partner adjustment and
advances the common repeat period if a pair is still obstructed. Local/bounded
searches likewise filter by staple clearance within their existing end windows.
Crossover tables, nick rules, continuation bounds and transaction guards remain
unchanged. Regression: `tests/test_scaffold_end_clearance.py` (recorded same-cell
extrusion/Sweep, independent replay, and far-face alignment cases).

## Continued helices — 2026-10-08

User-confirmed contract: Sweep from a blunt end preserves the existing duplex
backbone across the segment boundary. In `Sweep_test` all six source tracks
continue through bp 62/63; only the four added tracks have ends there. Both modes
must route one scaffold while retaining all twelve scaffold/staple interface
bonds, including bonds explicitly recorded as forced ligations. See
[`docs/scaffold_routing.md`](../docs/scaffold_routing.md).

`backbone_continuations.py` recognizes authored connections from strand order and
sweep attachment/forced-ligation provenance. The loader no longer invents forced
ligations for ordinary sweep joins. `scaffold_continuations.py` contracts connected
segments into a temporary routing view, then restores the original helix IDs,
frames, deformations, staple strands and forced-ligation records. Reroute/reset
operates on that view, so it cannot drop the internal connections. A nick on the
scaffold does not erase track continuity established by the complementary strand.

Heterogeneous tracks use `scaffold_face_paths.py`: seamed end-turn pairs share both
free faces; seamless traversal pairs the actual outgoing free face. Seamed routing
uses local end turns rather than applying one matched translation to unequal
lengths. The adapter rejects lost connections, fragmentation, excessive extension,
invalid junctions, missing buried closure, or seams in a seamless result.
Nonconsecutive or inserted-base forced junctions are not flattened into ordinary
backbone. Integration coverage: `tests/test_scaffold_continuations.py`.

## Routing integrity update — 2026-09-22

R1–R9 regressions are covered by `tests/test_routing_integrity.py`. Public seamed,
bounded, matched, and seamless routes are transactional: an occupied extension or
invalid direction rejects the candidate without changing the design or feature history.
Reset now acts only when an automatic-route marker exists, preserves disjoint scaffold
coverage, and declines to rebuild mixed stapled/unstapled paths or explicitly manual
scaffold crossovers. Forced ligations still bypass reset; routing additionally protects
their directed backbone edges and original records, including extra bases and periodic
seam metadata. Assigned scaffold sequence follows nucleotide identity through reset and
routing (including insertions/deletions); newly added material receives `N`.
The older “staples are the design” statement below is limited by these protections.
See `docs/audits/topology_conversion_20260922/routing_resolution.md` for verification
and the remaining conversion findings, which were not changed in this work.

<a id="-issue-9-fixed-2026-07-13--autoscaffold-is-now-idempotent-backendcorescaffold_resetpy"></a>
- [✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`)](details/project_autoscaffold_single_strand/01-issue-9-fixed-2026-07-13--autoscaffold-is-now-idempotent-backend.md#-issue-9-fixed-2026-07-13--autoscaffold-is-now-idempotent-backendcorescaffold_resetpy)

- [✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`) — continued detail](details/project_autoscaffold_single_strand/02-issue-9-fixed-2026-07-13--autoscaffold-is-now-idempotent-backend.md)

- [✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`) — continued detail](details/project_autoscaffold_single_strand/03-issue-9-fixed-2026-07-13--autoscaffold-is-now-idempotent-backend.md)
