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
