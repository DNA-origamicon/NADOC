# Refactor 10-I — `pathview.js` palette extraction + console.log gating

**Worker prompt. (c)+(b)+(d) hybrid: extract palette + gate debug logs.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` Findings #6 (Pass 2-A main.js console.log gating reference), #23 (Pass 8-A audit; pathview.js #2 god-file candidate; 24 ungated console.log + 48 hex colors)
4. `frontend/src/cadnano-editor/pathview.js` — skim to confirm signal counts; identify palette and debug-log clusters

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

Two small targeted improvements, single pass:

1. **Palette extraction**: identify hex-color constants used as fill/stroke values; move to `frontend/src/cadnano-editor/pathview/palette.js` if there's a clear constants block, OR identify the top ~20 most-repeated colors and define them as module-private constants at the top of pathview.js (palette-on-the-spot, not a separate file).
2. **Console.log gating**: wrap the 24 ungated `console.log` calls behind a `DBG` constant (`const DBG = false;` at module top). Same pattern as Pass 2-A's `window.nadocDebug.verbose` for main.js; here it's module-local.

**Recency caveat**: pathview.js was recently touched (cadnano-editor commits 8228205 / 07d3256). If pre-state shows the file dirty in master OR the commit log shows a touch within the last 5 commits, **STOP and report** — defer until cooled.

## In scope

- Read all 24 `console.log` callsites; confirm each is dev-debug (not user-facing event). If any look user-facing (e.g. error path, one-shot info), leave unconditional.
- Add `const DBG = false;` near top of pathview.js.
- Wrap each dev-debug console.log: `if (DBG) console.log(...)`.
- For palette: pick whichever fits — separate file (if a clean color-constants block exists at module top) or in-file constants (if colors are scattered across draw functions).

## Out of scope

- The 4076-LOC body of `pathview.js` itself — leave ALL drawing logic untouched
- Other cadnano-editor files
- Hex colors in any other frontend file

## Verification

3× baseline. Frontend lint + tests.

```bash
git log --oneline -5 frontend/src/cadnano-editor/pathview.js   # recency check
git status -- frontend/src/cadnano-editor/pathview.js   # dirty check
for i in 1 2 3; do just test > /tmp/10I_test_pre$i.txt 2>&1; done
just lint > /tmp/10I_lint_pre.txt 2>&1
```

USER TODO: smoke-test the cadnano-editor sub-app (load a saved design, verify path view renders strands, crossovers, nicks).

## Stop conditions

- Step 0 fails → STOP
- pathview.js is dirty in master OR was touched in last 5 commits → STOP, report (recency caveat)
- Any console.log message looks like a user-facing event/error → leave unconditional, document
- Tests fail post-change → revert, STOP

## Output (Findings #37)

Required:
- DBG flag added Y/N
- N console.logs gated (target: most of 24)
- Palette: Y/N extracted; if Y, file path + LOC; if N, in-file constants
- Lint Δ
- USER TODO for in-app verification
- Linked: #6 (debug-log gating precedent), #23 (parent audit)

## USER TODO template
1. `just frontend` and load a saved cadnano design
2. Open the Path View — confirm strands, crossovers, nicks render correctly
3. Try drag-to-resize a domain; confirm path updates
4. Set `localStorage._nadocPathDbg = true` (or however the gate is exposed) and reload — confirm console.logs reappear (proves gate works)
5. Reset; confirm DevTools console clean

## Do NOT
- Touch drawing logic
- Change palette values (move verbatim)
- Commit / append to REFACTOR_AUDIT.md
