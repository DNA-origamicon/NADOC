---
name: Browser DevTools console debugging tips
description: console.debug is hidden by default; repeated identical messages are collapsed; always use console.log with a timestamp for diagnostic output
type: feedback
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
Two Chrome DevTools gotchas that waste debugging time in NADOC frontend work:

1. **`console.debug` is hidden by default.** Chrome only shows debug-level messages when the console filter is set to "Verbose." For any diagnostic output that needs to be reliably visible, use `console.log`.

2. **Repeated identical messages are collapsed.** If the same string is logged multiple times, DevTools shows it once with a count badge (e.g., `×5`). For live-polling loops where you want to see each occurrence, include a timestamp or changing value in the message:
   ```javascript
   console.log(`[applyFem] ${new Date().toLocaleTimeString()} amp=${amp}× maxΔ=${maxDelta.toFixed(3)} nm`)
   ```

**How to apply:** Any diagnostic `console.debug` added to NADOC code should be changed to `console.log` before testing. Add `new Date().toLocaleTimeString()` or `performance.now().toFixed(0)` to messages inside polling loops.
