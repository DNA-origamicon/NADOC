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
  // The molecular-figure rig (ChimeraX "ambient" lighting mode). There is no
  // key light and no light *direction* to speak of: shape is carried by ambient
  // occlusion (turn on Occlusion shading) and by the outline pass, not by a
  // highlight. The three weak directionals are a multi-direction fill, spread
  // wide so none of them reads as a key — they only stop the structure from
  // going completely flat when occlusion is off. Pair with the `flat` materials.
  ambient: {
    label: 'Ambient (occlusion-only, figure)',
    ambient: { color: 0xffffff, intensity: 0.75 },
    lights: [
      { color: 0xffffff, intensity: 0.18, position: [ 10,  10,  10] },
      { color: 0xffffff, intensity: 0.18, position: [-10,   4,  -8] },
      { color: 0xffffff, intensity: 0.18, position: [  2, -10,   6] },
    ],
  },

  // ChimeraX `lighting full`: key 0.7 / fill 0.3 / ambient 0.8, with the key
  // light casting a real shadow ON TOP of ambient occlusion. Unlike `ambient`
  // (which is occlusion-only), here the directional term carries roughly half
  // the shading — which is why the shadow visibly sweeps across the structure
  // as it is reoriented, provided the rig is pinned to the camera.
  //
  // Positions are ChimeraX's own key/fill direction vectors NEGATED, because it
  // stores the direction light TRAVELS while three.js places the light where it
  // shines FROM. Both use the same camera frame (x right, y up, z toward the
  // viewer), so key (.577,-.577,-.577) → upper-left-front, and fill
  // (-.2,-.2,-.959) → almost straight-on, slightly up and right.
  //
  // A consumer that pins the rig to the camera should treat these as DIRECTIONS
  // and rescale them onto the scene's bounding sphere; used unpinned they are
  // ordinary world-space positions and still read correctly.
  full: {
    label: 'Full (key shadow)',
    // TUNED AWAY FROM CHIMERAX'S OWN NUMBERS, deliberately. ChimeraX `full` is
    // key 0.7 / fill 0.3 / ambient 0.8, but a cast shadow can only subtract the
    // KEY light, so fill + ambient are a floor it can never go below — at those
    // values the deepest possible shadow removes just 39% of the light and
    // reads as a grey smudge on a DNA structure. Dropping fill entirely and
    // ambient to 0.15 takes that to ~93%, which is what actually makes the
    // shadow legible. Chosen from side-by-side comparison, 2026-07-28.
    ambient: { color: 0xffffff, intensity: 0.15 },
    lights: [
      { color: 0xffffff, intensity: 2.0, position: [-0.577,  0.577, 0.577] },  // key (casts the shadow)
      { color: 0xffffff, intensity: 0.0, position: [ 0.2,    0.2,   0.959] },  // fill (off by default)
    ],
  },

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
