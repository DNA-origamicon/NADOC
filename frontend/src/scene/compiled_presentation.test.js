import { expect, it } from 'vitest'
import { presentationAnimation, compilationEstimate, presentationHTML } from './compiled_presentation.js'

it('preserves keyframe order and source ranges while giving cuts a visible frame', () => {
  const source = { loop: true, keyframes: [{ id: 'a', hold_duration_s: 0, trajectory_frame_start: 12, trajectory_frame_end: 19 }] }
  const result = presentationAnimation(source, 30)
  expect(result.loop).toBe(false)
  expect(result.keyframes[0].hold_duration_s).toBeCloseTo(1 / 30)
  expect(result.keyframes[0].trajectory_frame_start).toBe(12)
  expect(source.keyframes[0].hold_duration_s).toBe(0)
})
it('estimates only from measured completed work', () => {
  expect(compilationEstimate(0, 100, 2000)).toBe(null)
  expect(compilationEstimate(20, 100, 2000)).toBe(8)
})
it('builds a self-contained file and escapes untrusted titles and clip metadata', () => {
  const html = presentationHTML('</script><img src=x>', [{ name: '</script>', video: 'data:video/webm;base64,AA==', first: 'data:image/png;base64,AA==', last: 'data:image/png;base64,AA==' }])
  expect(html).not.toContain('<img src=x>')
  expect(html).toContain('connect-src')
  expect(html).toContain('data:video/webm;base64,AA==')
  expect(html).not.toMatch(/<script[^>]+src=/)
})
