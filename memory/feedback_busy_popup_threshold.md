---
name: "Working…" popup threshold — 5 s, not 1.5 s
description: User finds the busy/working popup more annoying than useful for sub-5s ops. Threshold is now 5000 ms.
type: feedback
originSessionId: fdc481cc-d1e5-40f0-848f-0796d43300bb
---
The "Working…" auto-popup that appears for slow API calls is gated by `_BUSY_POPUP_DELAY_MS` in `frontend/src/api/client.js`. Set to **5000 ms** (was 1500 ms).

**Why:** at 1.5 s, fast-but-not-instant ops (cluster commits, animation keyframe setup, library refreshes) flashed the popup just long enough to obscure the UI without communicating useful status. The user explicitly asked to raise the threshold so the popup only fires for genuinely long ops (large autostaple runs, big bundle imports, full-design relax) where the UI would otherwise look frozen.

**How to apply:** if the user later asks to surface progress for a specific operation that finishes in 1–4 s, prefer adding a *targeted* `showOpProgress` / `_showProgress` at the call site (with a sensible header) rather than lowering the global threshold — the threshold protects against the flash-popup distraction across all routine API traffic.
