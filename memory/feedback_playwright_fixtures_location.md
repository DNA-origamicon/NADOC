---
name: playwright-fixtures-location
description: All .nadoc files created by Playwright tests go in workspace/playwright_tests/ and are deleted when no longer needed.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d44c6f6a-0587-4ad7-870b-b63171ba6b9b
---

> Scope note: Playwright is now a troubleshooting-only tool, not a routine verification step (too slow for iteration — see [[REFERENCE_PLAYWRIGHT]] and CLAUDE.md "Verification expectations"). This rule applies *when* you do write a spec to repro a bug or clarify behavior.

Playwright tests that create transient `.nadoc` fixtures (saved designs, "New design" outputs, intermediate exports, etc.) MUST write them under `workspace/playwright_tests/` — not at the top of `workspace/`. Delete the fixture as soon as the test no longer needs it (in test teardown, or at the end of the spec).

**Why:** Past test runs already littered `workspace/` with `CT-tab-test_*.nadoc`, `DD-test.nadoc`, and similar one-shot files alongside real designs. Mixing them makes it harder to find the user's actual fixtures (e.g. `hinge.nadoc`, `Examples/teeth.nadoc`) and risks accidentally loading a stale test artifact. A dedicated subfolder keeps test detritus quarantined; aggressive cleanup keeps it from accumulating across runs.

**How to apply:**
- When writing a new spec that calls `POST /api/design/save`, `File → Save`, the "New design" flow, or any other path that produces a `.nadoc` on disk: route the path through `workspace/playwright_tests/<spec>-<n>.nadoc`. Create the directory on demand if missing.
- Before claiming the spec done, add a `test.afterEach` / `test.afterAll` (or inline `fs.unlinkSync` at the end of the `test()` body) that deletes anything the spec wrote.
- Tests that only READ existing fixtures (`workspace/hinge.nadoc`, `Examples/*.nadoc`) are unaffected — this rule covers test-generated files only.
- If you see `CT-tab-test_*.nadoc` / `DD-test.nadoc` / similar at the top of `workspace/`, treat them as legacy debris from earlier work — safe to delete, and confirm with the user before bulk-removing if more than a handful.

**Auto-saved File>New parts (added 2026-06-03):** the harness/gesture specs create parts via the
real File>New flow, which auto-saves to `workspace/` *root* (you can't redirect it to
`playwright_tests/` without touching app code). Policy for those: name the part with the `__e2e__`
prefix (the shared harness `frontend/e2e/helpers/scene_harness.js` `loadScaffoldedPart` does this;
do the same in any new gesture spec / File>New test), and let the Playwright `globalTeardown`
(`frontend/e2e/global-teardown.js`, wired in `playwright.config.js`) delete
`workspace/__e2e__*.{nadoc,nass}` after the run. `workspace/` is gitignored, so this is local-only.
Same spirit as the rule above (quarantine + aggressive cleanup), just via a name prefix because the
save path is fixed by the app.

Related: [[REFERENCE_PLAYWRIGHT]] — the canonical E2E patterns + helpers; reference that file when wiring fixture paths.
