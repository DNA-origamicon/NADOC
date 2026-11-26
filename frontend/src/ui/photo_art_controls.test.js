// @vitest-environment jsdom
import { it, expect, vi } from 'vitest'
import { initPhotoArtControls } from './photo_art_controls.js'
import { DEFAULT_PHOTO_SETTINGS } from '../scene/photo_mode.js'
it('themes reset previous styling, edits become Custom, and switching representations refreshes compatibility', () => {
  document.body.innerHTML = '<select id="photo-material"></select><select id="photo-art-theme"></select><div id="photo-material-note"></div><input id="photo-saturation" type="range" min="0" max="2" step=".05"><span id="photo-saturation-label"></span>'
  let settings = { ...DEFAULT_PHOTO_SETTINGS, exportWidth: 1234 }, representations = ['surface']
  const mode = { getSettings: () => settings, getMaterialAvailability: () => ({ representations }),
    setMaterialPresets: value => Object.assign(settings, value), setColorGrade: value => Object.assign(settings, value) }
  const changed = vi.fn()
  const ui = initPhotoArtControls({ mode, defaults: DEFAULT_PHOTO_SETTINGS, applyProfile: value => Object.assign(settings, value), changed })
  const theme = document.getElementById('photo-art-theme'), material = document.getElementById('photo-material')
  material.value = 'glass'; material.dispatchEvent(new Event('change'))
  expect(settings.surface).toBe('glass')
  representations = ['full', 'surface']; ui.sync()
  expect(material.querySelector('[value="glass"]').disabled).toBe(true)
  theme.value = 'electric'; theme.dispatchEvent(new Event('change'))
  expect(settings.saturation).toBe(1.3)
  theme.value = 'scientific-light'; theme.dispatchEvent(new Event('change'))
  expect(settings.saturation).toBe(1)
  expect(settings.studioEnvironment).toBe(false)
  expect(settings.outline).toBe(true)
  expect(settings.exportWidth).toBe(1234)
  const saturation = document.getElementById('photo-saturation')
  saturation.value = '.5'; saturation.dispatchEvent(new Event('input'))
  expect(theme.value).toBe('')
  expect(settings.saturation).toBe(.5)
  ui.dispose(); changed.mockClear()
  saturation.dispatchEvent(new Event('input'))
  expect(changed).not.toHaveBeenCalled()
  document.body.replaceChildren()
})
