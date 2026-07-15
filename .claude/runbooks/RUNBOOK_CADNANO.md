# cadnano-2d — diagnostics runbook
Loaded on demand from the `cadnano-2d` rule. Debug technique / debug globals / known issues; not auto-loaded.

## Debugging: Bead Position Intercept Technique

When beads flash to 3D for one frame after a mutation, the cause is always some code writing
`entry.pos.x` back to the geometry value after `reapplyPositions`. Find it with:

```javascript
// 1. Enable debug mode and do the mutation. After the flash, the monitor fires.
window._cnDebug = true

// OR: manually intercept e0.pos.x in the console to get a stack trace:
const e0 = window._cnEntries().find(e => !e.nuc.helix_id.startsWith('__'))
let _xVal = e0.pos.x
Object.defineProperty(e0.pos, 'x', {
  configurable: true, enumerable: true,
  get() { return _xVal },
  set(v) {
    if (Math.abs(v - 1.949) > 0.5) console.trace('[INTERCEPT] pos.x →', v.toFixed(3))
    _xVal = v
  },
})
```

The stack trace will point to the exact function calling `pos.set()`, `pos.copy()`, or
`revertToGeometry()`. Note: intercept must be set up AFTER `_rebuild()` creates new entries
(the monitor inside `_startPostReapplyMonitor` does this automatically when `_cnDebug = true`).

## Debug Globals (enabled with window._cnDebug = true)
- `window._cnCheck()` — current state: active flag, bead count at midX, map sizes
- `window._cnEntries()` — live backbone entries array
- `window._cnMonitor()` — per-frame watcher, stops when bead0.x leaves midX, returns stop fn
- `_startPostReapplyMonitor()` (internal) — auto-runs after every `reapplyPositions()`;
  installs Object.defineProperty intercept on e0.pos.x; logs stack trace on first bad write

## Known Issues / Needs Testing (as of 2026-04-01)
- Cadnano mode has had significant bug fixes but **no automated tests yet**
- Arc bow direction (bowDir) was designed for unfold layout; in cadnano flat layout the bow
  is in Z (horizontal in X- view) — visually reasonable but not verified against caDNAno conventions
- `__xb_` and `__ext_` arc entries are silently skipped in `applyCadnanoPositions()` — their
  visual state during cadnano mode is undefined
- Camera position after deactivation (ortho→persp) uses `orthoHalfH / tan(fov/2)` to infer
  a perspective-equivalent distance — may feel too close or too far in some designs
- Loop/skip markers snap to cadnano positions at end of 250ms animation (no smooth lerp)
