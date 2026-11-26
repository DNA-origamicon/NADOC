import { MATERIALS, ART_THEMES, materialPresets, materialAvailable, selectedMaterial, themeSettings, selectedTheme } from '../scene/photo_renderer/art_themes.js'

/** One material policy, including mixed scenes. Existing saved per-representation looks remain readable. */
export function initPhotoArtControls({ mode, defaults, applyProfile, changed, root = document }) {
  const material = root.getElementById('photo-material')
  const theme = root.getElementById('photo-art-theme')
  const note = root.getElementById('photo-material-note')
  const listeners = []
  const listen = (el, event, fn) => { if (el) { el.addEventListener(event, fn); listeners.push(() => el.removeEventListener(event, fn)) } }
  function options(select, entries, custom) {
    if (!select) return
    select.replaceChildren()
    for (const [value, label] of [['', custom], ...entries]) {
      const option = document.createElement('option')
      option.value = value; option.textContent = label; option.disabled = value === ''
      select.append(option)
    }
  }
  options(material, Object.entries(MATERIALS), 'Custom / mixed')
  options(theme, Object.entries(ART_THEMES).map(([id, t]) => [id, t.label]), 'Custom')
  function sync() {
    const settings = mode.getSettings()
    const visible = mode.getMaterialAvailability?.() ?? { representations: [], unsupported: 0 }
    if (material) {
      for (const option of material.options) if (option.value) option.disabled = !materialAvailable(option.value, visible.representations)
      material.disabled = !visible.representations.length
      material.value = selectedMaterial(settings, visible.representations)
    }
    if (note) note.textContent = visible.unsupported
      ? 'Some visible objects retain their dedicated materials. Surface-only finishes require a surface-only view.'
      : visible.representations.length ? 'One finish across representations. Surface-only finishes require a surface-only view.' : 'Show a molecular representation to choose its material.'
    if (theme) theme.value = selectedTheme(settings, defaults)
    for (const key of ['exposure', 'contrast', 'saturation']) {
      const el = root.getElementById(`photo-${key}`), label = root.getElementById(`photo-${key}-label`)
      if (el) el.value = String(settings[key] ?? 1)
      if (label) label.textContent = (settings[key] ?? 1).toFixed(2)
    }
  }
  listen(material, 'change', () => {
    const visible = mode.getMaterialAvailability?.().representations ?? []
    if (!materialAvailable(material.value, visible)) { sync(); return }
    mode.setMaterialPresets(materialPresets(material.value)); sync(); changed()
  })
  listen(theme, 'change', () => {
    const settings = themeSettings(theme.value, defaults)
    if (settings) { applyProfile({ ...mode.getSettings(), ...settings }); sync(); changed() }
  })
  for (const key of ['exposure', 'contrast', 'saturation']) listen(root.getElementById(`photo-${key}`), 'input', event => {
    mode.setColorGrade({ [key]: Number(event.target.value) }); sync(); changed()
  })
  sync()
  return { sync, dispose() { listeners.forEach(fn => fn()) } }
}
