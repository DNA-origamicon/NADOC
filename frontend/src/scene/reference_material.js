/**
 * Coverage transparency keeps reference surfaces in the depth-writing pass.
 * Blended object-center sorting cannot order an enclosing STL against instanced
 * DNA: one draw call can contain fragments on both sides of another object.
 * Alpha hashing discards a fraction of surface samples, then depth-tests the
 * remaining samples normally. This also handles concave/intersecting references
 * without re-sorting millions of triangles as the camera moves.
 */
export function setReferenceOpacity(material, opacity) {
  const alphaHash = opacity < 1
  const recompile = material.alphaHash !== alphaHash || material.transparent
  material.opacity = opacity
  material.alphaHash = alphaHash
  material.transparent = false
  material.depthTest = true
  material.depthWrite = true
  if (recompile) material.needsUpdate = true
}
