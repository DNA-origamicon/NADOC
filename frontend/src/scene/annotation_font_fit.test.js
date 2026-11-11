import { expect, it } from 'vitest'
import { fitAnnotationFont } from './annotation_font_fit.js'
it('fits extreme text sizes safely and recalculates for smaller viewports without changing the saved size', () => {
  const box = document.createElement('div'), icon = document.createElement('span')
  icon.innerHTML = '<svg></svg>'
  const el = document.createElement('div')
  Object.defineProperties(box, {
    offsetWidth: { get() { return Math.min(parseFloat(box.style.maxWidth), 12 * parseFloat(box.style.fontSize) + 24) } },
    offsetHeight: { get() { return 16 + 26 * parseFloat(box.style.fontSize) } },
  })
  const rec = { box, icon, el, styleSig: 'huge text' }, entry = { size: 1e300 }
  fitAnnotationFont(rec, entry, { width: 800, height: 600 })
  expect(rec.size.w).toBeLessThanOrEqual(784); expect(rec.size.h).toBeLessThanOrEqual(584)
  expect(Number.isFinite(rec.displaySize)).toBe(true)
  const previous = rec.displaySize
  fitAnnotationFont(rec, entry, { width: 200, height: 100 })
  expect(rec.size.w).toBeLessThanOrEqual(184); expect(rec.size.h).toBeLessThanOrEqual(84)
  expect(rec.displaySize).toBeLessThan(previous)
  expect(entry.size).toBe(1e300)
})

it('preserves fitting font sizes and only shrinks as much as the custom box needs', () => {
  const box = document.createElement('div'), icon = document.createElement('span'), text = document.createElement('span'), el = document.createElement('div')
  icon.hidden = true
  Object.defineProperties(box, { offsetWidth: { get: () => 200 }, offsetHeight: { get: () => 100 } })
  Object.defineProperties(text, { scrollWidth: { get: () => 100 }, scrollHeight: { get: () => parseFloat(box.style.fontSize) * 4 } })
  const rec = { box, icon, text, el, styleSig: 'custom' }, entry = { size: 20 / 13, boxSize: { w: 200, h: 100 } }
  fitAnnotationFont(rec, entry, { width: 800, height: 600 })
  expect(rec.displaySize).toBe(20 / 13)
  rec.styleSig = 'larger requested font'; entry.size = 100 / 13
  fitAnnotationFont(rec, entry, { width: 800, height: 600 })
  expect(rec.displaySize * 13).toBeCloseTo(24, 1)
  expect(entry.size).toBe(100 / 13)
})
