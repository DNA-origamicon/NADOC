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

**A spec that OPENS an existing design and edits it through the UI writes to that file (2026-08-02).**
This is the sharper version of the rule above, and it bit: a throwaway verification spec loaded
`workspace/6hb_sim_v2.nadoc` from the welcome screen, clicked "+ New animation" and "Add trajectory
keyframe", and the app **auto-saved all of it back to the user's design** — three animations across
three runs. `workspace/` is gitignored, so `git status` shows nothing and there is no backup to
restore from; the session cache is no help either (the e2e backend runs with
`NADOC_DISABLE_SESSION_CACHE=1`, and it only snapshots the docs it happens to have open).

**How to apply:** before a spec mutates an existing design through the UI, either (a) copy the
fixture to `workspace/playwright_tests/` first and open the copy, or (b) `cp` the original to the
scratchpad and restore it in `afterAll`. If neither happened and you only notice afterwards:
snapshot the file as-found, work out exactly what the spec added (the pre-run state is often
recoverable by reasoning — count the spec's create-clicks against what is in the file), and **ask
before writing** — it is the user's data and the prior state cannot be diffed.
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
