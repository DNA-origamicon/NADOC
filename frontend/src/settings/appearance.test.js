import { expect, it } from 'vitest'
import { applyAppearance } from './appearance.js'
import { DEFAULTS } from './preferences.js'
import { initTextScaling, scaledFontSize } from './text_scaling.js'
it('scales fixed text and tokens without scaling viewport dimensions', async () => {
  document.body.innerHTML = '<span style="font-size: 12px;width:100px">Label</span>'
  const stop = initTextScaling()
  applyAppearance({ ...DEFAULTS, textScale: 1.5 })
  const span = document.querySelector('span')
  expect(span.style.fontSize).toContain('--nadoc-text-scale')
  expect(span.style.width).toBe('100px')
  expect(document.documentElement.style.getPropertyValue('--text-base')).toBe('22.5px')
  span.style.fontSize = '16px'; await new Promise(resolve => setTimeout(resolve, 0))
  expect(span.style.fontSize).toContain('16px')
  expect(scaledFontSize('var(--text-base)')).toBe('var(--text-base)')
  expect(scaledFontSize('14px')).toContain('--nadoc-text-scale')
  stop()
})

import { themedColorValue } from './legacy_theme.js'
it('themes legacy interface colors without altering molecular colors or sizes', () => {
  expect(themedColorValue('1px solid #30363d')).toBe('1px solid var(--color-border-default)')
  expect(themedColorValue('rgb(13, 17, 23)')).toBe('var(--color-bg-canvas)')
  expect(themedColorValue('#ff0000')).toBe('#ff0000')
})
