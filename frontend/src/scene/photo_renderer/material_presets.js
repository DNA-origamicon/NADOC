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
      roughness: 0.55, metalness: 0.0,
      transmission: 0.45, transparent: true, ior: 1.4, thickness: 1.0,
      attenuationColor: new THREE.Color(0xffe7d6), attenuationDistance: 4.0,
    },
    wax: {
      roughness: 0.30, metalness: 0.0,
      transmission: 0.85, transparent: true, ior: 1.45, thickness: 1.5,
      attenuationColor: new THREE.Color(0xffd9a0), attenuationDistance: 1.2,
    },
    skin: {
      roughness: 0.40, metalness: 0.0,
      transmission: 0.55, transparent: true, ior: 1.4, thickness: 1.0,
      attenuationColor: new THREE.Color(0xff9b80), attenuationDistance: 0.8,
      sheen: 0.3, sheenColor: new THREE.Color(0xffd0bb),
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
    'cpk-metallic': {
      roughness: 0.30, metalness: 1.0, clearcoat: 0.0,
    },
  },
}

// Preset labels shown in the UI dropdowns
export const PRESET_LABELS = {
  full:      { matte: 'Matte', glossy: 'Glossy', metallic: 'Metallic' },
  cylinders: { matte: 'Matte', glossy: 'Glossy', metallic: 'Metallic' },
  surface:   { gummy: 'Gummy (default)', wax: 'Wax (SSS)', skin: 'Skin (SSS)', matte: 'Matte', glass: 'Glass' },
  atomistic: { 'cpk-matte': 'CPK Matte', 'cpk-glossy': 'CPK Glossy', 'cpk-metallic': 'CPK Metallic' },
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
  // The molecular-surface mesh is a marching-cubes envelope with a few non-
  // manifold junction edges; it must render both sides or those triangles cull.
  // (The normal-mode MeshPhongMaterial also uses DoubleSide for the same reason.)
  if (repr === 'surface') mat.side = THREE.DoubleSide

  // Stash the preset's transmission target so the opacity slider can restore it
  // when sliding back below 1.0 after we've zeroed it for full-opacity.
  mat.userData.presetTransmission = params.transmission ?? 0

  // Only the surface rep carries a meaningful incoming opacity (it has its own
  // opacity slider). For full / cylinders / atomistic the global Translucency
  // slider is the sole transparency control, so a normal-mode <1 opacity must
  // NOT leak in — e.g. base slabs are built at opacity 0.90 in normal mode so
  // beads read through them; inheriting that here left slabs permanently
  // semi-transparent and unresponsive to the Translucency slider (which only
  // drives `transmission`, never resets `opacity`). Force these reps opaque so
  // each slab matches its corresponding bead and the slider is authoritative.
  const effectiveOpacity = (repr === 'surface') ? opacity : 1.0

  if (effectiveOpacity >= 1.0) {
    // opacity=1 must mean fully opaque even on SSS/transmissive presets — the
    // slider is authoritative.  Zero transmission and disable blending.
    mat.transmission = 0
    mat.transparent  = false
    mat.opacity      = 1
  } else {
    mat.transparent = true
    if (!params.transmission) mat.opacity = effectiveOpacity
  }
  return mat
}

/**
 * Build an emissive fluorophore material.
 * Raster: per-instance color drives emission via an onBeforeCompile patch.
 * Path tracer: reads material.emissive * material.emissiveIntensity as area-light radiance.
 *
 * @param {number} intensity   — emissive multiplier (≈ 1 = LED-bright, ≈ 10 = bloom)
 * @param {boolean} vertexColors
 */
export function makeFluorophoreEmissive(intensity = 5.0, vertexColors = false) {
  const mat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    vertexColors,
    emissive: new THREE.Color(0xffffff),
    emissiveIntensity: intensity,
    roughness: 0.40, metalness: 0.0,
  })
  // Raster patch: replace the emissive-map chunk so totalEmissiveRadiance comes
  // from vColor (which carries instanceColor) when the mesh is instanced.
  mat.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <emissivemap_fragment>',
      [
        'vec3 totalEmissiveRadiance = emissive;',
        '#ifdef USE_INSTANCING_COLOR',
        '  totalEmissiveRadiance = vColor * emissive.r;',
        '#endif',
      ].join('\n'),
    )
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
