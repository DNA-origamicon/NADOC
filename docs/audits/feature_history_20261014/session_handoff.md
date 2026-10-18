# Dependency overhaul session handoff

Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Updated: October 18, 2026 (S58, Claude session). **Sessions since last gate flip or milestone close: 0**
(reset: Bend/Twist production gates flipped, user-authorized).
**Tools done: 0/4** — Bend/Twist gates are ON but two contract items remain (C8 large parts, C9
decision), so they are not counted done. CAD ledger: **20/34 complete, 14 remaining (7 core, 7 parked)**.

## Current state

User authorized (October 18): raise the isolated preview's toy allowances, admit ordinary
routing/scaffold/staple commands in prefix replay, enable the three Bend/Twist gates in
production and update the tests/harness that assumed them off.

- **Gates ON:** `DEFORMATION_PREVIEW_ENABLED` (backend), `ISOLATED_DEFORMATION_HISTORY_ENABLED`,
  `ISOLATED_DEFORMATION_CREATION_ENABLED` (frontend). Sweep/transform/routing gates unchanged (off).
- **Real-size parts work.** Allowances in `part_deformation_preview.py`,
  `part_dna_comparison_contract.py`, the DTO output budget and session capture/Apply deadlines
  are sized for ordinary parts. `ORDINARY_UNESTIMATED` admits deterministic routing kinds
  (auto-scaffold, autostaple, auto-break, sequences, helix/strand/domain edits, patterns);
  imports, nanoparticles, proteins, photoproducts, relax and autorefine kinds stay refused.
- **Legacy fallback.** All saved workspace files lack a recipe root, so the isolated editor refuses
  them; history Edit, the toolbar/sidebar launcher and blunt-end menus then continue the same
  gesture in the legacy editor (`onUnsupported`, codes in `UNSUPPORTED_PART_CODES`).
  New designs verify through ordinary steps and use the isolated editor.
- **C4:** an Apply that breaks a downstream feature is refused, names it ("F3 Bend cannot
  regenerate after this edit: …") and publishes nothing.
- **Measured (C8):** see the [Bend/Twist plan S58](bend_twist_release_acceptance.md). Isolated
  preview is faster than legacy at all sizes; 18hb×504 preview (1.55 s) is ~3× the 500 ms budget.

Contract status, Bend/Twist: C1–C7 pass (bounded fixtures plus the 6hb real-scale host test);
C8 partial (large parts over budget); C9 open: legacy path retained as fallback for unverified
files, which needs a user decision (keep permanently vs. offer migration to verified history).

Validation: focused frontend 194 passed; `just test-frontend` 773 files / 9306 passed, 1 skipped;
history browser suite 38 passed (10.0 m), cleanup verified; focused backend modules pass;
`just test-smart` FAST: 15 failed / 18955 passed / 19 skipped, DEFERRED full suite, FAST SUITE TOO
SLOW (371 s). This change's 4 failures fixed and rerun; 13 pre-existing (10 strict registration
from untracked sealed admission, 1 strict immutable evaluation, 2 junction-balance tolerance).
Not exercised on the user's live dev server.

## R1 incremental rebuild — delivered (S60, October 18, 2026)

Re-plan R1–R5 is in [operating_contract.md §9](operating_contract.md) (user-approved; experimental build).
`backend/core/part_replay_cache.py` hash-chains the explicit root and exact command inputs.
A full-key hit returns the cached result; for geometry-only Bend/Twist edits, commands in
`DEFORMATION_INDEPENDENT` (seamless/seamed/matched auto-scaffold, autostaple, auto-crossover,
auto-break, auto-merge) reuse cached topology with the current deformations substituted.
Wired into the preview prefix replay, the Apply-time source proof (`ReplayPrefix` records the
chain position) and `regenerate`. Invariants (deformation writes only `deformations`; listed
kinds pass deformations through and are invariant under deformation parameters) are asserted on
honeycomb and square recipes in `tests/test_part_replay_cache.py`, plus cold-replay equality.

