/**
 * Coloring-mode availability + cycling logic extracted from main.js. Pure: the
 * assembly-active flag is a parameter (was a store read). The store/menu/toast
 * wiring stays in main.js. Unit-tested in coloring_modes.test.js.
 */

/** Coloring modes each representation supports (insertion order = cycle order). */
export const COLORING_SUPPORT = {
  'full':       new Set(['strand', 'base', 'cluster', 'overhang-only']),
  'beads':      new Set(['strand', 'base', 'cluster', 'overhang-only']),
  'cylinders':  new Set(['strand', 'cluster', 'overhang-only']),
  'vdw':        new Set(['strand', 'base', 'cluster', 'cpk']),
  'ballstick':  new Set(['strand', 'base', 'cluster', 'cpk']),
  'surface':    new Set(['strand', 'cluster']),
  'hull-prism': new Set(),
}

/**
 * Coloring modes available for `repr`, accounting for the assembly atomistic path
 * (per-atom cpk/strand/cluster + per-source tint; no 'base').
 */
export function supportedColoringSet(repr, assemblyActive = false) {
  const isAtom = repr === 'vdw' || repr === 'ballstick'
  if (assemblyActive) {
    if (isAtom)             return new Set(['cpk', 'strand', 'cluster', 'source'])
    if (repr === 'surface') return new Set(['strand', 'cluster', 'source'])
  }
  return COLORING_SUPPORT[repr] ?? new Set(['strand', 'base', 'cluster'])
}

/** Next mode after `current` in `modes` (wrapping); null when <2 options. */
export function nextColoringMode(modes, current) {
  if (modes.length < 2) return null
  const idx = modes.indexOf(current)
  return modes[(idx + 1) % modes.length]
}

/**
 * Mixed-representation state of an assembly's instances, for the
 * View → Representation menu. Pure decision (the DOM radio/dot sync stays in
 * main.js):
 *   • { kind: 'none' }              — no instances; leave menu to design-mode handling.
 *   • { kind: 'single', repr }      — all instances agree → check that representation.
 *   • { kind: 'mixed' }             — instances disagree → clear checks, light the dot.
 * Instances with no `representation` default to 'full' (matches the renderer default).
 */
export function reprMenuState(instances) {
  if (!instances || instances.length === 0) return { kind: 'none' }
  const reps = new Set()
  for (const inst of instances) reps.add(inst.representation ?? 'full')
  if (reps.size === 1) return { kind: 'single', repr: [...reps][0] }
  return { kind: 'mixed' }
}

/**
 * When the current coloring mode is no longer supported by `activeRepr`, the
 * mode to fall back to so the menu's checkmark always reflects an available
 * item — null when `currentMode` is still supported (no change needed) or no
 * fallback applies (e.g. Hull Prism, which supports nothing). Atomistic prefers
 * CPK; everything else prefers strand.
 */
export function coloringFallbackMode(activeRepr, currentMode, assemblyActive = false) {
  const supported = supportedColoringSet(activeRepr, assemblyActive)
  if (supported.has(currentMode)) return null
  const isAtom = activeRepr === 'vdw' || activeRepr === 'ballstick'
  if (isAtom && supported.has('cpk')) return 'cpk'
  if (supported.has('strand'))       return 'strand'
  return null
}
