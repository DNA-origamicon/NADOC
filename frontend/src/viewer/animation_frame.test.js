import { it, expect } from 'vitest'
import { animationFrame } from './animation_frame.js'
it('retains unicode captions and styling as plain text while rejecting invalid bounds', () => {
  const value = { time: 1, duration: 2, camera: {}, text: { text: '<b>DNA →</b>', fontFamily: 'sans-serif', fontSizePx: 24, opacity: .5, color: '#fff', align: 'center', bold: true } }
  expect(animationFrame(value).text.text).toBe('<b>DNA →</b>')
  expect(animationFrame(value).text.opacity).toBe(.5)
  expect(() => animationFrame({ ...value, time: 3 })).toThrow()
  expect(() => animationFrame({ ...value, text: { ...value.text, opacity: Infinity } })).toThrow()
  expect(() => animationFrame({ ...value, text: { ...value.text, text: 'a'.repeat(2049) } })).toThrow()
})
