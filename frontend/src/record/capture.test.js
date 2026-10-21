import { it, expect, vi } from 'vitest'
import { verifySource, selectedSourceHandle, outputSize, drawFrame } from './capture.js'
const track = (surface, handle = 'nadoc-1', origin = 'https://nadoc.test') => ({
  getSettings: () => ({ displaySurface: surface }), getCaptureHandle: () => ({ handle, origin }),
})
it('accepts only the originating NADOC browser tab', () => {
  expect(() => verifySource(track('browser'), 'nadoc-1', 'https://nadoc.test')).not.toThrow()
  for (const candidate of [track('monitor'), track('window'), track('browser', 'another-tab'), track('browser', 'nadoc-1', 'https://other.test'), undefined, { getSettings: () => ({ displaySurface: 'browser' }) }]) {
    expect(() => verifySource(candidate, 'nadoc-1', 'https://nadoc.test')).toThrow('original NADOC')
  }
})
it('preserves the complete capture at the chosen aspect ratio', () => {
  const ctx = { fillRect: vi.fn(), drawImage: vi.fn() }
  const video = { videoWidth: 1000, videoHeight: 1000 }
  drawFrame(ctx, video, 1920, 1080)
  expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, 1920, 1080)
  expect(ctx.drawImage).toHaveBeenCalledWith(video, 420, 0, 1080, 1080)
  expect(outputSize(1234, 987, 'native')).toEqual([1234, 987])
  expect(outputSize(1234, 987, '1280x720')).toEqual([1280, 720])
})

it('selects only registered same-origin NADOC tabs', () => {
  const id = 'nadoc-capture-v1:12345678-1234-1234-1234-123456789abc'
  expect(selectedSourceHandle(track('browser', id), 'https://nadoc.test')).toBe(id)
  for (const candidate of [track('monitor', id), track('window', id), track('browser', id, 'https://other.test'), track('browser', 'unregistered')]) {
    expect(() => selectedSourceHandle(candidate, 'https://nadoc.test')).toThrow('NADOC 3D viewer')
  }
})
