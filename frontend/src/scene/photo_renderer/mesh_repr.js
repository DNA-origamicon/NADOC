/**
 * Which photo-mode representation a scene mesh belongs to.
 *
 * Lifted verbatim out of photo mode v1's photo_renderer.js (now under
 * archive/photo_mode_v1/) so the current photo mode can
 * pick a material preset per representation without duplicating the name table
 * (two copies would silently drift the moment a renderer adds a mesh name).
 *
 * The name map is the authority; `inferRepr` is the fallback for meshes that
 * don't carry one of these names — chiefly the atomistic renderer's atom/bond
 * InstancedMeshes, which are unnamed.
 */

import * as THREE from 'three'

/** Mesh name → representation. */
export const MESH_NAME_TO_REPR = {
  backboneSpheres:           'full',
  backboneCubes:             'full',
  strandCones:               'full',
  baseSlabs:                 'full',
  extensionFluorophores:     'full',
  helixCylinders:            'cylinders',
  overhangCylinders:         'cylinders',
  overhangFullCylinders:     'cylinders',
  curvedHelixCylindersProxy: 'cylinders',
  curvedOverhangFullCylindersProxy: 'cylinders',
  curvedOvhgGroup:           'cylinders',
  'dna-surface':             'surface',
}

/**
 * Fallback for unnamed meshes: the marching-cubes surface is the only thing
 * drawn DoubleSide, and the atomistic renderer is the only thing using a bare
 * MeshStandardMaterial.
 *
 * CAUTION — this must be evaluated against the mesh's ORIGINAL material, before
 * any photo-mode swap. `MeshPhysicalMaterial` extends `MeshStandardMaterial`, so
 * once a swap has run every unnamed mesh infers as 'atomistic'. photo_renderer's
 * own `setMaterialPreset` has that latent bug (documented in
 * memory/project_photo_mode.md); callers that record the representation at swap
 * time, from the source material, sidestep it.
 */
export function inferRepr(obj) {
  if (obj.material?.side === THREE.DoubleSide) return 'surface'
  if (obj.material instanceof THREE.MeshStandardMaterial) return 'atomistic'
  return 'full'
}

/** Name map first, inference second. */
export function reprOf(obj) {
  return MESH_NAME_TO_REPR[obj.name] ?? inferRepr(obj)
}
