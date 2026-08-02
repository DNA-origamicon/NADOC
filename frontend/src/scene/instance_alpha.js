/**
 * Per-instance alpha for InstancedMeshes — the shader patch and the material half
 * of installing it.
 *
 * An InstancedMesh has one material for all its instances, so fading a subset means
 * a per-instance channel: an `instanceAlpha` InstancedBufferAttribute on the (cloned)
 * geometry, multiplied into the fragment alpha by a small `onBeforeCompile` patch.
 * Three factors ride this one channel today — reference-geometry ghosting,
 * mixed-representation visibility, and per-cluster opacity — composited by
 * helix_renderer, which owns the buffers.
 *
 * This module exists because the patch has to be re-installable from OUTSIDE
 * helix_renderer: photo mode REPLACES every mesh material with a flat figure
 * material, which drops `onBeforeCompile` and silently renders faded geometry
 * opaque. The `userData` markers below are what lets the swap put it back.
 *
 * Pure and three-only. Unit-tested in instance_alpha.test.js.
 */
import * as THREE from 'three'

/**
 * The shader patch: declare the attribute, pass it through as a varying, multiply it
 * into `diffuseColor.a`, and discard near-zero fragments (that is how the hide path
 * works). Only touches `diffuseColor.a` — no stock chunk variable is redefined
 * (see LESSONS D5).
 *
 * Deliberately a MODULE-LEVEL NAMED FUNCTION rather than a fresh closure per
 * material: three's `Material.customProgramCacheKey()` returns
 * `onBeforeCompile.toString()`, so one shared function means one shared compiled
 * program across every patched material, while unpatched materials keep a distinct
 * key. Rebuilding this as a per-material arrow would recompile the shader once per
 * mesh for no benefit.
 */
export function instanceAlphaOnBeforeCompile(shader) {
  patchShaderForInstanceAlpha(shader)
}

/**
 * The patch as a plain shader-source transform, so a material that ALREADY has an
 * `onBeforeCompile` (the sphere impostors) can compose it instead of being
 * clobbered by an assignment. Safe to compose: it touches only the `<common>`
 * prepend, `<begin_vertex>` and `<color_fragment>`, none of which the impostor
 * patch replaces.
 *
 * Only apply this to a mesh that actually HAS the `instanceAlpha` attribute — an
 * absent attribute reads as 0 in GLSL, which the discard below turns into an
 * invisible mesh.
 */
export function patchShaderForInstanceAlpha(shader) {
  shader.vertexShader =
    'attribute float instanceAlpha;\nvarying float vInstanceAlpha;\n' + shader.vertexShader
  shader.vertexShader = shader.vertexShader.replace(
    '#include <begin_vertex>',
    '#include <begin_vertex>\n  vInstanceAlpha = instanceAlpha;',
  )
  shader.fragmentShader = 'varying float vInstanceAlpha;\n' + shader.fragmentShader
  shader.fragmentShader = shader.fragmentShader.replace(
    '#include <color_fragment>',
    '#include <color_fragment>\n  diffuseColor.a *= vInstanceAlpha;\n  if ( diffuseColor.a < 0.02 ) discard;',
  )
}

/**
 * The geometry half only: clone the shared template and add the attribute, without
 * touching the material. For meshes whose material needs a bespoke composition
 * (impostors) rather than the stock assignment.
 * @returns {boolean} true if it installed, false if already present
 */
export function installInstanceAlphaGeometry(mesh) {
  if (!mesh || mesh._instanceAlpha) return false
  const capacity = mesh.instanceMatrix.count
  mesh.geometry = mesh.geometry.clone()
  const attr = new THREE.InstancedBufferAttribute(new Float32Array(capacity).fill(1), 1)
  attr.setUsage(THREE.DynamicDrawUsage)
  mesh.geometry.setAttribute('instanceAlpha', attr)
  mesh._instanceAlpha = attr
  return true
}

/**
 * Patch *mat* so it honours the `instanceAlpha` attribute. Idempotent.
 *
 * Leaves `depthWrite` alone (true, for the structural meshes): a single
 * InstancedMesh holds both faded and opaque instances, so dropping depthWrite to
 * improve blending would break the opaque ones — and `shadow_bounds.isShadowExcluded`
 * reads `depthWrite:false` as "overlay, cannot occlude", which would silently drop
 * the whole mesh out of photo mode's key shadow. `photoForceDepthWrite` pins that
 * intent so a future blending tweak can't quietly kill the shadow.
 *
 * @param {THREE.Material} mat
 */
export function applyInstanceAlphaMaterial(mat) {
  if (!mat) return mat
  mat.onBeforeCompile = instanceAlphaOnBeforeCompile
  mat.transparent = true
  mat.userData = mat.userData || {}
  // Marker read by photo_mode.swapToFlatMaterials — a fresh figure material has no
  // onBeforeCompile, so without this the fade vanishes in photo mode and in export.
  mat.userData.instanceAlphaPatch = true
  mat.userData.photoForceDepthWrite = true
  mat.needsUpdate = true
  return mat
}

/**
 * Give *mesh* a per-instance `instanceAlpha` attribute (default 1.0) and patch its
 * material to honour it. Idempotent; no-op on a mesh that already has one.
 *
 * Clones the geometry first — the GEO_* templates are SHARED between meshes, so
 * setting an attribute on one would leak into all of them.
 *
 * Lazy by contract: this flips the material to `transparent`, which changes render
 * ordering and costs fill rate, so only install on meshes that actually need to fade.
 *
 * @param {THREE.InstancedMesh} mesh
 */
export function installInstanceAlpha(mesh) {
  if (!installInstanceAlphaGeometry(mesh)) return
  applyInstanceAlphaMaterial(mesh.material)
}

/** Write one instance's alpha. No-op if the mesh has no alpha channel installed. */
export function setInstanceAlpha(mesh, idx, a) {
  const attr = mesh?._instanceAlpha
  if (!attr) return
  attr.setX(idx, a)
  attr.needsUpdate = true
}
