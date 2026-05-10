# Refactor 14-A — Fix initial strand-color sync between cadnano editor and 3D view

**Worker prompt. (bugfix) — interrupt-style investigation. Find root cause before fixing.**

## User report (2026-05-10)

> Strand colors do not start out synced between cadnano editor and 3D view. Both appear the correct color after explicit user assignment. Everything else looks fine.

So the symptom is: on initial design load, the two views render strands with DIFFERENT colors. Only after the user explicitly assigns a color (e.g. via the paint palette or color-picker) do both views agree.

## Pre-read

1. `CLAUDE.md` (Three-Layer Law — topology owns `design.strands[].color`; both views are geometric-layer readers)
2. `memory/feedback_crossover_no_reasoning.md` — analogous rule: don't reason geometrically about derived behaviors. Apply here: don't guess which view is "wrong" — trace the actual color values both views read on initial load.
3. `memory/feedback_design_renderer_visibility_rule.md` if it exists — hiding design touches 4 modules; color may have similar multi-module touch surface.
4. `.claude/rules/rendering.md` and `.claude/rules/cadnano-2d.md` if they exist (path-scoped architecture maps)
5. `frontend/src/scene/helix_renderer.js` post-Pass-10-H — uses `STAPLE_PALETTE` from `helix_renderer/palette.js` and reads strand colors via `buildStapleColorMap`
6. `frontend/src/cadnano-editor/pathview.js` post-Pass-10-I — has its own `pathview/palette.js` with 30 hex-color constants; uses CADNANO_PALETTE
7. `backend/core/models.py` — `Strand.color` field definition + default
8. `backend/core/sequences.py` and any strand-coloring code (auto-assign-staple-colors)

## Step 0 — CWD safety (precondition #15 HARDENED)

```bash
pwd
git rev-parse --show-toplevel
if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
    echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
    exit 1
fi
```

## Goal

**Phase 1: Investigation.** Identify root cause. Required deliverables:
1. What value is in `design.strands[i].color` on a freshly-loaded design (before any user action)?
2. What color does the 3D view (`helix_renderer.js`) render that strand as?
3. What color does the cadnano editor (`pathview.js`) render that strand as?
4. If 2 and 3 differ from each other or from 1, which one is wrong, and where in the code does the divergence happen?
5. Why does explicit user assignment make them sync? (i.e. what code path runs on color-assignment that doesn't run on initial load?)

**Phase 2: Fix.** Once root cause is identified:
- Fix the root cause, not the symptom
- Both views should read from `design.strands[i].color` on initial load + after every mutation
- The fix should be minimal — likely a missing sync call, an incorrect default, or a stale-cache issue
- Do NOT change the canonical color storage location (`design.strands[i].color` is the source of truth per Three-Layer Law)

## In scope

### Investigation tools

- Read both rendering pipelines end-to-end for the color path
- `console.log` snippets are OK in the worktree for the diagnosis phase but MUST be removed before final commit
- Use `just dev` + `just frontend` to reproduce the bug. Load any saved `.nadoc` (e.g. `Examples/teeth.nadoc`) and visually compare the two views' strand colors before any user action
- Compare to behavior post-color-assignment (paint a strand a different color via cadnano palette) — what changes?

### Likely failure modes (don't assume, but check)

- **Initial null/undefined color**: maybe new strands get `color = null` and one view has a fallback to a palette index while the other has a fallback to gray
- **Auto-staple-coloring runs only on user trigger**: maybe `assignStapleSequences` or a similar endpoint auto-colors but isn't called on `/design/load`
- **Color map cached in renderer**: `buildStapleColorMap` may compute on first render but not invalidate on `setState({design: ...})` — first render uses initial values, subsequent updates re-read
- **Different palette modulo**: both views could use the strand-id-modulo-palette-length pattern but with different palette lengths or different modulo math
- **Sequence-mode override**: if `colorMode === 'sequence'` is the default in one view but not the other, they'd render differently

### Out of scope

- Refactoring color-handling beyond the fix (no leaf extraction in this pass)
- Changing the user-facing palette values (CADNANO_PALETTE / STAPLE_PALETTE both stay)
- Touching atomistic rendering color cascade (separate)
- The 3D view's strand-color-mode UI (Strand Color / Domain / Sequence) — those work post-user-action per user; just fix initial sync

## Verification

3× baseline + lint + vite + vitest:

```bash
for i in 1 2 3; do just test > /tmp/14A_test_pre$i.txt 2>&1; done
just lint > /tmp/14A_lint_pre.txt 2>&1
cd frontend && npx vite build > /tmp/14A_vite_pre.txt 2>&1
cd frontend && npx vitest run > /tmp/14A_vitest_pre.txt 2>&1
```

Post:
- vite build PASS
- vitest PASS
- backend tests ⊆ baseline
- Lint Δ ≤ 0
- All diagnostic `console.log` calls removed
- **CRITICAL**: USER TODO must specify exactly how to verify the fix in-app

## Stop conditions

- Step 0 fails → STOP (literal `exit 1`)
- Root cause can't be determined from code alone (e.g. requires server-side state inspection on the user's machine) → STOP, report findings + propose specific question for user
- Fix requires touching the Three-Layer-Law topology layer in a non-obvious way → STOP, escalate per CLAUDE.md "When you don't know"
- Multiple plausible root causes — pick the most likely + flag the alternatives for user confirmation before merging

## Output (Findings #50)

Required:
- **Root cause diagnosis**: 1-3 paragraphs explaining where the divergence happens, with file:line citations
- **Fix description**: minimal diff + why this fix addresses the root cause
- **Why explicit user assignment masked the bug**: trace the code path that runs on assignment that wasn't running on load
- vite build status
- vitest pass count
- Backend test failure set
- Lint Δ
- USER TODO with explicit reproduction steps + verification steps
- Linked: applicable Pass 13 audits (#46 cadnano-editor or #23 frontend audit), `feedback_design_renderer_visibility_rule.md` if relevant

## USER TODO template (worker fills in)

1. `just dev` + `just frontend`
2. Load `Examples/teeth.nadoc` (or whichever design the user originally tested with)
3. **Pre-fix expected**: 3D view + cadnano editor show different strand colors (the bug)
4. **Post-fix expected**: both views show identical strand colors on initial load (without any user action)
5. Paint a strand a different color via the cadnano palette → confirm both views still update in sync (regression check)
6. Switch color modes (Strand Color / Domain / Sequence) → confirm both views switch in sync
7. Ctrl-Z → confirm both views revert in sync
8. If all clean, mark Finding #50 USER VERIFIED.

## Do NOT

- Guess which view is "wrong" without tracing the actual color values both read
- Change the canonical color storage (`design.strands[i].color` is source of truth)
- Touch atomistic rendering
- Refactor color-handling beyond the fix
- Leave `console.log` debug statements in the final commit
- Commit / append to REFACTOR_AUDIT.md (manager aggregates)
