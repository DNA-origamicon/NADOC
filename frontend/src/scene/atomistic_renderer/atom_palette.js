// Atomistic palette + radius constants extracted from atomistic_renderer.js
// (Refactor 12-B). Pure leaf module: contains the CPK element catalog,
// highlight constants, sphere/bond radius constants, and the colour-dim helper.
//
// Leaf module: imports nothing from atomistic_renderer.js or sibling modules
// under atomistic_renderer/. Imports nothing from `three` either — these are
// plain-number / plain-object constants and a pure colour-math helper.

// ── Element catalogue ─────────────────────────────────────────────────────────

export const ELEMENTS = {
  P: { vdw: 0.190, color: 0xFF8C00 },   // orange
  C: { vdw: 0.170, color: 0x505050 },   // dark grey
  N: { vdw: 0.155, color: 0x3050F8 },   // blue
  O: { vdw: 0.140, color: 0xFF0D0D },   // red
}

// ── Highlight colours ─────────────────────────────────────────────────────────

export const C_HIGHLIGHT   = 0xFFFFFF   // selected — white
export const C_DIM_FACTOR  = 0.15       // CPK × this for unrelated atoms

export function _dimColor(cpkHex, factor) {
  const r = (((cpkHex >> 16) & 0xFF) * factor) | 0
  const g = (((cpkHex >>  8) & 0xFF) * factor) | 0
  const b = (((cpkHex      ) & 0xFF) * factor) | 0
  return (r << 16) | (g << 8) | b
}

// ── Geometry constants ────────────────────────────────────────────────────────

export const BALL_RADIUS   = 0.07    // nm, ball-and-stick mode
export const BOND_RADIUS   = 0.025   // nm, cylinder radius
