/**
 * Assembly layout math extracted from main.js. Pure (no renderer/store).
 * Unit-tested in assembly_layout.test.js.
 */

/**
 * Offset [dx,0,0] (nm) to place a duplicate just past the source instance — its
 * x-extent plus a small gap, with a floor so single-helix parts still jump
 * visibly. `entry` is an instance-center {size?:{x}, radius}. Null if no entry.
 */
export function assemblyDuplicateOffset(entry) {
  if (!entry) return null
  const GAP = 2.0  // nm — small breathing room past the touch point
  const MIN = 5    // nm — keeps single-helix parts visibly jumping too
  const xExtent = entry.size?.x ?? (entry.radius * 2)
  return [Math.max(MIN, xExtent + GAP), 0, 0]
}