Measured, 18hb × 504 bp ordinary part (host, in-process): Apply after a routed bend 3.5 s → 0.25 s;
bend placed before autostaple: repeat edit Apply 0.16 s (first edit after load still pays one full
proof replay, ~3.2 s). Open 2.4–3.1 s and evaluate 1.4–1.7 s are now display-bound (native
projection, finite checks, geometry arrays, deep copies, byte-check encoding), not replay-bound.

Checks: focused recipe/preview/repair/routing modules pass; `tests/test_part_replay_cache.py`
8 passed; history browser suite 38 passed (10.0 m), cleanup verified; `just test-smart` FAST:
14 failed / 18964 passed / 19 skipped, DEFERRED full, FAST SUITE TOO SLOW (386 s). One failure was
this change (service-read budget test retargeted; 28 pass); 13 pre-existing as before.

## Single next bounded task

**ID:** S61 (still next) — Partial display projection for Bend/Twist preview (R1 follow-on, C8).
**Objective:** Evaluate returns candidate geometry only for helices whose geometry the edit can
change (the deformation's affected helices plus anything downstream that reads deformation
geometry), with the unchanged prefix display reused client-side; Open reuses one projection.
**Acceptance:** 18hb × 504 evaluate ≤ 1.0 s; display equals full projection on fixtures (exact);
browser suite passes. **Exclusions:** geometry/constants changes, new lifecycle layers.

## R2 legacy conversion — delivered (S62, October 18, 2026; user chose option B)

File → **Convert history to verified…** (`ui/history_conversion.js`, `POST /design/history/convert`,
`core/part_legacy_conversion.py`). Rows are upgraded to version-1 contracts where saved inputs are
complete; unseeded deformation-independent routing rows (auto-scaffold, autostaple, auto-crossover,
...) become **frozen** rows (`core/part_frozen_topology.py`: saved output topology, replayed only
when input topology matches the saved pre-state, deformations passed through). The boundary sits
after the last row that is neither; the saved state there becomes an explicit import root, with the
saved file's final document metadata and lazily created default clusters. Accepted only on exact
proof (`reproduced_import`). The open design is replaced as one undoable step and saved under a NEW
name (`overwrite=false`); autosave is pointed at the new file first, so the original is never written.

Workspace survey (in memory, nothing written): 89 files with history; **78 convert exactly**;
34 keep ≥1 editable feature; 94/565 rows (17%) stay editable; **3/8 bends/twists** editable.
Not convertible: 4 files whose baseline exceeds the 1 MB import-root limit (raising it changes
numerical-engine manifests, see below), 1 with a mid-log cursor, 2 >12 MB not surveyed.
Bends stay absorbed when a later row cannot replay: unseeded extrusions (incl. deformed
continuations, which genuinely depend on the bend) or legacy rows the legacy editor left stale
(6hb_curved: loop skips were never recomputed after a later legacy bend edit).

Also fixed: the history proof compared `metadata` wholesale, so any workspace save (identity stamp)
made every native part fail its proof and Apply 409 — `IDENTITY_METADATA_FIELDS` are now excluded
from the reproducibility comparison only (fingerprint unchanged).

Checks: `test_part_legacy_conversion.py` 7, conversion UI vitest 4, browser conversion case
(menu → confirm → file browser → new file; original bytes unchanged; converted bend edits through
the isolated editor) pass; history browser suite 39 passed (9.3 m); `just test-frontend` 774 files /
9310 passed; `just test-smart` FAST 13 failed / 18972 passed (same 13 pre-existing), DEFERRED full.

## User decisions pending

1. Raise the 1 MB import-root limit (`PartRecipeRoot.source_json`): it is in
   `part_history_contract.py`, which the CPD/duplex/streptavidin numerical manifests hash, so it
   needs a recorded schema-compatibility transition. Approve doing that ceremony, or keep the limit.
2. Stale legacy rows (e.g. 6hb_curved loop skips): offer an explicit "re-derive from current bend"
   repair? It would change topology and needs review per file.
3. C9: keep the legacy editor as the fallback for unconvertible files.
4. Whether to triage the 13 pre-existing `test-smart` failures (sealed path, junction balance).

## Session discipline and Git

One task per session; ≤15 appended plan evidence lines; no new reports. Handoff ≤150 lines.
Commits: explicit overhaul-only paths and hunks; mixed/untracked Codex harness and sealed files excluded.
