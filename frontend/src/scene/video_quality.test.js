import { it, expect } from 'vitest'
import { videoBitrate } from './video_quality.js'
it('scales video quality with resolution and frame rate with bounded memory/encoder demand', () => {
  expect(videoBitrate(1280, 720, 30)).toBe(8_000_000)
  expect(videoBitrate(3840, 2160, 30)).toBe(49_766_400)
  expect(videoBitrate(3840, 2160, 60)).toBe(99_532_800)
  expect(videoBitrate(8000, 8000, 60)).toBe(120_000_000)
  expect(() => videoBitrate(NaN, 1080, 30)).toThrow('Invalid')
})
