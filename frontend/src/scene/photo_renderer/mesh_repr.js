/**
 * Which photo-mode representation a scene mesh belongs to.
 *
 * Lifted verbatim out of photo mode v1's photo_renderer.js (now under
 * archive/photo_mode_v1/) so the current photo mode can
 * pick a material preset per representation without duplicating the name table
 * (two copies would silently drift the moment a renderer adds a mesh name).
 *
 * The name map is the authority; `inferRepr` is the fallback for meshes that
 * don't carry one of these names.
 */

import * as THREE from 'three'

/** Mesh name → representation. */
export const MESH_NAME_TO_REPR = {
  backboneSpheres:           'full',
  backboneCubes:             'full',
  strandCones:               'full',
  baseSlabs:                 'full',
  slabBackboneConnectors:    'full',
  extensionFluorophores:     'full',
  helixCylinders:            'cylinders',
  overhangCylinders:         'cylinders',
  overhangFullCylinders:     'cylinders',
  curvedHelixCylindersProxy: 'cylinders',
  curvedCylGroup:            'cylinders',
  curvedOverhangFullCylindersProxy: 'cylinders',
  curvedOvhgGroup:           'cylinders',
  linkerBindingCylinders:    'cylinders',
  linkerBridgeCylinders:     'cylinders',
  sharedLodMid:              'cylinders',
  sharedLodOverhangs:        'cylinders',
  sharedLodCurvedCyl:        'cylinders',
  'dna-surface':             'surface',
  'dna-surface-region':      'surface',
  assemblySurface:           'surface',
  // Atomistic renderer meshes. Named 2026-07-30 so `inferRepr` never has to guess
  // for them: under the impostor flag their material is a MeshPhongMaterial, so
  // material-class inference cannot identify them.
  atomSpheres:               'atomistic',
  atomBonds:                 'atomistic',
}

/**
 * Fallback for unnamed meshes: the marching-cubes surface is the only thing
 * drawn DoubleSide. Atomistic meshes are explicitly named above; material class
 * is not a safe discriminator because hulls and other ordinary PBR geometry also
 * use MeshStandardMaterial.
 *
 * Evaluate this against the original material: the DoubleSide fallback is a
 * property of the source surface renderer and should not be inferred from a
 * replacement material whose side may have been copied for another reason.
 */
export function inferRepr(obj) {
  if (obj.material?.side === THREE.DoubleSide) return 'surface'
  return 'full'
}

/** Name map first, including named representation groups, inference second. */
export function reprOf(obj) {
  let node = obj
  while (node) {
    const mapped = MESH_NAME_TO_REPR[node.name]
    if (mapped) return mapped
    node = node.parent
  }
  // Atomistic meshes are explicitly named. Treating every MeshStandardMaterial
  // as atomistic made ordinary hull-prism and other PBR meshes consume the CPK
  // selector, which is especially visible when Full and Atomistic differ.
  return inferRepr(obj)
}
