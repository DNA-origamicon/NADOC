/**
 * Photo mode — style presets ("Style" dropdown at the top of the Photo tab).
 *
 * A style preset is nothing more than a NAMED BUNDLE OF THE ORDINARY SETTINGS.
 * Every knob it sets is also individually exposed in the panel; picking a style
 * just writes a coherent set of them at once. This keeps one source of truth
 * (the settings object) and means a style is applied through exactly the same
 * path as loading a profile.
 *
 * Why `publication` looks the way it does — it is a deliberate REJECTION of the
 * photoreal knobs, not a tuning of them. The house style of ChimeraX/PyMOL
 * figures (the look people read as "professional" in a paper) is:
 *
 *   • non-photorealistic: no specular lobe, no reflections, no bloom, no mist,
 *     no floor, no shadow — every one of those reads as "amateur 3D render"
 *     in a journal figure
 *   • shape conveyed by AMBIENT OCCLUSION, not by a key light
 *   • silhouette outlines doing the work of separating overlapping helices
 *   • near-parallel projection (perspective on a 60 nm object is a video-game tell)
 *   • flat matte materials, white background, subtle depth cue
 *
 * `studio` is the historic photoreal default (kept so the old look is one click
 * away). `custom` is not a preset — it is what the dropdown shows when the
 * live settings don't match any preset.
 */

export const CUSTOM_STYLE = 'custom'

export const STYLE_PRESETS = Object.freeze({
  publication: Object.freeze({
    label: 'Publication (figure)',

    // Lighting: occlusion does the shading; no directional key.
    lighting:      'ambient',
    lightingYaw:   0,
    lightingPitch: 0,
    sun:           false,

    // Materials: pure diffuse, zero specular.
    full:      'flat',
    cylinders: 'flat',
    surface:   'flat',
    atomistic: 'cpk-flat',
    translucency: 0,

    // The figure pass — the actual "publication" look.
    outline:                  true,
    outlineColor:             '#1b1f24',
    outlineStrength:          1.0,
    outlineThickness:         1.4,
    outlineDepthSensitivity:  0.35,
    outlineCreaseSensitivity: 0.85,
    depthCue:                 true,
    depthCueColor:            '#ffffff',
    depthCueStrength:         0.35,

    // Occlusion shading (GTAO) instead of the small screen-space SSAO garnish.
    ao:          true,
    aoRadius:    2.0,
    aoIntensity: 1.0,
    ssao:        false,

    // Near-parallel projection.
    parallel: true,
    fov:      8,

    // Everything photoreal: off.
    bloom:                 false,
    envEffect:             'none',
    environment:           'off',
    environmentBackground: false,
    floor:                 'off',
    floorGrid:             false,
    fluorophoreEmissive:   false,
    pathTracing:           false,
    exposure:              1.0,
    bgType:                'white',
  }),

  // A second molecular-figure look, tuned to ChimeraX's "soft lighting + strong
  // ambient occlusion on a black background" render (no silhouette outline). Where
  // `publication` is occlusion-ONLY/flat and separates overlapping helices with a
  // black contour, `publication2` keeps a gentle top key light for rounded form and
  // lets DEEP ambient-occlusion shadow do the separating — the strands' own gaps
  // (per-strand split surface) go dark in the crevices exactly like the ChimeraX shot.
  publication2: Object.freeze({
    label: 'Publication 2 (soft occlusion)',

    // Soft single key from above + occlusion — gentle directional shading, not flat.
    lighting:      'scientific',
    lightingYaw:   0,
    lightingPitch: 0,
    sun:           false,

    // Matte, zero specular (same non-photoreal materials as Publication).
    full:      'flat',
    cylinders: 'flat',
    surface:   'flat',
    atomistic: 'cpk-flat',
    translucency: 0,

    // NO outline and NO depth-cue fog — occlusion shadow does the separation here.
    outline:  false,
    depthCue: false,

    // Strong GTAO is the PRIMARY depth cue — deep crevice/cavity darkening.
    ao:          true,
    aoRadius:    2.5,
    aoIntensity: 1.5,
    ssao:        false,

    // Moderate perspective (ChimeraX's default camera), not the near-parallel lens.
    parallel: false,
    fov:      30,

    // Black background; everything photoreal off.
    bloom:                 false,
    envEffect:             'none',
    environment:           'off',
    environmentBackground: false,
    floor:                 'off',
    floorGrid:             false,
    fluorophoreEmissive:   false,
    pathTracing:           false,
    exposure:              1.0,
    bgType:                'black',
  }),

  studio: Object.freeze({
    label: 'Studio (product render)',

    lighting:      'studio',
    lightingYaw:   0,
    lightingPitch: 0,
    sun:           false,

    full:      'matte',
    cylinders: 'matte',
    surface:   'gummy',
    atomistic: 'cpk-matte',
    translucency: 0,

    outline:  false,
    depthCue: false,

    ao:   false,
    ssao: true,

    parallel: false,
    fov:      55,

    bloom:                 false,
    envEffect:             'none',
    environment:           'room',
    environmentBackground: false,
    floor:                 'off',
    floorGrid:             false,
    fluorophoreEmissive:   false,
    pathTracing:           false,
    exposure:              1.0,
    bgType:                'transparent',
  }),
})

/** Human-readable label for a style key (or 'Custom'). */
export function styleLabel(name) {
  return STYLE_PRESETS[name]?.label ?? 'Custom'
}

/**
 * The settings patch for a named style — `label` stripped, since it is UI text
 * and must never end up in the persisted settings object.
 *
 * @param {string} name
 * @returns {object|null}  patch to merge over the current settings, or null
 */
export function resolveStyle(name) {
  const preset = STYLE_PRESETS[name]
  if (!preset) return null
  const { label: _label, ...settings } = preset
  return settings
}

/**
 * Which style (if any) the given settings currently match. Only the keys the
 * preset actually defines are compared, so a style still "matches" after the
 * user changes something the preset has no opinion about (resolution, profile
 * name, mist wispiness, …).
 *
 * @param {object} settings  — photoRenderer.getSettings()
 * @returns {string} a key of STYLE_PRESETS, or CUSTOM_STYLE
 */
export function detectStyle(settings) {
  if (!settings) return CUSTOM_STYLE
  for (const [name, preset] of Object.entries(STYLE_PRESETS)) {
    const patch = resolveStyle(name)
    const match = Object.entries(patch).every(([k, v]) => settings[k] === v)
    if (match) return name
  }
  return CUSTOM_STYLE
}
