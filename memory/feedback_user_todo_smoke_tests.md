---
name: User-runnable smoke tests must be flagged as USER TODO with explicit steps
description: When a code change requires manual verification I cannot perform (running app, browser smoke test, hardware check), I must label it "USER TODO" with numbered steps the user can follow.
type: feedback
originSessionId: 0f03295e-0d56-4711-b877-76c393d9521b
---
When a refactor or change requires manual verification that I cannot perform from the CLI (most commonly: clicking through a feature in `just frontend`, hardware-attached tests, or anything needing visual inspection), the report MUST include a section labelled exactly `USER TODO` with numbered, explicit steps.

**Why:** Burying "NOT VERIFIED IN APP" inside a paragraph leaves the user guessing what they need to do. They may forget, do a partial check, or skip steps. After the 03-B animation-endpoint merge I gave a vague "you should run that smoke test" — the user said this should have been a structured `USER TODO` list.

**How to apply:** at the end of any report where I cannot finish verification, output:

```
## USER TODO
1. <Concrete step — e.g. "Start the app: `just frontend && open http://localhost:5173`">
2. <Next step — e.g. "Open the Animation panel">
3. <Next step — e.g. "Click 'New animation', name it 'test'">
4. <Verification — "Confirm no errors in DevTools console">
5. <Cleanup — "Delete the test animation">
```

Use this for: frontend smoke tests, design-file-load checks, GROMACS / NAMD pipeline runs, anything where I'd otherwise write `NOT VERIFIED IN APP`. The `NOT VERIFIED IN APP` caveat is still allowed at the top of the message but must be paired with the `USER TODO` block.
