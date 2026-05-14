/**
 * Photo mode — PBR material presets.
 *
 * All presets produce THREE.MeshPhysicalMaterial parameters.
 * Per-instance colours (instanceColor) and per-vertex colours (vertexColors)
 * are preserved by the caller; these params only control surface response.
 */

import * as THREE from 'three'

// ── Preset tables ─────────────────────────────────────────────────────────────

export const PRESETS = {
  full: {
    matte: {
      roughness: 0.85, metalness: 0.0, clearcoat: 0.0,
    },
    glossy: {
      roughness: 0.20, metalness: 0.0, clearcoat: 0.5, clearcoatRoughness: 0.1,
    },
    metallic: {
      roughness: 0.30, metalness: 1.0, clearcoat: 0.0,
    },
  },

  cylinders: {
    matte: {
      roughness: 0.85, metalness: 0.0, clearcoat: 0.0,
    },
    glossy: {
      roughness: 0.20, metalness: 0.0, clearcoat: 0.5, clearcoatRoughness: 0.1,
    },
    metallic: {
      roughness: 0.30, metalness: 1.0, clearcoat: 0.0,
    },
  },

  surface: {
    gummy: {
      roughness: 0.70, metalness: 0.0,
      transmission: 0.30, transparent: true, ior: 1.4,
      thickness: 0.5,
    },
    matte: {
      roughness: 0.85, metalness: 0.0, transmission: 0.0,
    },
    glass: {
      roughness: 0.05, metalness: 0.0,
      transmission: 0.95, transparent: true, ior: 1.5,
      clearcoat: 1.0, clearcoatRoughness: 0.0, thickness: 1.0,
    },
  },

  atomistic: {
    'cpk-matte': {
      roughness: 0.60, metalness: 0.0,
    },
    'cpk-glossy': {
      roughness: 0.20, metalness: 0.0,
    },
  },
}

// Preset labels shown in the UI dropdowns
export const PRESET_LABELS = {
  full:      { matte: 'Matte', glossy: 'Glossy', metallic: 'Metallic' },
  cylinders: { matte: 'Matte', glossy: 'Glossy', metallic: 'Metallic' },
  surface:   { gummy: 'Gummy (default)', matte: 'Matte', glass: 'Glass' },
  atomistic: { 'cpk-matte': 'CPK Matte', 'cpk-glossy': 'CPK Glossy' },
}

// ── Factory ───────────────────────────────────────────────────────────────────

/**
 * Create a MeshPhysicalMaterial from a named preset.
 *
 * @param {'full'|'cylinders'|'surface'|'atomistic'} repr
 * @param {string} presetName
 * @param {boolean} [vertexColors]  — carry over from the original material
 * @param {number}  [opacity]       — if < 1, enables transparency
 * @returns {THREE.MeshPhysicalMaterial}
 */
export function makeMaterial(repr, presetName, vertexColors = false, opacity = 1.0) {
  const params = PRESETS[repr]?.[presetName] ?? PRESETS.full.matte
  const mat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    vertexColors,
    ...params,
  })
  if (opacity < 1.0) {
    mat.transparent = true
    if (!params.transmission) mat.opacity = opacity
  }
  return mat
}

/**
 * Clone a material, keeping the same preset params but re-applying
 * the original's vertexColors + opacity state.
 * Used when the surface material changes colour mode while photo mode is active.
 */
export function cloneMaterialForOriginal(photMat, origMat) {
  photMat.vertexColors = origMat.vertexColors
  photMat.opacity      = origMat.opacity
  photMat.transparent  = photMat.transparent || origMat.transparent
  photMat.needsUpdate  = true
}
