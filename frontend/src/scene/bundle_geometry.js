/**
 * Pure geometry helpers extracted from main.js — design axis-extent math used to
 * position the slice plane. No scene/DOM/store access, so these are unit-testable
 * directly (see bundle_geometry.test.js).
 */

// Compute the extent of the design along the given plane normal. This is where
// the slice plane starts when first toggled on.
export function bundleAxisRange(design, plane) {
  if (!design || !design.helices.length) return { min: 0, max: 0 }
  let min = Infinity, max = -Infinity
  for (const h of design.helices) {
    let lo, hi
    if      (plane === 'XY') { lo = Math.min(h.axis_start.z, h.axis_end.z); hi = Math.max(h.axis_start.z, h.axis_end.z) }
    else if (plane === 'XZ') { lo = Math.min(h.axis_start.y, h.axis_end.y); hi = Math.max(h.axis_start.y, h.axis_end.y) }
    else                     { lo = Math.min(h.axis_start.x, h.axis_end.x); hi = Math.max(h.axis_start.x, h.axis_end.x) }
    if (lo < min) min = lo
    if (hi > max) max = hi
  }
  return { min, max }
}

// Currently unused (no call sites at extraction time) — kept as the natural
// sibling of bundleMidOffset; safe to remove if it stays dead.
export function bundleMaxOffset(design, plane) { return bundleAxisRange(design, plane).max }

export function bundleMidOffset(design, plane) {
  const { min, max } = bundleAxisRange(design, plane)
  return (min + max) / 2
}
