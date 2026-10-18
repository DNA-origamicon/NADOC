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

## Single next bounded task

**ID:** S59 — Bend/Twist large-part preview performance.
**Tool / contract items:** Bend/Twist; C8 (parent FH-20).
**Status:** Unstarted. No blocker.
**Objective:** Bring per-change preview on an 18hb×504 scaffolded+stapled part within 2× budget
(≤ 1.0 s) and reduce Open (5.8 s), without changing geometry or weakening bounds.
**Inputs:** S58 measurements; profile of `evaluate` (native projection `project_for_deformation_preview`,
`_inputs` re-admission of prefix each call, `copy_prefix` deepcopy) and of `prepare` (full prefix replay).
**Deliverables:** Measured profile; the smallest change(s) removing repeated per-call work (for
example caching the prefix admission/projection already done at prepare); before/after timings
at 6hb×126, 18hb×252, 18hb×504; browser-side render time for one evaluate.
**Files:** `backend/api/part_deformation_preview_dto.py`, `part_deformation_preview.py`,
`backend/core/part_dna_comparison.py` only if needed; real-scale test.
**Acceptance:** Identical display payloads before/after (exact JSON equality on fixtures);
`tests/test_deformation_preview_real_scale.py` and focused preview modules pass.
**Exclusions:** Geometry/constants/topology changes, new lifecycle layers, other tools.
**Stop condition:** Budget met, or the remaining cost is attributed to a named phase with numbers.

## User decisions pending

1. C9: keep the legacy editor permanently as the fallback for unverified saved files, or plan an
   explicit "convert history to verified" migration (needs `.nadoc` migration approval).
2. Whether the 13 pre-existing `test-smart` failures (sealed-path and junction-balance) should be
   triaged now; they are outside Bend/Twist.

## Session discipline and Git

One task per session; ≤15 appended plan evidence lines; no new reports. Handoff ≤150 lines.
Ledger only for milestone changes; memory only for gate flips or milestone closure.
S58 commit: explicit overhaul-only paths (see the commit body); mixed/shared files excluded.
