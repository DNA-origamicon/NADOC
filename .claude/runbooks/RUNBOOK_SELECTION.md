# selection — diagnostics runbook
Loaded on demand from the `selection` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

## Symptoms
- Context menu button visible but click does nothing
- "Extrude" or "Nick" in context menu silently fails
- Handler appears to return early with no error
- Button callback fires but `info` / `_bluntInfo` / `_pendingEntry` is null at the use-point
- Ctrl+click adds bead to _ctrlBeads but subsequent action does nothing

## First-Check Invariants

1. **State capture before cleanup** — module-level state MUST be captured into a local `const` BEFORE any cleanup function that nulls it. This is the most common silent failure mode.

2. **toolFilters ≠ selectableTypes** — `toolFilters` controls overlay visibility only; it does NOT gate selection behavior. Changing `toolFilters.bluntEnds = false` hides blunt end rings but does NOT prevent click events on selection_manager.

3. **deformToolActive blocks all selection** — if `store.deformToolActive = true`, canvas events are intercepted at capture phase before selection_manager sees them. If clicks do nothing, check if deform tool is stuck active.

## The Context Menu State Capture Pattern

**WRONG — always exits early:**
```js
async function _handleExtrude() {
  _hideMenu()           // sets _bluntInfo = null
  if (!_bluntInfo) return    // always returns!
  // never reached
}
```

**CORRECT:**
```js
async function _handleExtrude() {
  const info = _bluntInfo   // capture FIRST
  _hideMenu()               // now safe to null
  if (!info) return
  // use info ...
}
```

Apply whenever a handler: (1) reads module-level state, AND (2) calls a function that clears that state.

## Diagnosis Tree

### Context menu button does nothing
1. Find the handler function in `selection_manager.js`
2. Check if it calls a `_hideMenu()` / `_closeDialog()` type function
3. Check if module-level state is read AFTER that cleanup call
4. If yes → apply state capture pattern above

### Click on bead does nothing at all
1. Check `store.deformToolActive` — if true, selection manager is disabled
2. Check `store.selectableTypes` — is the relevant type enabled?
3. Check that `store.toolFilters` isn't being confused with `selectableTypes`
4. Check NDC calculation uses `canvas.getBoundingClientRect()` not `window.innerWidth`

### Ctrl+click works but [X] measurement does nothing
1. `_ctrlBeads` (module-level array) needs exactly 2 entries
2. `selectionManager.onCtrlBeadsChange(callback)` must be registered (it is, in main.js)
3. `X` key handler in main.js checks beads length === 2 before acting

### Lasso selects wrong strands
1. Check `store.selectableTypes.scaffold` and `.staples` — global gates
2. Check if `domains` mode is on (`store.selectableTypes.domains`)
3. Lasso hits instanced mesh → checks instance ID → looks up strandId via design
