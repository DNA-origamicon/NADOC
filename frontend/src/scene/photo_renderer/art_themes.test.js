import { it, expect } from 'vitest'
import { ART_THEMES, REPRESENTATIONS, materialPresets, materialAvailable, selectedMaterial, themeSettings, selectedTheme } from './art_themes.js'
import { PRESETS } from './material_presets.js'
import { DEFAULT_PHOTO_SETTINGS } from '../photo_mode.js'
it('every theme resets the whole appearance, preserves output configuration, and uses valid materials', () => {
  for (const name of Object.keys(ART_THEMES)) {
    const settings = themeSettings(name, DEFAULT_PHOTO_SETTINGS)
    expect(settings).not.toHaveProperty('exportWidth')
    expect(settings).not.toHaveProperty('exportHeight')
    for (const repr of REPRESENTATIONS) expect(PRESETS[repr][settings[repr]]).toBeDefined()
    expect(selectedTheme(settings, DEFAULT_PHOTO_SETTINGS)).toBe(name)
    expect(Object.keys(settings).length).toBe(Object.keys(DEFAULT_PHOTO_SETTINGS).length - 2)
  }
})
it('common materials cover mixed scenes; surface finishes cannot silently skip visible representations', () => {
  expect(materialAvailable('metallic', REPRESENTATIONS)).toBe(true)
  expect(materialAvailable('glass', ['surface'])).toBe(true)
  expect(materialAvailable('glass', ['surface', 'full'])).toBe(false)
  expect(materialAvailable('glass', [])).toBe(false)
  expect(selectedMaterial(materialPresets('glossy'))).toBe('glossy')
  expect(selectedMaterial({ ...materialPresets('glossy'), full: 'flat' })).toBe('')
  expect(materialPresets('unknown')).toBe(null)
})
