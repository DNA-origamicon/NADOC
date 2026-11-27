/** Complete appearance recipes. Output dimensions and molecular colors are preserved. */
export const MATERIALS = {
  flat: 'Flat · scientific', matte: 'Matte', glossy: 'Glossy', metallic: 'Metallic',
  glass: 'Glass · surface only', wax: 'Wax · surface only',
  gummy: 'Gummy · surface only', skin: 'Soft tissue · surface only',
}
export const REPRESENTATIONS = ['full', 'cylinders', 'surface', 'atomistic']
export function materialPresets(name) {
  if (!Object.hasOwn(MATERIALS, name)) return null
  const common = ['flat', 'matte', 'glossy', 'metallic'].includes(name)
  const base = common ? name : 'matte'
  return { full: base, cylinders: base, surface: name, atomistic: `cpk-${base}` }
}
export function materialAvailable(name, representations) {
  return Object.hasOwn(MATERIALS, name) && representations.length > 0 &&
    (['flat', 'matte', 'glossy', 'metallic'].includes(name) || representations.every(r => r === 'surface'))
}
export function selectedMaterial(settings, representations = REPRESENTATIONS) {
  return Object.keys(MATERIALS).find(name => {
    const presets = materialPresets(name)
    return representations.length && representations.every(r => settings[r] === presets[r])
  }) ?? ''
}
export const ART_THEMES = {
  'bright-studio': { label: 'Bright studio', material: 'glossy', settings: {
    bgColor: '#f3f6fc', keyIntensity: 2.4, fillIntensity: .65, ambientIntensity: .25,
    studioEnvironmentIntensity: 1.2, floorOpacity: .18, exposure: 1.15, saturation: 1.1,
  } },
  'electric': { label: 'Electric · vivid gloss', material: 'glossy', settings: {
    bgColor: '#080d25', keyAzimuth: 145, keyElevation: 22, keyIntensity: 2.8,
    fillIntensity: .3, ambientIntensity: .12, studioEnvironmentIntensity: 1.5,
    studioEnvironmentRotation: 40, contrast: 1.15, saturation: 1.3, exposure: 1.15,
    floor: false,
  } },
  'metal-studio': { label: 'Polished metal', material: 'metallic', settings: {
    bgColor: '#171c27', keyIntensity: 2.5, fillIntensity: .3,
    studioEnvironmentIntensity: 1.8, studioEnvironmentRotation: -35,
    contrast: 1.1, floorOpacity: .25,
  } },
  'soft-studio': { label: 'Soft studio', material: 'matte', settings: {
    bgColor: '#e9e4dd', keyIntensity: 1.5, fillIntensity: .65, ambientIntensity: .35,
    floorOpacity: .12, contrast: .95, saturation: .9,
  } },
  'scientific-light': { label: 'Scientific · high contrast', material: 'flat', settings: {
    bgColor: '#ffffff', studioEnvironment: false, outline: true, outlineThickness: 1,
    outlineStrength: .8, depthCue: true, depthCueColor: '#ffffff', depthCueStrength: .2,
    floor: false, fov: 15,
  } },
  'scientific-dark': { label: 'Scientific · dark', material: 'flat', settings: {
    bgColor: '#090d14', studioEnvironment: false, keyIntensity: 2.3,
    fillIntensity: .15, outline: true, outlineThickness: .8, outlineColor: '#030509',
    depthCue: true, depthCueColor: '#090d14', depthCueStrength: .25,
    floor: false, fov: 15,
  } },
}
export function themeSettings(name, defaults) {
  const theme = Object.hasOwn(ART_THEMES, name) && ART_THEMES[name]
  if (!theme) return null
  const { exportWidth, exportHeight, pathTracing, pathTraceSamples, pathTraceExportBackend, ...appearance } = defaults
  return { ...appearance, fov: 35, parallel: false, ...materialPresets(theme.material), ...theme.settings }
}
export function selectedTheme(settings, defaults) {
  return Object.keys(ART_THEMES).find(name => Object.entries(themeSettings(name, defaults))
    .every(([key, value]) => settings[key] === value)) ?? ''
}
