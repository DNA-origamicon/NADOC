/**
 * Pure presentation helper extracted from main.js — the motion-status chip's
 * colour palette by severity. The DOM wiring (_setMotionChip) stays in main.js
 * and calls this. Unit-tested in motion_chip.test.js.
 */

const MOTION_CHIP_COLORS = {
  info:   { fg: '#8b949e', bd: '#30363d', bg: '#161b22' },
  ok:     { fg: '#3fb950', bd: '#238636', bg: '#0d2316' },
  warn:   { fg: '#d29922', bd: '#9e6a03', bg: '#1c1810' },
  locked: { fg: '#f85149', bd: '#a40e26', bg: '#1c0d0d' },
}

/** {fg,bd,bg} for a motion-chip severity ('info' fallback for unknown). */
export function motionChipStyle(severity = 'info') {
  return MOTION_CHIP_COLORS[severity] || MOTION_CHIP_COLORS.info
}
