/**
 * Photo mode — lighting presets.
 *
 * Each preset defines an ambient light + an array of directional lights.
 * applyLighting() installs them into a dedicated Group that is added to the
 * scene on photo-mode entry and removed on exit.  The original scene lights
 * are hidden (not removed) so they restore cleanly.
 */

import * as THREE from 'three'

// ── Preset descriptors ────────────────────────────────────────────────────────

export const LIGHTING_PRESETS = {
  scientific: {
    label: 'Scientific',
    ambient: { color: 0xffffff, intensity: 0.5 },
    lights: [
      { color: 0xffffff, intensity: 1.0, position: [8, 14, 6] },
    ],
  },

  studio: {
    label: 'Studio',
    ambient: { color: 0xfff5e4, intensity: 0.3 },
    lights: [
      { color: 0xffd9a0, intensity: 1.2, position: [8, 14,  6] },   // warm key
      { color: 0x99ccff, intensity: 0.4, position: [-6, -4, -8] },  // cool fill
      { color: 0xffffff, intensity: 0.2, position: [-2,  8, -10] }, // rim
    ],
  },

  softbox: {
    label: 'Soft Box',
    ambient: { color: 0xffffff, intensity: 0.7 },
    lights: [
      { color: 0xffffff, intensity: 0.5, position: [10,  8,  4] },
      { color: 0xffffff, intensity: 0.5, position: [-10, 8, -4] },
    ],
  },

  dramatic: {
    label: 'Dramatic',
    ambient: { color: 0x111111, intensity: 0.05 },
    lights: [
      { color: 0xffffff, intensity: 1.8, position: [8,  14,  6] },
      { color: 0x334466, intensity: 0.3, position: [-4,  4, -6] },
    ],
  },

  flat: {
    label: 'Flat',
    ambient: { color: 0xffffff, intensity: 1.0 },
    lights: [],
  },

  backlit: {
    label: 'Back-lit',
    ambient: { color: 0x334466, intensity: 0.4 },
    lights: [
      { color: 0x88aaff, intensity: 1.5, position: [-8, -2, -12] }, // rim from behind
      { color: 0xffffff, intensity: 0.3, position: [ 4,  6,   8] }, // weak front fill
    ],
  },
}

// ── Application ───────────────────────────────────────────────────────────────

/**
 * Replace all lights in photoGroup with those from the named preset.
 *
 * @param {string} presetName  — key in LIGHTING_PRESETS
 * @param {THREE.Group} photoGroup  — group that holds photo-mode lights
 */
export function applyLighting(presetName, photoGroup) {
  const preset = LIGHTING_PRESETS[presetName] ?? LIGHTING_PRESETS.scientific

  // Clear existing photo lights
  while (photoGroup.children.length > 0) {
    const child = photoGroup.children[0]
    photoGroup.remove(child)
    child.dispose?.()
  }

  const amb = new THREE.AmbientLight(preset.ambient.color, preset.ambient.intensity)
  photoGroup.add(amb)

  for (const ld of preset.lights) {
    const light = new THREE.DirectionalLight(ld.color, ld.intensity)
    light.position.set(...ld.position)
    photoGroup.add(light)
  }
}
