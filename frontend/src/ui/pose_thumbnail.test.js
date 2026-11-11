import { afterEach, expect, it, vi } from 'vitest'
import { attachPoseThumbnail, enhancePoseSelect } from './pose_thumbnail.js'
import { capturePoseThumbnail } from '../viewer/pose_thumbnail_capture.js'
const pose = { id: 'p', name: 'Side view', thumbnail: 'data:image/jpeg;base64,YQ==' }
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
it('captures a small image after rendering, preserving aspect ratio', () => {
  const canvas = document.createElement('canvas'); canvas.width = 800; canvas.height = 400; document.body.append(canvas)
  const render = vi.fn(), draw = vi.fn()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ fillRect() {}, drawImage: draw })
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(function () { expect([this.width, this.height]).toEqual([240, 120]); return pose.thumbnail })
  expect(capturePoseThumbnail(canvas, render)).toBe(pose.thumbnail)
  expect(render.mock.invocationCallOrder[0]).toBeLessThan(draw.mock.invocationCallOrder[0])
})
it('shows a thumbnail on pose hover and hides it on leave', () => {
  const row = document.createElement('button'); document.body.append(row)
  attachPoseThumbnail(row, pose)
  row.dispatchEvent(new Event('pointerenter'))
  expect(document.querySelector('.pose-thumbnail').src).toBe(pose.thumbnail)
  row.dispatchEvent(new Event('pointerleave'))
  expect(document.querySelector('.pose-thumbnail')).toBeNull()
})
it('pose menu choices support hover images and update the original select', () => {
  document.body.innerHTML = '<select><option value="">None</option><option value="p">Side view</option></select>'
  const select = document.querySelector('select'), change = vi.fn()
  select.addEventListener('change', change); enhancePoseSelect(select, [pose])
  select.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
  const option = document.querySelectorAll('.pose-options button')[1]
  option.dispatchEvent(new Event('pointerenter'))
  expect(document.querySelector('.pose-thumbnail')).toBeTruthy()
  option.click()
  expect(select.value).toBe('p'); expect(change).toHaveBeenCalledOnce()
  expect(document.querySelector('.pose-options')).toBeNull()
})
